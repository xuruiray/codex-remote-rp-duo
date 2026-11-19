"""Own the Codex app-server subprocess and its line-oriented RPC transport."""

import itertools
import json
import logging
import queue
import re
import subprocess
import threading
import tomllib
from pathlib import Path


class RpcError(RuntimeError):
    def __init__(self, error):
        if not isinstance(error, dict):
            error = {}
        super().__init__(error.get("message", "Codex 请求失败"))
        self.code = error.get("code")


class AppServer:
    def __init__(self, executable, workspace, on_notification, on_disconnect, on_request=None):
        self._ids = itertools.count(1)
        self._pending = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._running = True
        self._on_notification = on_notification
        self._on_disconnect = on_disconnect
        self._on_request = on_request
        self._process = subprocess.Popen(
            [executable, "app-server", "--disable", "apps", "--disable", "plugins",
             "--disable", "hooks", *_disabled_servers()],
            cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self._reader = threading.Thread(target=self._read, name="codex-rpc", daemon=True)
        self._reader.start()

    @property
    def connected(self):
        with self._lock:
            return self._running and self._process.poll() is None

    def call(self, method, params):
        recipient = queue.Queue(1)
        with self._lock:
            if not self._running:
                raise RuntimeError("Codex 进程已退出")
            key = next(self._ids)
            self._pending[key] = recipient
        try:
            self._send({"id": key, "method": method, "params": params})
            try:
                response = recipient.get(timeout=25)
            except queue.Empty as error:
                raise RuntimeError("Mac 上的 Codex 响应超时") from error
            if "error" in response:
                raise RpcError(response["error"])
            if "result" not in response:
                raise RuntimeError("Mac 上的 Codex 返回了无效响应")
            return response["result"]
        finally:
            with self._lock:
                self._pending.pop(key, None)

    def notify(self, method):
        self._send({"method": method})

    def reply(self, ident, result):
        self._send({"id": ident, "result": result})

    def close(self):
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        finally:
            if threading.current_thread() != self._reader:
                self._reader.join(timeout=2)
            self._process.stdin.close()
            self._process.stdout.close()

    def _send(self, value):
        with self._write_lock:
            try:
                self._process.stdin.write(json.dumps(value) + "\n")
                self._process.stdin.flush()
            except (OSError, ValueError) as error:
                raise RuntimeError("Codex 进程已断开") from error

    def _read(self):
        try:
            for line in self._process.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self._dispatch(value)
                except (ValueError, KeyError, TypeError, AttributeError):
                    logging.warning("Ignored malformed app-server message")
        finally:
            with self._lock:
                self._running = False
                waiting = list(self._pending.values())
                self._pending.clear()
            for recipient in waiting:
                recipient.put_nowait({"error": {"message": "Codex 进程已退出"}})
            self._on_disconnect()

    def _dispatch(self, value):
        if "id" in value and "method" in value:
            if value["method"] == "item/tool/requestUserInput" and self._on_request is not None:
                try:
                    self._on_request(value["id"], value["params"])
                except (ValueError, KeyError, TypeError) as error:
                    self._send({"id": value["id"], "error": {"code": -32602, "message": str(error)}})
                return
            reply = {"decision": "decline"} if value["method"].endswith("/requestApproval") else None
            if reply is not None:
                self._send({"id": value["id"], "result": reply})
            else:
                self._send({"id": value["id"], "error": {
                    "code": -32601, "message": "Unsupported client request",
                }})
        elif "id" in value:
            with self._lock:
                recipient = self._pending.pop(value["id"], None)
            if recipient is not None:
                recipient.put_nowait(value)
        else:
            self._on_notification(value.get("method"), value.get("params", {}))


def _disabled_servers():
    config_path = Path.home() / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.is_file() else {}
    overrides = []
    for name in config.get("mcp_servers", {}):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise RuntimeError(f"Unsupported MCP configuration name: {name}")
        overrides.extend(("-c", f"mcp_servers.{name}.enabled=false"))
    return overrides
