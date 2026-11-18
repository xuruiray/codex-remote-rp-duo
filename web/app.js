import {mountChanges} from "./changes-panel.js";
import {mountConversation} from "./conversation.js";
import {mountFollowSidebar} from "./follow-sidebar.js";

const params = new URLSearchParams(location.hash.slice(1));
const token = params.get("token") || "";
const panel = params.get("panel") || "single";
document.body.dataset.panel = panel;
if (panel === "top") {
  const heading = document.querySelector(".conversation-heading");
  heading.querySelector(".conversation-context").append(document.getElementById("workspace"));
  document.querySelector("header").append(heading);
}
if (panel === "single") document.querySelector("#messages .empty").textContent = "输入任务后，Codex 的回复会显示在这里。";
const find = (id) => document.getElementById(id);
const activity = find("activity");
const progress = find("progress");
const prompt = find("prompt");
const connection = find("connection");
const connectionLabel = connection.querySelector(".sr-only");
const modelPicker = find("model");
const effortPicker = find("effort");
let busy = false;
let requests = false;
let online = false;
let interruptible = false;
let activeTurn = null;
let runningThreads = new Set();
let lastActivity = "";
let activeThread = null;
let activeName = null;
let activeArchived = false;
let listingArchived = false;
let listSearch = "";
let cursor = null;
let listLoading = false;
let listRequest = 0;
let view = "chat";
let sessionMenuTarget = null;
let refreshSequence = 0;
let restoredDraft = null;
let hasSnapshot = false;
const draftStorageKey = "duo-codex-composer-drafts";
const maxDrafts = 20;
const savedComposer = readComposer();
let drafts = savedComposer.drafts;
let pendingSubmissions = savedComposer.pendingSubmissions;
let modelOptions = [];
const effortLabels = {none: "无", minimal: "极低", low: "低", medium: "中", high: "高", xhigh: "极高", max: "最高"};

function readComposer() {
  try {
    if (panel !== "top") {
      const saved = JSON.parse(localStorage.getItem(draftStorageKey));
      if (Array.isArray(saved)) return {drafts: new Map(saved), pendingSubmissions: []};
      if (saved) return {drafts: new Map(saved.drafts), pendingSubmissions: readPending(saved)};
    }
  } catch (_) {
    // Storage can be unavailable. The composer can still work in memory.
  }
  return {drafts: new Map(), pendingSubmissions: []};
}

function readPending(saved) {
  return saved.pendingSubmissions || (saved.pendingSubmission ? [saved.pendingSubmission] : []);
}

function saveDrafts() {
  if (panel === "top") return;
  while (drafts.size > maxDrafts) drafts.delete(drafts.keys().next().value);
  try {
    localStorage.setItem(draftStorageKey, JSON.stringify({drafts: [...drafts], pendingSubmissions}));
  } catch (_) {
    // The in-memory draft is still available for a live connection switch.
  }
}

function rememberDraft(thread, text) {
  drafts.delete(thread);
  if (text) drafts.set(thread, text);
  saveDrafts();
}

function buttons() {
  find("send").hidden = busy;
  find("stop").hidden = !busy;
  find("send").disabled = !online || busy || requests || activeArchived || !prompt.value.trim();
  prompt.disabled = activeArchived;
  prompt.placeholder = activeArchived ? "恢复此会话后可以继续对话。" : "询问 Codex，或交给它一个任务…";
  find("stop").disabled = !online || !interruptible || requests;
  find("task-tab").disabled = !online || requests;
  find("task-tab").setAttribute("aria-pressed", String(view === "chat" && !activeThread));
  find("session-pin").disabled = !online || requests;
  const menuBusy = runningThreads.has(sessionMenuTarget?.thread.id);
  find("rename").disabled = !online || menuBusy || requests;
  find("archive").disabled = !online || menuBusy || requests;
  find("session-confirm").disabled = !online || menuBusy || requests;
  modelPicker.disabled = !online || busy || requests || !modelPicker.options.length;
  effortPicker.disabled = !online || busy || requests || effortPicker.options.length < 2;
}

