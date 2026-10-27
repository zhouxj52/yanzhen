// Presentation only. All decisions, observations and results come from the API.
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const pretty = (value) => JSON.stringify(value, null, 2);
export const statusNames = {
  queued: "等待执行",
  running: "正在检查",
  waiting_approval: "等待你确认操作",
  completed: "验收完成",
  error: "执行受阻",
  cancelled: "已取消",
};
export const verdictNames = {
  pass: "通过",
  fail: "发现问题",
  blocked: "暂无法检查",
  unclear: "需要澄清",
};
export const providerNames = {
  openjiuwen: "openJiuwen · 官方工作流编排",
  manual: "预设 / 手动流程 · 不调用模型",
  deepseek: "DeepSeek · AI 规划",
  qwen: "Qwen · AI 规划",
  jiuwenswarm: "JiuwenSwarm · AI 规划",
};
export const actionNames = {
  navigate: "打开页面",
  click: "点击页面控件",
  fill: "填写内容",
  select: "选择选项",
  wait_for: "等待页面",
  assert_visible: "观察控件是否可见",
  assert_text: "读取页面文字",
  http_request: "请求接口",
  assert_status: "核对接口响应",
  assert_json: "核对接口数据",
  reload: "刷新页面",
  compare_state: "比较前后状态",
};
const valueText = (value) =>
  value === undefined
    ? "未取得观测"
    : value === null
      ? "空值"
      : typeof value === "string"
        ? value === ""
          ? "空内容"
          : `“${value}”`
        : pretty(value);

export function describeAction(action) {
  if (!action) return "";
  const name = action.locator?.value || "对应控件";
  const prefix =
    action.actor && action.actor !== "anonymous"
      ? `使用测试身份 ${action.actor}，`
      : "";
  const descriptions = {
    navigate: `打开${action.url === "." ? "项目首页" : ` ${action.url}`}`,
    click: `点击“${name}”`,
    fill: `在“${name}”中填写 ${valueText(action.value)}`,
    select: `在“${name}”中选择 ${valueText(action.value)}`,
    wait_for: `等待“${name}”在页面出现`,
    reload: "刷新当前页面，重新读取项目状态",
    http_request: `向 ${action.url} 发起 ${action.method || "GET"} 请求${action.json_body ? `，提交 ${pretty(action.json_body)}` : ""}`,
    assert_visible: `检查“${name}”是否可见`,
    assert_text: `读取“${name}”的文字`,
  };
  return (
    prefix +
    (descriptions[action.kind] || actionNames[action.kind] || action.kind)
  );
}

function probeText(probe) {
  if (!probe) return "所需观测";
  const moment =
    {
      before: "执行前",
      after: "操作完成后重新读取的",
      checkpoint: "对应操作后的",
      always: "整个过程中的",
    }[probe.phase] || "";
  if (probe.source_type === "http_status") return `${probe.url} 的 HTTP 状态`;
  if (probe.source_type === "http_json")
    return `${moment}接口 ${probe.url}${probe.pointer ? ` 中 ${probe.pointer}` : ""} 的值`;
  const subject = probe.locator?.value || "指定元素";
  return `${moment}页面中“${subject}”${probe.source_type === "dom_visible" ? "的可见状态" : "的内容"}`;
}

function predicateText(assertion, contract) {
  const left = contract.probes.find((p) => p.id === assertion.left);
  const right =
    assertion.right_probe &&
    contract.probes.find((p) => p.id === assertion.right_probe);
  if (
    left?.source_type === "dom_visible" &&
    assertion.op === "eq" &&
    typeof assertion.expected === "boolean"
  )
    return `页面中应${assertion.expected ? "能" : "不能"}看到“${left.locator.value}”。`;
  const op =
    {
      eq: "应等于",
      ne: "应不等于",
      contains: "应包含",
      not_contains: "应不包含",
      in: "应属于",
      not_in: "应不属于",
      gte: "应大于或等于",
      lte: "应小于或等于",
    }[assertion.op] || assertion.op;
  return `${probeText(left)}，${op} ${right ? probeText(right) : valueText(assertion.expected)}。`;
}

