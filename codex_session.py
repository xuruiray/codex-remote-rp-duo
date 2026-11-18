"""Manage the Duo’s selected view and independent Codex conversations."""

import json
import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from app_server import AppServer, RpcError
from change_set import TurnChanges
from session_messages import MAX_DETAIL, export_entry, read_attachment_image, session_entry, shorten


PAGE_SIZE = 50
PINNED_SECTION_NAMES = {"pinned", "置顶", "置顶会话"}


@dataclass
class Chat:
    workspace: Path
    id: str | None = None
    name: str | None = None
    loaded: bool = False
    archived: bool = False
    turn: str | None = None
    submission: str | None = None
    messages: list = field(default_factory=list)
    activity: list = field(default_factory=list)
    history_cursor: str | None = None
    history_error: bool = False
    outcome: str | None = None
    unread: bool = False
    changes: TurnChanges = field(init=False)

    def __post_init__(self):
        self.changes = TurnChanges(self.workspace)

    @property
    def busy(self):
        return self.submission is not None

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

    def history_slice(self, end):
        start = max(0, end - PAGE_SIZE)
        anchor = self.messages[start]["id"] if start < len(self.messages) else "oldest"
        return {
            "messages": [export_entry(message) for message in self.messages[start:end]],
            "history_before": anchor if start or self.history_cursor else None,
            "history_error": self.history_error,
        }