function renderEfforts() {
  const model = modelOptions.find(entry => entry.id === modelPicker.value);
  effortPicker.replaceChildren();
  if (!model) return;
  const defaultLabel = effortLabels[model.default_effort] || model.default_effort || "";
  effortPicker.append(new Option(defaultLabel ? "模型默认 · " + defaultLabel : "模型默认", ""));
  for (const effort of model.efforts) effortPicker.append(new Option(effortLabels[effort] || effort, effort));
  if (model.efforts.includes("high")) effortPicker.value = "high";
}

function renderModels(models, defaultModel) {
  if (!models || JSON.stringify(models) === JSON.stringify(modelOptions)) return;
  const previous = modelPicker.value;
  modelOptions = models;
  modelPicker.replaceChildren(...models.map(model => new Option(model.label, model.id)));
  modelPicker.value = models.some(model => model.id === previous) ? previous : defaultModel;
  renderEfforts();
}

async function request(path, data, image = false) {
  const options = {
    headers: {Authorization: "Bearer " + token},
    signal: AbortSignal.timeout(data === undefined ? 6000 : 30000)
  };
  if (data !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(data);
  }
  const response = await fetch("/api/" + path, options);
  if (response.ok && image) return response.blob();
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败");
  return result;
}

const changes = panel === "bottom" ? null : mountChanges({
  root: find("changes"), toggle: find("changes-toggle"), close: find("changes-close"),
  countLabel: find("changes-count"), notice: find("changes-notice"),
  list: find("change-files"), detail: find("change-detail"),
  loadDiff: (thread, turn, path) => request("file-diff", {thread_id: thread, turn_id: turn, path}),
});
const conversation = panel === "bottom" ? null : mountConversation({
  panel, messages: find("messages"), older: find("older"),
  loadAttachment: (thread, message, index) => request("attachment", {thread_id: thread, message_id: message, index}, true),
  loadOlder: (thread, before) => request("history", {thread_id: thread, before}),
  retryHistory: async (id, archived) => {
    await request("select", {id, archived, retry_history: true});
    await refresh();
  },
});

async function loadFollowPins() {
  const threads = [];
  const visited = new Set();
  let cursor = null;
  do {
    visited.add(cursor);
    const result = await request("threads", {pinned: true, cursor});
    threads.push(...result.threads);
    cursor = result.next;
  } while (cursor && !visited.has(cursor));
  return threads;
}

const followSidebar = panel === "top" ? mountFollowSidebar({
  root: find("follow-sidebar"),
  loadPinned: loadFollowPins,
  select: async (id) => {
    await request("select", {id});
    await refresh();
  },
}) : null;

function render(state) {
  const reconnected = !online && state.connected;
  online = state.connected;
  busy = state.busy;
  interruptible = state.interruptible;
  activeTurn = state.turn_id;
  runningThreads = new Set(state.running_thread_ids || []);
  const selectionChanged = activeThread !== state.thread_id;
  const externalSelection = hasSnapshot && selectionChanged && !requests;
  bindSubmissionThreads(state.submissions, state.thread_id);
  if (panel !== "top" && (!hasSnapshot || selectionChanged)) {
    prompt.value = drafts.get(state.thread_id) || "";
  }
  hasSnapshot = true;
  activeThread = state.thread_id;
  activeName = state.thread_name;
  activeArchived = state.archived;
  if (panel === "bottom" && externalSelection) {
    find("error").hidden = true;
    if (view !== "chat") tab("chat");
  }
  followSidebar?.update(state);
  renderModels(state.models, state.default_model);
  applyRestoredDraft();
  confirmSubmissions(state.submissions);
  find("thread-title").textContent = activeName || (activeThread ? "对话" : "新聊天");
  find("workspace").textContent = state.workspace + (state.workspace_fallback ? "（原目录已不存在）" : "");
  const transport = location.hostname === "127.0.0.1" ? "USB" : "Wi-Fi";
  updateConnection(online ? (busy ? "running" : "ready") : "offline",
    online ? (busy ? "Mac 正在执行" : "Mac 已连接") + " · " + transport : "Codex 已断开");
  if (panel !== "bottom") {
    changes.update(state);
    conversation.update(state);
    const activitySignature = JSON.stringify(state.activity);
    if (activitySignature !== lastActivity) {
      const newest = state.activity.at(-1);
      progress.hidden = !newest;
      find("progress-title").textContent = newest ? "进度 · " + newest : "进度";
      activity.replaceChildren(...state.activity.slice().reverse().map((event) => {
        const row = document.createElement("li");
        row.textContent = event;
        return row;
      }));
      lastActivity = activitySignature;
    }
  }
  for (const entry of find("session-list").querySelectorAll("button[data-thread-id]")) {
    entry.classList.toggle("selected", entry.dataset.threadId === activeThread);
    entry.querySelector(".session-running").hidden = !runningThreads.has(entry.dataset.threadId);
  }
  if (reconnected && view !== "chat") loadSessions();
  buttons();
}

