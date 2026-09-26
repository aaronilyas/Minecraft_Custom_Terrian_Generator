"""Local ACP client. Agents edit a project only by running mapctl."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import signal
import subprocess
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from mcmap import __version__
from mcmap.acp.rpc import INVALID_PARAMS, INTERNAL_ERROR, METHOD_NOT_FOUND, NdjsonPeer, RpcError
from mcmap.model import now_iso
from mcmap.store import ProjectStore, StoreError

MAX_INLINE_IMAGE_BYTES = 1_572_864
DEFAULT_OUTPUT_BYTES = 1_048_576
WRITE_DENIED = "Direct writes are disabled. Use python -m mcmap.cli apply."
COMMAND_DENIED = "Command is not allowed"

_DEFAULT_AGENTS = {
    "grok": {
        "name": "Grok",
        "command": "grok",
        "args": ["agent", "--no-leader", "stdio"],
        "enabled": True,
        "requires_binary": True,
    },
    "codex": {
        "name": "Codex",
        "command": "npx",
        "args": ["-y", "@agentclientprotocol/codex-acp"],
        "enabled": False,
        "requires_binary": True,
    },
    "test": {
        "name": "Test agent",
        "command": "",
        "args": ["-m", "mcmap.acp.test_agent"],
        "enabled": True,
        "requires_binary": False,
    },
}


class _PermissionWait:
    def __init__(self, request_id: str, title: str, detail: str, options: list[dict]):
        self.event = threading.Event()
        self.response: dict | None = None
        self.error: BaseException | None = None
        self.public = {
            "requestId": request_id,
            "title": title,
            "detail": detail,
            "options": options,
        }


class _Terminal:
    def __init__(self, proc: subprocess.Popen, limit: int):
        self.proc = proc
        self.limit = limit
        self.output = bytearray()
        self.truncated = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._pump, name="acp-terminal", daemon=True)
        self.thread.start()

    def _pump(self) -> None:
        stream = self.proc.stdout
        if stream is None:
            return
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            with self.lock:
                if self.limit <= 0:
                    self.truncated = True
                    continue
                self.output.extend(chunk)
                if len(self.output) > self.limit:
                    del self.output[: len(self.output) - self.limit]
                    self.truncated = True

    def read(self) -> tuple[str, bool, dict | None]:
        with self.lock:
            data = bytes(self.output)
            truncated = self.truncated
        if truncated:
            data = _trim_utf8_start(data)
        return data.decode("utf-8", errors="replace"), truncated, _exit_status(self.proc.poll())

    def wait(self) -> dict:
        code = self.proc.wait()
        self.thread.join(timeout=2)
        return _exit_status(code) or {"exitCode": code, "signal": None}

    def kill(self) -> None:
        if self.proc.poll() is not None:
            return
        pid = self.proc.pid
        try:
            if pid:
                os.killpg(pid, signal.SIGTERM)
                return
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            self.proc.terminate()
        except OSError:
            return

    def release(self) -> None:
        self.kill()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pid = self.proc.pid
            try:
                if pid:
                    os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    self.proc.kill()
                except OSError:
                    return
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return
        self.thread.join(timeout=1)


class _Session:
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        project_id: str,
        project_dir: Path,
        permission_mode: str,
    ):
        self.id = session_id
        self.agent_id = agent_id
        self.project_id = project_id
        self.project_dir = project_dir
        self.permission_mode = permission_mode
        self.agent_session_id = ""
        self.status = "starting"
        self.messages: list[dict] = []
        self.pending_permission: dict | None = None
        self.pending_waits: dict[str, _PermissionWait] = {}
        self.error: str | None = None
        self.capabilities: dict = {}
        self.stop_reason: str | None = None
        self.mapctl_allowed = False
        self.terminals: dict[str, _Terminal] = {}
        self.next_terminal = 0
        self.proc: subprocess.Popen | None = None
        self.peer: NdjsonPeer | None = None
        self.stderr_buf = bytearray()
        self.stderr_lock = threading.Lock()
        self.lock = threading.RLock()
        self._stopped = False
        self._tail_role = ""
        self._tail_message_id: str | None = None
        self._tool_indexes: dict[str, int] = {}

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "agentId": self.agent_id,
                "projectId": self.project_id,
                "status": self.status,
                "messages": [{"role": item["role"], "text": item["text"], "at": item["at"]} for item in self.messages],
                "pendingPermission": deepcopy(self.pending_permission) if self.pending_permission else None,
                "error": self.error,
                "capabilities": deepcopy(self.capabilities),
                "stopReason": self.stop_reason,
            }

    def stderr_text(self) -> str:
        with self.stderr_lock:
            return bytes(self.stderr_buf).decode("utf-8", errors="replace")

    def add_message(self, role: str, text: str) -> None:
        if not text:
            return
        with self.lock:
            self.messages.append({"role": role, "text": text, "at": now_iso()})

    def append_text(self, role: str, text: str, message_id: str | None) -> None:
        if not text:
            return
        with self.lock:
            if self.messages and self.messages[-1]["role"] == role:
                if message_id is None or message_id == self._tail_message_id:
                    self.messages[-1]["text"] += text
                    if message_id is not None:
                        self._tail_role = role
                        self._tail_message_id = message_id
                    return
            self.messages.append({"role": role, "text": text, "at": now_iso()})
            self._tail_role = role
            self._tail_message_id = message_id

    def upsert_tool(self, tool_id: Any, title: str) -> None:
        with self.lock:
            key = str(tool_id) if tool_id else ""
            index = self._tool_indexes.get(key) if key else None
            if index is not None and 0 <= index < len(self.messages):
                self.messages[index]["text"] = title
                return
            self.messages.append({"role": "tool", "text": title, "at": now_iso()})
            if key:
                self._tool_indexes[key] = len(self.messages) - 1

    def begin_permission(self, request_id: str, title: str, detail: str, options: list[dict]) -> _PermissionWait:
        wait = _PermissionWait(request_id, title, detail, options)
        with self.lock:
            self.pending_waits[request_id] = wait
            if self.pending_permission is None:
                self.pending_permission = wait.public
        return wait

    def finish_permission(self, request_id: str) -> None:
        with self.lock:
            self.pending_waits.pop(request_id, None)
            current = self.pending_permission
            if current and current.get("requestId") == request_id:
                self.pending_permission = None
                for wait in self.pending_waits.values():
                    self.pending_permission = wait.public
                    break

    def complete_turn(self, stop_reason: str | None) -> None:
        with self.lock:
            if self.status != "running":
                return
            self.stop_reason = stop_reason
            self.status = "idle"
            self.pending_permission = None
            if stop_reason and stop_reason != "end_turn":
                self.messages.append({"role": "system", "text": f"stopReason: {stop_reason}", "at": now_iso()})

    def fail(self, message: str) -> None:
        with self.lock:
            if self.status in {"closed", "error"}:
                return
            self.status = "error"
            self.error = message
            self.messages.append({"role": "system", "text": message, "at": now_iso()})

    def shutdown(self) -> None:
        with self.lock:
            if self._stopped:
                return
            self._stopped = True
            self.status = "closed"
            self.pending_permission = None
            waits = list(self.pending_waits.values())
            terminals = list(self.terminals.values())
            peer = self.peer
            proc = self.proc
        for wait in waits:
            if not wait.event.is_set():
                wait.response = {"outcome": {"outcome": "cancelled"}}
                wait.event.set()
        for terminal in terminals:
            terminal.release()
        if peer is not None:
            peer.close()
        _terminate_process(proc)


class AgentManager:
    def __init__(self, repo_root: str, projects_root: str, python_executable: str):
        self.repo_root = Path(repo_root).resolve()
        self.projects_root = Path(projects_root).resolve()
        self.python_executable = python_executable
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    def list_agents(self) -> list[dict]:
        config = self._agent_config()
        return [self._describe_agent(agent_id, config.get(agent_id)) for agent_id in ("grok", "codex", "test")]

    def start(self, agent_id: str, project_id: str, permission_mode: str = "ask") -> dict:
        if not isinstance(agent_id, str) or not agent_id:
            raise RuntimeError("agentId is required.")
        if permission_mode not in {"ask", "allow-mapctl"}:
            raise RuntimeError("permissionMode must be ask or allow-mapctl.")
        spec = self._describe_agent(agent_id, self._agent_config().get(agent_id))
        if not spec["available"]:
            raise RuntimeError(spec["reason"] or f"{agent_id} is unavailable.")
        project_dir = self._project_dir(project_id)
        session = _Session(str(uuid.uuid4()), agent_id, project_id, project_dir, permission_mode)
        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(
                [spec["command"], *spec["args"]],
                cwd=str(self.repo_root),
                env=self._child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("Could not open the agent pipes.")
            peer = NdjsonPeer(proc.stdout, proc.stdin, on_close=lambda exc: self._agent_exited(session, exc))
            session.proc = proc
            session.peer = peer
            peer.set_request_handler(
                lambda method, params, request_id: self._on_agent_request(session, method, params, request_id)
            )
            peer.set_notification_handler(lambda method, params: self._on_agent_notification(session, method, params))
            threading.Thread(target=_drain_stderr, args=(session,), name="acp-stderr", daemon=True).start()
            peer.start()
            try:
                initialized = peer.request("initialize", _initialize_params(), timeout=20)
            except TimeoutError as exc:
                raise RuntimeError("Timed out during initialize after 20 seconds.") from exc
            if not isinstance(initialized, dict) or initialized.get("protocolVersion") != 1:
                version = initialized.get("protocolVersion") if isinstance(initialized, dict) else None
                raise RuntimeError(f"Unsupported ACP protocol version: {version}.")
            try:
                created = peer.request(
                    "session/new",
                    {"cwd": str(project_dir), "mcpServers": []},
                    timeout=30,
                )
            except TimeoutError as exc:
                raise RuntimeError("Timed out during session/new after 30 seconds.") from exc
            agent_session_id = created.get("sessionId") if isinstance(created, dict) else None
            if not isinstance(agent_session_id, str) or not agent_session_id:
                raise RuntimeError("Agent did not return a session id.")
            session.agent_session_id = agent_session_id
            capabilities = initialized.get("agentCapabilities") or {}
            session.capabilities = capabilities if isinstance(capabilities, dict) else {}
            session.status = "idle"
        except Exception as exc:
            session.shutdown()
            _terminate_process(proc)
            raise RuntimeError(_start_failure(agent_id, exc, session)) from exc
        with self._lock:
            self._sessions[session.id] = session
        return session.snapshot()

    def get(self, session_id: str) -> dict:
        return self._require(session_id).snapshot()

    def prompt(self, session_id: str, text: str, include_images: bool = True) -> dict:
        if not isinstance(text, str):
            raise RuntimeError("Prompt text must be a string.")
        session = self._require(session_id)
        with session.lock:
            if session.status == "running":
                raise RuntimeError("A prompt is already running.")
            if session.status != "idle":
                raise RuntimeError(f"Session is {session.status}.")
            session.messages.append({"role": "user", "text": text, "at": now_iso()})
            session.status = "running"
            session.stop_reason = None
            session.error = None
        threading.Thread(
            target=self._run_prompt,
            args=(session, text, bool(include_images)),
            name="acp-prompt",
            daemon=True,
        ).start()
        return session.snapshot()

    def cancel(self, session_id: str) -> dict:
        session = self._require(session_id)
        peer = session.peer
        if peer is not None and session.agent_session_id:
            try:
                peer.notify("session/cancel", {"sessionId": session.agent_session_id})
            except Exception as exc:
                session.fail(_with_stderr(session, exc))
        with session.lock:
            waits = list(session.pending_waits.values())
            session.pending_permission = None
        for wait in waits:
            if not wait.event.is_set():
                wait.response = {"outcome": {"outcome": "cancelled"}}
                wait.event.set()
        return session.snapshot()

    def resolve_permission(self, session_id: str, request_id: str, outcome: str) -> dict:
        if outcome not in {"allow", "deny"}:
            raise RuntimeError("Permission outcome must be allow or deny.")
        session = self._require(session_id)
        key = str(request_id)
        with session.lock:
            wait = session.pending_waits.get(key)
            if wait is None or wait.event.is_set():
                raise RuntimeError("No pending permission matches that request.")
            option_id = _select_option(wait.public["options"], outcome)
            if outcome == "allow":
                session.mapctl_allowed = True
            wait.response = {"outcome": {"outcome": "selected", "optionId": option_id}}
            if session.pending_permission and session.pending_permission.get("requestId") == key:
                session.pending_permission = None
            wait.event.set()
        return session.snapshot()

    def close(self, session_id: str) -> None:
        self._require(session_id).shutdown()

    def _agent_exited(self, session: _Session, exc: BaseException) -> None:
        message = _with_stderr(session, exc)
        with session.lock:
            if session._stopped or session.status == "closed":
                return
            waits = list(session.pending_waits.values())
            if session.status != "error":
                session.status = "error"
                session.error = message
                session.pending_permission = None
                session.messages.append({"role": "system", "text": message, "at": now_iso()})
        for wait in waits:
            if not wait.event.is_set():
                wait.error = ConnectionError(message)
                wait.event.set()

    def _require(self, session_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError("Session not found.")
        return session

    def _project_dir(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not project_id:
            raise RuntimeError("projectId is required.")
        store = ProjectStore(self.projects_root)
        try:
            directory = store.project_dir(project_id)
        except StoreError as exc:
            raise RuntimeError(exc.message) from exc
        if not (directory / "project.json").is_file():
            raise RuntimeError("Project not found.")
        return directory

    def _agent_config(self) -> dict:
        path = self.repo_root / "data" / "agents.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read data/agents.json: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("data/agents.json must be an object keyed by agent id.")
        return data

    def _describe_agent(self, agent_id: str, override: object) -> dict:
        if agent_id not in _DEFAULT_AGENTS:
            raise RuntimeError(f"Unknown agent {agent_id}.")
        default = _DEFAULT_AGENTS[agent_id]
        if override is None:
            override = {}
        if not isinstance(override, dict):
            raise RuntimeError(f"data/agents.json entry for {agent_id} must be an object.")
        command = default["command"] or self.python_executable
        if "command" in override:
            if not isinstance(override["command"], str) or not override["command"]:
                raise RuntimeError(f"data/agents.json command for {agent_id} must be a string.")
            command = override["command"]
        if "args" in override:
            args = override["args"]
            if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
                raise RuntimeError(f"data/agents.json args for {agent_id} must be a list of strings.")
        else:
            args = list(default["args"])
        if "enabled" in override:
            if not isinstance(override["enabled"], bool):
                raise RuntimeError(f"data/agents.json enabled for {agent_id} must be true or false.")
            enabled = override["enabled"]
            enabled_in_file = True
        else:
            enabled = bool(default["enabled"])
            enabled_in_file = False
        reason = None
        available = True
        if not enabled:
            available = False
            if agent_id == "codex" and not enabled_in_file:
                reason = "Codex stays disabled until data/agents.json sets codex.enabled to true."
            else:
                reason = "Disabled in data/agents.json."
        elif default["requires_binary"] and shutil.which(command) is None:
            available = False
            reason = f"{command} is not on PATH."
        return {
            "id": agent_id,
            "name": default["name"],
            "available": available,
            "reason": reason,
            "command": command,
            "args": list(args),
            "enabled": enabled,
        }

    def _child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        return _prefix_pythonpath(env, self.repo_root)

    def _run_prompt(self, session: _Session, text: str, include_images: bool) -> None:
        peer = session.peer
        if peer is None:
            session.fail("Agent connection is closed.")
            return
        try:
            blocks = self._prompt_blocks(session, text, include_images)
            result = peer.request(
                "session/prompt",
                {"sessionId": session.agent_session_id, "prompt": blocks},
                timeout=None,
            )
        except Exception as exc:
            session.fail(_with_stderr(session, exc))
            return
        stop_reason = result.get("stopReason") if isinstance(result, dict) else None
        session.complete_turn(stop_reason if isinstance(stop_reason, str) else None)

    def _prompt_blocks(self, session: _Session, text: str, include_images: bool) -> list[dict]:
        images = self._reference_images(session) if include_images else []
        prompt_caps = (session.capabilities or {}).get("promptCapabilities") or {}
        inline = bool(prompt_caps.get("image")) if isinstance(prompt_caps, dict) else False
        blocks: list[dict] = [
            {"type": "text", "text": self._instructions(session.project_id, [str(image["path"]) for image in images])},
            {"type": "text", "text": text},
        ]
        for image in images:
            blocks.append(
                {
                    "type": "resource_link",
                    "uri": image["path"].as_uri(),
                    "name": image["name"],
                    "mimeType": image["mime"],
                    "title": image["title"],
                }
            )
        if inline:
            for image in images:
                path = image["path"]
                if path.stat().st_size >= MAX_INLINE_IMAGE_BYTES:
                    continue
                blocks.append(
                    {
                        "type": "image",
                        "mimeType": image["mime"],
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                        "uri": path.as_uri(),
                    }
                )
        return blocks

    def _instructions(self, project_id: str, image_paths: list[str]) -> str:
        text = (
            "You edit a Minecraft Java 1.21.4 survival map. Change the plan, generate terrain, "
            "or export only by running this argv, not a shell string:\n"
            "\n"
            f"{self.python_executable} -m mcmap.cli --root {self.projects_root} --project {project_id} <command>\n"
            "\n"
            "Read docs/OPERATIONS.md in the repo. Do not write project.json yourself. "
            "Invalid blocks and coordinates are rejected by the CLI. "
            "Reference images are listed below as absolute paths."
        )
        if image_paths:
            text += "\n" + "\n".join(image_paths)
        return text

    def _reference_images(self, session: _Session) -> list[dict]:
        path = session.project_dir / "project.json"
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read the project: {exc}") from exc
        if not isinstance(project, dict):
            raise RuntimeError("Could not read the project.")
        directory = (session.project_dir / "assets").resolve()
        images = []
        for asset in project.get("assets") or []:
            if not isinstance(asset, dict) or not isinstance(asset.get("filename"), str):
                continue
            file_path = (directory / asset["filename"]).resolve()
            if not _is_within(file_path, directory) or not file_path.is_file():
                continue
            mime = asset.get("mime")
            if not isinstance(mime, str) or not mime:
                mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            title = asset.get("caption") if isinstance(asset.get("caption"), str) and asset.get("caption") else file_path.name
            images.append({"path": file_path, "name": file_path.name, "mime": mime, "title": title})
        return images

    def _on_agent_notification(self, session: _Session, method: str, params: dict) -> None:
        if method == "session/update":
            _record_update(session, params.get("update"))

    def _on_agent_request(self, session: _Session, method: str, params: dict, request_id: Any) -> Any:
        if method == "session/request_permission":
            return self._permission(session, request_id, params)
        if method == "fs/read_text_file":
            return {"content": self._read_file(session, params)}
        if method == "fs/write_text_file":
            raise RpcError(INTERNAL_ERROR, WRITE_DENIED)
        if method == "terminal/create":
            return {"terminalId": self._terminal_create(session, params)}
        if method == "terminal/output":
            return self._terminal_output(session, params)
        if method == "terminal/wait_for_exit":
            return self._terminal_wait(session, params)
        if method == "terminal/kill":
            self._terminal_get(session, params).kill()
            return {}
        if method == "terminal/release":
            terminal = self._terminal_pop(session, params)
            terminal.release()
            return {}
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _permission(self, session: _Session, request_id: Any, params: dict) -> dict:
        tool = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        title = tool.get("title") if isinstance(tool.get("title"), str) and tool.get("title") else "Permission requested"
        options = _normalize_options(params.get("options"))
        if not options:
            raise RpcError(INVALID_PARAMS, "Permission request did not include options.")
        wait = session.begin_permission(str(request_id), title, _permission_detail(tool), options)
        session.add_message("tool", title)
        wait.event.wait()
        session.finish_permission(str(request_id))
        if wait.error is not None:
            raise wait.error
        if not isinstance(wait.response, dict):
            raise RpcError(INTERNAL_ERROR, "Permission request was closed.")
        return wait.response

    def _read_file(self, session: _Session, params: dict) -> str:
        raw_path = params.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise RpcError(INVALID_PARAMS, "path is required.")
        path = Path(raw_path)
        if not path.is_absolute():
            raise RpcError(INTERNAL_ERROR, "Reading that path is not allowed.")
        resolved = path.resolve()
        roots = (
            session.project_dir.resolve(),
            (self.repo_root / "docs").resolve(),
            (self.repo_root / "schema").resolve(),
        )
        if not any(_is_within(resolved, root) for root in roots):
            raise RpcError(INTERNAL_ERROR, "Reading that path is not allowed.")
        if not resolved.exists():
            raise RpcError(INTERNAL_ERROR, "File not found.")
        if not resolved.is_file():
            raise RpcError(INTERNAL_ERROR, "Path is not a file.")
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RpcError(INTERNAL_ERROR, f"File could not be read: {exc}") from exc
        return _slice_text(text, params)

    def _terminal_create(self, session: _Session, params: dict) -> str:
        command = params.get("command")
        args = params.get("args") if params.get("args") is not None else []
        if not self._command_allowed(session, command, args):
            raise RpcError(INTERNAL_ERROR, COMMAND_DENIED)
        cwd = self._resolve_cwd(params.get("cwd"))
        limit = _output_limit(params.get("outputByteLimit") if "outputByteLimit" in params else None)
        env = self._child_env()
        for item in params.get("env") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("value"), str):
                env[item["name"]] = item["value"]
        _prefix_pythonpath(env, self.repo_root)
        try:
            proc = subprocess.Popen(
                [command, *args],
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            raise RpcError(INTERNAL_ERROR, f"Could not start the command: {exc}") from exc
        terminal = _Terminal(proc, limit)
        with session.lock:
            session.next_terminal += 1
            terminal_id = f"term-{session.next_terminal}"
            session.terminals[terminal_id] = terminal
        return terminal_id

    def _command_allowed(self, session: _Session, command: Any, args: Any) -> bool:
        if not _is_safe_mapctl(command, args, self.python_executable, self.projects_root, session.project_id):
            return False
        with session.lock:
            if session.permission_mode == "allow-mapctl":
                return True
            return session.mapctl_allowed

    def _resolve_cwd(self, raw: Any) -> Path:
        if raw is None or raw == "":
            return self.repo_root
        if not isinstance(raw, str):
            raise RpcError(INTERNAL_ERROR, COMMAND_DENIED)
        path = Path(raw)
        if not path.is_absolute():
            path = self.repo_root / path
        resolved = path.resolve()
        if not _is_within(resolved, self.repo_root):
            raise RpcError(INTERNAL_ERROR, COMMAND_DENIED)
        if not resolved.is_dir():
            raise RpcError(INTERNAL_ERROR, COMMAND_DENIED)
        return resolved

    def _terminal_get(self, session: _Session, params: dict) -> _Terminal:
        terminal_id = params.get("terminalId")
        if not isinstance(terminal_id, str):
            raise RpcError(INVALID_PARAMS, "Unknown terminal.")
        with session.lock:
            terminal = session.terminals.get(terminal_id)
        if terminal is None:
            raise RpcError(INVALID_PARAMS, "Unknown terminal.")
        return terminal

    def _terminal_pop(self, session: _Session, params: dict) -> _Terminal:
        terminal_id = params.get("terminalId")
        if not isinstance(terminal_id, str):
            raise RpcError(INVALID_PARAMS, "Unknown terminal.")
        with session.lock:
            terminal = session.terminals.pop(terminal_id, None)
        if terminal is None:
            raise RpcError(INVALID_PARAMS, "Unknown terminal.")
        return terminal

    def _terminal_output(self, session: _Session, params: dict) -> dict:
        text, truncated, exit_status = self._terminal_get(session, params).read()
        return {"output": text, "truncated": truncated, "exitStatus": exit_status}

    def _terminal_wait(self, session: _Session, params: dict) -> dict:
        return self._terminal_get(session, params).wait()


def _initialize_params() -> dict:
    return {
        "protocolVersion": 1,
        "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True},
        "clientInfo": {"name": "mcmap-studio", "title": "Minecraft Map Studio", "version": __version__},
    }


def _record_update(session: _Session, update: Any) -> None:
    if not isinstance(update, dict):
        return
    kind = update.get("sessionUpdate")
    message_id = update.get("messageId") if isinstance(update.get("messageId"), str) else None
    if kind == "agent_message_chunk":
        session.append_text("agent", _content_text(update.get("content")), message_id)
    elif kind == "agent_thought_chunk":
        session.append_text("system", _content_text(update.get("content")), message_id)
    elif kind in {"tool_call", "tool_call_update"}:
        title = update.get("title")
        if isinstance(title, str) and title:
            session.upsert_tool(update.get("toolCallId"), title)
    elif kind == "plan":
        lines = []
        for entry in update.get("entries") or []:
            if isinstance(entry, dict):
                lines.append(f"{entry.get('status', '')}: {entry.get('content', '')}".strip())
        if lines:
            session.add_message("system", "Plan\n" + "\n".join(lines))


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        kind = content.get("type")
        if kind in {None, "text"} and "text" in content:
            return str(content.get("text") or "")
        nested = content.get("content")
        if nested is not None and nested is not content:
            return _content_text(nested)
        return ""
    if isinstance(content, list):
        return "".join(_content_text(item) for item in content)
    return ""


def _permission_detail(tool: dict) -> str:
    raw = tool.get("rawInput")
    if isinstance(raw, dict):
        command = raw.get("command")
        args = raw.get("args")
        if isinstance(command, str) and isinstance(args, list):
            return " ".join([command, *[str(item) for item in args]])[:500]
        try:
            return json.dumps(raw, ensure_ascii=False)[:500]
        except TypeError:
            return str(raw)[:500]
    if raw is None:
        return str(tool.get("kind") or "")
    return str(raw)[:500]


def _normalize_options(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    options = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("optionId"), str) or not item.get("optionId"):
            continue
        options.append(
            {
                "optionId": item["optionId"],
                "name": str(item.get("name") or item["optionId"]),
                "kind": str(item.get("kind") or ""),
            }
        )
    return options


def _select_option(options: list[dict], outcome: str) -> str:
    needles = ("allow",) if outcome == "allow" else ("reject", "deny")
    for needle in needles:
        for option in options:
            if needle in option["kind"].lower() or needle in option["optionId"].lower():
                return option["optionId"]
    raise RuntimeError(f"The agent did not offer an option to {outcome}.")


def _slice_text(text: str, params: dict) -> str:
    if params.get("line") is None and params.get("limit") is None:
        return text
    rows = text.splitlines(keepends=True)
    start = 1
    if params.get("line") is not None:
        try:
            start = int(params["line"])
        except (TypeError, ValueError) as exc:
            raise RpcError(INVALID_PARAMS, "line must be an integer.") from exc
    if start < 1:
        start = 1
    selected = rows[start - 1 :]
    if params.get("limit") is not None:
        try:
            count = int(params["limit"])
        except (TypeError, ValueError) as exc:
            raise RpcError(INVALID_PARAMS, "limit must be an integer.") from exc
        if count < 0:
            count = 0
        selected = selected[:count]
    return "".join(selected)


def _is_safe_mapctl(command: Any, args: Any, python_executable: str, projects_root: Path, project_id: str) -> bool:
    # Safe mapctl is only the configured interpreter, module, root, and project.
    if not isinstance(command, str) or not command:
        return False
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return False
    if len(args) < 2 or args[0] != "-m" or args[1] != "mcmap.cli":
        return False
    if not _same_path(command, python_executable):
        return False
    flags = _long_options(args)
    root = flags.get("--root")
    project = flags.get("--project")
    if root is None or project is None:
        return False
    return project == project_id and _same_path(root, projects_root)


def _long_options(args: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and "=" in token[2:]:
            key, value = token.split("=", 1)
            found[key] = value
            index += 1
            continue
        if token.startswith("--") and index + 1 < len(args):
            found[token] = args[index + 1]
            index += 2
            continue
        index += 1
    return found


def _output_limit(raw: Any) -> int:
    if raw is None:
        return DEFAULT_OUTPUT_BYTES
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_OUTPUT_BYTES
    if limit < 0:
        return 0
    return limit


def _same_path(left: str | Path, right: str | Path) -> bool:
    left_path = Path(left)
    right_path = Path(right)
    try:
        return os.path.samefile(left_path, right_path)
    except OSError:
        return left_path.resolve() == right_path.resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _prefix_pythonpath(env: dict[str, str], repo_root: Path) -> dict[str, str]:
    server = str(repo_root / "server")
    current = [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part and part != server]
    env["PYTHONPATH"] = os.pathsep.join([server, *current]) if current else server
    return env


def _trim_utf8_start(data: bytes) -> bytes:
    index = 0
    while index < len(data) and (data[index] & 0xC0) == 0x80:
        index += 1
    return data[index:]


def _exit_status(code: int | None) -> dict | None:
    if code is None:
        return None
    if code < 0:
        number = -code
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = str(number)
        return {"exitCode": None, "signal": name}
    return {"exitCode": code, "signal": None}


def _terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return


def _drain_stderr(session: _Session) -> None:
    stream = session.proc.stderr if session.proc is not None else None
    if stream is None:
        return
    while True:
        try:
            chunk = stream.readline()
        except Exception:
            return
        if not chunk:
            return
        with session.stderr_lock:
            session.stderr_buf.extend(chunk)
            if len(session.stderr_buf) > 8192:
                del session.stderr_buf[:-8192]


def _with_stderr(session: _Session, exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    stderr = session.stderr_text().strip()
    if stderr and stderr not in message:
        return f"{message}\n{stderr[-2000:]}"
    return message


def _start_failure(agent_id: str, exc: BaseException, session: _Session) -> str:
    if isinstance(exc, RuntimeError):
        text = str(exc).strip() or "Agent failed to start."
    else:
        text = str(exc).strip() or exc.__class__.__name__
    stderr = session.stderr_text().strip()
    if stderr and stderr not in text:
        text = f"{text}\n{stderr[-2000:]}"
    if text.startswith("Could not start"):
        return text
    return f"Could not start {agent_id}: {text}"