class Codex:
    def __init__(self, workspace, executable, session_file=None):
        self.workspace = workspace
        self.session_file = session_file
        self.lock = threading.RLock()
        self.action = threading.Lock()
        self.selected = Chat(workspace)
        self.chats = OrderedDict()
        self.submissions = OrderedDict()
        self._rpc = AppServer(executable, workspace, self.notify, self.disconnected)
        try:
            self._initialize()
        except BaseException:
            self.close()
            raise

    def _initialize(self):
        self._rpc.call("initialize", {
            "clientInfo": {"name": "duo_codex", "title": "Codex", "version": "0.1.16"},
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
                self.selected.add_event("上次打开的会话暂时无法恢复，可从全部会话重新打开")

    def save_selection(self):
        if self.session_file is None:
            return
        try:
            if not self.selected.id:
                self.session_file.unlink(missing_ok=True)
                return
            temp = self.session_file.with_suffix(".tmp")
            descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"id": self.selected.id, "archived": self.selected.archived}, stream)
            temp.replace(self.session_file)
        except OSError:
            self.selected.add_event("Mac 无法保存上次打开的会话")

    def show_chat(self, chat):
        self.selected = chat
        chat.unread = False
        if chat.id is not None:
            self.chats[chat.id] = chat
            self.chats.move_to_end(chat.id)
        while len(self.chats) > 32:
            stale = next((item for item in self.chats.values() if not item.busy and not item.unread and item is not chat), None)
            if stale is None:
                break
            del self.chats[stale.id]
        self.save_selection()

    def close(self):
        self._rpc.close()

    def disconnected(self):
        with self.lock:
            for chat in self.chats.values():
                if not chat.busy:
                    continue
                self.fail_submission(chat, chat.submission, "Codex 进程已退出，请在 Mac 重新启动连接")
                chat.turn = None
                chat.submission = None
                chat.loaded = False

    def fail_submission(self, chat, submission, error):
        receipt = self.submissions.get(submission)
        chat.add_event(error)
        self.finish_chat(chat, "failed")
        if receipt and receipt["status"] == "sending":
            receipt.update(status="failed", error=error)
            chat.messages[:] = [message for message in chat.messages if message["id"] != submission]

    def finish_chat(self, chat, outcome):
        chat.outcome = outcome
        chat.unread = chat is not self.selected

    def _follow_activity(self):
        return [{
            "id": chat.id,
            "title": chat.name or "未命名对话",
            "status": "running" if chat.busy else chat.outcome,
            "unread": chat.unread,
            "follow": chat.busy or chat.unread or chat is self.selected,
            "summary": chat.activity[-1] if chat.activity else "",
        } for chat in reversed(self.chats.values()) if not chat.archived and (
            chat.busy or chat.outcome
        )]

    def notify(self, method, params):
        with self.lock:
            chat = self.chats.get(params.get("threadId"))
            if not chat or not chat.busy:
                return
            turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
            if chat.turn and turn_id and turn_id != chat.turn:
                return
            if method == "turn/started":
                self.submissions[chat.submission]["status"] = "sent"
                chat.turn = params["turn"]["id"]
                chat.changes.turn_id = chat.turn
                chat.add_event("Codex 正在 Mac 上运行")
            elif method == "turn/diff/updated" and params["turnId"] == chat.changes.turn_id:
                chat.changes.apply_diff(params["diff"])
            elif method == "item/agentMessage/delta":
                message = chat.entry(params["itemId"], lambda: {
                    "role": "assistant", "text": "", "id": params["itemId"], "complete": False,
                })
                message["text"] += params["delta"]
            elif method == "item/reasoning/summaryTextDelta":
                item_id = params["itemId"]
                trace = chat.entry(item_id, lambda: session_entry({"type": "reasoning", "id": item_id}, False))
                index = params["summaryIndex"]
                parts = trace["parts"]
                parts[index] = parts.get(index, "") + params["delta"]
                trace["text"] = "\n\n".join(parts[i] for i in sorted(parts))
            elif method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
                is_command = method.startswith("item/commandExecution/")
                item = {"type": "commandExecution" if is_command else "fileChange", "id": params["itemId"]}
                trace = chat.entry(item["id"], lambda: session_entry(item, False))
                if len(trace.get("output", "")) < MAX_DETAIL:
                    trace["output"] = shorten(trace.get("output", "") + params["delta"])
            elif method == "item/fileChange/patchUpdated":
                item = {"type": "fileChange", "id": params["itemId"], "changes": params["changes"]}
                chat.update_item(item, False)
                if params["turnId"] == chat.changes.turn_id:
                    chat.changes.apply_item(item)
            elif method == "turn/plan/updated":
                markers = {"pending": "○", "inProgress": "◐", "completed": "✓"}
                steps = "\n".join(f"{markers.get(step['status'], '○')} {step['step']}" for step in params["plan"])
                text = "\n\n".join(part for part in (params.get("explanation"), steps) if part)
                chat.update_item({"type": "plan", "id": params["turnId"] + ":plan", "text": text}, True)
            elif method in {"item/started", "item/completed"}:
                item = params["item"]
                kind = item.get("type")
                if kind != "userMessage":
                    chat.update_item(item, method == "item/completed")
                if kind == "fileChange" and params["turnId"] == chat.changes.turn_id:
                    chat.changes.apply_item(item)
                if kind in {"commandExecution", "fileChange"}:
                    label = "终端" if kind == "commandExecution" else "文件"
                    detail = item.get("command") or "工作区变更"
                    prefix = "开始" if method == "item/started" else "完成"
                    chat.add_event(f"{prefix} · {label} · {detail}")
            elif method == "turn/completed":
                turn = params["turn"]
                error = turn.get("error") or {}
                outcome = turn.get("status")
                status = {"completed": "任务完成", "interrupted": "任务已停止",
                          "failed": "任务失败"}.get(outcome, "任务已结束")
                self.finish_chat(chat, outcome or "ended")
                chat.add_event(f"{status} · {error['message']}" if error.get("message") else status)
                chat.submission = None
                chat.turn = None

    def run_prompt(self, chat, text, model, effort, submission, workspace):
        try:
            if not chat.loaded:
                options = {
                    "threadId": chat.id,
                    "excludeTurns": True,
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "model": model,
                }
                if workspace != chat.workspace:
                    options["cwd"] = str(workspace)
                self._rpc.call("thread/resume", options)
                with self.lock:
                    chat.loaded = True
            request = {
                "threadId": chat.id,
                "cwd": str(workspace),
                "model": model,
                "summary": "detailed",
                "input": [{"type": "text", "text": text, "text_elements": []}],
            }
            if effort is not None:
                request["effort"] = effort
            self._rpc.call("turn/start", request)
            with self.lock:
                receipt = self.submissions.get(submission)
                if receipt and receipt["status"] == "sending":
                    receipt["status"] = "sent"
        except (OSError, RuntimeError) as error:
            with self.lock:
                receipt = self.submissions.get(submission)
                if chat.submission == submission and receipt and receipt["status"] == "sending":
                    self.fail_submission(chat, submission, str(error))
                    chat.submission = None
                    chat.turn = None

    def start_prompt(self, text, model=None, effort=None, submission=None, expected_thread=None):
        model = self.model if model is None else model
        if not isinstance(model, str) or model not in self.models:
            raise ValueError("这个 Codex 账号当前无法使用所选模型")
        if effort is not None and effort not in self.models[model]["efforts"]:
            raise ValueError("所选模型不支持此推理强度")
        with self.action:
            with self.lock:
                chat = self.selected
                if submission in self.submissions:
                    return
                if submission is not None and chat.id != expected_thread:
                    raise ValueError("会话已切换，请确认要发送到的会话")
                if chat.busy or chat.archived or not self._rpc.connected:
                    raise ValueError("当前会话无法接收新任务")
            if chat.id is None:
                response = self._rpc.call("thread/start", {
                    "cwd": str(chat.workspace), "model": model,
                    "approvalPolicy": "never", "sandbox": "workspace-write",
                })
                with self.lock:
                    chat.id = response["thread"]["id"]
                    chat.name = text.strip()[:100]
                    chat.loaded = True
                    self.show_chat(chat)
            with self.lock:
                submission = submission or str(uuid.uuid4())
                self.submissions[submission] = {"status": "sending", "thread_id": chat.id}
                if len(self.submissions) > 64:
                    active = {item.submission for item in self.chats.values() if item.busy}
                    expired = next((ident for ident in self.submissions if ident not in active and ident != submission), None)
                    if expired is not None:
                        self.submissions.pop(expired)
                chat.submission = submission
                chat.outcome = None
                chat.unread = False
                workspace = chat.workspace
                if not workspace.is_dir():
                    workspace = self.workspace
                    chat.add_event(f"原工作目录已不存在，本轮使用 {workspace.name}")
                chat.changes = TurnChanges(workspace)
                chat.messages.append({"role": "user", "id": submission, "text": text})
                chat.add_event("任务已发往 Mac")
        threading.Thread(target=self.run_prompt, args=(chat, text, model, effort, submission, workspace),
                         daemon=True).start()

    def interrupt(self, expected_thread=None, expected_turn=None):
        with self.lock:
            chat = self.selected
            if expected_thread is not None and expected_thread != chat.id:
                raise ValueError("会话已切换，请确认要停止的任务")
            if expected_turn is not None and expected_turn != chat.turn:
                raise ValueError("任务已结束或切换")
            if not chat.turn:
                raise ValueError("还没有可停止的任务")
            params = {"threadId": chat.id, "turnId": chat.turn}
        self._rpc.call("turn/interrupt", params)

    def reset(self):
        with self.action, self.lock:
            self.show_chat(Chat(self.workspace))

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
            with self.lock:
                cached = self.chats.get(thread_id)
                if retry_history and thread_id != self.selected.id:
                    raise ValueError("会话已切换，请重新打开历史")
                if cached and (cached.busy or (cached.archived == archived and not cached.history_error
                                                 and (cached.loaded or cached is self.selected))):
                    self.show_chat(cached)
                    return
            thread = self._rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
            chat = Chat(Path(thread["cwd"]), id=thread_id,
                        name=thread.get("name") or thread.get("preview", "")[:100], archived=archived)
            try:
                page = self.initial_history(thread_id)
            except (OSError, RuntimeError):
                page = {"data": []}
                chat.history_error = True
            if page["data"]:
                latest = page["data"][0]
                chat.changes.turn_id = latest["id"]
                for item in latest["items"]:
                    if item["type"] == "fileChange":
                        chat.changes.apply_item(item)
            chat.messages = self.turn_entries(page)
            chat.history_cursor = page.get("nextCursor")
            with self.lock:
                if cached:
                    chat.outcome = cached.outcome
                    chat.activity = cached.activity
                self.show_chat(chat)

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
            with self.lock:
                chat = self.chats.get(thread_id)
                if chat and chat.busy:
                    raise ValueError("该会话仍在执行任务")
            params = {"threadId": thread_id}
            if name is not None:
                params["name"] = name
            self._rpc.call("thread/" + operation, params)
            with self.lock:
                if chat:
                    if operation == "name/set":
                        chat.name = name
                    else:
                        chat.archived = operation == "archive"
                        if chat.archived:
                            chat.unread = False
                            chat.outcome = None
                        chat.loaded = False
                        if self.selected is chat:
                            self.save_selection()

    def older_history(self, before, thread_id):
        with self.action:
            while True:
                with self.lock:
                    chat = self.selected
                    if thread_id != chat.id:
                        raise ValueError("会话已切换，请重新打开历史")
                    end = next((index for index, message in enumerate(chat.messages)
                                if message["id"] == before), None)
                    if end is None:
                        if before != "oldest":
                            raise ValueError("历史位置已变化，请重新打开会话")
                        end = len(chat.messages)
                    cursor = chat.history_cursor
                    if end >= PAGE_SIZE or not cursor:
                        return chat.history_slice(end)
                page = self.turn_page(thread_id, cursor)
                with self.lock:
                    chat.messages[:0] = self.turn_entries(page)
                    chat.history_cursor = page.get("nextCursor")
                    if chat.history_cursor == cursor:
                        chat.history_cursor = None

    def get_diff(self, thread_id, turn_id, path):
        with self.lock:
            chat = self.selected
            if thread_id != chat.id or turn_id != chat.changes.turn_id:
                raise ValueError("变更已切换，请重新选择文件")
            return chat.changes.get_file(path)

    def get_attachment(self, thread_id, message_id, index):
        with self.lock:
            chat = self.selected
            if thread_id != chat.id:
                raise ValueError("会话已切换，请重新打开附件")
            entry = next((message for message in chat.messages
                          if message["id"] == message_id and message["role"] == "user"), None)
            attachments = entry.get("attachments", []) if entry else []
            if not 0 <= index < len(attachments) or not attachments[index]["path"]:
                raise ValueError("历史图片不可用")
            path = attachments[index]["path"]
        return read_attachment_image(path)

    def snapshot(self, include_messages=True, include_controls=True, include_following=False):
        with self.lock:
            chat = self.selected
            data = {
                "workspace": chat.changes.cwd.name,
                "workspace_fallback": chat.changes.cwd != chat.workspace,
                "thread_name": chat.name,
                "thread_id": chat.id,
                "archived": chat.archived,
                "connected": self._rpc.connected,
                "busy": chat.busy,
                "interruptible": chat.turn is not None,
                "turn_id": chat.turn,
                "activity": list(chat.activity),
            }
            if include_messages:
                data.update(chat.history_slice(len(chat.messages)))
                data["changes"] = chat.changes.summary()
            if include_following:
                data["follow_activity"] = self._follow_activity()
            if include_controls:
                data.update({"models": list(self.models.values()), "default_model": self.model,
                             "submissions": {ident: dict(receipt) for ident, receipt in self.submissions.items()},
                             "running_thread_ids": [item.id for item in self.chats.values() if item.busy]})
            return data