async function refresh() {
  const sequence = ++refreshSequence;
  try {
    const state = await request("state?panel=" + panel);
    if (sequence === refreshSequence) render(state);
  } catch (failure) {
    if (sequence !== refreshSequence) return;
    online = false;
    followSidebar?.disconnected();
    updateConnection("connecting", "Mac 连接中断 · 正在重连");
    if (failure.name === "TypeError" || failure.name === "TimeoutError") {
      window.DuoConnection?.checkAlternate();
    }
    buttons();
  }
}

function updateConnection(state, label) {
  connection.dataset.state = state;
  if (connectionLabel.textContent === label) return;
  connectionLabel.textContent = label;
  connection.title = label;
}

function connectionDraft() {
  if (requests) return null;
  return {thread: activeThread, text: prompt.value, drafts: [...drafts], pendingSubmissions,
          model: modelPicker.value, effort: effortPicker.value};
}

function restoreConnectionDraft(state) {
  pendingSubmissions = readPending(state);
  if (panel !== "top" && Array.isArray(state.drafts)) {
    drafts = new Map(state.drafts);
    saveDrafts();
  }
  restoredDraft = state;
  applyRestoredDraft();
  return true;
}

function applyRestoredDraft() {
  if (!restoredDraft || !online || restoredDraft.thread !== activeThread) return;
  prompt.value = restoredDraft.text;
  rememberDraft(activeThread, prompt.value);
  if ([...modelPicker.options].some(model => model.value === restoredDraft.model)) {
    modelPicker.value = restoredDraft.model;
    renderEfforts();
    if ([...effortPicker.options].some(effort => effort.value === restoredDraft.effort)) {
      effortPicker.value = restoredDraft.effort;
    }
  }
  restoredDraft = null;
}

function bindSubmissionThreads(receipts, nextThread) {
  for (const submitted of pendingSubmissions) {
    const thread = receipts?.[submitted.id]?.thread_id;
    if (submitted.thread !== null || !thread) continue;
    submitted.thread = thread;
    if (activeThread === null && nextThread === thread) {
      rememberDraft(thread, hasSnapshot ? prompt.value : drafts.get(null) || "");
      rememberDraft(null, "");
    } else {
      saveDrafts();
    }
  }
}

function confirmSubmissions(receipts) {
  if (!pendingSubmissions.length) return;
  const count = pendingSubmissions.length;
  pendingSubmissions = pendingSubmissions.filter(submitted => {
    const receipt = receipts?.[submitted.id];
    if (!receipt || receipt.status === "sending") return true;
    const thread = submitted.thread;
    const error = find("error");
    if (receipt.status === "sent") {
      if (drafts.get(thread) === submitted.text) rememberDraft(thread, "");
      if (thread === activeThread && prompt.value === submitted.text) prompt.value = "";
      if (thread === activeThread) error.hidden = true;
    } else if (thread === activeThread) {
      error.textContent = "消息未发送：" + receipt.error;
      error.hidden = false;
    }
    return false;
  });
  if (count !== pendingSubmissions.length) saveDrafts();
}

