"""Deterministic ACP agent used by tests and the agent panel.

Run with ``python -m mcmap.acp.test_agent``. Speaks newline-delimited JSON-RPC.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from mcmap.acp.rpc import INVALID_PARAMS, NdjsonPeer, RpcError


class TestAgent:
    def __init__(self, reader, writer):
        self.peer = NdjsonPeer(reader, writer)
        self.peer.set_request_handler(self._handle_request)
        self.peer.set_notification_handler(self._handle_notification)
        self.lock = threading.Lock()
        self.sessions: dict[str, dict] = {}
        self.cancel_events: dict[str, threading.Event] = {}
        self.image_enabled = os.environ.get("MCMAP_TEST_AGENT_IMAGE", "1") != "0"

    def serve(self) -> None:
        self.peer.start()
        self.peer._thread.join()

    def _handle_notification(self, method: str, params: dict) -> None:
        if method != "session/cancel":
            return
        session_id = str(params.get("sessionId") or "")
        with self.lock:
            event = self.cancel_events.get(session_id)
        if event is not None:
            event.set()

    def _handle_request(self, method: str, params: dict, _request_id: Any) -> Any:
        if method == "initialize":
            return self._initialize()
        if method == "session/new":
            return self._new_session(params)
        if method == "session/prompt":
            return self._prompt(params)
        raise RpcError(-32601, f"Method not found: {method}")

    def _initialize(self) -> dict:
        return {
            "protocolVersion": 1,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {
                    "image": self.image_enabled,
                    "audio": False,
                    "embeddedContext": True,
                },
                "mcpCapabilities": {"http": False, "sse": False},
            },
            "agentInfo": {
                "name": "mcmap-test-agent",
                "title": "Minecraft Map Studio Test Agent",
                "version": "1.0.0",
            },
            "authMethods": [],
        }

    def _new_session(self, params: dict) -> dict:
        session_id = f"test-{uuid.uuid4()}"
        with self.lock:
            self.sessions[session_id] = {"cwd": params.get("cwd") or os.getcwd()}
            self.cancel_events[session_id] = threading.Event()
        return {"sessionId": session_id}

    def _install_cancel(self, session_id: str) -> threading.Event:
        event = threading.Event()
        with self.lock:
            self.cancel_events[session_id] = event
        return event

    def _prompt(self, params: dict) -> dict:
        session_id = str(params.get("sessionId") or "")
        blocks = params.get("prompt") if isinstance(params.get("prompt"), list) else []
        event = self._install_cancel(session_id)
        try:
            return self._dispatch_prompt(session_id, blocks, event)
        except RpcError as exc:
            self._say(session_id, exc.message)
            return {"stopReason": "end_turn"}
        except Exception as exc:
            self._say(session_id, str(exc))
            return {"stopReason": "end_turn"}

    def _dispatch_prompt(self, session_id: str, blocks: list, event: threading.Event) -> dict:
        user_text = _last_text(blocks)
        full_text = "\n".join(_all_text(blocks))
        if "CANCEL_ME" in user_text:
            self._say(session_id, "working")
            if event.wait(timeout=30):
                return {"stopReason": "cancelled"}
            self._say(session_id, "cancel timed out")
            return {"stopReason": "end_turn"}
        if "NEED_PERMISSION" in user_text:
            return self._need_permission(session_id, full_text)
        if "WRITE_FILE:" in user_text:
            return self._write_file(session_id)
        if "READ_FILE:" in user_text:
            return self._read_file(session_id, user_text)
        if "APPLY_JSON:" in user_text:
            return self._apply(session_id, user_text, full_text)
        if "CHUNK_ME" in user_text:
            self._say(session_id, "hel")
            self._say(session_id, "lo")
            return {"stopReason": "end_turn"}
        if "UNSAFE_COMMAND" in user_text:
            return self._unsafe(session_id)
        images = sum(1 for block in blocks if isinstance(block, dict) and block.get("type") == "image")
        links = sum(1 for block in blocks if isinstance(block, dict) and block.get("type") == "resource_link")
        self._say(session_id, f"text_length={len(user_text)} image={images} resource_link={links}")
        return {"stopReason": "end_turn"}

    def _need_permission(self, session_id: str, full_text: str) -> dict:
        try:
            python_executable, root, project = _mapctl_invocation(full_text)
            raw = {
                "command": python_executable,
                "args": ["-m", "mcmap.cli", "--root", root, "--project", project, "get"],
            }
        except Exception:
            raw = {"command": "python", "args": ["-m", "mcmap.cli", "get"]}
        result = self.peer.request(
            "session/request_permission",
            {
                "sessionId": session_id,
                "toolCall": {
                    "toolCallId": "mapctl-get",
                    "title": "mapctl get",
                    "kind": "execute",
                    "status": "pending",
                    "rawInput": raw,
                },
                "options": [
                    {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"},
                ],
            },
        )
        outcome = result.get("outcome") if isinstance(result, dict) else {}
        if not isinstance(outcome, dict):
            outcome = {}
        if outcome.get("outcome") == "selected" and "allow" in str(outcome.get("optionId") or "").lower():
            self._say(session_id, "allowed")
        else:
            self._say(session_id, "denied")
        return {"stopReason": "end_turn"}

    def _write_file(self, session_id: str) -> dict:
        with self.lock:
            cwd = self.sessions.get(session_id, {}).get("cwd") or os.getcwd()
        path = str(Path(cwd) / "project.json")
        self.peer.request(
            "fs/write_text_file",
            {"sessionId": session_id, "path": path, "content": "hacked"},
        )
        self._say(session_id, "wrote")
        return {"stopReason": "end_turn"}

    def _read_file(self, session_id: str, user_text: str) -> dict:
        path = user_text.split("READ_FILE:", 1)[1].strip()
        result = self.peer.request("fs/read_text_file", {"sessionId": session_id, "path": path})
        content = result.get("content") if isinstance(result, dict) else ""
        self._say(session_id, str(content or ""))
        return {"stopReason": "end_turn"}

    def _apply(self, session_id: str, user_text: str, full_text: str) -> dict:
        python_executable, root, project = _mapctl_invocation(full_text)
        payload_text = user_text.split("APPLY_JSON:", 1)[1].lstrip()
        payload, _ = json.JSONDecoder().raw_decode(payload_text)
        if not isinstance(payload, dict):
            raise RpcError(INVALID_PARAMS, "APPLY_JSON payload must be an object.")
        created = self.peer.request(
            "terminal/create",
            {
                "sessionId": session_id,
                "command": python_executable,
                "args": [
                    "-m",
                    "mcmap.cli",
                    "--root",
                    root,
                    "--project",
                    project,
                    "apply",
                    "--json",
                    json.dumps(payload),
                ],
            },
        )
        terminal_id = created.get("terminalId") if isinstance(created, dict) else None
        if not isinstance(terminal_id, str):
            raise RpcError(INVALID_PARAMS, "terminal/create did not return a terminal id.")
        try:
            self.peer.request(
                "terminal/wait_for_exit",
                {"sessionId": session_id, "terminalId": terminal_id},
            )
            output = self.peer.request(
                "terminal/output",
                {"sessionId": session_id, "terminalId": terminal_id},
            )
        finally:
            try:
                self.peer.request(
                    "terminal/release",
                    {"sessionId": session_id, "terminalId": terminal_id},
                )
            except Exception:
                pass
        text = output.get("output") if isinstance(output, dict) else ""
        self._say(session_id, str(text or "exit"))
        return {"stopReason": "end_turn"}

    def _unsafe(self, session_id: str) -> dict:
        created = self.peer.request(
            "terminal/create",
            {"sessionId": session_id, "command": "/bin/echo", "args": ["hello"]},
        )
        terminal_id = created.get("terminalId") if isinstance(created, dict) else None
        if isinstance(terminal_id, str):
            try:
                self.peer.request("terminal/release", {"sessionId": session_id, "terminalId": terminal_id})
            except Exception:
                pass
        self._say(session_id, "ran")
        return {"stopReason": "end_turn"}

    def _say(self, session_id: str, text: str) -> None:
        self.peer.notify(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                },
            },
        )


def _all_text(blocks: list) -> list[str]:
    texts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
    return texts


def _last_text(blocks: list) -> str:
    texts = _all_text(blocks)
    return texts[-1] if texts else ""


def _mapctl_invocation(text: str) -> tuple[str, str, str]:
    needle = " -m mcmap.cli --root "
    for line in text.splitlines():
        index = line.find(needle)
        if index < 0:
            continue
        python_executable = line[:index].strip()
        parts = line[index + len(needle) :].strip().split()
        if len(parts) >= 3 and parts[1] == "--project" and python_executable:
            return python_executable, parts[0], parts[2]
    raise RpcError(INVALID_PARAMS, "Prompt did not include the mapctl argv.")


def main() -> None:
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    sys.stdout = sys.stderr
    TestAgent(reader, writer).serve()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"test agent failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
