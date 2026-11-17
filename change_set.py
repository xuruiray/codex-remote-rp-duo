"""Extract per-file views of the current Codex turn's recorded changes."""
import ast
import re
from pathlib import Path

DIFF_START = re.compile(r"(?m)^diff --git (.+)$")
HUNK_START = re.compile(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
MAX_PATCH = 240_000


def git_path(value):
    if value.startswith('"'):
        try:
            return ast.literal_eval("b" + value).decode("utf-8", errors="replace")
        except (SyntaxError, ValueError):
            return value.strip('"')
    return value.split("\t", 1)[0]


def patch_info(path, kind, diff):
    added = deleted = 0
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added += 1
        elif in_hunk and line.startswith("-"):
            deleted += 1
    return {"path": path, "kind": kind, "added": added, "deleted": deleted, "diff": diff}


def stored_patch(path, kind, text):
    has_header = text.startswith(("--- ", "@@ ")) and HUNK_START.search(text)
    if kind not in {"add", "delete"} or DIFF_START.match(text) or has_header:
        return text
    # Saved add/delete items can contain the entire file body instead of a unified diff.
    old_side, new_side = ("/dev/null", "b/" + path) if kind == "add" else ("a/" + path, "/dev/null")
    headers = f"--- {old_side}\n+++ {new_side}\n"
    lines = text.splitlines()
    if not lines:
        return headers
    if kind == "add":
        hunk = f"@@ -0,0 +1,{len(lines)} @@\n"
        prefix = "+"
    else:
        hunk = f"@@ -1,{len(lines)} +0,0 @@\n"
        prefix = "-"
    patch = headers + hunk + "".join(prefix + line + "\n" for line in lines)
    return patch if text.endswith("\n") else patch + "\\ No newline at end of file\n"


def split_diff(diff):
    result = {}
    starts = list(DIFF_START.finditer(diff))
    for index, header in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(diff)
        patch = diff[header.start():stop]
        name = None
        old_name = None
        kind = "update"
        for line in patch.splitlines()[1:]:
            if line.startswith("@@"):
                break
            if line.startswith("rename to "):
                name = git_path(line.removeprefix("rename to "))
                kind = "rename"
            elif line.startswith("new file mode "):
                kind = "add"
            elif line.startswith("deleted file mode "):
                kind = "delete"
            elif line.startswith("--- "):
                old_name = git_path(line[4:]).removeprefix("a/")
            elif line.startswith("+++ "):
                updated_name = git_path(line[4:])
                if updated_name != "/dev/null":
                    name = updated_name.removeprefix("b/")
        if not name:
            name = old_name
        if not name:
            _, separator, tail = header[1].rpartition(" b/")
            if separator:
                name = git_path(tail)
            else:
                quoted = re.search(r'("(?:[^"\\]|\\.)*")$', header[1])
                if quoted:
                    name = git_path(quoted[1]).removeprefix("b/")
        if name and name != "/dev/null":
            result[name] = patch_info(name, kind, patch)
    return result


class TurnChanges:
    def __init__(self, cwd, turn_id=None):
        self.cwd = Path(cwd)
        self.turn_id = turn_id
        self.by_item = {}
        self.aggregate = None
        self.files = {}
        self.revision = 0

    def apply_item(self, item):
        item_id = item["id"]
        if item.get("status") in {"failed", "declined"}:
            self.by_item.pop(item_id, None)
        elif item.get("changes"):
            self.by_item[item_id] = item["changes"]
        self.rebuild()

    def apply_diff(self, text):
        parsed = split_diff(text)
        if parsed or not text.strip():
            self.aggregate = parsed
            self.rebuild()

    def rebuild(self):
        if self.aggregate is not None:
            files = self.aggregate
        else:
            files = {}
            for changes in self.by_item.values():
                for change in changes:
                    path = change.get("path")
                    if not path:
                        continue
                    path = str(Path(path).relative_to(self.cwd)) if Path(path).is_relative_to(self.cwd) else path
                    kind = change.get("kind", {})
                    kind = kind.get("type", "update") if isinstance(kind, dict) else kind
                    patch = stored_patch(path, kind, change.get("diff") or "")
                    if path in files and files[path]["diff"] != patch:
                        patch = files[path]["diff"].rstrip() + "\n\n" + patch
                    files[path] = patch_info(path, kind, patch)
        if files != self.files:
            self.files = files
            self.revision += 1

    def summary(self):
        return {
            "turn_id": self.turn_id,
            "revision": self.revision,
            "files": [{key: value for key, value in item.items() if key != "diff"}
                      for item in self.files.values()],
        }

    def get_file(self, path):
        if path not in self.files:
            raise ValueError("此文件已不在当前变更中")
        item = self.files[path]
        return {**item, "diff": item["diff"][:MAX_PATCH], "truncated": len(item["diff"]) > MAX_PATCH}