async function change(path, data) {
  if (requests) return false;
  requests = true;
  buttons();
  const error = find("error");
  error.hidden = true;
  try {
    await request(path, data);
    await refresh();
    return true;
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
    return false;
  } finally {
    requests = false;
    buttons();
  }
}

function focusEntry() {
  if (panel !== "bottom") return false;
  const field = find("sessions").hidden ? prompt : find("session-search");
  if (field.disabled) return false;
  field.focus({preventScroll: true});
  return document.activeElement === field;
}

find("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = prompt.value;
  focusEntry();
  if (!online || busy || requests || !text.trim()) return;
  let submission = pendingSubmissions.find(item => item.thread === activeThread && item.text === text);
  if (!submission) {
    submission = {id: crypto.randomUUID(), text, thread: activeThread};
    pendingSubmissions.push(submission);
    saveDrafts();
  }
  if (await change("prompt", {
    text, thread_id: submission.thread, submission: submission.id,
    model: modelPicker.value || null, effort: effortPicker.value || null,
  })) {
    if (panel === "bottom") focusEntry();
    else prompt.blur();
    buttons();
  }
});
async function openComposer(action, data) {
  if (!(await change(action, data))) return;
  tab("chat");
  buttons();
}

find("task-tab").addEventListener("click", () => openComposer("new", {}));
find("stop").addEventListener("click", () => change("stop", {thread_id: activeThread, turn_id: activeTurn}));
function tab(mode) {
  const changed = mode !== view;
  if (changed) {
    ++listRequest;
    listLoading = false;
    cursor = null;
    listingArchived = false;
    find("archived").textContent = "归档";
  }
  view = mode;
  const showSessions = view !== "chat";
  find("composer").hidden = showSessions;
  find("sessions").hidden = !showSessions;
  closeSessionMenu();
  find("task-tab").setAttribute("aria-pressed", String(!showSessions && !activeThread));
  find("sessions-tab").setAttribute("aria-pressed", String(view === "all"));
  find("pinned-tab").setAttribute("aria-pressed", String(view === "pinned"));
  focusEntry();
  if (changed && panel === "bottom") window.DuoConnection?.consoleInputChanged?.();
}

async function loadSessions(append = false) {
  if (append && (listLoading || !cursor)) return;
  const ticket = ++listRequest;
  const archived = listingArchived;
  if (!append) listSearch = find("session-search").value.trim();
  closeSessionMenu();
  listLoading = true;
  find("more").disabled = true;
  const list = find("session-list");
  const footer = find("session-more");
  const error = find("error");
  error.hidden = true;
  if (!append) {
    const empty = find("session-empty");
    empty.hidden = true;
    footer.hidden = true;
    list.replaceChildren(empty, footer);
    list.scrollTop = 0;
  }
  try {
    const result = await request("threads", {
      archived, search: listSearch,
      cursor: append ? cursor : null, pinned: view === "pinned",
    });
    if (ticket !== listRequest) return;
    const displayed = new Set([...list.querySelectorAll(".session-open")].map(button => button.dataset.threadId));
    for (const thread of result.threads) {
      if (displayed.has(thread.id)) continue;
      displayed.add(thread.id);
      list.insertBefore(makeSessionRow(thread, archived), footer);
    }
    cursor = append && cursor === result.next ? null : result.next;
    updateListFooter();
  } catch (failure) {
    if (ticket !== listRequest) return;
    error.textContent = failure.message;
    error.hidden = false;
  } finally {
    if (ticket === listRequest) {
      listLoading = false;
      find("more").disabled = false;
    }
  }
}

function updateListFooter() {
  find("session-empty").hidden = Boolean(find("session-list").querySelector(".session-row"));
  find("session-more").hidden = !cursor;
}

