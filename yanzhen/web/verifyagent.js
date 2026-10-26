import {
  esc,
  pretty,
  statusNames,
  verdictNames,
  providerNames,
  describeAction,
  contractSummary,
  resultView,
  traceView,
  logView,
} from "./verifyagent-view.js?v=start-3";

const $ = (selector) => document.querySelector(selector);
const state = {
  target: null,
  bundle: null,
  run: null,
  config: null,
  mode: "own",
  connection: null,
  connectionKey: null,
  targetSnapshot: null,
  polling: false,
  minimizing: false,
  checking: false,
  drafting: false,
  approvalSending: false,
};
const terminal = (run) =>
  run && ["completed", "error", "cancelled"].includes(run.status);
const active = () => state.run && !terminal(state.run);

async function api(path, body) {
  let response;
  try {
    response = await fetch("/api/verify" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new Error("连接不上验真后台，请确认服务已经启动，然后重新尝试。");
  }
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 404 && path === "/targets/check")
      throw new Error(
        "当前后台仍是旧版本，请重启更新后的验真服务，再检查连接。",
      );
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "提交的内容不完整，请核对项目地址与高级设置。",
    );
  }
  return data;
}

function error(err) {
  $("#va-error").hidden = false;
  $("#va-error").textContent = err.message;
  if (!$("#va-workspace").hidden)
    $("#va-error").scrollIntoView({ block: "center", behavior: "smooth" });
  else $("#va-welcome-status").textContent = err.message;
}

function bind(selector, fn) {
  $(selector).addEventListener("click", async (event) => {
    event.preventDefault();
    const button = $(selector);
    if (button.dataset.busy === "1") return;
    button.dataset.busy = "1";
    button.disabled = true;
    $("#va-error").hidden = true;
    try {
      await fn();
    } catch (err) {
      error(err);
    } finally {
      delete button.dataset.busy;
      button.disabled = false;
      controls();
    }
  });
}

function stages(index) {
  document.querySelectorAll(".va-stages li").forEach((element, n) => {
    element.classList.toggle("current", n === index);
    element.classList.toggle("done", n < index);
    if (n === index) element.setAttribute("aria-current", "step");
    else element.removeAttribute("aria-current");
  });
}

