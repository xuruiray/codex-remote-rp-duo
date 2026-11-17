import {diffBlock} from "./diff-view.js";

export function mountChanges({root, toggle, close, countLabel, notice, list, detail, loadDiff}) {
  let thread = null;
  let busy = false;
  let changesState = null;
  let changesKey = "";
  let activeFile = null;
  let diffRequest = 0;
  let noticeTimer;

  function clearNotice() {
    clearTimeout(noticeTimer);
    notice.textContent = "";
  }

  function showEmptyNotice() {
    clearNotice();
    notice.textContent = busy ? "正在执行，暂未记录文件变更" : "本轮没有文件变更";
    noticeTimer = setTimeout(clearNotice, 2400);
  }

  function changeNote(text) {
    const note = document.createElement("p");
    note.className = "empty";
    note.textContent = text;
    detail.replaceChildren(note);
  }

  async function showFile(path) {
    activeFile = path;
    for (const button of list.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.path === path));
    }
    const ticket = ++diffRequest;
    changeNote("正在读取 diff…");
    try {
      const file = await loadDiff(thread, changesState.turn_id, path);
      if (ticket !== diffRequest) return;
      const title = document.createElement("div");
      title.className = "change-path";
      title.textContent = file.path;
      if (!file.diff) {
        changeNote("Codex 记录了此文件变更，没有可显示的文本 diff。");
        detail.prepend(title);
        return;
      }
      detail.replaceChildren(title, diffBlock(file.diff));
      if (file.truncated) {
        const note = document.createElement("p");
        note.textContent = "此 diff 较长，面板已截断后续内容。";
        detail.append(note);
      }
    } catch (failure) {
      if (ticket === diffRequest) changeNote(failure.message);
    }
  }

  function drawChanges() {
    const files = changesState?.files || [];
    const labels = {add: "新增", delete: "删除", rename: "重命名", update: "修改"};
    list.replaceChildren(...files.map(file => {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.path = file.path;
      button.className = "subtle";
      button.title = file.path;
      const name = document.createElement("span");
      const stat = document.createElement("small");
      name.textContent = file.path;
      stat.append(labels[file.kind] || "修改", " ");
      for (const [prefix, value, className] of [["+", file.added, "added"], ["−", file.deleted, "removed"]]) {
        if (!value) continue;
        const count = document.createElement("span");
        count.className = className;
        count.textContent = prefix + value;
        stat.append(count, " ");
      }
      button.append(name, stat);
      button.addEventListener("click", () => showFile(file.path));
      row.append(button);
      return row;
    }));
    showFile(files.some(file => file.path === activeFile) ? activeFile : files[0].path);
  }

  function toggleChanges(open) {
    root.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) drawChanges();
    else ++diffRequest;
  }

  function update(state) {
    const changes = state.changes;
    const changedTurn = thread !== state.thread_id || changesState?.turn_id !== changes?.turn_id;
    thread = state.thread_id;
    busy = state.busy;
    if (changedTurn) {
      activeFile = null;
      clearNotice();
    }
    changesState = changes;
    const count = changes?.files.length || 0;
    const label = String(count);
    if (countLabel.textContent !== label) countLabel.textContent = label;
    toggle.classList.toggle("has-changes", count > 0);
    const key = JSON.stringify([thread, changes?.turn_id, changes?.revision, count]);
    if (count) {
      if (notice.textContent) clearNotice();
      if (key !== changesKey && !root.hidden) drawChanges();
    } else if (!root.hidden) {
      toggleChanges(false);
    }
    changesKey = key;
  }

  toggle.addEventListener("click", () => {
    if (!changesState?.files.length) {
      showEmptyNotice();
      return;
    }
    toggleChanges(root.hidden);
  });
  close.addEventListener("click", () => toggleChanges(false));
  return {update};
}