function makeSessionRow(thread, archived) {
  const row = document.createElement("li");
  row.className = "session-row";
  const button = document.createElement("button");
  button.className = "subtle session-open";
  button.type = "button";
  button.dataset.threadId = thread.id;
  button.classList.toggle("selected", thread.id === activeThread);
  const heading = document.createElement("span");
  const title = document.createElement("span");
  title.className = "session-title";
  const pinned = document.createElement("span");
  pinned.className = "session-pinned";
  pinned.textContent = "已置顶";
  const status = document.createElement("span");
  status.className = "session-running";
  status.textContent = "运行中";
  status.hidden = !runningThreads.has(thread.id);
  heading.append(title, pinned, status);
  const meta = document.createElement("span");
  meta.className = "session-meta";
  meta.textContent = thread.workspace + " · " + new Date(thread.updated_at * 1000).toLocaleDateString("zh-CN");
  button.append(heading, meta);
  button.addEventListener("click", () => openComposer("select", {id: thread.id, archived}));
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "subtle session-row-menu";
  trigger.textContent = "⋯";
  trigger.setAttribute("aria-controls", "session-menu");
  trigger.setAttribute("aria-expanded", "false");
  const updateTitle = () => {
    title.textContent = thread.title;
    pinned.hidden = !thread.pinned;
    trigger.setAttribute("aria-label", thread.title + "的会话操作");
  };
  updateTitle();
  trigger.addEventListener("click", event => {
    if (sessionMenuTarget?.trigger === trigger) {
      closeSessionMenu();
      return;
    }
    openSessionMenu({thread, archived, row, trigger, updateTitle}, event.detail === 0);
  });
  row.append(button, trigger);
  return row;
}

function openSessionMenu(target, fromKeyboard) {
  closeSessionMenu();
  sessionMenuTarget = target;
  find("session-menu-actions").hidden = false;
  find("session-menu-confirmation").hidden = true;
  find("session-rename").hidden = true;
  find("session-pin").textContent = target.thread.pinned ? "取消置顶" : "置顶";
  find("archive").textContent = target.archived ? "恢复" : "归档";
  find("session-menu").hidden = false;
  target.trigger.setAttribute("aria-expanded", "true");
  buttons();
  positionSessionMenu();
  if (fromKeyboard) find("session-pin").focus({preventScroll: true});
  else focusEntry();
}

function positionSessionMenu() {
  const anchor = sessionMenuTarget.trigger.getBoundingClientRect();
  const menu = find("session-menu");
  const gap = 5;
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  const below = anchor.bottom + gap;
  const y = below + h <= window.innerHeight - gap ? below : anchor.top - h - gap;
  menu.style.left = Math.max(gap, Math.min(anchor.right - w, window.innerWidth - w - gap)) + "px";
  menu.style.top = Math.max(gap, Math.min(y, window.innerHeight - h - gap)) + "px";
}

function closeSessionMenu(returnFocus = false) {
  if (!sessionMenuTarget) return;
  const {trigger} = sessionMenuTarget;
  sessionMenuTarget = null;
  if (document.activeElement === find("session-name")) focusEntry();
  trigger.setAttribute("aria-expanded", "false");
  find("session-menu").hidden = true;
  if (returnFocus && trigger.isConnected) trigger.focus({preventScroll: true});
}

async function runSessionAction(target, action, data) {
  if (!(await change(action, {id: target.thread.id, ...data}))) return;
  if (!target.row.isConnected) {
    if (view !== "chat") await loadSessions();
    return;
  }
  if (action === "archive" || action === "unarchive" || (action === "pin" && view === "pinned" && !data.pinned)) {
    target.row.remove();
    updateListFooter();
    return;
  }
  if (action === "rename") target.thread.title = target.thread.name = data.name;
  if (action === "pin") target.thread.pinned = data.pinned;
  target.updateTitle();
}

