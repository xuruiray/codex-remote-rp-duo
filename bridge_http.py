"""Serve the Duo web client and authenticated session requests."""

import hmac
import json
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


WEB = Path(__file__).resolve().parent / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/changes-panel.js": ("changes-panel.js", "application/javascript; charset=utf-8"),
    "/conversation.js": ("conversation.js", "application/javascript; charset=utf-8"),
    "/diff-view.js": ("diff-view.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/vendor/markdown-it.min.js": ("vendor/markdown-it.min.js", "application/javascript; charset=utf-8"),
    "/assets/chatgpt-icon.png": ("assets/chatgpt-icon.png", "image/png"),
}


def make_handler(codex, token):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def write_bytes(self, status, body, mime):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' blob:; frame-src 'none'; "
                             "object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def reply(self, status, value):
            self.write_bytes(status, json.dumps(value, ensure_ascii=False).encode(), "application/json")

        def authorized(self):
            accepted = hmac.compare_digest(
                self.headers.get("Authorization", "").encode(), f"Bearer {token}".encode()
            )
            if not accepted:
                self.reply(401, {"error": "请在 Mac 上重新运行 USB 连接"})
            return accepted

        def do_GET(self):
            url = urlsplit(self.path)
            path = url.path
            if path in ASSETS:
                name, mime = ASSETS[path]
                self.write_bytes(200, (WEB / name).read_bytes(), mime)
            elif path == "/api/state":
                if self.authorized():
                    panel = parse_qs(url.query).get("panel", [""])[0]
                    self.reply(200, codex.snapshot(
                        include_messages=panel != "bottom", include_controls=panel != "top",
                        include_following=panel == "top",
                    ))
            else:
                self.reply(404, {"error": "页面不存在"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if not self.authorized():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 64000:
                    raise ValueError("任务内容太长")
                data = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(data, dict):
                    raise ValueError("请求格式无效")
                if path == "/api/prompt":
                    value = data.get("text")
                    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
                        raise ValueError("请输入 1 到 8000 字的任务")
                    submission = data.get("submission")
                    if submission is not None:
                        submission = str(uuid.UUID(submission)) if isinstance(submission, str) else ""
                        if not submission:
                            raise ValueError("消息编号无效")
                    codex.start_prompt(value, data.get("model"), data.get("effort"), submission,
                                       data.get("thread_id"))
                elif path == "/api/stop":
                    codex.interrupt(data.get("thread_id"), data.get("turn_id"))
                elif path == "/api/new":
                    codex.reset()
                elif path == "/api/threads":
                    search = data.get("search", "")
                    cursor = data.get("cursor")
                    if not isinstance(search, str) or len(search) > 150:
                        raise ValueError("搜索词过长")
                    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 1000):
                        raise ValueError("分页位置无效")
                    self.reply(200, codex.list_threads(
                        data.get("archived") is True, search, cursor, pinned=data.get("pinned") is True,
                    ))
                    return
                elif path == "/api/history":
                    before = data.get("before")
                    if not isinstance(before, str) or not 1 <= len(before) <= 256:
                        raise ValueError("历史位置无效")
                    self.reply(200, codex.older_history(before, data.get("thread_id")))
                    return
                elif path == "/api/file-diff":
                    filename = data.get("path")
                    if not isinstance(filename, str) or not filename:
                        raise ValueError("文件路径无效")
                    self.reply(200, codex.get_diff(data.get("thread_id"), data.get("turn_id"), filename))
                    return
                elif path == "/api/attachment":
                    index = data.get("index")
                    message_id = data.get("message_id")
                    if type(index) is not int or not isinstance(message_id, str):
                        raise ValueError("附件无效")
                    content, mime = codex.get_attachment(data.get("thread_id"), message_id, index)
                    self.write_bytes(200, content, mime)
                    return
                elif path in {"/api/select", "/api/rename", "/api/archive", "/api/unarchive", "/api/pin"}:
                    supplied_id = data.get("id")
                    if not isinstance(supplied_id, str):
                        raise ValueError("会话 ID 无效")
                    thread_id = str(uuid.UUID(supplied_id))
                    if path == "/api/select":
                        codex.select(thread_id, data.get("archived") is True,
                                     retry_history=data.get("retry_history") is True)
                    elif path == "/api/pin":
                        codex.pin(thread_id, data.get("pinned") is True)
                    elif path == "/api/rename":
                        name = data.get("name", "")
                        if not isinstance(name, str) or not name.strip() or len(name) > 120:
                            raise ValueError("请输入 1 到 120 字的会话名称")
                        codex.update_thread(thread_id, "name/set", name.strip())
                    else:
                        codex.update_thread(thread_id, path.removeprefix("/api/"))
                else:
                    self.reply(404, {"error": "操作不存在"})
                    return
            except (ValueError, RuntimeError, OSError) as error:
                self.reply(409, {"error": str(error)})
                return
            self.reply(200, {"ok": True})

        def log_request(self, code="-", size="-"):
            if code == 500:
                super().log_request(code, size)

    return Handler
