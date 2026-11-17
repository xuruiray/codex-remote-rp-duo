import {diffBlock} from "./diff-view.js";

function createMarkdown() {
  const renderer = window.markdownit({html: false}).disable("image");
  renderer.renderer.rules.link_open = (tokens, index) =>
    '<span class="markdown-link" title="' + renderer.utils.escapeHtml(tokens[index].attrGet("href") || "") + '">';
  renderer.renderer.rules.link_close = () => "</span>";
  return renderer;
}

const markdown = createMarkdown();
function desktopUserText(text) {
  const match = text.match(/^\s*# Files mentioned by the user:[^\S\r\n]*\r?\n([\s\S]*?)\r?\n## My request:[^\S\r\n]*(?:\r?\n|$)([\s\S]*)$/);
  if (!match) return {text, files: []};
  const files = [...match[1].matchAll(/^## (.+?): (?:[/~]|[A-Za-z]:[\\/]).+$/gm)].map(file => file[1]);
  return files.length ? {text: match[2], files, metadata: match[1].trim()} : {text, files: []};
}

const MAX_COMMAND_GROUP = 32;

export function mountConversation({messages, older, panel, loadAttachment, loadOlder, retryHistory}) {
  let thread = null;
  let archived = false;
  let latestEntries = [];
  let olderEntries = [];
  let historyBefore = null;
  let historyError = false;
  let loadedOlder = false;
  let historyRequest = 0;
  const renderedEntries = new Map();
  let renderedCommandGroups = new Map();

  function imageAttachment(entry, attachment, index) {
    const node = document.createElement(attachment.preview ? "details" : "div");
    node.className = "attachment";
    const label = document.createElement(attachment.preview ? "summary" : "span");
    label.textContent = "图片 · " + attachment.name;
    node.append(label);
    if (!attachment.preview) return node;
    const preview = document.createElement("div");
    preview.className = "attachment-preview";
    node.append(preview);
    let requested = false;
    node.addEventListener("toggle", async () => {
      if (!node.open || requested) return;
      requested = true;
      preview.textContent = "正在读取图片…";
      const selected = thread;
      try {
        const blob = await loadAttachment(selected, entry.id, index);
        if (!node.isConnected || selected !== thread) return;
        if (!blob.type.startsWith("image/")) throw new Error("图片格式无法预览");
        const url = URL.createObjectURL(blob);
        const img = document.createElement("img");
        img.alt = attachment.name;
        img.addEventListener("load", () => URL.revokeObjectURL(url), {once: true});
        img.addEventListener("error", () => {
          URL.revokeObjectURL(url);
          requested = false;
          preview.textContent = "图片无法显示";
        }, {once: true});
        preview.replaceChildren(img);
        img.src = url;
      } catch (failure) {
        requested = false;
        preview.textContent = failure.message;
      }
    });
    return node;
  }

  function renderUserAttachments(entry, userText) {
    const media = entry.attachments || [];
    const fields = document.createElement("div");
    fields.className = "user-attachments";
    for (const [index, attachment] of media.entries()) fields.append(imageAttachment(entry, attachment, index));
    const mediaNames = new Set(media.map(image => image.name));
    for (const file of userText.files) {
      if (mediaNames.has(file)) continue;
      const label = document.createElement("div");
      label.className = "attachment";
      label.textContent = "文件 · " + file;
      fields.append(label);
    }
    if (userText.metadata) {
      const details = document.createElement("details");
      details.className = "attachment attachment-info";
      const summary = document.createElement("summary");
      summary.textContent = "附件信息";
      const text = document.createElement("pre");
      text.textContent = userText.metadata;
      details.append(summary, text);
      fields.append(details);
    }
    return fields.hasChildNodes() ? fields : null;
  }

  function applyMessageDisclosure(record) {
    const folded = !record.toggle.hidden && record.collapsed;
    record.node.classList.toggle("is-collapsed", folded);
    record.toggle.textContent = folded ? "展开" : "收起";
    record.toggle.setAttribute("aria-expanded", String(!folded));
  }

  function measureMessageDisclosures() {
    const width = messages.clientWidth;
    if (!width) return;
    const measured = [];
    for (const record of renderedEntries.values()) {
      if (!record.toggle || !record.node.isConnected || record.measuredWidth === width) continue;
      const lineHeight = parseFloat(getComputedStyle(record.content).lineHeight);
      measured.push([record, record.content.scrollHeight > lineHeight * 5 + 1]);
    }
    for (const [record, canCollapse] of measured) {
      record.measuredWidth = width;
      record.toggle.hidden = !canCollapse;
      applyMessageDisclosure(record);
    }
  }

  function renderEntry(entry) {
    if (entry.role === "trace" && !entry.text && !entry.output && !entry.diff) return null;
    const signature = JSON.stringify(entry);
    const rendered = renderedEntries.get(entry.id);
    if (rendered?.signature === signature) return rendered.node;
    const isTrace = entry.role === "trace";
    const node = rendered?.node || document.createElement(isTrace ? "details" : "article");
    const record = {node, signature, collapsed: rendered?.collapsed ?? entry.role === "user"};
    node.className = isTrace ? "trace" : "message " + entry.role;
    if (isTrace) {
      node.dataset.kind = entry.kind;
      if (!rendered && entry.kind === "reasoning" && entry.status === "inProgress") node.open = true;
      const heading = document.createElement("summary");
      const label = document.createElement("span");
      label.className = "trace-label";
      label.textContent = entry.label;
      const meta = document.createElement("small");
      const statuses = {inProgress: "进行中", completed: "完成", failed: "失败", declined: "已拒绝"};
      meta.textContent = typeof entry.exit_code === "number" ? "退出码 " + entry.exit_code : statuses[entry.status] || "";
      heading.append(label);
      if (["command", "file", "tool"].includes(entry.kind) && entry.text) {
        const preview = document.createElement("span");
        preview.className = "trace-preview";
        preview.textContent = entry.text.split("\n", 1)[0];
        heading.append(preview);
      }
      heading.append(meta);
      const detail = document.createElement("div");
      detail.className = "trace-content";
      if (entry.kind === "reasoning") {
        detail.classList.add("markdown");
        detail.innerHTML = markdown.render(entry.text);
      } else {
        for (const [key, value] of Object.entries({text: entry.text, output: entry.output, diff: entry.diff})) {
          if (!value) continue;
          if (key === "diff") {
            detail.append(diffBlock(value));
          } else {
            const pre = document.createElement("pre");
            pre.textContent = value;
            detail.append(pre);
          }
        }
      }
      node.replaceChildren(heading, detail);
    } else {
      const label = document.createElement("div");
      label.className = "role";
      label.textContent = entry.role === "user" ? "你" : "Codex";
      const content = document.createElement("div");
      content.id = "message-" + entry.id;
      const isUser = entry.role === "user";
      content.classList.add("message-content", isUser ? "user-text" : "markdown");
      const userText = isUser ? desktopUserText(entry.text) : null;
      const text = userText ? userText.text : entry.text;
      if (isUser) content.textContent = text;
      else content.innerHTML = markdown.render(text || "…");
      const attachments = userText && renderUserAttachments(entry, userText);
      node.replaceChildren(label, ...[attachments, content].filter(Boolean));
      if (text && entry.complete !== false) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "message-toggle";
        toggle.setAttribute("aria-controls", content.id);
        toggle.hidden = true;
        record.toggle = toggle;
        record.content = content;
        applyMessageDisclosure(record);
        toggle.addEventListener("click", () => {
          record.collapsed = !record.collapsed;
          applyMessageDisclosure(record);
        });
        node.append(toggle);
      }
    }
    renderedEntries.set(entry.id, record);
    return node;
  }

  function commandGroup(entries, commandCount, previousGroups, currentGroups, usedGroups) {
    const rows = entries.map(renderEntry);
    const group = entries.map(entry => previousGroups.get(entry.id))
      .find(candidate => candidate && !usedGroups.has(candidate))
      || document.createElement("details");
    if (!group.firstChild) {
      const summary = document.createElement("summary");
      const list = document.createElement("div");
      list.className = "command-group-list";
      group.className = "command-group";
      group.open = rows.some(row => row.open);
      group.append(summary, list);
    }
    group.firstElementChild.textContent = "已执行 " + commandCount + " 条命令";
    const list = group.lastElementChild;
    if (rows.length !== list.children.length || rows.some((row, index) => row !== list.children[index])) {
      list.replaceChildren(...rows);
    }
    for (const entry of entries) currentGroups.set(entry.id, group);
    usedGroups.add(group);
    return group;
  }

  function conversationNodes(entries) {
    const nodes = [];
    const currentGroups = new Map();
    const usedGroups = new Set();
    let run = [];
    let commandCount = 0;
    let trailingFiles = [];
    function flush() {
      if (commandCount === 1) nodes.push(renderEntry(run[0]));
      if (commandCount > 1) {
        nodes.push(commandGroup(run, commandCount, renderedCommandGroups, currentGroups, usedGroups));
      }
      nodes.push(...trailingFiles.map(renderEntry));
      run = [];
      commandCount = 0;
      trailingFiles = [];
    }
    for (const entry of entries) {
      if (entry.role === "trace" && !entry.text && !entry.output && !entry.diff) continue;
      const successfulCommand = entry.kind === "command" && entry.status === "completed"
        && entry.exit_code === 0
        && (!entry.source || ["agent", "unifiedExecStartup", "unifiedExecInteraction"].includes(entry.source));
      if (successfulCommand) {
        if (commandCount === MAX_COMMAND_GROUP) flush();
        run.push(...trailingFiles, entry);
        trailingFiles = [];
        ++commandCount;
      } else if (entry.kind === "file" && commandCount) {
        trailingFiles.push(entry);
      } else {
        flush();
        nodes.push(renderEntry(entry));
      }
    }
    flush();
    renderedCommandGroups = currentGroups;
    return nodes;
  }

  function drawMessages(scrollMode = "keep") {
    const previousHeight = messages.scrollHeight;
    const previousScroll = messages.scrollTop;
    const nearBottom = previousHeight - previousScroll - messages.clientHeight < 45;
    const entries = [...olderEntries, ...latestEntries];
    const ids = new Set(entries.map(entry => entry.id));
    for (const id of renderedEntries.keys()) {
      if (!ids.has(id)) renderedEntries.delete(id);
    }
    const nodes = conversationNodes(entries);
    if (!nodes.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = historyError ? "历史暂时无法加载，可以重试。" :
        panel === "top" ? "在下屏打开会话，或开始新聊天。" : "输入消息后，回复会显示在这里。";
      nodes.push(empty);
    }
    if (nodes.length !== messages.children.length ||
        nodes.some((node, index) => messages.children[index] !== node)) {
      messages.replaceChildren(...nodes);
    }
    measureMessageDisclosures();
    if (scrollMode === "older") {
      messages.scrollTop = previousScroll + messages.scrollHeight - previousHeight;
    } else {
      messages.scrollTop = nearBottom || scrollMode === "latest" ? messages.scrollHeight : previousScroll;
    }
  }

  function update(state) {
    const selectionChanged = thread !== state.thread_id;
    const errorChanged = historyError !== Boolean(state.history_error);
    thread = state.thread_id;
    archived = state.archived;
    historyError = Boolean(state.history_error);
    if (selectionChanged) {
      ++historyRequest;
      older.disabled = false;
      olderEntries = [];
      loadedOlder = false;
      renderedEntries.clear();
      renderedCommandGroups.clear();
    }
    if (loadedOlder) {
      const newest = new Set(state.messages.map(entry => entry.id));
      const known = new Set(olderEntries.map(entry => entry.id));
      const firstRetained = latestEntries.findIndex(entry => newest.has(entry.id));
      if (firstRetained > 0) {
        olderEntries.push(...latestEntries.slice(0, firstRetained).filter(entry => !known.has(entry.id)));
      }
      olderEntries = olderEntries.filter(entry => !newest.has(entry.id));
    } else {
      historyBefore = state.history_before;
    }
    if (selectionChanged || errorChanged || JSON.stringify(state.messages) !== JSON.stringify(latestEntries)) {
      latestEntries = state.messages;
      drawMessages(selectionChanged ? "latest" : "keep");
    }
    older.hidden = !historyBefore && !historyError;
    if (selectionChanged || errorChanged) older.textContent = historyError ? "重试加载历史" : "更早的记录";
  }

  older.addEventListener("click", async () => {
    const ticket = ++historyRequest;
    older.disabled = true;
    try {
      if (historyError) {
        await retryHistory(thread, archived);
        return;
      }
      const page = await loadOlder(thread, historyBefore);
      if (ticket !== historyRequest) return;
      loadedOlder = true;
      const known = new Set([...olderEntries, ...latestEntries].map(entry => entry.id));
      olderEntries.unshift(...page.messages.filter(entry => !known.has(entry.id)));
      historyBefore = page.history_before;
      older.textContent = "更早的记录";
      older.hidden = !historyBefore;
      drawMessages("older");
    } catch (_) {
      if (ticket === historyRequest) older.textContent = "重试加载历史";
    } finally {
      if (ticket === historyRequest) older.disabled = false;
    }
  });

  new ResizeObserver(measureMessageDisclosures).observe(messages);
  return {update};
}
