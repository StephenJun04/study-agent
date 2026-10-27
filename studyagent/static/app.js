"use strict";

// The server owns retrieval, grading and mastery. This file only presents public API state.
const $ = (id) => document.getElementById(id);
const storagePrefix = "studyagent.v1.";
const state = {
  spaces: [], spaceId: null, overview: null, session: null, health: null,
  generation: 0, tab: "chat", citations: [], conversations: new Map(), drafts: new Map(), pending: new Set(),
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`); svg.append(use); return svg;
}
function button(text, className, action) {
  const node = el("button", className, text); node.type = "button";
  if (action) node.addEventListener("click", action);
  return node;
}
function readStored(key, fallback = null) {
  try { return JSON.parse(localStorage.getItem(storagePrefix + key)) ?? fallback; } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(storagePrefix + key, JSON.stringify(value)); } catch { /* API state remains authoritative if storage is unavailable. */ }
}
function showMessage(id, message) { const node = $(id); node.textContent = message || ""; node.hidden = !message; }
let toastTimer;
function toast(message) {
  showMessage("toast", message); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4500);
}
function safeUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try { const url = new URL(value, window.location.origin); return ["http:", "https:"].includes(url.protocol) ? url.href : null; } catch { return null; }
}
function link(text, url, className) {
  const href = safeUrl(url);
  if (!href) return el("span", className, text);
  const a = el("a", className, text); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
}
function loading(label) { const node = el("p", "loading-note"); node.append(el("span", "spinner"), document.createTextNode(label)); return node; }
function currentSpace() { return state.spaces.find((space) => space.id === state.spaceId); }
function scopeUrl(spaceId, suffix = "") { return `/spaces/${encodeURIComponent(spaceId)}${suffix}`; }
function isCurrent(spaceId, generation) { return state.spaceId === spaceId && (generation === undefined || state.generation === generation); }
function ready() { return state.health && state.health.ready !== false; }
function pending(key) { return state.pending.has(key); }
function errorText(error) { return error instanceof Error ? error.message : String(error); }

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  const request = { credentials: "same-origin", ...options, signal: controller.signal };
  if (request.body && !(request.body instanceof FormData)) {
    request.headers = { "Content-Type": "application/json", ...request.headers };
    request.body = JSON.stringify(request.body);
  }
  try {
    const response = await fetch(`/api${path}`, request);
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      let detail = data?.detail || data?.error;
      if (Array.isArray(detail)) detail = detail.map((item) => item.msg || "请检查输入内容").join("；");
      if (typeof detail !== "string") detail = `请求未完成（HTTP ${response.status}），请稍后重试。`;
      const error = new Error(detail); error.status = response.status; throw error;
    }
    if (data === null && response.status !== 204) throw new Error("服务返回了无法识别的数据，请确认本地 API 已启动。");
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("请求等待时间较长。操作可能仍在服务端进行，请刷新查看状态后再重试。");
    if (error instanceof TypeError) throw new Error("暂时无法连接本地服务。请确认服务仍在运行，然后点击右上角刷新。");
    throw error;
  } finally { clearTimeout(timeout); }
}

async function runBusy(key, node, label, action, errorId) {
  if (pending(key)) return;
  state.pending.add(key);
  const original = node ? [...node.childNodes].map((child) => child.cloneNode(true)) : [];
  if (node) { node.disabled = true; node.replaceChildren(el("span", "spinner"), document.createTextNode(label)); }
  if (errorId) showMessage(errorId, "");
  try { return await action(); }
  catch (error) { if (errorId) showMessage(errorId, errorText(error)); else toast(errorText(error)); }
  finally { state.pending.delete(key); if (node?.isConnected) { node.disabled = false; node.replaceChildren(...original); } syncControls(); }
}

function renderHealth() {
  const badge = $("provider-badge"); badge.replaceChildren(el("span", "status-dot")); badge.className = "provider-badge";
  const health = state.health;
  if (!health) { badge.classList.add("offline"); badge.append(document.createTextNode("服务未连接")); return; }
  const provider = String(health.provider || "模型服务");
  const isFake = /fake|mock|offline|demo/i.test(provider);
  if (isFake) {
    badge.classList.add("fake"); badge.append(document.createTextNode("离线演示 · 非真实模型"));
    showMessage("system-banner", "当前为离线演示模式：回答与题目由测试提供器生成，用于验证流程，不代表 DeepSeek 的真实表现。");
  } else if (health.ready === false) {
    badge.classList.add("warning"); badge.append(document.createTextNode(`${provider === "deepseek" ? "DeepSeek" : provider} · 待配置`));
    showMessage("system-banner", health.reason || health.error || "DeepSeek 尚未就绪。请在本地 .env 中配置 DEEPSEEK_API_KEY 并重启服务；无需在网页输入密钥。");
  } else {
    badge.append(document.createTextNode(`${provider === "deepseek" ? "DeepSeek" : provider} · 已配置`));
    showMessage("system-banner", "");
  }
  badge.title = health.model ? `模型：${health.model}` : provider;
  syncControls();
}

function renderSpaces() {
  $("space-count").textContent = state.spaces.length;
  $("space-list-empty").hidden = state.spaces.length > 0;
  const fragment = document.createDocumentFragment();
  for (const space of state.spaces) {
    const item = button("", `space-link${space.id === state.spaceId ? " active" : ""}`, () => selectSpace(space.id));
    if (space.id === state.spaceId) item.setAttribute("aria-current", "page");
    item.append(icon(space.kind === "focus" ? "focus" : "book"));
    const text = el("span", "space-text"); text.append(el("strong", "", space.name), el("small", "", space.kind === "focus" ? "专注空间" : "课程空间")); item.append(text); fragment.append(item);
  }
  $("space-list").replaceChildren(fragment);
}

function renderHeader() {
  const space = currentSpace();
  $("welcome").hidden = Boolean(space); $("active-workspace").hidden = !space;
  $("breadcrumb-name").textContent = space?.name || "开始学习";
  if (!space) return;
  $("space-name").textContent = space.name; $("space-topic").textContent = space.topic || "";
  $("space-kind").textContent = space.kind === "focus" ? "FOCUS · 专注空间" : "COURSE · 课程空间";
  const docs = state.overview?.documents || []; const concepts = state.overview?.concepts || [];
  $("space-summary").textContent = `${docs.length} 份资料 · ${concepts.length} 个概念`;
  $("document-count").textContent = docs.length; $("focus-admit-note").hidden = space.kind !== "focus";
}

function conversation(spaceId) {
  if (!state.conversations.has(spaceId)) {
    const value = readStored(`chat.${spaceId}`, {});
    state.conversations.set(spaceId, { id: value.id || null, messages: Array.isArray(value.messages) ? value.messages : [], pending: false });
  }
  return state.conversations.get(spaceId);
}
function saveConversation(spaceId, convo) { store(`chat.${spaceId}`, { id: convo.id, messages: convo.messages.slice(-100) }); }
function citationLocation(citation) {
  const parts = [];
  if (citation.page !== null && citation.page !== undefined) parts.push(`第 ${citation.page} 页`);
  if (citation.section) parts.push(String(citation.section));
  return parts.join(" · ") || "原文片段";
}
function citationUrl(citation, spaceId = state.spaceId) {
  if (citation.document_id && spaceId) {
    return `/api${scopeUrl(spaceId, `/documents/${encodeURIComponent(citation.document_id)}/file`)}${citation.page ? `#page=${encodeURIComponent(citation.page)}` : ""}`;
  }
  return safeUrl(citation.url);
}
function citationChips(citations, spaceId) {
  const row = el("div", "message-citations");
  for (const [index, citation] of citations.entries()) {
    const chip = link(`[${index + 1}] ${citation.filename || "资料"} · ${citationLocation(citation)}`, citationUrl(citation, spaceId), "citation-chip");
    chip.addEventListener("click", () => { if (isCurrent(spaceId)) renderEvidence(citations); }); row.append(chip);
  }
  return row;
}
function renderChat() {
  if (!state.spaceId) return;
  const convo = conversation(state.spaceId), container = $("chat-messages");
  const fragment = document.createDocumentFragment();
  if (!convo.messages.length) {
    const empty = el("div", "chat-empty"), mark = el("div", "empty-mark"); mark.append(icon("spark"));
    empty.append(mark, el("h2", "", "今天，想弄明白什么？"), el("p", "", (state.overview?.documents || []).length ? "从当前资料出发，解释一个概念、比较两个观点，或接着上一个问题深入。" : "先在资料库放入课程材料，再带着问题回来。你也可以先描述想学习的内容。"));
    const prompts = el("div", "prompt-suggestions");
    for (const text of ["梳理这份资料的核心概念", "用一个例子解释重点", "这些概念之间有什么联系？"]) {
      prompts.append(button(text, "prompt-chip", () => { $("chat-input").value = text; $("chat-input").focus(); }));
    }
    empty.append(prompts); fragment.append(empty);
  }
  for (const message of convo.messages) {
    const isUser = message.role === "user";
    if (!["user", "assistant"].includes(message.role)) continue;
    const article = el("article", `message ${isUser ? "user" : "assistant"}`), avatar = el("span", "message-avatar", isUser ? "你" : undefined);
    if (!isUser) avatar.append(icon("spark"));
    const body = el("div", "message-body");
    body.append(el("div", "message-role", isUser ? "你" : "StudyAgent"), el("div", "message-text", message.content || message.answer || ""));
    if (message.citations?.length) body.append(citationChips(message.citations, state.spaceId));
    if (message.gap) body.append(el("p", "decision-note", typeof message.gap === "string" ? message.gap : "当前资料的证据存在缺口，请补充相关资料后继续。"));
    article.append(avatar, body); fragment.append(article);
  }
  if (convo.pending) fragment.append(loading("正在检索当前空间的资料并组织回答…"));
  container.replaceChildren(fragment); container.scrollTop = container.scrollHeight; syncControls();
}

function renderEvidence(citations = []) {
  state.citations = Array.isArray(citations) ? citations : [];
  $("evidence-count").textContent = state.citations.length;
  const fragment = document.createDocumentFragment();
  if (!state.citations.length) fragment.append(el("p", "empty-small", "提问或开始学习后，相关原文、页码和出处会出现在这里。"));
  for (const [index, citation] of state.citations.entries()) {
    const card = el("article", "evidence-item"), heading = el("h3", "evidence-title");
    heading.append(el("span", "evidence-number", index + 1), el("span", "", citation.filename || "学习资料"));
    card.append(heading, el("p", "evidence-location", citationLocation(citation)));
    if (citation.quote || citation.text) card.append(el("blockquote", "evidence-quote", citation.quote || citation.text));
    const source = link("查看原文", citationUrl(citation), "evidence-link"); source.append(icon("external")); card.append(source); fragment.append(card);
  }
  $("evidence-list").replaceChildren(fragment);
}

function conceptName(id) { return (state.overview?.concepts || []).find((concept) => concept.id === id)?.name || id || "当前概念"; }
function graphEndpoint(value) { return typeof value === "object" && value ? value.id : value; }
function renderGraph() {
  const concepts = state.overview?.concepts || [], graph = state.overview?.graph || {}, edges = Array.isArray(graph.edges) ? graph.edges : [];
  const container = $("concept-graph"), relations = $("graph-relations"); container.replaceChildren(); relations.replaceChildren();
  const svgNS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs = {}, text) { const node = document.createElementNS(svgNS, tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value)); if (text !== undefined) node.textContent = text; return node; }
  if (!concepts.length) {
    const placeholder = svgEl("svg", { viewBox: "0 0 230 110", class: "graph-placeholder", "aria-hidden": "true" });
    placeholder.append(svgEl("path", { d: "M45 72 105 32 185 64M105 32 125 88M45 72 125 88 185 64" }));
    for (const [cx, cy, r] of [[45, 72, 12], [105, 32, 17], [185, 64, 12], [125, 88, 8]]) placeholder.append(svgEl("circle", { cx, cy, r }));
    container.append(placeholder, el("p", "graph-empty-label", "资料校验后，概念将在这里连接。"));
  } else {
    const visible = concepts.slice(0, 8), positions = new Map();
    const rows = Math.ceil(visible.length / 2), height = Math.max(100, rows * 55 + 20);
    visible.forEach((concept, index) => positions.set(concept.id, { x: index % 2 ? 178 : 57, y: 30 + Math.floor(index / 2) * 55 }));
    const svg = svgEl("svg", { viewBox: `0 0 235 ${height}`, class: "knowledge-svg", role: "img", "aria-label": `${concepts.length} 个概念，${edges.length} 条关系。下方可查看文字关系。` });
    for (const edge of edges) {
      const a = positions.get(graphEndpoint(edge.source || edge.from || edge.prerequisite_id)), b = positions.get(graphEndpoint(edge.target || edge.to || edge.concept_id));
      if (a && b) svg.append(svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y }));
    }
    for (const concept of visible) {
      const point = positions.get(concept.id), group = svgEl("g");
      group.append(svgEl("title", {}, concept.name), svgEl("rect", { x: point.x - 50, y: point.y - 16, width: 100, height: 32, rx: 8 }));
      group.append(svgEl("text", { x: point.x, y: point.y + 3, "text-anchor": "middle" }, concept.name.length > 8 ? concept.name.slice(0, 8) + "…" : concept.name)); svg.append(group);
    }
    container.append(svg, el("p", "graph-legend", `${concepts.length} 个概念 · ${edges.length} 条关系${concepts.length > 8 ? " · 图示前 8 个" : ""}`));
  }
  if (!edges.length) relations.append(el("p", "", concepts.length ? "尚无已建立的概念关系。" : "上传资料后查看概念关系。"));
  for (const edge of edges) {
    const source = graphEndpoint(edge.source || edge.from || edge.prerequisite_id), target = graphEndpoint(edge.target || edge.to || edge.concept_id);
    const relation = edge.relation || edge.type || "关联";
    relations.append(el("p", "", `${conceptName(source)} → ${conceptName(target)}${relation ? `（${relation}）` : ""}`));
  }
}

function renderConcepts() {
  const concepts = state.overview?.concepts || [], select = $("goal-concept"), previous = select.value;
  select.replaceChildren(new Option(concepts.length ? "选择你想理解的概念" : "上传资料后选择概念", ""));
  for (const concept of concepts) select.add(new Option(concept.name, concept.id));
  if (concepts.some((concept) => concept.id === previous)) select.value = previous;
  else if (state.session?.goal_concept_id) select.value = state.session.goal_concept_id;
  $("concept-count").textContent = `${concepts.length} 个概念`;
  const fragment = document.createDocumentFragment();
  if (!concepts.length) fragment.append(el("div", "empty-state", "还没有可学习的概念。请先在资料库上传与当前主题相关的资料。"));
  for (const concept of concepts) {
    const card = el("article", "concept-row"), info = el("div", "concept-info"), mastery = el("div", "concept-mastery");
    info.append(el("h3", "", concept.name));
    if (concept.description) info.append(el("p", "", concept.description));
    const record = concept.mastery || {}, score = typeof record.score === "number" && Number.isFinite(record.score) ? record.score : null;
    mastery.append(el("div", "mastery-label", score === null ? "未测评" : `${Math.round(score * 100)}% · ${record.attempts || 0} 次`));
    const track = el("div", "mastery-track"), fill = el("div", "mastery-fill"); fill.style.width = `${score === null ? 0 : Math.max(0, Math.min(100, score * 100))}%`; track.append(fill); mastery.append(track);
    const choose = button("选为目标", "text-button", () => { setTab("learn"); select.value = concept.id; select.focus(); toast(`已选择：${concept.name}`); });
    card.append(info, mastery, choose); fragment.append(card);
  }
  $("concept-list").replaceChildren(fragment); syncControls();
}

const statusLabels = { admitted: "已纳入", accepted: "校验通过", valid: "校验通过", ready: "可用于学习", indexed: "可用于学习", rejected: "未通过校验", pending: "等待校验", processing: "处理中", error: "处理失败", needs_clarification: "需要补充说明", needs_confirmation: "需要确认" };
function renderDocuments() {
  const docs = state.overview?.documents || [], spaceId = state.spaceId, courses = state.spaces.filter((space) => space.kind === "course");
  $("material-summary").textContent = `${docs.length} 份资料`;
  const fragment = document.createDocumentFragment();
  if (!docs.length) fragment.append(el("div", "empty-state", "资料库还是空的。上传第一份资料，为这段学习建立依据。"));
  for (const doc of docs) {
    const card = el("article", "document-card"), top = el("div", "document-top"), mark = el("span", "document-icon"), main = el("div", "document-main"); mark.append(icon("file"));
    const statusClass = ["rejected", "error"].includes(doc.status) ? "rejected" : ["pending", "processing", "needs_clarification", "needs_confirmation"].includes(doc.status) ? "pending" : "";
    main.append(el("h3", "", doc.filename || "未命名资料"), el("span", `document-status ${statusClass}`, statusLabels[doc.status] || doc.status || "状态未知"));
    top.append(mark, main); card.append(top);
    if (doc.reason) card.append(el("p", "document-reason", doc.reason));
    const actions = el("div", "document-actions"), source = link("打开文件", `/api${scopeUrl(spaceId, `/documents/${encodeURIComponent(doc.id)}/file`)}`, "text-button"); source.append(icon("external")); actions.append(source);
    if (doc.source_url) actions.append(link("原始来源", doc.source_url, "text-button")); card.append(actions);
    if (currentSpace()?.kind === "focus") {
      if (!courses.length) card.append(el("p", "helper", "创建课程空间后，可将这份资料纳入课程。"));
      else {
        const form = el("form", "admit-form"), select = el("select"), submit = el("button", "button secondary", "纳入课程"); submit.type = "submit";
        select.setAttribute("aria-label", `将 ${doc.filename || "资料"} 纳入哪门课程`); select.required = true; select.add(new Option("选择目标课程", ""));
        for (const course of courses) select.add(new Option(course.name, course.id));
        const result = el("p", "form-result"), error = el("p", "inline-error"); result.setAttribute("role", "status"); error.setAttribute("role", "alert");
        form.append(select, submit, result, error);
        form.addEventListener("submit", async (event) => {
          event.preventDefault(); if (!select.value) return;
          const courseId = select.value; error.textContent = ""; result.textContent = "";
          await runBusy(`admit.${spaceId}.${doc.id}`, submit, "校验中…", async () => {
            try {
              const document = await api(scopeUrl(courseId, "/admit"), { method: "POST", body: { source_space_id: spaceId, document_id: doc.id } });
              result.textContent = `${statusLabels[document.status] || document.status || "已处理"}。${document.reason || ""} 课程与专注空间的掌握记录独立保存。`;
            } catch (failure) { error.textContent = errorText(failure); }
          });
        }); card.append(form);
      }
    }
    fragment.append(card);
  }
  $("document-list").replaceChildren(fragment);
}

function renderMemories() {
  const memories = state.overview?.memories || []; const fragment = document.createDocumentFragment();
  for (const memory of memories) {
    const value = typeof memory === "string" ? memory : memory.content || memory.text;
    if (value) fragment.append(el("p", "memory-item", value));
  }
  $("memory-list").replaceChildren(fragment);
}

function renderOverview() { renderHeader(); renderConcepts(); renderGraph(); renderDocuments(); renderMemories(); }

function setTab(name, focus = false) {
  if (!["chat", "learn", "materials"].includes(name)) name = "chat";
  state.tab = name; if (state.spaceId) store(`tab.${state.spaceId}`, name);
  for (const tab of document.querySelectorAll("[data-tab]")) {
    const selected = tab.dataset.tab === name; tab.classList.toggle("active", selected); tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
    $(`panel-${tab.dataset.tab}`).hidden = !selected;
  }
  if (focus) $(`tab-${name}`).focus();
  if (name === "learn") { renderSession(); if (state.session?.citations?.length) renderEvidence(state.session.citations); }
  if (name === "chat" && state.spaceId) { const latest = conversation(state.spaceId).messages.findLast((item) => item.role === "assistant"); renderEvidence(latest?.citations || []); }
}

function sessionStatus(status) { return ({ waiting: "等待作答", running: "学习进行中", paused: "已暂停", stopped: "已结束", completed: "本次目标已完成", error: "需要恢复", needs_clarification: "需要补充说明" })[status] || status || "状态未知"; }
function saveSession(view, spaceId) { store(`session.${spaceId}`, view?.id || null); }
function renderSession() {
  const container = $("session-content"), session = state.session; container.replaceChildren();
  if (pending(`start.${state.spaceId}`)) { container.append(loading("正在检索概念依据，准备讲解与练习…")); return; }
  if (!session) { container.append(el("p", "session-empty", "选择学习目标后，从解释开始。每道题由你提交答案，反馈和掌握情况由服务端更新。")); return; }
  const spaceId = state.spaceId, sessionId = session.id, locallyPaused = readStored(`paused.${spaceId}`, null) === sessionId;
  const card = el("article", "session-card"), header = el("div", "session-header");
  header.append(el("strong", "", locallyPaused && session.status === "waiting" ? "练习已暂存" : sessionStatus(session.status)), el("span", "", `学习步骤 ${session.step ?? 0}`));
  card.append(header);
  const body = el("div", "session-body");
  body.append(el("p", "session-goal", `目标：${conceptName(session.goal_concept_id)} · 当前：${conceptName(session.current_concept_id)}`));
  if (locallyPaused && !["completed", "stopped", "needs_clarification"].includes(session.status)) {
    body.append(el("p", "explanation", "当前讲解与练习已保留。继续后会回到同一道未提交的题目。"));
  } else {
    if (session.feedback) {
      const feedback = el("div", `feedback${session.feedback.correct === false ? " incorrect" : ""}`);
      feedback.append(el("strong", "", session.feedback.correct === true ? "上一题 · 回答正确" : session.feedback.correct === false ? "上一题 · 再校准一下理解" : "上一题反馈"));
      feedback.append(el("p", "", session.feedback.feedback || "作答结果已记录。")); body.append(feedback);
    }
    if (session.explanation) body.append(el("div", "explanation", session.explanation));
    if (session.citations?.length) body.append(citationChips(session.citations, spaceId));
    if (session.error) body.append(el("p", "session-notice", typeof session.error === "string" ? session.error : "学习流程中断，可点击恢复继续。"));
    if (session.quiz && !["stopped", "completed", "needs_clarification"].includes(session.status)) body.append(buildQuiz(session, spaceId));
    else if (session.status === "completed") body.append(el("p", "session-notice", "本次学习已完成。可以选择另一个概念，或回到对话继续追问。"));
  }
  card.append(body);
  const actions = el("div", "session-actions");
  if (!["completed", "stopped", "needs_clarification"].includes(session.status)) {
    if (locallyPaused || ["error", "paused", "needs_clarification", "running"].includes(session.status)) {
      const resume = button(locallyPaused ? "继续这次学习" : "恢复学习", "button primary", () => sessionAction("resume", resume));
      resume.dataset.sessionAction = "resume"; resume.disabled = !ready() || pending(`session.${spaceId}`); actions.append(resume);
    } else {
      actions.append(button("暂存并返回对话", "button secondary", () => { store(`paused.${spaceId}`, sessionId); setTab("chat"); toast("已保留当前练习，可随时回来继续。"); }));
    }
    const stop = button("结束本次学习", "text-button", () => sessionAction("stop", stop)); stop.dataset.sessionAction = "stop"; stop.disabled = pending(`session.${spaceId}`); actions.append(stop);
  } else actions.append(button("回到对话", "button secondary", () => setTab("chat")));
  card.append(actions); container.append(card);
}

function buildQuiz(session, spaceId) {
  const quiz = session.quiz, form = el("form", "quiz-form"), fieldset = el("fieldset");
  form.append(el("p", "quiz-label", "CHECK YOUR UNDERSTANDING")); fieldset.append(el("legend", "", quiz.question || "请完成这道练习"));
  const options = Array.isArray(quiz.options) ? quiz.options : [];
  if (options.length) {
    options.forEach((option, index) => {
      const label = el("label", "quiz-option"), input = el("input"); input.type = "radio"; input.name = "answer"; input.value = String(option); input.required = true;
      label.append(input, el("span", "", `${String.fromCharCode(65 + index)}. ${option}`)); fieldset.append(label);
    });
  } else {
    const answer = el("textarea"); answer.name = "answer"; answer.rows = 3; answer.required = true; answer.maxLength = 6000; answer.setAttribute("aria-label", "你的答案"); answer.placeholder = "用自己的话写下答案…"; fieldset.append(answer);
  }
  const submit = el("button", "button primary", "提交答案"); submit.type = "submit"; submit.disabled = !ready() || pending(`session.${spaceId}`);
  form.append(fieldset, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); const answer = new FormData(form).get("answer"); if (!answer || pending(`session.${spaceId}`)) return;
    const generation = state.generation;
    // One id per displayed quiz submission is reused on an explicit retry.
    const submissionKey = `submission.${spaceId}.${session.id}.${quiz.id}`;
    const previous = readStored(submissionKey, null);
    const submissionId = previous?.answer === answer ? previous.id : (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    store(submissionKey, { id: submissionId, answer });
    await runBusy(`session.${spaceId}`, submit, "正在核对与更新…", async () => {
      fieldset.disabled = true;
      try {
        const view = await api(scopeUrl(spaceId, `/sessions/${encodeURIComponent(session.id)}/answer`), { method: "POST", body: { quiz_id: quiz.id, submission_id: submissionId, answer: String(answer) } });
        saveSession(view, spaceId);
        if (isCurrent(spaceId, generation)) { state.session = view; renderSession(); renderEvidence(view.citations || []); await refreshOverview(spaceId, generation); refreshTracesIfOpen(); }
      } catch (error) { if (isCurrent(spaceId, generation)) showMessage("learn-error", errorText(error)); }
      finally { fieldset.disabled = false; }
    });
  }); return form;
}

async function sessionAction(action, node) {
  const spaceId = state.spaceId, sessionId = state.session?.id, generation = state.generation; if (!sessionId) return;
  await runBusy(`session.${spaceId}`, node, action === "stop" ? "正在结束…" : "正在恢复…", async () => {
    try {
      const view = await api(scopeUrl(spaceId, `/sessions/${encodeURIComponent(sessionId)}/${action}`), { method: "POST", body: {} }); saveSession(view, spaceId); store(`paused.${spaceId}`, null);
      if (isCurrent(spaceId, generation)) { state.session = view; renderSession(); renderEvidence(view.citations || []); await refreshOverview(spaceId, generation); refreshTracesIfOpen(); }
    } catch (error) { if (isCurrent(spaceId, generation)) showMessage("learn-error", errorText(error)); }
  });
}

async function refreshOverview(spaceId, generation = state.generation) {
  const overview = await api(scopeUrl(spaceId, "/overview"));
  if (isCurrent(spaceId, generation)) { state.overview = overview; renderOverview(); }
  return overview;
}

async function restoreChat(spaceId, generation) {
  const convo = conversation(spaceId); if (!convo.id || convo.pending) return;
  try {
    const response = await api(scopeUrl(spaceId, `/chats/${encodeURIComponent(convo.id)}`));
    if (Array.isArray(response.history) && !convo.pending) {
      convo.messages = response.history.filter((item) => ["user", "assistant"].includes(item.role)).map((item) => ({ ...item, content: item.content || item.answer || "" })); saveConversation(spaceId, convo);
      if (isCurrent(spaceId, generation)) { renderChat(); if (state.tab === "chat") renderEvidence(convo.messages.findLast((item) => item.role === "assistant")?.citations || []); }
    }
  } catch (error) { if (error.status !== 404 && isCurrent(spaceId, generation)) showMessage("chat-error", `对话恢复未完成：${errorText(error)}`); }
}

async function selectSpace(spaceId) {
  if (!state.spaces.some((space) => space.id === spaceId)) return;
  if (state.spaceId) state.drafts.set(state.spaceId, $("chat-input").value);
  const generation = ++state.generation; state.spaceId = spaceId; state.overview = null; state.session = null;
  store("selectedSpace", spaceId); $("chat-input").value = state.drafts.get(spaceId) || "";
  for (const id of ["chat-error", "learn-error", "upload-error", "upload-result", "preference-error", "preference-result", "global-error"]) showMessage(id, "");
  $("upload-form").reset(); $("file-label").textContent = "选择一份学习资料"; $("preference-form").reset();
  $("sidebar").classList.remove("open"); $("menu-toggle").setAttribute("aria-expanded", "false");
  renderSpaces(); renderOverview(); renderChat(); renderEvidence([]); $("trace-list").replaceChildren();
  setTab(readStored(`tab.${spaceId}`, "chat"));
  $("session-content").replaceChildren(loading("正在恢复学习记录…"));
  try {
    const overview = await refreshOverview(spaceId, generation);
    if (!isCurrent(spaceId, generation)) return;
    let sessionId = readStored(`session.${spaceId}`, null);
    const sessions = Array.isArray(overview.sessions) ? overview.sessions : [];
    if (!sessionId || !sessions.some((session) => session.id === sessionId)) sessionId = sessions.find((session) => !["completed", "stopped", "needs_clarification"].includes(session.status))?.id || null;
    const jobs = [restoreChat(spaceId, generation)];
    if (sessionId) jobs.push((async () => {
      try {
        const session = await api(scopeUrl(spaceId, `/sessions/${encodeURIComponent(sessionId)}`));
        if (isCurrent(spaceId, generation)) { state.session = session; saveSession(session, spaceId); renderSession(); renderConcepts(); if (state.tab === "learn") renderEvidence(session.citations || []); }
      } catch (error) { if (isCurrent(spaceId, generation)) { renderSession(); showMessage("learn-error", `学习记录恢复未完成：${errorText(error)}`); } }
    })()); else renderSession();
    await Promise.allSettled(jobs); if (isCurrent(spaceId, generation)) refreshTracesIfOpen();
  } catch (error) { if (isCurrent(spaceId, generation)) showMessage("global-error", errorText(error)); }
}

function safeTracePayload(payload) {
  if (!payload || typeof payload !== "object") return typeof payload === "string" ? payload : "";
  const safe = {};
  // Traces intentionally omit assessment internals and raw model prompts.
  for (const key of ["action", "reason", "tool", "status", "message", "concept_id", "evidence_ids", "document_id", "count", "accepted", "decision"]) {
    if (payload[key] !== undefined) safe[key] = key === "decision" ? safeTracePayload(payload[key]) : payload[key];
  }
  return safe;
}
async function loadTraces() {
  if (!state.spaceId) return;
  const spaceId = state.spaceId, generation = state.generation, container = $("trace-list"); container.replaceChildren(loading("读取轨迹…"));
  try {
    const query = state.tab === "learn" && state.session?.id ? `?session_id=${encodeURIComponent(state.session.id)}` : "";
    const response = await api(scopeUrl(spaceId, `/traces${query}`)); if (!isCurrent(spaceId, generation)) return;
    const traces = Array.isArray(response) ? response : response.traces || [], fragment = document.createDocumentFragment();
    if (!traces.length) fragment.append(el("p", "empty-small", "还没有决策轨迹。提问、上传资料或完成练习后再来查看。"));
    for (const trace of traces.slice(-30).reverse()) {
      const card = el("article", "trace-item"), payload = safeTracePayload(trace.payload);
      card.append(el("h3", "", trace.kind || "流程记录"));
      if (trace.created_at) card.append(el("p", "", String(trace.created_at).replace("T", " ").slice(0, 19)));
      if (typeof payload === "string") card.append(el("p", "", payload));
      else if (Object.keys(payload).length) card.append(el("pre", "", JSON.stringify(payload, null, 2)));
      else card.append(el("p", "", "状态已记录。"));
      fragment.append(card);
    }
    container.replaceChildren(fragment);
  } catch (error) { if (isCurrent(spaceId, generation)) container.replaceChildren(el("p", "inline-error", errorText(error))); }
}
function refreshTracesIfOpen() { if ($("trace-details").open) void loadTraces(); }

function syncControls() {
  const spaceId = state.spaceId, active = Boolean(spaceId), available = ready();
  $("chat-send").disabled = !active || !available || Boolean(active && conversation(spaceId).pending);
  $("new-chat").disabled = !active || Boolean(active && conversation(spaceId).pending);
  $("start-learning").disabled = !active || !available || !(state.overview?.concepts || []).length || pending(`start.${spaceId}`) || pending(`session.${spaceId}`);
  $("upload-submit").disabled = !active || pending(`upload.${spaceId}`);
  $("save-preference").disabled = !active || pending(`preference.${spaceId}`);
  $("chat-hint").textContent = !available ? "模型尚未就绪，请查看上方连接提示" : "Enter 发送 · Shift + Enter 换行";
  for (const submit of document.querySelectorAll(".quiz-form button[type=submit]")) submit.disabled = !available || pending(`session.${spaceId}`);
  for (const action of document.querySelectorAll("[data-session-action]")) action.disabled = pending(`session.${spaceId}`) || (action.dataset.sessionAction === "resume" && !available);
}

function openSpaceDialog(kind = "course") {
  $("space-form").reset(); $("space-form").querySelector(`input[name=kind][value=${kind}]`).checked = true;
  showMessage("space-error", ""); $("space-dialog").showModal(); $("space-name-input").focus();
}

$("new-space").addEventListener("click", () => openSpaceDialog());
$("welcome-course").addEventListener("click", () => openSpaceDialog("course"));
$("welcome-focus").addEventListener("click", () => openSpaceDialog("focus"));
$("close-dialog").addEventListener("click", () => $("space-dialog").close());
$("cancel-dialog").addEventListener("click", () => $("space-dialog").close());
$("menu-toggle").addEventListener("click", () => { const open = $("sidebar").classList.toggle("open"); $("menu-toggle").setAttribute("aria-expanded", String(open)); });
document.addEventListener("click", (event) => { if ($("sidebar").classList.contains("open") && !event.target.closest("#sidebar, #menu-toggle")) { $("sidebar").classList.remove("open"); $("menu-toggle").setAttribute("aria-expanded", "false"); } });
document.addEventListener("keydown", (event) => { if (event.key === "Escape") { $("sidebar").classList.remove("open"); $("menu-toggle").setAttribute("aria-expanded", "false"); } });

$("space-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget), name = String(form.get("name") || "").trim(), topic = String(form.get("topic") || "").trim();
  if (!name || !topic) { showMessage("space-error", "请填写空间名称与主题范围。"); return; }
  await runBusy("create-space", $("create-space"), "正在创建…", async () => {
    const space = await api("/spaces", { method: "POST", body: { name, topic, kind: form.get("kind") } });
    state.spaces.push(space); $("space-dialog").close(); await selectSpace(space.id); toast("学习空间已创建。现在可以添加资料了。"); setTab("materials");
  }, "space-error");
});

for (const tab of document.querySelectorAll("[data-tab]")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    const tabs = ["chat", "learn", "materials"], current = tabs.indexOf(tab.dataset.tab);
    if (["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) {
      event.preventDefault(); const index = event.key === "Home" ? 0 : event.key === "End" ? 2 : (current + (event.key === "ArrowRight" ? 1 : 2)) % 3; setTab(tabs[index], true);
    }
  });
}

$("chat-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$("chat-send").disabled) $("chat-form").requestSubmit(); } });
$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const spaceId = state.spaceId, generation = state.generation, input = $("chat-input"), message = input.value.trim();
  if (!spaceId || !message || !ready()) return;
  const convo = conversation(spaceId); if (convo.pending) return;
  showMessage("chat-error", ""); convo.pending = true; const userMessage = { role: "user", content: message }; convo.messages.push(userMessage);
  input.value = ""; state.drafts.set(spaceId, ""); renderChat();
  try {
    const response = await api("/chat", { method: "POST", body: { space_id: spaceId, chat_id: convo.id, message, baseline: false } });
    convo.id = response.chat_id || convo.id; convo.messages.push({ role: "assistant", content: response.answer || "", citations: response.citations || [], decision: response.decision, gap: response.gap }); saveConversation(spaceId, convo);
    if (isCurrent(spaceId, generation)) { renderEvidence(response.citations || []); refreshTracesIfOpen(); }
  } catch (error) {
    convo.messages = convo.messages.filter((item) => item !== userMessage);
    if (isCurrent(spaceId, generation)) { showMessage("chat-error", errorText(error)); if (!input.value) input.value = message; }
    else state.drafts.set(spaceId, message);
  } finally { convo.pending = false; if (isCurrent(spaceId)) renderChat(); }
});
$("new-chat").addEventListener("click", () => { if (!state.spaceId || conversation(state.spaceId).pending) return; const convo = { id: null, messages: [], pending: false }; state.conversations.set(state.spaceId, convo); saveConversation(state.spaceId, convo); renderChat(); renderEvidence([]); showMessage("chat-error", ""); $("chat-input").focus(); });

$("goal-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const spaceId = state.spaceId, generation = state.generation, conceptId = $("goal-concept").value; if (!spaceId || !conceptId || !ready()) return;
  await runBusy(`start.${spaceId}`, $("start-learning"), "正在准备…", async () => {
    if (isCurrent(spaceId, generation)) renderSession();
    try {
      const view = await api(scopeUrl(spaceId, "/sessions"), { method: "POST", body: { concept_id: conceptId } }); saveSession(view, spaceId); store(`paused.${spaceId}`, null);
      if (isCurrent(spaceId, generation)) { state.session = view; renderEvidence(view.citations || []); await refreshOverview(spaceId, generation); refreshTracesIfOpen(); }
    } catch (error) { if (isCurrent(spaceId, generation)) showMessage("learn-error", errorText(error)); }
  });
  if (isCurrent(spaceId, generation)) renderSession();
});

$("document-file").addEventListener("change", () => { $("file-label").textContent = $("document-file").files[0]?.name || "选择一份学习资料"; });
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const spaceId = state.spaceId, generation = state.generation, file = $("document-file").files[0]; if (!spaceId || !file) return;
  if (!/\.(pdf|txt|md|markdown)$/i.test(file.name)) { showMessage("upload-error", "请选择 PDF、TXT 或 Markdown 文件。"); return; }
  const form = new FormData(); form.append("file", file); const source = $("source-url").value.trim(); if (source) form.append("source_url", source);
  showMessage("upload-error", ""); showMessage("upload-result", "");
  await runBusy(`upload.${spaceId}`, $("upload-submit"), "正在解析与校验…", async () => {
    try {
      const document = await api(scopeUrl(spaceId, "/documents"), { method: "POST", body: form });
      if (isCurrent(spaceId, generation)) {
        showMessage("upload-result", `${statusLabels[document.status] || document.status || "资料已处理"}。${document.reason || ""}`);
        $("upload-form").reset(); $("file-label").textContent = "选择一份学习资料"; await refreshOverview(spaceId, generation); renderChat(); refreshTracesIfOpen();
      }
    } catch (error) { if (isCurrent(spaceId, generation)) showMessage("upload-error", errorText(error)); }
  });
});

$("preference-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const spaceId = state.spaceId, generation = state.generation, content = $("preference-input").value.trim(); if (!spaceId || !content) return;
  showMessage("preference-error", ""); showMessage("preference-result", "");
  await runBusy(`preference.${spaceId}`, $("save-preference"), "正在校验…", async () => {
    try {
      const result = await api(scopeUrl(spaceId, "/preferences"), { method: "POST", body: { content } });
      if (isCurrent(spaceId, generation)) { showMessage("preference-result", result.reason || result.message || (result.accepted === false ? "这条偏好未通过校验。" : "学习偏好已保存。")); await refreshOverview(spaceId, generation); refreshTracesIfOpen(); }
    } catch (error) { if (isCurrent(spaceId, generation)) showMessage("preference-error", errorText(error)); }
  });
});
$("trace-details").addEventListener("toggle", () => { if ($("trace-details").open) void loadTraces(); });
$("refresh-traces").addEventListener("click", () => runBusy(`traces.${state.spaceId}`, $("refresh-traces"), "读取中…", loadTraces));

async function boot() {
  showMessage("global-error", "");
  const results = await Promise.allSettled([api("/health"), api("/spaces")]);
  if (results[0].status === "fulfilled") { state.health = results[0].value; renderHealth(); }
  else { state.health = null; renderHealth(); showMessage("system-banner", errorText(results[0].reason)); }
  if (results[1].status === "fulfilled") {
    state.spaces = Array.isArray(results[1].value) ? results[1].value : results[1].value.spaces || []; renderSpaces();
    const selected = state.spaceId || readStored("selectedSpace"); const space = state.spaces.find((item) => item.id === selected) || state.spaces[0];
    if (space) await selectSpace(space.id); else { state.spaceId = null; renderHeader(); }
  } else showMessage("global-error", errorText(results[1].reason));
  syncControls();
}
$("refresh-app").addEventListener("click", () => runBusy("refresh", $("refresh-app"), "", boot));
void boot();