find("sessions-tab").addEventListener("click", () => {
  tab("all");
  loadSessions();
});
find("pinned-tab").addEventListener("click", () => {
  tab("pinned");
  loadSessions();
});
find("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (panel === "bottom") focusEntry();
  else document.activeElement.blur();
  loadSessions();
});
find("archived").addEventListener("click", () => {
  if (listLoading) return;
  listingArchived = !listingArchived;
  find("archived").textContent = listingArchived ? "查看未归档" : "归档";
  loadSessions();
});
find("more").addEventListener("click", () => {
  focusEntry();
  loadSessions(true);
});
find("session-list").addEventListener("scroll", () => closeSessionMenu());
window.addEventListener("resize", () => {
  if (sessionMenuTarget) positionSessionMenu();
});
document.addEventListener("pointerdown", event => {
  if (sessionMenuTarget && !sessionMenuTarget.trigger.contains(event.target) &&
      !find("session-menu").contains(event.target)) closeSessionMenu();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && sessionMenuTarget) closeSessionMenu(true);
});
find("sessions").addEventListener("mousedown", event => {
  if (panel === "bottom" && event.target.closest(".session-row-menu, .session-menu button, #more")) {
    event.preventDefault();
  }
});
find("session-pin").addEventListener("click", () => {
  const target = sessionMenuTarget;
  closeSessionMenu();
  focusEntry();
  if (target) runSessionAction(target, "pin", {pinned: !target.thread.pinned});
});
find("rename").addEventListener("click", () => {
  if (!sessionMenuTarget) return;
  const name = find("session-name");
  name.value = sessionMenuTarget.thread.name || sessionMenuTarget.thread.title;
  find("session-menu-actions").hidden = true;
  find("session-rename").hidden = false;
  positionSessionMenu();
  name.focus({preventScroll: true});
  name.select();
});
find("archive").addEventListener("click", event => {
  if (!sessionMenuTarget) return;
  const {thread, archived} = sessionMenuTarget;
  const action = archived ? "恢复" : "归档";
  find("session-menu-actions").hidden = true;
  find("session-menu-confirmation").hidden = false;
  find("session-confirmation-label").textContent = action + "「" + thread.title + "」？";
  find("session-confirm").textContent = "确认" + action;
  positionSessionMenu();
  if (event.detail === 0) find("session-cancel").focus({preventScroll: true});
});
find("session-cancel").addEventListener("click", () => {
  closeSessionMenu();
  focusEntry();
});
find("session-confirm").addEventListener("click", () => {
  const target = sessionMenuTarget;
  closeSessionMenu();
  focusEntry();
  if (target) runSessionAction(target, target.archived ? "unarchive" : "archive");
});
find("cancel-rename").addEventListener("click", () => {
  closeSessionMenu();
  focusEntry();
});
find("session-rename").addEventListener("submit", async event => {
  event.preventDefault();
  const target = sessionMenuTarget;
  const name = find("session-name").value.trim();
  if (!target || !name) return;
  focusEntry();
  closeSessionMenu();
  await runSessionAction(target, "rename", {name});
});
prompt.addEventListener("input", () => {
  rememberDraft(activeThread, prompt.value);
  buttons();
});
modelPicker.addEventListener("change", () => { renderEfforts(); buttons(); });
prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    find("composer").requestSubmit();
  }
});
buttons();
function scrollReading(pixels) {
  if (panel === "bottom") return;
  const diff = find("change-detail");
  const target = !find("changes").hidden && diff.scrollHeight > diff.clientHeight ? diff : find("messages");
  target.scrollBy(0, pixels);
}

window.DuoPanel = Object.freeze({
  focusComposer: focusEntry, captureDraft: connectionDraft, restoreDraft: restoreConnectionDraft, scrollReading,
});
// The previous APK calls these names directly when its WebView loads the updated bridge.
Object.assign(window, {focusEntry, connectionDraft, restoreConnectionDraft});
(async function poll() {
  await refresh();
  setTimeout(poll, 700);
})();
