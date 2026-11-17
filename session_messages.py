"""Normalize Codex timeline items and read local image attachments."""

import os
import stat
from pathlib import Path


MAX_DETAIL = 24000
MAX_ATTACHMENT = 12 * 1024 * 1024
TRACE_ITEMS = {
    "reasoning": ("reasoning", "思考摘要"),
    "commandExecution": ("command", "终端命令"),
    "fileChange": ("file", "文件变更"),
    "plan": ("plan", "执行计划"),
    "webSearch": ("tool", "网页搜索"),
}


def shorten(text):
    if len(text) <= MAX_DETAIL:
        return text
    return text[:MAX_DETAIL] + "\n[后续内容已截断]"


def file_changes(changes):
    paths = "\n".join(change["path"] for change in changes if change.get("path"))
    diff = "\n\n".join(change["diff"] for change in changes if change.get("diff"))
    return shorten(paths), shorten(diff)


def session_entry(item, complete=True):
    kind = item["type"]
    key = item["id"]
    if kind == "userMessage":
        parts = item["content"]
        text = "\n".join(part["text"] for part in parts if part["type"] == "text")
        attachments = []
        for part in parts:
            if part["type"] in {"image", "localImage"}:
                path = Path(part["path"]) if part.get("path") else None
                attachments.append({"name": path.name if path else "图片附件", "path": str(path) if path else None})
        return {"role": "user", "id": key, "text": text or ("" if attachments else "附件"),
                "attachments": attachments}
    if kind == "agentMessage":
        return {"role": "assistant", "id": key, "text": item.get("text", ""), "complete": complete}
    if kind not in TRACE_ITEMS:
        return None
    flavor, label = TRACE_ITEMS[kind]
    entry = {"role": "trace", "id": key, "kind": flavor, "label": label, "text": "",
             "status": item.get("status") or ("completed" if complete else "inProgress")}
    if kind == "reasoning":
        # Forward only the protocol's model-provided summary.
        entry["parts"] = dict(enumerate(item.get("summary") or []))
        entry["text"] = "\n\n".join(entry["parts"].values())
    elif kind == "commandExecution":
        entry["text"] = item.get("command") or ""
        entry["output"] = shorten(item.get("aggregatedOutput") or "")
        entry["exit_code"] = item.get("exitCode")
        entry["source"] = item.get("source")
    elif kind == "fileChange":
        entry["text"], entry["diff"] = file_changes(item.get("changes") or [])
    elif kind == "plan":
        entry["text"] = item.get("text") or ""
    elif kind == "webSearch":
        entry["text"] = item.get("query") or ""
    return entry


def export_entry(entry):
    visible = {key: value for key, value in entry.items() if key != "parts"}
    visible["text"] = shorten(visible["text"])
    if entry.get("attachments"):
        visible["attachments"] = [
            {"name": item["name"], "preview": item["path"] is not None}
            for item in entry["attachments"]
        ]
    return visible


def read_attachment_image(path):
    if not Path(path).is_absolute():
        raise ValueError("历史图片不可用")
    def opener(filename, flags):
        return os.open(filename, flags | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        with open(path, "rb", opener=opener) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ATTACHMENT:
                raise ValueError("这张图片无法预览")
            data = stream.read(MAX_ATTACHMENT + 1)
    except OSError as error:
        raise ValueError("Mac 上已找不到这张图片") from error
    if len(data) > MAX_ATTACHMENT:
        raise ValueError("这张图片太大，无法预览")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return data, "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return data, "image/webp"
    raise ValueError("此图片格式无法预览")