export function contractSummary(bundle) {
  const questions = bundle.clarification_questions.length
    ? `<div class="va-assumptions"><h4>请先补充这些信息</h4><ul>${bundle.clarification_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul><p class="va-field-help">返回修改需求，补充清楚后重新生成清单。</p></div>`
    : "";
  return (
    questions +
    bundle.contracts
      .map((c, index) => {
        const predicates = (list) =>
          list
            .map(
              (p) =>
                `<li>${esc(predicateText(p, c))}<span class="va-quote">需求原文：${esc(p.source.quote)}${p.source.basis === "assumption" ? " · 包含需要确认的推导条件" : ""}</span></li>`,
            )
            .join("");
        const operations = [
          ...new Set([
            ...c.constraints.required_actions,
            ...c.constraints.required_operations.map((o) => o.kind),
          ]),
        ];
        const assumptions = [
          ...new Set([
            ...c.assumptions,
            ...[...c.preconditions, ...c.postconditions, ...c.invariants]
              .filter(
                (p) => p.source.basis === "assumption" && p.source.explanation,
              )
              .map((p) => p.source.explanation),
          ]),
        ];
        return `<article class="va-contract-item"><h3>${index + 1}. ${esc(c.title)}</h3>${c.preconditions.length ? `<h4>开始前需要满足</h4><ul>${predicates(c.preconditions)}</ul>` : ""}${operations.length ? `<h4>需要实际完成的操作</h4><p class="va-field-help">${operations.map((k) => esc(actionNames[k] || k)).join(" → ")}</p>` : ""}<h4>怎样才算满足要求</h4><ol>${predicates(c.postconditions)}</ol>${c.invariants.length ? `<h4>整个过程都必须满足</h4><ul>${predicates(c.invariants)}</ul>` : ""}${c.constraints.forbidden_actions.length ? `<h4>禁止的操作</h4><p class="va-field-help">${c.constraints.forbidden_actions.map((k) => esc(actionNames[k] || k)).join("、")}</p>` : ""}${assumptions.length ? `<div class="va-assumptions"><h4>这些测试条件，需要你一起确认</h4><ul>${assumptions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}</article>`;
      })
      .join("")
  );
}

export function resultView(run) {
  return (
    run.results
      .map(
        (r) =>
          `<article><details ${r.verdict === "fail" || r.verdict === "blocked" ? "open" : ""}><summary><span class="va-verdict ${esc(r.verdict)}">${esc(verdictNames[r.verdict])} · ${esc(r.verdict.toUpperCase())}</span>${esc(r.title)}</summary>${(r.assertions || []).map((a) => `<div class="va-assertion ${esc(a.verdict)}"><p><strong>${esc(verdictNames[a.verdict])}</strong>${a.source?.quote ? `：${esc(a.source.quote)}` : ""}</p>${"actual" in a ? `<p>实际观测：${esc(valueText(a.actual))}<br />应满足的比较：${esc({ eq: "等于", ne: "不等于", contains: "包含", not_contains: "不包含", gte: "不小于", lte: "不大于", in: "属于", not_in: "不属于" }[a.operator] || a.operator || "")} ${esc(valueText(a.expected))}</p>` : "<p>所需操作或观测尚未完成，不能判断为通过。</p>"}</div>`).join("")}${!r.assertions?.length ? `<p class="va-field-help">${esc(r.reason || "尚未得到完整观测，请查看执行记录。")}</p>` : ""}<details class="va-developer"><summary>查看完整结果数据</summary><pre>${esc(pretty(r))}</pre></details></details></article>`,
      )
      .join("") ||
    '<p class="va-hint">还没有完成的检查项，不会提前显示为通过。</p>'
  );
}

export function traceView(run, active) {
  return (
    [...run.trace]
      .reverse()
      .map((t) => {
        const evidence = run.evidence.find(
          (e) => e.evidence_id === t.evidence_id,
        );
        const screenshot = evidence?.artifact_reference;
        return `<article class="${t.ok ? "" : "error"}"><details><summary>${esc(describeAction(t.action))}<br /><time>${t.ok ? "执行完成" : "执行受阻"} · ${t.duration_ms} ms</time></summary>${t.error ? `<p>${esc(t.error.message)}</p>` : ""}${screenshot && !active ? `<a target="_blank" rel="noopener" href="/api/verify/runs/${run.id}/artifacts/${esc(screenshot)}">查看这一步的截图 ↗</a>` : ""}<pre>${esc(pretty(t))}</pre></details></article>`;
      })
      .join("") || '<p class="va-hint">还没有执行动作。</p>'
  );
}

export function logView(run) {
  const phases = {
    observe: "读取项目",
    plan: "规划下一步",
    act: "操作项目",
    replan: "根据新观测调整",
    verify: "核对实际结果",
    approval: "等待你确认",
    error: "执行受阻",
    cleanup: "清理会话",
  };
  return [...run.events]
    .slice(-20)
    .reverse()
    .map((e) => {
      let text = e.decision
        ? e.decision.action
          ? describeAction(e.decision.action)
          : "规划器结束了本轮操作规划。"
        : "";
      if (!text && e.action) text = describeAction(e.action);
      if (!text)
        text =
          {
            observe: "正在读取项目的实际状态。",
            plan: "根据已确认的清单和当前状态，选择下一步。",
            act: "正在执行记录中的操作。",
            replan: "将新的状态或错误反馈给规划器。",
            verify: "根据固定的验收标准核对实际证据。",
            approval: "操作会修改测试数据，等待确认后继续。",
          }[e.phase] || e.message;
      return `<article><time>${esc(new Date(e.timestamp).toLocaleTimeString("zh-CN"))} · ${esc(phases[e.phase] || e.phase)}</time>${esc(text)}${e.decision?.explanation ? `<details class="va-developer"><summary>查看规划器原始说明</summary><p>${esc(e.decision.explanation)}</p></details>` : ""}</article>`;
    })
    .join("");
}
