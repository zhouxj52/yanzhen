"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const state = {
  config: null,
  bundle: null,
  run: null,
  poll: null,
  selected: null,
  busy: false,
  runs: [],
  view: "overview",
  chartFilter: "all",
  evidenceLimit: 12,
  libraryGeneration: 0,
  opening: 0,
};
const verdicts = {
  pass: "通过",
  fail: "发现缺陷",
  blocked: "执行受阻",
  unclear: "需要澄清",
};
const escapeText = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("服务未返回有效响应");
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
const post = (path, data) =>
  api(path, { method: "POST", body: JSON.stringify(data) });
let toastTimer;
function toast(message, error = false) {
  $("#toast").textContent = message;
  $("#toast").classList.toggle("error", error);
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => ($("#toast").hidden = true),
    error ? 9000 : 4500,
  );
}
function activeView(name) {
  if (
    ![
      "overview",
      "workbench",
      "history",
      "evidence",
      "guide",
    ].includes(name)
  )
    name = "overview";
  state.view = name;
  $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + name));
  $$(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name),
  );
  $("#page-name").textContent = {
    overview: "项目概览",
    workbench: "验收工作台",
    history: "运行记录",
    evidence: "证据中心",
    guide: "使用指南",
  }[name];
  window.history.replaceState(null, "", "#" + name);
  closeSidebar();
  if (name === "history") renderHistory();
  if (name === "evidence") renderLibrary();
  window.scrollTo(0, 0);
}
function setStep(number) {
  $$(".step").forEach((s) =>
    s.classList.toggle("current", Number(s.dataset.step) === number),
  );
}
function updateButtons() {
  const executing =
    state.run && ["queued", "running", "finalizing"].includes(state.run.status);
  const locked = state.busy || executing;
  $("#analyze").disabled = locked;
  $("#requirements").disabled = locked;
  $("#provider").disabled = locked;
  $("#load-example").disabled = locked;
  $("#target").disabled = locked;
  $("#new-draft").disabled = locked;
  $("#freeze").disabled = locked || !state.bundle || state.bundle.frozen;
  $("#run").disabled = state.busy || executing || !state.bundle?.frozen;
  $("#replay").disabled = state.busy || state.run?.status !== "completed";
  $("#cancel").disabled =
    state.busy || !["queued", "running"].includes(state.run?.status);
  $("#integrity").disabled = !state.run?.artifacts?.includes("manifest.json");
}
function dirty() {
  if (state.bundle) {
    state.bundle = null;
    renderBundle();
    setStep(1);
  }
  $("#char-count").textContent = $("#requirements").value.length + " 字";
  updateButtons();
}
function renderBundle() {
  const bundle = state.bundle;
  $("#contract-count").textContent = bundle?.contracts.length || 0;
  $("#bundle-status").textContent = bundle
    ? bundle.frozen
      ? "已冻结"
      : "待审阅"
    : "等待分析";
  $("#bundle-status").className =
    "status-pill " + (bundle?.frozen ? "frozen" : "neutral");
  $("#digest").textContent = bundle
    ? "SHA-256 " + bundle.digest.slice(0, 18) + "…"
    : "尚未生成内容摘要";
  if (!bundle) {
    $("#contracts").innerHTML =
      '<div class="empty-contract"><div class="empty-icon">≋</div><h3>先明确标准，再开始验收</h3><p>输入需求后，生成角色、预期行为和来源引用。<br>审阅并冻结，执行过程中保持标准不变。</p></div>';
    return;
  }
  $("#contracts").innerHTML = bundle.contracts
    .map(
      (c) =>
        `<article class="contract-item"><div class="contract-title"><span class="contract-id">${escapeText(c.id)}</span>${escapeText(c.title)}</div><div class="contract-meta">角色 ${escapeText(c.role)} · 预期 ${escapeText(c.expected)}${c.kind === "unclear" ? " · 需要澄清" : ""}</div><div class="contract-quote">${escapeText(c.source_quote)}</div></article>`,
    )
    .join("");
}
async function analyze() {
  ++state.opening;
  state.busy = true;
  updateButtons();
  $("#analyze").textContent = "正在分析需求…";
  try {
    state.bundle = await post("/api/analyze", {
      requirements: $("#requirements").value,
      provider: $("#provider").value,
      target: $("#target").value,
    });
    renderBundle();
    setStep(2);
    toast("契约已生成，请核对原文、角色与预期结果。");
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.busy = false;
    $("#analyze").innerHTML =
      icon("sparkles") + "生成验收契约" + icon("arrow-right");
    updateButtons();
  }
}
async function freeze() {
  if (!state.bundle) return;
  state.busy = true;
  updateButtons();
  try {
    state.bundle = await post(`/api/bundles/${state.bundle.id}/freeze`, {
      digest: state.bundle.digest,
    });
    renderBundle();
    setStep(3);
    $("#run-id").textContent = "标准已锁定，可以开始验收";
    toast("契约已冻结；执行过程不能放宽验收标准。");
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.busy = false;
    updateButtons();
  }
}
async function startRun(replay = false) {
  ++state.opening;
  state.busy = true;
  state.selected = null;
  $("#run-status").textContent = "正在创建任务";
  updateButtons();
  try {
    const run = replay
      ? await post(`/api/runs/${state.run.id}/replay`, {})
      : await post("/api/runs", {
          bundle_id: state.bundle.id,
          scenario: $("#scenario").value,
          browser: $("#browser").checked,
          target: $("#target").value,
        });
    state.run = run;
    renderRun();
    clearTimeout(state.poll);
    await pollRun(run.id);
    toast(
      replay
        ? "已创建全新环境，按原冻结契约重放。"
        : "验收已开始，证据将随执行过程更新。",
    );
  } catch (e) {
    toast(e.message, true);
    if (state.run) renderRun();
    else $("#run-status").textContent = "创建任务失败";
  } finally {
    state.busy = false;
    updateButtons();
  }
}
async function pollRun(id) {
  try {
    if (state.run?.id !== id) return;
    const updated = await api("/api/runs/" + id);
    if (state.run?.id !== id) return;
    state.run = updated;
    renderRun();
    if (["queued", "running", "finalizing"].includes(state.run.status))
      state.poll = setTimeout(() => pollRun(id), 900);
    else {
      refreshHistory();
      updateButtons();
      if (state.run.status === "error")
        toast(state.run.error || "执行未完成", true);
    }
  } catch (e) {
    if (state.run?.id !== id) return;
    toast("查询运行失败：" + e.message, true);
    state.poll = setTimeout(() => pollRun(id), 3000);
  }
}
function renderRun() {
  const run = state.run;
  if (!run) return;
  const finished = ["completed", "error", "cancelled"].includes(run.status);
  $("#run-status").textContent = {
    queued: "等待执行",
    running: "正在验收",
    finalizing: "正在整理证据",
    completed: "验收完成",
    error: "运行中断",
    cancelled: "任务已取消（保留已完成结果）",
  }[run.status];
  $("#run-dot").className = "run-dot " + run.status;
  $("#run-id").textContent =
    run.id.slice(0, 12) +
    " · " +
    scenarioName(run) +
    (run.target === "todomvc"
      ? " · 浏览器"
      : run.browser_requested
        ? " · 浏览器＋接口"
        : " · 仅接口");
  $("#export").classList.toggle(
    "disabled",
    !finished || !run.artifacts?.includes("evidence.zip"),
  );
  const downloadable = finished && run.artifacts?.includes("evidence.zip");
  $("#export").setAttribute("aria-disabled", String(!downloadable));
  if (downloadable)
    $("#export").href = `/api/runs/${run.id}/artifacts/evidence.zip`;
  else $("#export").removeAttribute("href");
  for (const key of Object.keys(verdicts))
    $(`[data-metric="${key}"]`).textContent = run.summary?.[key] ?? 0;
  const results = run.results || [];
  if (state.selected === null && finished && results.length)
    state.selected = Math.max(
      0,
      results.findIndex((r) => r.verdict === "fail"),
    );
  $("#results").innerHTML = results.length
    ? results
        .map(
          (r, i) =>
            `<tr data-result="${i}" tabindex="0" role="button" aria-label="查看${escapeText(r.title)}证据" class="${state.selected === i ? "selected" : ""}"><td><small>${escapeText(r.contract_id)}</small>${escapeText(r.title)}</td><td><span class="verdict ${r.verdict}">${verdicts[r.verdict]}</span></td><td>${r.evidence.length} 项</td><td>${(r.duration_ms / 1000).toFixed(1)}s</td></tr>`,
        )
        .join("")
    : '<tr><td colspan="4" class="empty-row">' +
      (run.status === "cancelled"
        ? "任务已取消；未执行的检查不作判定。"
        : "正在准备独立测试环境，等待第一条结果…") +
      "</td></tr>";
  $$("[data-result]").forEach((row) => {
    const select = () => {
      state.selected = Number(row.dataset.result);
      renderRun();
    };
    row.onclick = select;
    row.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        select();
      }
    };
  });
  $("#events").innerHTML = (run.events || [])
    .map(
      (e) =>
        `<li><time>${new Date(e.time).toLocaleTimeString("zh-CN")}</time>${escapeText(e.message)}</li>`,
    )
    .join("");
  $("#event-count").textContent = (run.events || []).length + " 个事件";
  renderEvidence();
  renderInnovations();
  $("#comparison").hidden = !run.replay_comparison;
  if (run.replay_comparison)
    $("#comparison").textContent = run.replay_comparison.matches
      ? "✓ 已在新环境重放，冻结契约和各项判定与原运行一致。"
      : "重放结果存在差异或未完成验证，请检查原始证据。";
  updateButtons();
}
function renderEvidence() {
  const result = state.run?.results?.[state.selected];
  if (!result) {
    $("#evidence").innerHTML =
      '<div class="evidence-title">EVIDENCE / 证据详情</div><div class="evidence-empty">选择一条验收结果<br>查看执行步骤与原始证据。</div>';
    return;
  }
  const base = `/api/runs/${state.run.id}/artifacts/`;
  $("#evidence").innerHTML =
    `<div class="evidence-title">EVIDENCE / ${escapeText(result.contract_id)}</div><span class="verdict ${result.verdict}">${verdicts[result.verdict]}</span><h3>${escapeText(result.title)}</h3><p>${escapeText(result.summary)}</p><ol>${result.replay_steps.map((s) => "<li>" + escapeText(s) + "</li>").join("")}</ol>${result.evidence.map((e) => (e.kind === "screenshot" ? `<details open><summary>${escapeText(e.description)}</summary><a href="${base + encodeURIComponent(e.file)}" target="_blank" rel="noopener"><img class="evidence-image" src="${base + encodeURIComponent(e.file)}" alt="${escapeText(e.description)}"></a></details>` : `<details${e.kind === "repair" ? " open" : ""}><summary>${escapeText(e.description)}</summary><pre>${escapeText(JSON.stringify(e.data, null, 2))}</pre></details>`)).join("")}`;
  renderConflicts(result);
}
async function refreshHistory() {
  try {
    const runs = await api("/api/runs");
    state.runs = runs;
    $("#history-count").textContent = runs.length;
    renderOverview();
    renderHistory();
    if (state.view === "evidence") await renderLibrary();
    renderPalette();
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}
async function openRun(id) {
  if (state.busy) return;
  const opening = ++state.opening;
  try {
    const run = await api("/api/runs/" + id);
    const bundle = await api("/api/bundles/" + run.bundle_id);
    if (opening !== state.opening) return;
    clearTimeout(state.poll);
    state.run = run;
    state.bundle = bundle;
    configureTarget(run.target || "reimbursement", false);
    $("#requirements").value = state.bundle.requirements;
    $("#provider").value = state.bundle.provider;
    $("#scenario").value = state.run.scenario;
    $("#browser").checked = state.run.browser_requested;
    $("#char-count").textContent = $("#requirements").value.length + " 字";
    state.selected = null;
    renderBundle();
    renderRun();
    setStep(3);
    activeView("workbench");
    $(".execution-card").scrollIntoView({ block: "start" });
    if (["queued", "running", "finalizing"].includes(state.run.status))
      await pollRun(id);
  } catch (e) {
    toast(e.message, true);
  }
}
function providerChanged() {
  dirty();
  const provider = $("#provider").value;
  const model = provider !== "offline";
  const config = state.config.providers?.[provider] || {};
  $("#provider-help").textContent = model
    ? config.configured
      ? "将通过服务端调用 " +
        config.label +
        " · " +
        config.model +
        "，只用于解析需求。"
      : "请在项目本地 .env 配置 " +
        (provider === "deepseek" ? "YZ_DEEPSEEK_API_KEY" : "YZ_LLM_API_KEY") +
        "，启用模型并重启服务。"
    : "无需模型密钥。仅识别内置场景，不代表模型推理能力。";
  $("#model-mode").textContent = model
    ? (config.label || provider) + " API"
    : "离线演示 · 固定规则";
}
function renderModelAvailability() {
  for (const provider of ["qwen", "deepseek"]) {
    const config = state.config.providers?.[provider] || {
      enabled: provider === "qwen" && state.config.model_enabled,
    };
    const option = $('#provider option[value="' + provider + '"]');
    option.disabled = !config.enabled;
    option.textContent =
      (provider === "deepseek" ? "DeepSeek" : "Qwen") +
      (config.enabled ? " API" : " · 暂未启用");
  }
  $("#sidebar-model-note").textContent = state.config.model_enabled
    ? "模型接口已启用，可选择离线规则或已配置的模型。"
    : "模型调用已关闭，浏览器执行和证据校验正常可用。";
  $("#guide-model-status").textContent = state.config.model_enabled
    ? "接口已启用，按需选择"
    : "默认关闭";
}
async function init() {
  try {
    state.config = await api("/api/config");
    $("#requirements").value = state.config.default_requirements;
    $("#char-count").textContent = $("#requirements").value.length + " 字";
    $("#scenario").innerHTML = Object.entries(state.config.scenarios)
      .map(
        ([key, value]) =>
          `<option value="${key}">${escapeText(value)}</option>`,
      )
      .join("");
    $("#scenario").value = "broken";
    renderModelAvailability();
    $("#requirements").addEventListener("input", dirty);
    $("#provider").onchange = providerChanged;
    $("#load-example").onclick = () => {
      $("#requirements").value =
        state.config.targets[$("#target").value].requirements;
      dirty();
    };
    $("#analyze").onclick = analyze;
    $("#freeze").onclick = freeze;
    $("#run").onclick = () => startRun();
    $("#replay").onclick = () => startRun(true);
    $("#cancel").onclick = async () => {
      try {
        await post(`/api/runs/${state.run.id}/cancel`, {});
        toast("取消请求已提交，已完成结果会保留。");
      } catch (error) {
        toast(error.message, true);
      }
    };
    $("#integrity").onclick = async () => {
      try {
        const result = await api(`/api/runs/${state.run.id}/integrity`);
        toast(
          result.valid
            ? `证据校验通过，${result.files_checked} 个文件完整。`
            : result.errors.join("\n"),
          !result.valid,
        );
      } catch (error) {
        toast(error.message, true);
      }
    };
    $("#refresh-history").onclick = () => refreshFeedback("记录已更新");
    $("#refresh-overview").onclick = () => refreshFeedback("概览已更新");
    $("#refresh-evidence").onclick = () => refreshFeedback("证据列表已更新");
    $$("[data-view]").forEach(
      (b) => (b.onclick = () => activeView(b.dataset.view)),
    );
    await refreshHistory();
    bindWorkspace();
    configureTarget("reimbursement", false);
    $("#target").onchange = () => {
      configureTarget($("#target").value, true);
    };
    $("#review-repair").onclick = reviewRepairCandidate;
    renderBundle();
    resetRun();
    hydrateIcons();
    $("#service-status").textContent = "服务连接正常";
    activeView(location.hash.slice(1) || "overview");
    updateButtons();
  } catch (e) {
    toast("工作台初始化失败：" + e.message, true);
  }
}

// Original inline icons; no external font, CDN or component runtime is needed.
const strokes = {
  layout:
    '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  flask:
    '<path d="M9 3h6m-5 0v6l-6 10a1.3 1.3 0 0 0 1 2h14a1.3 1.3 0 0 0 1-2L14 9V3M7 15h10"/>',
  history: '<path d="M3 5v5h5m-5 0a9 9 0 1 1 1 7m8-11v6l4 2"/>',
  archive:
    '<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v13h14V8m-10 4h6"/>',
  book: '<path d="M12 5C8 2 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1v15"/>',
  code: '<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/>',
  "shield-check":
    '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 11 3 3 5-5"/>',
  "arrow-right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  "chevron-right": '<path d="m9 5 7 7-7 7"/>',
  "panel-left":
    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3 2.5c-.5.2-.5 1-.5 2M12 17h.01"/>',
  refresh:
    '<path d="M20 8V3l-4 4M4 16v5l4-4M20 8a8 8 0 0 0-14-2M4 16a8 8 0 0 0 14 2"/>',
  rotate: '<path d="M3 3v6h6m-6 0a9 9 0 1 1 0 7"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8Zm-10 10 10 5 10-5M2 18l10 5 10-5"/>',
  users:
    '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-15a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5"/>',
  workflow:
    '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M9 6h6a3 3 0 0 1 3 3v6M6 9v9h9"/>',
  database:
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  "file-text": '<path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6"/>',
  "file-json":
    '<path d="M14 3H5v18h14V8Zm0 0v5h5M10 11H9v2l-1 1 1 1v2h1m4-6h1v2l1 1-1 1v2h-1"/>',
  sparkles:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
  "list-check": '<path d="m3 6 2 2 3-4m3 2h10M3 13h4m4 0h10M3 20h4m4 0h10"/>',
  fingerprint:
    '<path d="M4 13v-2a8 8 0 0 1 16 0v4M7 17v-6a5 5 0 0 1 10 0v5l-1 5M10 20l1-5v-4a1 1 0 0 1 2 0v5l-1 6M4 17l-1 3"/>',
  play: '<path d="m8 4 13 8-13 8Z"/>',
  square: '<rect x="5" y="5" width="14" height="14" rx="1"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  terminal:
    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  x: '<path d="m5 5 14 14M19 5 5 19"/>',
};
function icon(name) {
  return (
    '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">' +
    (strokes[name] || strokes["file-text"]) +
    "</svg>"
  );
}
function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
  });
}
const statusNames = {
  completed: "已完成",
  queued: "排队中",
  running: "执行中",
  finalizing: "整理证据",
  cancelled: "已取消",
  error: "已中断",
};
const working = () =>
  ["queued", "running", "finalizing"].includes(state.run?.status);
