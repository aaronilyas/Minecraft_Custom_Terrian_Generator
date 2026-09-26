"""Newline-delimited JSON-RPC 2.0 for the Agent Client Protocol.

Requests are handled off the reader thread. session/prompt stays open while the
agent calls client methods, and those handlers may block for a user or a
subprocess without stalling the reader.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future
from typing import Any, BinaryIO, Callable


METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class NdjsonPeer:
    def __init__(self, reader: BinaryIO, writer: BinaryIO, on_close: Callable[[BaseException], None] | None = None):
        self._reader = reader
        self._writer = writer
        self._on_close = on_close
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[Any, Future] = {}
        self._next_id = 0
        self._closed = threading.Event()
        self._request_handler: Callable[[str, dict, Any], Any] | None = None
        self._notification_handler: Callable[[str, dict], None] | None = None
        self._thread = threading.Thread(target=self._read_loop, name="acp-ndjson", daemon=True)

    def set_request_handler(self, handler: Callable[[str, dict, Any], Any]) -> None:
        self._request_handler = handler

    def set_notification_handler(self, handler: Callable[[str, dict], None]) -> None:
        self._notification_handler = handler

    def start(self) -> None:
        self._thread.start()

    def request(self, method: str, params: dict | None = None, timeout: float | None = None) -> Any:
        if self._closed.is_set():
            raise ConnectionError("Agent connection is closed.")
        request_id = self._allocate_id()
        future: Future = Future()
        with self._pending_lock:
            if self._closed.is_set():
                raise ConnectionError("Agent connection is closed.")
            self._pending[request_id] = future
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        try:
            message = future.result(timeout=timeout)
        except TimeoutError:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        if not isinstance(message, dict):
            raise RpcError(INTERNAL_ERROR, "Agent returned a response that is not an object.")
        if "error" in message and message["error"] is not None:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise RpcError(
                int(error.get("code", INTERNAL_ERROR)),
                str(error.get("message") or "RPC error"),
                error.get("data"),
            )
        return message.get("result")

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        self._fail_all(ConnectionError("Agent connection is closed."))
        with self._write_lock:
            try:
                self._writer.close()
            except Exception:
                pass

    def _allocate_id(self) -> int:
        with self._pending_lock:
            self._next_id += 1
            return self._next_id

    def _send(self, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        write_error: BaseException | None = None
        with self._write_lock:
            if self._closed.is_set() and "method" in message:
                raise ConnectionError("Agent connection is closed.")
            try:
                self._writer.write(payload)
                self._writer.flush()
            except Exception as exc:
                write_error = ConnectionError(f"Failed to write to the agent: {exc}")
        if write_error is not None:
            self._fail_all(write_error)
            raise write_error

    def _fail_all(self, exc: BaseException) -> None:
        with self._pending_lock:
            first = not self._closed.is_set()
            self._closed.set()
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)
        if first and self._on_close is not None:
            try:
                self._on_close(exc)
            except Exception:
                return

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                line = self._reader.readline()
                if not line:
                    break
                self._handle_line(line)
        except Exception as exc:
            self._fail_all(ConnectionError(f"Agent connection failed: {exc}"))
            return
        self._fail_all(ConnectionError("Agent connection closed."))

    def _handle_line(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return
        if "method" in message:
            if message.get("id") is not None:
                self._dispatch_request(message)
            else:
                self._dispatch_notification(message)
            return
        if "id" not in message:
            return
        with self._pending_lock:
            future = self._pending.pop(message["id"], None)
        if future is not None and not future.done():
            future.set_result(message)

    def _dispatch_notification(self, message: dict) -> None:
        handler = self._notification_handler
        if handler is None:
            return
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        try:
            handler(str(message.get("method") or ""), params)
        except Exception:
            return

    def _dispatch_request(self, message: dict) -> None:
        # A handler may block on session/request_permission or terminal/wait_for_exit.
        # Keeping that off this thread is what lets the matching response arrive.
        threading.Thread(
            target=self._run_request,
            args=(message,),
            name="acp-request",
            daemon=True,
        ).start()

    def _run_request(self, message: dict) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        try:
            handler = self._request_handler
            if handler is None:
                raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
            result = handler(method, params, request_id)
            if result is None:
                result = {}
            self._reply(request_id, result=result)
        except RpcError as exc:
            self._reply(request_id, error={"code": exc.code, "message": exc.message})
        except Exception as exc:
            self._reply(request_id, error={"code": INTERNAL_ERROR, "message": str(exc)})

    def _reply(self, request_id: Any, result: Any = None, error: dict | None = None) -> None:
        if self._closed.is_set():
            return
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            body["error"] = error
        else:
            body["result"] = result
        try:
            self._send(body)
        except Exception:
            return
