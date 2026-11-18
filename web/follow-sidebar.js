const statuses = {
  running: "运行中",
  completed: "已完成",
  interrupted: "已停止",
  failed: "失败",
  ended: "已结束",
};

const pinRefreshMs = 4000;
const priority = thread => thread.unread ? 0 : thread.status === "running" ? 1 : 2;

export function mountFollowSidebar({root, loadPinned, select}) {
  const list = root.querySelector("#follow-list");
  const count = root.querySelector("#follow-count");
  const attention = root.querySelector("#follow-attention");
  const notice = root.querySelector("#follow-error");
  let state = {online: false, selected: null, activity: []};
  let pins = [];
  let nextPinRefresh = 0;
  let refreshing = false;
  let selecting = false;
  let onlyAttention = false;
  let pinError = "";
  let selectionError = "";
  let signature = "";
  const buttons = new Map();

  function makeRow(thread) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "follow-open";
    button.dataset.threadId = thread.id;
    button.addEventListener("click", () => open(thread.id));
    const marker = document.createElement("span");
    marker.className = "follow-marker";
    marker.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    const title = document.createElement("span");
    title.className = "follow-name";
    const status = document.createElement("span");
    status.className = "follow-status";
    text.append(title, status);
    button.append(marker, text);
    row.append(button);
    return {row, button, title, status};
  }

  function render() {
    const entries = new Map(pins.map(thread => [thread.id, thread]));
    for (const thread of state.activity) {
      const pin = entries.get(thread.id);
      if (pin || thread.follow) entries.set(thread.id, {...pin, ...thread});
    }
    const threads = [...entries.values()].sort((first, second) =>
      priority(first) - priority(second) ||
      (priority(first) < 2 ? first.id.localeCompare(second.id) : 0));
    const pending = threads.filter(thread => thread.unread);
    count.textContent = threads.length;
    attention.textContent = "待处理 " + pending.length;
    attention.setAttribute("aria-pressed", String(onlyAttention));
    attention.disabled = !onlyAttention && !pending.length;
    notice.textContent = selectionError || pinError;
    notice.hidden = !notice.textContent;

    const shown = onlyAttention ? pending : threads;
    const nextSignature = JSON.stringify([shown, state.selected, state.online, selecting, onlyAttention]);
    if (signature === nextSignature) return;
    signature = nextSignature;
    const focused = list.contains(document.activeElement) ? document.activeElement.dataset.threadId : null;
    const scrollTop = list.scrollTop;
    const rows = shown.map(thread => {
      const key = thread.id;
      const row = buttons.get(key) || makeRow(thread);
      buttons.set(key, row);
      row.button.dataset.status = thread.unread ? "unread" : thread.status || "pinned";
      row.button.setAttribute("aria-current", String(key === state.selected));
      row.button.disabled = !state.online;
      row.button.setAttribute("aria-disabled", String(selecting));
      row.title.textContent = thread.title;
      const label = statuses[thread.status] || "已置顶";
      const statusText = thread.unread ? label + " · 未读" : label;
      const detail = thread.status === "running" ? thread.summary : "";
      row.status.textContent = [statusText, detail].filter(Boolean).join(" · ");
      row.button.title = [thread.title, statusText, thread.summary].filter(Boolean).join("\n");
      return row.row;
    });
    const visible = new Set(shown.map(thread => thread.id));
    for (const key of buttons.keys()) if (!visible.has(key)) buttons.delete(key);
    if (!rows.length) {
      const empty = document.createElement("li");
      empty.className = "follow-empty";
      empty.textContent = onlyAttention ? "暂无待处理会话" : "运行中和置顶会话会显示在这里";
      rows.push(empty);
    }
    let position = list.firstChild;
    for (const row of rows) {
      if (row === position) position = position.nextSibling;
      else list.insertBefore(row, position);
    }
    while (position) {
      const next = position.nextSibling;
      position.remove();
      position = next;
    }
    list.scrollTop = scrollTop;
    if (focused && buttons.has(focused) && state.online) buttons.get(focused).button.focus({preventScroll: true});
    else if (focused && !attention.disabled) attention.focus({preventScroll: true});
  }

  async function refreshPins() {
    if (!state.online || refreshing || Date.now() < nextPinRefresh) return;
    refreshing = true;
    try {
      pins = await loadPinned();
      pinError = "";
    } catch (_) {
      pinError = "暂时无法加载置顶会话";
    } finally {
      refreshing = false;
      nextPinRefresh = Date.now() + pinRefreshMs;
      render();
    }
  }

  async function open(id) {
    if (!state.online || selecting || id === state.selected) return;
    selecting = true;
    selectionError = "";
    render();
    try {
      await select(id);
    } catch (error) {
      selectionError = error.message;
    } finally {
      selecting = false;
      render();
    }
  }

  attention.addEventListener("click", () => {
    onlyAttention = !onlyAttention;
    selectionError = "";
    render();
  });
  root.hidden = false;
  return {
    update(snapshot) {
      if (!state.online && snapshot.connected) nextPinRefresh = 0;
      state = {online: snapshot.connected, selected: snapshot.thread_id, activity: snapshot.follow_activity || []};
      render();
      refreshPins();
    },
    disconnected() {
      state.online = false;
      render();
    },
  };
}