const scenarioName = (r) =>
  state.config?.targets?.[r.target || "reimbursement"]?.scenarios[r.scenario] ||
  state.config?.scenarios[r.scenario] ||
  r.scenario;
const statusPill = (r) =>
  '<span class="status-pill status-' +
  escapeText(r.status) +
  '">' +
  escapeText(statusNames[r.status] || r.status) +
  "</span>";
function dateText(value, timeOnly = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    ...(timeOnly ? {} : { month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
function emptyState(title, message, glyph = "archive") {
  return (
    '<div class="empty-state">' +
    icon(glyph) +
    "<h3>" +
    escapeText(title) +
    "</h3><p>" +
    escapeText(message) +
    "</p></div>"
  );
}
function summaryHTML(run) {
  return (
    '<span class="result-inline"><span class="pass-text">通过 ' +
    (run.summary?.pass || 0) +
    '</span><span class="fail-text">缺陷 ' +
    (run.summary?.fail || 0) +
    "</span></span>"
  );
}
function runRow(run, full = false) {
  const id = escapeText(run.id);
  return (
    '<tr class="' +
    (full ? "history-item" : "") +
    '"><td><div class="task-cell"><span class="task-icon">' +
    icon(run.parent_run ? "rotate" : "file-text") +
    "</span><div><strong>" +
    escapeText(scenarioName(run)) +
    (run.parent_run ? '<span class="replay-tag">重放</span>' : "") +
    '</strong><small title="' +
    id +
    '">' +
    id.slice(0, 16) +
    "</small></div></div></td><td>" +
    statusPill(run) +
    "</td><td>" +
    summaryHTML(run) +
    (full
      ? '<small class="muted">受阻 ' +
        (run.summary?.blocked || 0) +
        " · 待澄清 " +
        (run.summary?.unclear || 0) +
        "</small>"
      : "") +
    '</td><td class="date-cell">' +
    dateText(run.created_at) +
    '</td><td class="align-right"><button class="row-open" data-open-run="' +
    id +
    '">查看详情 →</button></td></tr>'
  );
}
function bindRunLinks(root) {
  root.querySelectorAll("[data-open-run]").forEach((button) => {
    button.onclick = () => {
      $("#search-dialog").close();
      openRun(button.dataset.openRun);
    };
  });
}
function renderOverview() {
  const runs = state.runs;
  const completed = runs.filter((r) => r.status === "completed").length;
  const metrics = [
    ["运行任务", runs.length, "history", "最近 50 次记录"],
    ["完成执行", completed, "shield-check", "包含存在缺陷的运行"],
    [
      "缺陷判定",
      runs.reduce((n, r) => n + (r.summary?.fail || 0), 0),
      "flask",
      "按检查项累计，非去重缺陷",
    ],
    [
      "独立重放",
      runs.filter((r) => r.parent_run).length,
      "rotate",
      "按原冻结契约新建环境",
    ],
  ];
  $("#overview-metrics").innerHTML = metrics
    .map(
      ([name, value, glyph, foot]) =>
        '<article class="card metric-card"><div class="metric-top"><span>' +
        name +
        "</span><i>" +
        icon(glyph) +
        '</i></div><div class="metric-value" data-overview-metric="' +
        glyph +
        '">' +
        value +
        '</div><div class="metric-foot">' +
        icon("info") +
        foot +
        "</div></article>",
    )
    .join("");
  $("#recent-runs").innerHTML = runs.length
    ? runs
        .slice(0, 5)
        .map((r) => runRow(r))
        .join("")
    : '<tr><td colspan="5">' +
      emptyState("还没有运行记录", "新建一次验收，开始积累可复核的证据。") +
      "</td></tr>";
  bindRunLinks($("#recent-runs"));
  renderChart();
}
function renderChart() {
  const recent = state.runs.slice(0, 14).reverse();
  const runs =
    state.chartFilter === "fail"
      ? recent.filter((r) => r.summary?.fail > 0)
      : recent;
  $("#chart-count").textContent = runs.length + " 次运行";
  $$("[data-chart-filter]").forEach((el) => {
    el.classList.toggle(
      "selected",
      el.dataset.chartFilter === state.chartFilter,
    );
    el.setAttribute(
      "aria-pressed",
      String(el.dataset.chartFilter === state.chartFilter),
    );
  });
  if (!runs.length) {
    $("#activity-chart").innerHTML = emptyState(
      "暂无匹配的运行",
      "完成验收后，这里会显示实际检查结果。",
      "layout",
    );
    return;
  }
  const width = 600,
    height = 185,
    top = 16,
    bottom = 153,
    left = 28;
  const max = Math.max(
    5,
    ...runs.map((r) =>
      Object.values(r.summary || {}).reduce((a, b) => a + b, 0),
    ),
  );
  let svg =
    '<svg role="img" aria-label="最近运行检查结果柱状图" viewBox="0 0 ' +
    width +
    " " +
    height +
    '" preserveAspectRatio="none">';
  for (let n = 0; n <= max; n += Math.max(1, Math.ceil(max / 5))) {
    const y = bottom - (n / max) * (bottom - top);
    svg +=
      '<line x1="' +
      left +
      '" x2="594" y1="' +
      y +
      '" y2="' +
      y +
      '" stroke="#e3e9f4" stroke-dasharray="3 4"/><text x="16" y="' +
      (y + 3) +
      '" text-anchor="end" fill="#8795af" font-size="9">' +
      n +
      "</text>";
  }
  const step = (width - left - 10) / runs.length,
    bw = Math.min(24, step * 0.5);
  runs.forEach((r, i) => {
    const x = left + step * (i + 0.5) - bw / 2;
    let y = bottom;
    svg +=
      "<g><title>" +
      escapeText(
        scenarioName(r) +
          " · " +
          dateText(r.created_at) +
          " · 通过 " +
          (r.summary?.pass || 0) +
          " / 缺陷 " +
          (r.summary?.fail || 0) +
          " / 受阻 " +
          (r.summary?.blocked || 0) +
          " / 待澄清 " +
          (r.summary?.unclear || 0),
      ) +
      "</title>";
    [
      ["pass", "#57a692"],
      ["fail", "#d17c80"],
      ["blocked", "#cfb274"],
      ["unclear", "#a4afc5"],
    ].forEach(([key, color]) => {
      const h = ((r.summary?.[key] || 0) / max) * (bottom - top);
      y -= h;
      if (h)
        svg +=
          '<rect x="' +
          x +
          '" y="' +
          y +
          '" width="' +
          bw +
          '" height="' +
          h +
          '" rx="2" fill="' +
          color +
          '"/>';
    });
    if (y === bottom)
      svg +=
        '<circle cx="' +
        (x + bw / 2) +
        '" cy="' +
        (bottom - 2) +
        '" r="2" fill="#c7ccda"/>';
    if (i % Math.ceil(runs.length / 6) === 0)
      svg +=
        '<text x="' +
        (x + bw / 2) +
        '" y="177" text-anchor="middle" fill="#8d9db9" font-size="9">' +
        dateText(r.created_at, true) +
        "</text>";
    svg += "</g>";
  });
  $("#activity-chart").innerHTML = svg + "</svg>";
}
function matchesQuery(r, query) {
  return (
    r.id +
    " " +
    scenarioName(r) +
    " " +
    (statusNames[r.status] || "") +
    " " +
    (r.parent_run ? "重放" : "")
  )
    .toLowerCase()
    .includes(query.toLowerCase());
}
function renderHistory() {
  const query = $("#history-search").value.trim(),
    status = $("#history-status").value;
  const runs = state.runs.filter(
    (r) =>
      matchesQuery(r, query) &&
      (status === "all" ||
        (status === "running"
          ? ["queued", "running", "finalizing"].includes(r.status)
          : r.status === status)),
  );
  $("#history-visible-count").textContent =
    runs.length + " / " + state.runs.length + " 条记录";
  $("#history-list").innerHTML = runs.length
    ? '<div class="table-scroll"><table class="data-table history-table"><thead><tr><th>运行任务</th><th>状态</th><th>检查结果</th><th>运行时间</th><th class="align-right">操作</th></tr></thead><tbody>' +
      runs.map((r) => runRow(r, true)).join("") +
      "</tbody></table></div>"
    : emptyState(
        "没有匹配的运行记录",
        state.runs.length
          ? "试试其他关键词，或调整状态筛选。"
          : "完成第一次验收后，运行记录会出现在这里。",
        "search",
      );
  bindRunLinks($("#history-list"));
}
async function verifyRun(id, button) {
  if (button) button.disabled = true;
  try {
    const result = await api("/api/runs/" + id + "/integrity");
    toast(
      result.valid
        ? "证据校验通过，" + result.files_checked + " 个文件完整。"
        : result.errors.join("\n"),
      !result.valid,
    );
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
async function renderLibrary() {
  const generation = ++state.libraryGeneration;
  const eligible = state.runs.filter(
    (r) => !["queued", "running", "finalizing"].includes(r.status),
  );
  const root = $("#evidence-library");
  if (!eligible.length) {
    root.innerHTML = emptyState(
      "还没有归档证据",
      "完成一次验收后，可在这里下载证据包。",
    );
    return;
  }
  root.innerHTML = emptyState("正在读取归档", "检查可用报告与文件清单…");
  const reports = await Promise.allSettled(
    eligible.slice(0, state.evidenceLimit).map((r) => api("/api/runs/" + r.id)),
  );
  if (generation !== state.libraryGeneration) return;
  root.innerHTML = reports
    .map((outcome, index) => {
      const run =
        outcome.status === "fulfilled" ? outcome.value : eligible[index];
      const files = run.artifacts || [],
        zip = files.includes("evidence.zip"),
        manifest = files.includes("manifest.json");
      const id = escapeText(run.id);
      return (
        '<article class="card evidence-card"><div class="evidence-card-top"><i>' +
        icon("archive") +
        "</i>" +
        statusPill(run) +
        "</div><h3>" +
        escapeText(scenarioName(run)) +
        "</h3><code>" +
        id.slice(0, 20) +
        "</code><p>" +
        dateText(run.created_at) +
        " · " +
        (zip ? files.length + " 个归档文件" : "暂不可下载证据包") +
        "</p>" +
        summaryHTML(run) +
        '<div class="evidence-card-actions"><button class="text-button" data-open-run="' +
        id +
        '">查看报告 →</button>' +
        (zip
          ? '<a class="button secondary" href="/api/runs/' +
            id +
            '/artifacts/evidence.zip">' +
            icon("download") +
            "证据包</a>"
          : "") +
        (manifest
          ? '<button class="text-button" data-verify-run="' +
            id +
            '">' +
            icon("shield-check") +
            "校验</button>"
          : "") +
        "</div></article>"
      );
    })
    .join("");
  bindRunLinks(root);
  root
    .querySelectorAll("[data-verify-run]")
    .forEach(
      (button) =>
        (button.onclick = () => verifyRun(button.dataset.verifyRun, button)),
    );
  if (eligible.length > state.evidenceLimit) {
    const more = document.createElement("button");
    more.className = "button secondary evidence-load-more";
    more.textContent = "再加载 12 条归档";
    more.onclick = () => {
      state.evidenceLimit += 12;
      renderLibrary();
    };
    root.append(more);
  }
}
function renderPalette() {
  const runs = state.runs
    .filter((r) => matchesQuery(r, $("#palette-search").value.trim()))
    .slice(0, 8);
  $("#palette-results").innerHTML = runs.length
    ? runs
        .map(
          (r) =>
            '<button class="palette-row" data-open-run="' +
            escapeText(r.id) +
            '"><span class="task-icon">' +
            icon("file-text") +
            "</span><div><strong>" +
            escapeText(scenarioName(r)) +
            "</strong><small>" +
            escapeText(r.id.slice(0, 16)) +
            " · " +
            dateText(r.created_at) +
            "</small></div>" +
            statusPill(r) +
            "</button>",
        )
        .join("")
    : emptyState("没有匹配的记录", "输入运行编号或场景名称查找。", "search");
  bindRunLinks($("#palette-results"));
}
function openSearch() {
  renderPalette();
  if (!$("#search-dialog").open) $("#search-dialog").showModal();
  $("#palette-search").focus();
}
function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  $("#sidebar-backdrop").hidden = true;
  $("#toggle-sidebar").setAttribute(
    "aria-expanded",
    String(
      innerWidth > 760 &&
        !document.body.classList.contains("sidebar-collapsed"),
    ),
  );
}
function resetRun() {
  $("#run-status").textContent = "准备就绪";
  $("#run-id").textContent = "等待冻结契约";
  $("#run-dot").className = "run-dot";
  $("#export").removeAttribute("href");
  $("#export").classList.add("disabled");
  $("#export").setAttribute("aria-disabled", "true");
  $$("[data-metric]").forEach((el) => (el.textContent = "—"));
  $("#results").innerHTML =
    '<tr><td colspan="4" class="empty-row">冻结验收契约后，开始第一次检查。</td></tr>';
  $("#events").innerHTML = "";
  $("#event-count").textContent = "0 个事件";
  $("#comparison").hidden = true;
  $("#reproductions").hidden = true;
  $("#repair-panel").hidden = true;
  $("#repair-verdict").textContent = "";
  renderEvidence();
}
function newDraft() {
  activeView("workbench");
  if (state.busy || working()) {
    toast("当前任务正在执行，可在完成后新建验收。");
    return;
  }
  ++state.opening;
  clearTimeout(state.poll);
  state.bundle = null;
  state.run = null;
  state.selected = null;
  configureTarget($("#target").value, true);
  $("#provider").value = "offline";
  $("#scenario").value =
    $("#target").value === "todomvc" ? "upstream" : "broken";
  $("#browser").checked = true;
  providerChanged();
  renderBundle();
  resetRun();
  setStep(1);
  updateButtons();
}
async function refreshFeedback(message) {
  const buttons = [
    $("#refresh-overview"),
    $("#refresh-history"),
    $("#refresh-evidence"),
  ];
  buttons.forEach((b) => (b.disabled = true));
  try {
    if (await refreshHistory()) toast(message);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}
function bindWorkspace() {
  $$("[data-project-target]").forEach(
    (button) =>
      (button.onclick = () => {
        if (state.busy || working()) {
          activeView("workbench");
          toast("当前任务仍在执行，完成后可切换项目。");
          return;
        }
        $("#target").value = button.dataset.projectTarget;
        newDraft();
      }),
  );
  $$(".nav-item").forEach((b) => {
    b.title = b.textContent.trim();
    if (b.dataset.view) b.setAttribute("aria-label", b.textContent.trim());
  });
  $$("[data-new-run]").forEach((b) => (b.onclick = newDraft));
  $("#new-draft").onclick = newDraft;
  $$("[data-chart-filter]").forEach(
    (b) =>
      (b.onclick = () => {
        state.chartFilter = b.dataset.chartFilter;
        renderChart();
      }),
  );
  $("#history-search").oninput = renderHistory;
  $("#history-status").onchange = renderHistory;
  $("#open-search").onclick = openSearch;
  $("#palette-search").oninput = renderPalette;
  $("#close-search").onclick = () => $("#search-dialog").close();
  $("#search-dialog").onclick = (e) => {
    if (e.target === $("#search-dialog")) {
      const rect = e.target.getBoundingClientRect();
      if (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      )
        e.target.close();
    }
  };
  $("#open-help").onclick = $("#mode-guide").onclick = () =>
    activeView("guide");
  $(".brand").onclick = (e) => {
    e.preventDefault();
    activeView("overview");
  };
  $("#toggle-sidebar").onclick = () => {
    if (innerWidth <= 760) {
      const open = document.body.classList.toggle("sidebar-open");
      $("#sidebar-backdrop").hidden = !open;
      $("#toggle-sidebar").setAttribute("aria-expanded", String(open));
    } else {
      document.body.classList.toggle("sidebar-collapsed");
      closeSidebar();
    }
  };
  $("#sidebar-backdrop").onclick = closeSidebar;
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearch();
    }
    if (e.key === "Escape") closeSidebar();
    if (
      e.key.toLowerCase() === "n" &&
      !e.ctrlKey &&
      !e.metaKey &&
      !e.altKey &&
      !$("#search-dialog").open &&
      !e.target.closest("input,textarea,select,[contenteditable]")
    )
      newDraft();
  });
  window.addEventListener("resize", closeSidebar);
  window.addEventListener("hashchange", () =>
    activeView(location.hash.slice(1)),
  );
  closeSidebar();
}
init();