function selectNavigation(view) {
  document.querySelectorAll("[data-va-nav]").forEach((link) => {
    const current = link.dataset.vaNav === view;
    link.classList.toggle("active", current);
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function showHistory() {
  $("#va-welcome").hidden = true;
  $("#va-demo-picker").hidden = true;
  $("#va-workspace").hidden = true;
  $("#va-history-panel").hidden = false;
  $("#va-history-panel").open = true;
  $("#va-mode").textContent = "查看已归档的验收记录";
  selectNavigation("history");
  history.replaceState(null, "", location.pathname + "?view=history");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showStage(index, { scroll = true } = {}) {
  $("#va-welcome").hidden = true;
  $("#va-demo-picker").hidden = true;
  $("#va-workspace").hidden = false;
  $("#va-history-panel").hidden = true;
  selectNavigation(state.mode === "history" ? "history" : "start");
  $("#va-setup-panel").hidden = index !== 0;
  $("#va-review-panel").hidden = index !== 1;
  $("#va-execution-panel").hidden = index < 2;
  $("#va-result-panel").hidden = index !== 3;
  const texts = [
    [
      "先接入你的项目。",
      "填写运行地址与验收要求，系统会先检查项目是否可访问。",
    ],
    ["先确认，要检查哪些事。", "核对具体标准和补充条件，然后锁定这一版清单。"],
    [
      "现在，实际操作项目。",
      "执行使用已确认的清单。修改测试数据前，会逐步征求确认。",
    ],
    [
      "看结果，也看依据。",
      "通过、问题与受阻项分别列出，每项都能追溯实际观测。",
    ],
  ];
  $("#va-flow-title").textContent = texts[index][0];
  $("#va-flow-description").textContent = texts[index][1];
  $("#va-flow-kind").textContent =
    state.mode === "example"
      ? "示例体验 · 真实操作，不调用模型"
      : state.mode === "history"
        ? "历史验收 · 读取已归档的实际记录"
        : "新的项目验收";
  stages(index);
  if (scroll)
    $("#va-workspace").scrollIntoView({ block: "start", behavior: "smooth" });
}

function defaultProvider() {
  const providers = state.config?.providers || {};
  return (
    ["deepseek", "qwen"].find(
      (name) => providers[name]?.enabled && providers[name]?.configured,
    ) || "manual"
  );
}

function clearConnection() {
  state.connection = null;
  state.connectionKey = null;
  $("#va-connection").hidden = true;
  controls();
}

function prepareNew(mode = "own") {
  if (active())
    throw new Error("当前验收仍在执行，请先取消或等待结束，再新建项目。");
  Object.assign(state, {
    target: null,
    bundle: null,
    run: null,
    mode,
    connection: null,
    connectionKey: null,
    targetSnapshot: null,
  });
  $("#va-intake-form").reset();
  $("#va-identities").value = "{}";
  $("#va-supplied").value = "";
  $("#va-actions").value = "";
  $("#va-namespace").value = "";
  $("#va-api-descriptions").value = "";
  $("#va-provider").value = defaultProvider();
  $("#va-settings").open = false;
  $("#va-contract-advanced").open = false;
  $("#va-confirm").checked = false;
  $("#va-example-note").hidden = true;
  $("#va-error").hidden = true;
  $("#va-connection").hidden = true;
  $("#va-contract-summary").innerHTML = "";
  $("#va-contract-editor").value = "";
  $("#va-repair-target").value = "";
  $("#va-replay-consent").checked = false;
  $("#va-results").innerHTML = "";
  $("#va-screenshots").innerHTML = "";
  $("#va-plan").textContent = "还没有执行动作。";
  $("#va-log").innerHTML = "";
  $("#va-trace").innerHTML = "";
  $("#va-mode").textContent = "准备一次新的验收";
  $("#va-history-panel").hidden = true;
  selectNavigation("start");
  history.replaceState(null, "", location.pathname);
  controls();
}

function targetInput(url) {
  if (!$("#va-authorized").checked)
    throw new Error("请先勾选确认：你有权在这个测试项目中进行验收。");
  const address = url || $("#va-url").value.trim();
  let parsed;
  try {
    parsed = new URL(address);
  } catch {
    throw new Error("请填写完整的项目运行地址，例如 http://127.0.0.1:3000。");
  }
  if (!["http:", "https:"].includes(parsed.protocol))
    throw new Error(
      "请填写 HTTP 或 HTTPS 的运行地址。ZIP 文件和 GitHub 源码链接目前不能直接导入。",
    );
  if (parsed.origin === location.origin)
    throw new Error("请填写待验收项目的地址，不是验真工作台自己的地址。");
  let identities;
  try {
    identities = JSON.parse($("#va-identities").value || "{}");
  } catch {
    $("#va-settings").open = true;
    throw new Error("高级设置中的测试身份不是有效 JSON，请让项目开发者核对。");
  }
  return {
    name: state.mode === "example" ? "本地验收体验项目" : `项目 ${parsed.host}`,
    base_url: address,
    interface: $("#va-interface").value,
    api_description_urls: $("#va-api-descriptions")
      .value.split(/\r?\n/)
      .map((v) => v.trim())
      .filter(Boolean),
    environment: "test",
    authorized: true,
    identities,
    namespace_header: $("#va-namespace").value.trim() || null,
    isolation_note: $("#va-namespace").value.trim()
      ? "用户声明目标支持按请求头隔离后端状态；由目标部署方保证此协议。"
      : "仅隔离浏览器/API 会话，不保证后端数据重置。",
  };
}

async function checkConnection(payload = targetInput()) {
  state.checking = true;
  controls();
  $("#va-connection").hidden = false;
  $("#va-connection").dataset.state = "checking";
  $("#va-connection").textContent = "正在从验真服务器读取项目入口，不调用模型…";
  try {
    const result = await api("/targets/check", payload);
    state.connection = result;
    state.connectionKey = JSON.stringify(payload);
    $("#va-connection").dataset.state = result.ready ? "ready" : "error";
    $("#va-connection").textContent = result.message;
    if (!result.ready) $("#va-url").setAttribute("aria-invalid", "true");
    else $("#va-url").removeAttribute("aria-invalid");
    return result.ready;
  } catch (err) {
    state.connection = null;
    $("#va-connection").dataset.state = "error";
    $("#va-connection").textContent = err.message;
    throw err;
  } finally {
    state.checking = false;
    controls();
  }
}

function controls() {
  const busy = active() || state.drafting || state.checking;
  const address = $("#va-url").value.trim(),
    requirements = $("#va-requirements").value.trim();
  const provider = $("#va-provider").value;
  const manualReady = provider !== "manual" || !!$("#va-supplied").value.trim();
  $("#va-draft").disabled =
    busy ||
    !state.config ||
    !address ||
    requirements.length < 5 ||
    !$("#va-authorized").checked ||
    !manualReady;
  $("#va-check-target").disabled =
    busy || !address || !$("#va-authorized").checked;
  $("#va-draft").textContent = state.drafting
    ? "正在整理实际检查项…"
    : "下一步：生成检查清单 →";
  $("#va-check-target").textContent = state.checking ? "检查中…" : "检查连接";
  let help = !address
    ? "先填写已经运行的项目地址。"
    : requirements.length < 5
      ? "再写下具体的功能与预期结果。"
      : !$("#va-authorized").checked
        ? "请勾选测试授权，然后继续。"
        : !manualReady
          ? "当前没有可用的 AI 配置。请先体验示例，或让管理员配置模型。"
          : "下一步会检查连接并生成清单；还不会开始操作项目。";
  if (state.connection && !state.connection.ready)
    help = "请先按连接提示处理项目地址或测试身份，再尝试。";
  $("#va-next-help").textContent = help;
  $("#va-model-note").textContent =
    provider === "manual"
      ? state.mode === "example"
        ? "本次示例：预设清单与操作，不调用大模型，也不产生模型费用。"
        : "手动方式需要开发者提供完整清单与操作；普通项目建议使用已配置的 AI。"
      : `将使用 ${providerNames[provider]} 整理清单，生成时会调用已配置的真实模型。`;
  const frozen = state.bundle?.frozen;
  $("#va-freeze").disabled =
    busy ||
    !state.bundle ||
    frozen ||
    !$("#va-confirm").checked ||
    !!state.bundle?.clarification_questions.length ||
    !state.bundle?.contracts.length;
  $("#va-freeze").hidden = !!frozen;
  $("#va-review-to-execution").hidden = !frozen;
  $("#va-revise").disabled = busy || !state.bundle;
  $("#va-start").disabled = busy || !frozen;
  $("#va-start").textContent = terminal(state.run)
    ? "按原清单再次验收"
    : "开始执行验收";
  $("#va-new").disabled = !!active();
  $("#va-show-review").disabled = !!active();
  $("#va-back-setup").disabled = !!active();
  $("#va-cancel").disabled = !active();
  $("#va-approve").disabled =
    !state.run?.pending_approval || state.approvalSending;
  $("#va-deny").disabled =
    !state.run?.pending_approval || state.approvalSending;
}

function bundleView() {
  const b = state.bundle;
  $("#va-contract-editor").value = pretty({
    contracts: b.contracts,
    clarification_questions: b.clarification_questions,
  });
  $("#va-contract-summary").innerHTML = contractSummary(b);
  $("#va-review-requirements").textContent = b.requirements;
  $("#va-contract-state").textContent =
    `版本 ${b.version} · ${b.frozen ? "已确认并锁定标准" : "等待你审阅"} · ${b.provider === "manual" ? "人工提供或编辑的检查清单" : "AI 生成的候选清单"}`;
  $("#va-digest").textContent = "内容校验 SHA-256 " + b.digest;
  $("#va-run-state").textContent = "清单已确认，点击开始执行。";
  $("#va-run-state").dataset.status = "ready";
  $("#va-ready-summary").textContent =
    `即将检查：${state.target.base_url}。使用已确认的第 ${b.version} 版清单（${b.contracts.length} 组要求）。执行前仍会逐步确认涉及写入的操作。`;
  controls();
}

async function createDraft(event) {
  event?.preventDefault();
  if (state.drafting || active()) return;
  $("#va-error").hidden = true;
  try {
    const payload = targetInput();
    const requirements = $("#va-requirements").value;
    if (requirements.trim().length < 5)
      throw new Error("请写下具体的功能和预期结果，至少 5 个字。");
    const provider = $("#va-provider").value;
    let supplied;
    if (provider === "manual") {
      try {
        supplied = JSON.parse($("#va-supplied").value);
      } catch {
        throw new Error(
          "手动方式需要完整的检查清单。你可以先载入示例，或选择已经配置的 AI 方式。",
        );
      }
    }
    if (
      !state.connection?.ready ||
      state.connectionKey !== JSON.stringify(payload)
    )
      if (!(await checkConnection(payload))) return;
    state.drafting = true;
    controls();
    const registered = await api("/targets", payload);
    const bundle = await api("/analyze", {
      requirements,
      target_id: registered.id,
      provider,
      ...(provider === "manual" ? { supplied } : {}),
    });
    state.target = registered;
    state.bundle = bundle;
    state.run = null;
    state.targetSnapshot = JSON.stringify(payload);
    $("#va-confirm").checked = false;
    bundleView();
    showStage(1);
  } catch (err) {
    error(err);
  } finally {
    state.drafting = false;
    controls();
  }
}

function renderGraph(run) {
  const edges = run.graph.edges || [],
    nodes = new Map(run.graph.nodes.map((n) => [n.evidence_id || n.id, n]));
  const relations = {
    supports: "支持",
    contradicts: "冲突",
    depends_on: "依赖",
    reproduces: "独立重现",
  };
  const sources = {
    dom_text: "页面文本",
    dom_visible: "页面可见性",
    http_status: "HTTP 状态",
    http_json: "重新读取的数据",
    http_response: "网络响应",
    tool_result: "实际操作",
    page_snapshot: "页面观察",
    api_snapshot: "接口观察",
  };
  const label = (id) => {
    const n = nodes.get(id);
    return n
      ? n.node_type === "evidence"
        ? `${sources[n.source_type] || n.source_type} / ${n.provenance.probe_id || n.action_id}`
        : n.assertion_id
          ? `检查 / ${n.assertion_id}`
          : `清单 / ${n.id}`
      : id;
  };
  $("#va-graph-summary").textContent =
    `${run.graph.nodes.length} 个实际证据节点 · ${edges.length} 条关联 · ${edges.filter((e) => e.relation === "contradicts").length} 条矛盾关系`;
  $("#va-graph").innerHTML = edges
    .map(
      (e) =>
        `<article class="${esc(e.relation)}"><b>${esc(relations[e.relation] || e.relation)}</b><span>${esc(label(e.source))} → ${esc(label(e.target))}</span></article>`,
    )
    .join("");
}

function renderReproductions(run) {
  $("#va-reproductions").innerHTML =
    run.results
      .filter((r) => r.verdict === "fail")
      .map(
        (r) =>
          `<div class="va-reproduction"><strong>${esc(r.title)}</strong><details><summary>查看将重复执行的原始操作</summary><ol>${run.trace
            .filter((t) => t.contract_id === r.contract_id)
            .map((t) => `<li>${esc(describeAction(t.action))}</li>`)
            .join(
              "",
            )}</ol></details><button class="button secondary" data-minimize="${esc(r.contract_id)}" ${state.minimizing ? "disabled" : ""}>精简步骤并独立复现</button></div>`,
      )
      .join("") +
    run.reproductions
      .map(
        (r) =>
          `<details class="va-reproduction"><summary>${r.status === "verified" ? "独立重放已确认" : esc(r.status)} · 步骤 ${r.original_planned_steps} → ${r.reduced_planned_steps} · 重放 ${r.replays} 次</summary><pre>${esc(pretty(r))}</pre></details>`,
      )
      .join("") +
    (run.repair_validation
      ? `<div class="va-notice">${run.repair_validation.verified ? "修复版本已按原清单全部通过。" : "修复复验尚未满足全部条件。"}<details><summary>查看复验依据</summary><pre>${esc(pretty(run.repair_validation))}</pre></details></div>`
      : "");
}

function renderRun(run) {
  const viewingHistory = !$("#va-history-panel").hidden;
  state.run = run;
  const isActive = !terminal(run);
  $("#va-ready-summary").textContent =
    `本次目标：${state.target.base_url} · 固定清单版本 ${state.bundle.version} · ${providerNames[run.planner] || run.planner}。`;
  $("#va-run-state").textContent =
    `${statusNames[run.status]} · 已记录 ${run.trace.length} 个实际动作${run.status === "error" ? "。已保留完成的证据，请查看受阻原因。" : ""}`;
  $("#va-run-state").dataset.status = run.status;
  $("#va-mode").textContent = providerNames[run.planner] || run.planner;
  $("#va-approval").hidden = !run.pending_approval;
  if (run.pending_approval) {
    $("#va-approval-description").textContent = describeAction(
      run.pending_approval.action,
    );
    $("#va-approval-action").textContent = pretty(run.pending_approval.action);
  }
  const plan = [...run.events].reverse().find((e) => e.decision);
  $("#va-plan").textContent =
    run.status === "completed"
      ? "实际操作已结束，验收结果和截图见下方。"
      : run.status === "error"
        ? "这次执行已受阻，请在记录中查看已保存的状态和原因。"
        : run.status === "cancelled"
          ? "验收已取消，可以回看已经完成的操作。"
          : plan?.decision.action
            ? describeAction(plan.decision.action)
            : plan
              ? "本轮操作规划已结束，正在按清单核对实际观测。"
              : "尚未产生操作计划，等待读取项目的实际状态。";
  $("#va-log").innerHTML = logView(run);
  $("#va-trace").innerHTML = traceView(run, isActive);
  $("#va-results").innerHTML = resultView(run);
  const counts = Object.fromEntries(
    ["pass", "fail", "blocked", "unclear"].map((key) => [
      key,
      run.results.filter((r) => r.verdict === key).length,
    ]),
  );
  $("#va-result-summary").textContent =
    `通过 ${counts.pass} 项 · 发现问题 ${counts.fail} 项 · 暂无法检查 ${counts.blocked} 项 · 需要澄清 ${counts.unclear} 项`;
  const shots = [
    ...new Map(
      run.evidence
        .filter((e) => e.artifact_reference)
        .map((e) => [e.artifact_reference, e]),
    ).values(),
  ].slice(-3);
  $("#va-screenshots").innerHTML = isActive
    ? ""
    : shots
        .map(
          (e) =>
            `<a target="_blank" rel="noopener" href="/api/verify/runs/${run.id}/artifacts/${encodeURIComponent(e.artifact_reference)}"><img loading="lazy" src="/api/verify/runs/${run.id}/artifacts/${encodeURIComponent(e.artifact_reference)}" alt="实际操作 ${esc(e.action_id)} 的截图" />实际截图 · ${esc(e.action_id)} ↗</a>`,
        )
        .join("");
  renderGraph(run);
  renderReproductions(run);
  $("#va-export").hidden = isActive;
  $("#va-export").href = `/api/verify/runs/${run.id}/artifacts/evidence.zip`;
  $("#va-repair").disabled = isActive || !counts.fail;
  if (viewingHistory)
    $("#va-mode").textContent = "查看已归档的验收记录";
  else showStage(isActive ? 2 : 3, { scroll: false });
  controls();
}

async function follow(identifier) {
  if (state.polling)
    throw new Error("当前已经有一次验收正在显示，请先等待结束或取消。");
  state.polling = true;
  try {
    for (;;) {
      const run = await api("/runs/" + encodeURIComponent(identifier));
      renderRun(run);
      if (terminal(run)) break;
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
  } finally {
    state.polling = false;
    await refreshHistory();
  }
}

async function refreshHistory() {
  const rows = await api("/runs");
  $("#va-history").innerHTML =
    rows
      .map(
        (r) =>
          `<button data-run="${esc(r.id)}">${esc(statusNames[r.status] || r.status)} · ${esc(providerNames[r.planner] || r.planner)}<span>${esc(new Date(r.created_at).toLocaleString("zh-CN"))} · ${esc(r.id.slice(0, 8))}</span></button>`,
      )
      .join("") ||
    '<p class="va-hint">还没有验收记录。可以先体验一个示例。</p>';
}

async function loadHistoryRun(id) {
  if (state.polling) throw new Error("请先等待当前验收完成，再查看其他记录。");
  const run = await api("/runs/" + id);
  state.bundle = await api("/bundles/" + run.bundle_id);
  state.target = await api("/targets/" + run.target_id);
  state.mode = "history";
  $("#va-url").value = state.target.base_url;
  $("#va-interface").value = state.target.interface;
  $("#va-identities").value = pretty(state.target.identities);
  $("#va-namespace").value = state.target.namespace_header || "";
  $("#va-api-descriptions").value = (
    state.target.api_description_urls || []
  ).join("\n");
  $("#va-provider").value = run.planner;
  $("#va-authorized").checked = state.target.authorized;
  $("#va-confirm").checked = state.bundle.frozen;
  $("#va-actions").value = pretty(run.trace.map((t) => t.action));
  $("#va-requirements").value = state.bundle.requirements;
  state.targetSnapshot = JSON.stringify(targetInput());
  bundleView();
  $("#va-history-panel").hidden = true;
  await follow(id);
  $("#va-history-panel").open = false;
  $("#va-workspace").scrollIntoView({ block: "start", behavior: "smooth" });
}

bind("#va-own-project", () => {
  prepareNew();
  showStage(0);
  $("#va-url").focus({ preventScroll: true });
});
bind("#va-try-demo", () => {
  $("#va-demo-picker").hidden = false;
  $("#va-demo-picker").scrollIntoView({ block: "center", behavior: "smooth" });
});
bind("#va-demo-close", () => {
  $("#va-demo-picker").hidden = true;
});
bind("#va-new", () => {
  prepareNew();
  $("#va-workspace").hidden = true;
  $("#va-welcome").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
});
bind("#va-show-history", showHistory);
bind("#va-mobile-history", showHistory);
bind("#va-check-target", () => checkConnection());
$("#va-intake-form").addEventListener("submit", createDraft);
for (const id of [
  "#va-url",
  "#va-interface",
  "#va-identities",
  "#va-namespace",
  "#va-api-descriptions",
])
  $(id).addEventListener("input", clearConnection);
for (const id of [
  "#va-requirements",
  "#va-authorized",
  "#va-provider",
  "#va-supplied",
  "#va-confirm",
])
  $(id).addEventListener("input", controls);
$("#va-authorized").addEventListener("change", clearConnection);

bind("#va-back-setup", () => showStage(0));
bind("#va-show-review", () => showStage(1));
bind("#va-review-to-execution", () => {
  if (state.run) renderRun(state.run);
  else showStage(2);
});
bind("#va-revise", async () => {
  let supplied;
  try {
    supplied = JSON.parse($("#va-contract-editor").value);
  } catch {
    throw new Error("结构化标准不是有效 JSON，请修正后再保存新版本。");
  }
  state.bundle = await api(`/bundles/${state.bundle.id}/versions`, {
    requirements: $("#va-requirements").value,
    target_id: state.bundle.target_id,
    provider: "manual",
    supplied,
  });
  $("#va-confirm").checked = false;
  bundleView();
  showStage(1);
});
bind("#va-freeze", async () => {
  if (!$("#va-confirm").checked)
    throw new Error("请先阅读检查项和测试条件，再勾选确认。");
  let edited;
  try {
    edited = JSON.parse($("#va-contract-editor").value);
  } catch {
    throw new Error("结构化标准有未保存的错误，请先修正或恢复原内容。");
  }
  if (
    pretty(edited) !==
    pretty({
      contracts: state.bundle.contracts,
      clarification_questions: state.bundle.clarification_questions,
    })
  )
    throw new Error(
      "高级设置里的标准已修改，请先“保存为新版本”再确认，避免确认了未显示的旧标准。",
    );
  state.bundle = await api(`/bundles/${state.bundle.id}/freeze`, {
    digest: state.bundle.digest,
    confirmed: true,
    accept_assumptions: true,
    reviewer: "local-user",
  });
  bundleView();
  showStage(2);
});
bind("#va-start", async () => {
  if (
    $("#va-requirements").value !== state.bundle.requirements ||
    JSON.stringify(targetInput()) !== state.targetSnapshot
  )
    throw new Error(
      "项目配置或要求已经改变。请返回接入步骤，重新生成并确认清单。",
    );
  const planner = $("#va-provider").value;
  let actions = [];
  if (planner === "manual")
    try {
      actions = JSON.parse($("#va-actions").value || "[]");
    } catch {
      throw new Error("手动操作计划不是有效 JSON，请在高级设置中核对。");
    }
  const run = await api("/runs", {
    bundle_id: state.bundle.id,
    planner,
    manual_actions: actions,
    ...(state.target.id !== state.bundle.target_id
      ? { candidate_target_id: state.target.id, parent_run: state.run.id }
      : {}),
  });
  showStage(2);
  await follow(run.id);
});
bind("#va-cancel", () => api(`/runs/${state.run.id}/cancel`, {}));
for (const [id, approved] of [
  ["#va-approve", true],
  ["#va-deny", false],
])
  bind(id, async () => {
    state.approvalSending = true;
    controls();
    try {
      await api(`/runs/${state.run.id}/approve`, {
        digest: state.run.pending_approval.digest,
        approved,
        reviewer: "local-user",
      });
      $("#va-approval").hidden = true;
    } finally {
      state.approvalSending = false;
    }
  });
bind("#va-refresh", refreshHistory);
bind("#va-repair", async () => {
  const payload = targetInput($("#va-repair-target").value.trim());
  if (!(await checkConnection(payload)))
    throw new Error(
      state.connection?.message || "修复版本未通过连接检查，请核对测试地址。",
    );
  const candidate = await api("/targets", payload);
  const failed = state.run.results.find((r) => r.verdict === "fail");
  const response = await api(
    `/runs/${state.run.id}/repair/${encodeURIComponent(failed.contract_id)}`,
    {
      kind: "external_target",
      candidate_target_id: candidate.id,
      contract_digest: state.run.contract_digest,
    },
  );
  state.target = candidate;
  $("#va-url").value = candidate.base_url;
  state.targetSnapshot = JSON.stringify(targetInput());
  await follow(response.run.id);
});
$("#va-history").addEventListener("click", async (event) => {
  const id = event.target.closest("[data-run]")?.dataset.run;
  if (id)
    try {
      await loadHistoryRun(id);
    } catch (err) {
      error(err);
    }
});
$("#va-reproductions").addEventListener("click", async (event) => {
  const id = event.target.closest("[data-minimize]")?.dataset.minimize;
  if (!id || state.minimizing) return;
  try {
    if (!$("#va-replay-consent").checked)
      throw new Error("请先确认允许在隔离测试环境中重复这些原始操作。");
    state.minimizing = true;
    renderReproductions(state.run);
    await api(`/runs/${state.run.id}/minimize/${encodeURIComponent(id)}`, {
      confirmed: true,
      budget: 12,
    });
    state.minimizing = false;
    renderRun(await api("/runs/" + state.run.id));
  } catch (err) {
    state.minimizing = false;
    error(err);
    renderReproductions(state.run);
  }
});
document.querySelectorAll("[data-example]").forEach((button) =>
  button.addEventListener("click", async () => {
    try {
      const sample = await api("/examples/" + button.dataset.example);
      prepareNew("example");
      $("#va-requirements").value = sample.requirements;
      $("#va-supplied").value = pretty(sample.supplied);
      $("#va-actions").value = pretty(sample.actions);
      $("#va-identities").value = pretty(sample.identities);
      $("#va-namespace").value = "X-Verify-Sandbox";
      $("#va-api-descriptions").value = "api/schema";
      $("#va-url").value =
        "http://127.0.0.1:8771/app/" +
        (button.dataset.example === "authorization"
          ? "auth_bug"
          : "persistence_bug") +
        "/";
      $("#va-provider").value = "manual";
      $("#va-interface").value =
        button.dataset.example === "authorization" ? "api" : "web";
      $("#va-example-note").hidden = false;
      $("#va-example-note").textContent =
        "示例项目和检查内容已经填好。先勾选测试授权，点击“下一步”，审阅清单后再执行。示例不会调用大模型。";
      showStage(0);
      controls();
    } catch (err) {
      error(err);
    }
  }),
);

try {
  state.config = await api("/capabilities");
  $("#va-service").textContent = "服务连接正常";
  for (const name of ["deepseek", "qwen"])
    $(`#va-provider option[value=${name}]`).disabled =
      !state.config.providers[name].enabled ||
      !state.config.providers[name].configured;
  $("#va-provider option[value=jiuwenswarm]").disabled =
    !state.config.swarm_sdk_installed || !state.config.swarm_configured;
  if (state.mode !== "example") $("#va-provider").value = defaultProvider();
  $("#va-allowlist").textContent =
    "服务器当前允许：" +
    (state.config.allowed_origins.join("、") ||
      "尚未登记项目地址，请联系管理员配置。");
  controls();
  await refreshHistory();
  const parameters = new URLSearchParams(location.search);
  const requestedRun = parameters.get("run");
  if (/^[a-f0-9]{32}$/.test(requestedRun || ""))
    await loadHistoryRun(requestedRun);
  else if (parameters.get("view") === "history") showHistory();
} catch (err) {
  $("#va-service").textContent = "后台暂不可用";
  error(err);
}
