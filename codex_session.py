"""Manage the selected Codex chat, live turn, and history on behalf of the Duo."""

import json
import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from app_server import AppServer, RpcError
from change_set import TurnChanges
from session_messages import MAX_DETAIL, export_entry, read_attachment_image, session_entry, shorten


PAGE_SIZE = 50
PINNED_SECTION_NAMES = {"pinned", "置顶", "置顶会话"}


class Codex:
    def __init__(self, workspace, executable, session_file=None):
        self.workspace = workspace
        self.session_file = session_file
        self.lock = threading.RLock()
        self.action = threading.Lock()
        self.thread = None
        self.loaded = False
        self.thread_name = None
        self.thread_workspace = workspace
        self.archived = False
        self.turn = None
        self.busy = False
        self.messages = []
        self.history_cursor = None
        self.history_error = False
        self.submissions = OrderedDict()
        self.starting_submission = None
        self.activity = []
        self.changes = TurnChanges(workspace)
        self._rpc = AppServer(executable, workspace, self.notify, self.disconnected)
        try:
            self._initialize()
        except BaseException:
            self.close()
            raise

    def _initialize(self):
        self._rpc.call("initialize", {
            "clientInfo": {"name": "duo_codex", "title": "Codex", "version": "0.1.15"},
        })
        self._rpc.notify("initialized")
        models = []
        cursor = None
        while True:
            page = self._rpc.call("model/list", {"includeHidden": False, "limit": 50, "cursor": cursor})
            models.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if not models:
            raise RuntimeError("当前 Codex 账号没有可用模型")
        preferred = next((item for item in models if item.get("isDefault")), models[0])
        self.model = preferred["model"]
        self.models = {
            item["model"]: {
                "id": item["model"],
                "label": item["displayName"],
                "default_effort": item["defaultReasoningEffort"],
                "efforts": [option["reasoningEffort"] for option in item["supportedReasoningEfforts"]],
            }
            for item in models
        }
        if self.session_file and self.session_file.is_file():
            try:
                selection = json.loads(self.session_file.read_text())
                self.select(str(uuid.UUID(selection["id"])), selection["archived"] is True)
            except (KeyError, TypeError, ValueError, OSError, RuntimeError):
                self.add_event("上次打开的会话暂时无法恢复，可从全部会话重新打开")

    def save_selection(self):
        if self.session_file is None:
            return
        try:
            if not self.thread:
                self.session_file.unlink(missing_ok=True)
                return
            temp = self.session_file.with_suffix(".tmp")
            descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"id": self.thread, "archived": self.archived}, stream)
            temp.replace(self.session_file)
        except OSError:
            self.add_event("Mac 无法保存上次打开的会话")

    def close(self):
        self._rpc.close()

    def disconnected(self):
        with self.lock:
            self.busy = False
            self.turn = None
            self.add_event("Codex 进程已退出，请在 Mac 重新启动连接")

    def add_event(self, text):
        self.activity = (self.activity + [text[:320]])[-16:]

    def entry(self, item_id, create):
        for message in reversed(self.messages):
            if message.get("id") == item_id:
                return message
        message = create()
        self.messages.append(message)
        return message

    def update_item(self, item, complete):
        incoming = session_entry(item, complete)
        if incoming is None:
            return
        existing = self.entry(item["id"], lambda: incoming)
        if incoming["role"] == "trace":
            for key in ("text", "parts", "output", "diff"):
                if not incoming.get(key) and existing.get(key):
                    incoming[key] = existing[key]
        existing.update(incoming)

    def notify(self, method, params):
        with self.lock:
            if not self.thread or params.get("threadId") != self.thread:
                return
            if method == "turn/started":
                if self.starting_submission:
                    self.submissions[self.starting_submission] = {"status": "sent"}
                self.turn = params["turn"]["id"]
                self.changes.turn_id = self.turn
                self.add_event("Codex 正在 Mac 上运行")
            elif method == "turn/diff/updated" and params["turnId"] == self.changes.turn_id:
                self.changes.apply_diff(params["diff"])
            elif method == "item/agentMessage/delta":
                message = self.entry(params["itemId"], lambda: {
                    "role": "assistant", "text": "", "id": params["itemId"], "complete": False,
                })
                message["text"] += params["delta"]
            elif method == "item/reasoning/summaryTextDelta":
                item_id = params["itemId"]
                trace = self.entry(item_id, lambda: session_entry({"type": "reasoning", "id": item_id}, False))
                index = params["summaryIndex"]
                parts = trace["parts"]
                parts[index] = parts.get(index, "") + params["delta"]
                trace["text"] = "\n\n".join(parts[i] for i in sorted(parts))
            elif method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
                is_command = method.startswith("item/commandExecution/")
                item = {"type": "commandExecution" if is_command else "fileChange", "id": params["itemId"]}
                trace = self.entry(item["id"], lambda: session_entry(item, False))
                if len(trace.get("output", "")) < MAX_DETAIL:
                    trace["output"] = shorten(trace.get("output", "") + params["delta"])
            elif method == "item/fileChange/patchUpdated":
                item = {"type": "fileChange", "id": params["itemId"], "changes": params["changes"]}
                self.update_item(item, False)
                if params["turnId"] == self.changes.turn_id:
                    self.changes.apply_item(item)
            elif method == "turn/plan/updated":
                markers = {"pending": "○", "inProgress": "◐", "completed": "✓"}
                steps = "\n".join(f"{markers.get(step['status'], '○')} {step['step']}" for step in params["plan"])
                text = "\n\n".join(part for part in (params.get("explanation"), steps) if part)
                self.update_item({"type": "plan", "id": params["turnId"] + ":plan", "text": text}, True)
            elif method in {"item/started", "item/completed"}:
                item = params["item"]
                kind = item.get("type")
                if kind != "userMessage":
                    self.update_item(item, method == "item/completed")
                if kind == "fileChange" and params["turnId"] == self.changes.turn_id:
                    self.changes.apply_item(item)
                if kind in {"commandExecution", "fileChange"}:
                    label = "终端" if kind == "commandExecution" else "文件"
                    detail = item.get("command") or "工作区变更"
                    prefix = "开始" if method == "item/started" else "完成"
                    self.add_event(f"{prefix} · {label} · {detail}")
            elif method == "turn/completed":
                turn = params["turn"]
                error = turn.get("error") or {}
                status = {"completed": "任务完成", "interrupted": "任务已停止",
                          "failed": "任务失败"}.get(turn.get("status"), "任务已结束")
                self.add_event(f"{status} · {error['message']}" if error.get("message") else status)
                self.busy = False
                self.turn = None

    def run_prompt(self, text, model, effort, submission, workspace):
        try:
            if not self.loaded:
                options = {
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "model": model,
                }
                if self.thread:
                    method = "thread/resume"
                    options["threadId"] = self.thread
                    options["excludeTurns"] = True
                    if workspace != self.thread_workspace:
                        options["cwd"] = str(workspace)
                else:
                    method = "thread/start"
                    options["cwd"] = str(self.workspace)
                response = self._rpc.call(method, options)
                with self.lock:
                    self.thread = response["thread"]["id"]
                    self.loaded = True
                    self.save_selection()
            request = {
                "threadId": self.thread,
                "cwd": str(workspace),
                "model": model,
                "summary": "detailed",
                "input": [{"type": "text", "text": text, "text_elements": []}],
            }
            if effort is not None:
                request["effort"] = effort
            with self.lock:
                self.starting_submission = submission
            self._rpc.call("turn/start", request)
            with self.lock:
                self.submissions[submission] = {"status": "sent"}
        except (OSError, RuntimeError) as error:
            with self.lock:
                if self.submissions[submission]["status"] != "sent":
                    self.add_event(str(error))
                    self.submissions[submission] = {"status": "failed", "error": str(error)}
                    self.messages[:] = [message for message in self.messages if message["id"] != submission]
                    self.busy = False
                    self.turn = None
        finally:
            with self.lock:
                if self.starting_submission == submission:
                    self.starting_submission = None

    def start_prompt(self, text, model=None, effort=None, submission=None, expected_thread=None):
        model = self.model if model is None else model
        if not isinstance(model, str) or model not in self.models:
            raise ValueError("这个 Codex 账号当前无法使用所选模型")
        if effort is not None and effort not in self.models[model]["efforts"]:
            raise ValueError("所选模型不支持此推理强度")
        with self.action, self.lock:
            if submission in self.submissions:
                return
            if submission is not None and self.thread != expected_thread:
                raise ValueError("会话已切换，请确认要发送到的会话")
            if self.busy or self.archived or not self._rpc.connected:
                raise ValueError("当前无法接收新任务")
            submission = submission or str(uuid.uuid4())
            self.submissions[submission] = {"status": "sending"}
            if len(self.submissions) > 32:
                self.submissions.popitem(last=False)
            self.busy = True
            workspace = self.thread_workspace
            if not workspace.is_dir():
                workspace = self.workspace
                self.add_event(f"原工作目录已不存在，本轮使用 {workspace.name}")
            self.changes = TurnChanges(workspace)
            self.messages.append({"role": "user", "id": submission, "text": text})
            self.add_event("任务已发往 Mac")
        threading.Thread(target=self.run_prompt, args=(text, model, effort, submission, workspace),
                         daemon=True).start()

    def interrupt(self):
        with self.lock:
            if not self.turn:
                raise ValueError("还没有可停止的任务")
            params = {"threadId": self.thread, "turnId": self.turn}
        self._rpc.call("turn/interrupt", params)

    def reset(self):
        with self.action:
            self.require_idle()
            with self.lock:
                self.thread = None
                self.loaded = False
                self.thread_name = None
                self.thread_workspace = self.workspace
                self.archived = False
                self.messages.clear()
                self.history_cursor = None
                self.history_error = False
                self.changes = TurnChanges(self.workspace)
                self.activity.clear()
                self.save_selection()

    def require_idle(self):
        with self.lock:
            if self.busy:
                raise ValueError("请等待当前任务完成，或先停止任务")

    def pinned_section(self, create=False):
        cursor = None
        while True:
            try:
                page = self._rpc.call("threadSection/list", {"limit": 50, "cursor": cursor})
            except RpcError as error:
                if error.code == -32601:
                    raise ValueError("置顶会话需要 Mac 的桌面版 Codex 组件") from error
                raise
            for section in page["data"]:
                if section["name"].casefold() in PINNED_SECTION_NAMES:
                    return section["id"]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if create:
            return self._rpc.call("threadSection/create", {"name": "Pinned"})["section"]["id"]
        return None

    def pin(self, thread_id, pinned):
        with self.action:
            section_id = self.pinned_section(create=pinned)
            if not pinned:
                thread = self._rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
                if not section_id or (thread.get("section") or {}).get("id") != section_id:
                    return
            self._rpc.call("thread/section/move", {"threadId": thread_id, "sectionId": section_id if pinned else None})

    def list_threads(self, archived, search, cursor, pinned=False):
        params = {"archived": archived, "limit": 24}
        if pinned:
            section_id = self.pinned_section()
            if section_id is None:
                return {"threads": [], "next": None}
            params["sectionId"] = section_id
        if search:
            params["searchTerm"] = search
        if cursor:
            params["cursor"] = cursor
        response = self._rpc.call("thread/list", params)
        return {
            "threads": [{
                "id": thread["id"],
                "name": thread.get("name"),
                "title": thread.get("name") or thread["preview"][:150] or "未命名对话",
                "workspace": Path(thread["cwd"]).name,
                "updated_at": thread["updatedAt"],
                "pinned": (thread.get("section") or {}).get("name", "").casefold() in PINNED_SECTION_NAMES,
            } for thread in response["data"]],
            "next": response.get("nextCursor"),
        }

    def select(self, thread_id, archived, retry_history=False):
        with self.action:
            self.require_idle()
            with self.lock:
                if retry_history and thread_id != self.thread:
                    raise ValueError("会话已切换，请重新打开历史")
                if thread_id == self.thread and archived == self.archived and not self.history_error:
                    return
            thread = self._rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
            try:
                page = self.initial_history(thread_id)
                history_error = False
            except (OSError, RuntimeError):
                page = {"data": []}
                history_error = True
            changes = TurnChanges(thread["cwd"])
            if page["data"]:
                latest = page["data"][0]
                changes.turn_id = latest["id"]
                for item in latest["items"]:
                    if item["type"] == "fileChange":
                        changes.apply_item(item)
            with self.lock:
                self.thread = thread_id
                self.loaded = False
                self.thread_name = thread.get("name") or thread.get("preview", "")[:100]
                self.thread_workspace = Path(thread["cwd"])
                self.archived = archived
                self.messages = self.turn_entries(page)
                self.history_cursor = page.get("nextCursor")
                self.history_error = history_error
                self.changes = changes
                self.activity.clear()
                self.save_selection()

    def initial_history(self, thread_id):
        try:
            return self.turn_page(thread_id)
        except RpcError as error:
            if error.code not in {-32601, -32602}:
                raise
            thread = self._rpc.call("thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
            return {"data": list(reversed(thread.get("turns") or []))}

    def turn_page(self, thread_id, cursor=None):
        return self._rpc.call("thread/turns/list", {
            "threadId": thread_id, "sortDirection": "desc", "itemsView": "full", "limit": 8, "cursor": cursor,
        })

    @staticmethod
    def turn_entries(page):
        return [entry for turn in reversed(page["data"]) for item in turn["items"]
                if (entry := session_entry(item)) is not None]

    def update_thread(self, thread_id, operation, name=None):
        with self.action:
            self.require_idle()
            params = {"threadId": thread_id}
            if name is not None:
                params["name"] = name
            self._rpc.call("thread/" + operation, params)
            with self.lock:
                if self.thread == thread_id:
                    if operation == "name/set":
                        self.thread_name = name
                    else:
                        self.archived = operation == "archive"
                        self.loaded = False
                        self.save_selection()

    def history_slice(self, end):
        start = max(0, end - PAGE_SIZE)
        anchor = self.messages[start]["id"] if start < len(self.messages) else "oldest"
        return {
            "messages": [export_entry(message) for message in self.messages[start:end]],
            "history_before": anchor if start or self.history_cursor else None,
            "history_error": self.history_error,
        }

    def older_history(self, before, thread_id):
        with self.action:
            while True:
                with self.lock:
                    if thread_id != self.thread:
                        raise ValueError("会话已切换，请重新打开历史")
                    end = next((index for index, message in enumerate(self.messages)
                                if message["id"] == before), None)
                    if end is None:
                        if before != "oldest":
                            raise ValueError("历史位置已变化，请重新打开会话")
                        end = len(self.messages)
                    cursor = self.history_cursor
                    if end >= PAGE_SIZE or not cursor:
                        return self.history_slice(end)
                page = self.turn_page(thread_id, cursor)
                with self.lock:
                    self.messages[:0] = self.turn_entries(page)
                    self.history_cursor = page.get("nextCursor")
                    if self.history_cursor == cursor:
                        self.history_cursor = None

    def get_diff(self, thread_id, turn_id, path):
        with self.lock:
            if thread_id != self.thread or turn_id != self.changes.turn_id:
                raise ValueError("变更已切换，请重新选择文件")
            return self.changes.get_file(path)

    def get_attachment(self, thread_id, message_id, index):
        with self.lock:
            if thread_id != self.thread:
                raise ValueError("会话已切换，请重新打开附件")
            entry = next((message for message in self.messages
                          if message["id"] == message_id and message["role"] == "user"), None)
            attachments = entry.get("attachments", []) if entry else []
            if not 0 <= index < len(attachments) or not attachments[index]["path"]:
                raise ValueError("历史图片不可用")
            path = attachments[index]["path"]
        return read_attachment_image(path)

    def snapshot(self, include_messages=True, include_controls=True):
        with self.lock:
            data = {
                "workspace": self.changes.cwd.name,
                "workspace_fallback": self.changes.cwd != self.thread_workspace,
                "thread_name": self.thread_name,
                "thread_id": self.thread,
                "archived": self.archived,
                "connected": self._rpc.connected,
                "busy": self.busy,
                "interruptible": self.turn is not None,
                "activity": list(self.activity),
            }
            if include_messages:
                data.update(self.history_slice(len(self.messages)))
                data["changes"] = self.changes.summary()
            if include_controls:
                data.update({"models": list(self.models.values()), "default_model": self.model,
                             "submissions": dict(self.submissions)})
            return data
