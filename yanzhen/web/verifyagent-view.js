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
  openjiuwen_team: "openJiuwen · 多角色协作执行",
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
  const checks = (run.coverage?.requirements || []).flatMap(r => r.checks);
  const measurement = {dom_text:'页面内容核对',dom_visible:'页面可见状态',http_status:'接口状态核对',http_json:'独立读取的数据'};
  const operators = {eq:'等于',ne:'不等于',contains:'包含',not_contains:'不包含',gte:'不小于',lte:'不大于',in:'属于',not_in:'不属于'};
  return run.results.map(r => `<article><details ${['fail','blocked'].includes(r.verdict) ? 'open' : ''}><summary><span class="va-verdict ${esc(r.verdict)}">${esc(verdictNames[r.verdict])} · ${esc(r.verdict.toUpperCase())}</span>${esc(r.title)}</summary><div class="va-result-detail">${(r.assertions || []).map((a,index) => {
    const linked = checks.find(c=>c.contract_id===r.contract_id && c.predicate_id===a.assertion_id);
    const probe = linked?.probes.find(p=>p.id!==linked.right_probe) || linked?.probes[0];
    const title = measurement[probe?.source_type] || (a.assertion_id.startsWith('required_') ? '必要业务操作' : `检查条件 ${index+1}`);
    return `<section class="va-assertion ${esc(a.verdict)}"><div class="va-assertion-head"><strong>${String(index+1).padStart(2,'0')} · ${esc(title)}</strong><span class="va-verdict ${esc(a.verdict)}">${esc(verdictNames[a.verdict])}</span></div>${'actual' in a ? `<div class="va-comparison"><div><span>实际观测</span><p>${esc(valueText(a.actual))}</p></div><div><span>标准要求 · ${esc(operators[a.operator] || a.operator || '')}</span><p>${esc(valueText(a.expected))}</p></div></div>` : '<p class="va-field-help">所需操作或观测尚未完成，不能判断为通过。</p>'}${a.source?.quote ? `<details class="va-assertion-source"><summary>查看这项检查的需求出处</summary><p>${esc(a.source.quote)}</p></details>` : ''}</section>`;
  }).join('')}${!r.assertions?.length ? `<p class="va-field-help">${esc(r.reason || '尚未得到完整观测，请查看执行记录。')}</p>` : ''}<details class="va-developer"><summary>查看完整结果数据</summary><pre>${esc(pretty(r))}</pre></details></div></details></article>`).join('') || '<p class="va-hint">还没有完成的检查项，不会提前显示为通过。</p>';
}

export function metricsView(run) {
  const counts = Object.fromEntries(['pass','fail','blocked','unclear'].map(key=>[key,run.results.filter(r=>r.verdict===key).length]));
  const gaps = run.coverage ? run.coverage.summary.uncovered + run.coverage.summary.partial : null;
  return [['pass','通过检查',counts.pass,'组检查'],['fail','发现问题',counts.fail,'组检查'],['blocked','受阻 / 待澄清',counts.blocked+counts.unclear,'组检查'],['uncovered','待补充检查',gaps,'条需求片段']].map(([kind,label,value,unit])=>`<article class="${kind}"><span>${label}</span><strong>${value===null?'—':value}</strong><small>${value===null?'关联数据尚未取得':unit}</small></article>`).join('');
}

export function coverageView(coverage, preview = false) {
  if (!coverage) return '<p class="va-hint">正在读取需求与检查的关联。</p>';
  const s = coverage.summary;
  const link = (artifact, label) => coverage.run_id && /^screen-[a-f0-9]{32}\.png$/.test(artifact || '')
    ? `<a target="_blank" rel="noopener" href="/api/verify/runs/${encodeURIComponent(coverage.run_id)}/artifacts/${encodeURIComponent(artifact)}">${esc(label)} ↗</a>` : '';
  const groups = {preconditions:'前置条件', postconditions:'结果检查', invariants:'全程约束'};
  const comparison = {eq:'应等于',ne:'应不等于',contains:'应包含',not_contains:'应不包含',in:'应属于',not_in:'应不属于',gte:'应不小于',lte:'应不大于'};
  const measurement = {dom_text:'页面内容',dom_visible:'页面可见状态',http_status:'接口状态',http_json:'接口重新读取'};
  const card = (c) => `<details class="va-coverage-check"><summary><strong>${esc(c.title)} · ${esc(groups[c.group])}</strong> <span class="va-verdict ${esc(c.verdict)}">${esc(verdictNames[c.verdict] || '尚未执行')}</span>${c.ambiguous ? ' · 重复引用待澄清' : ''}</summary>
    <div class="va-coverage-chain"><div><strong>1 · 冻结检查</strong><ul>${c.probes.map(p=>`<li>${esc(probeText(p))}</li>`).join('')}</ul><p>${esc(comparison[c.operator] || c.operator)} ${esc(c.right_probe ? probeText(c.probes.find(p=>p.id===c.right_probe)) : valueText(c.expected))}</p><details><summary>查看引用原文</summary><p>${esc(c.quote)}</p></details></div>
    <div><strong>2 · 该检查所在流程的实际步骤</strong>${c.steps.length ? `<ol>${c.steps.map(t=>`<li>${esc(describeAction(t.action))}<span>${t.ok ? '实际完成' : '受阻或证据待核对'} ${link(t.artifact, '截图')}</span></li>`).join('')}</ol>` : '<p>尚未执行任何步骤。</p>'}${c.operation_gaps.length ? '<p>仍有冻结操作未被可信记录证明完成。</p>' : ''}</div>
    <div><strong>3 · 断言直接使用的证据</strong>${c.evidence.length ? c.evidence.map(e=>`<div><p>${esc(measurement[e.source_type] || e.source_type)}的实际值：${esc(valueText(e.value))}</p><details class="va-coverage-proof"><summary>${e.ok ? '来源与完整性已核对' : '观测或完整性受阻'} · 查看依据</summary><p>对应观测：${esc(e.probe_id)}</p><p>证据 ID：<code>${esc(e.id)}</code></p>${link(e.artifact, '查看证据截图')}</details></div>`).join('') : '<p>尚未取得可用于该断言的证据。</p>'}</div></div></details>`;
  return `<div class="va-coverage-heading"><div><h3>${preview ? '确认前，先看看有没有漏掉的要求' : '需求 → 检查 → 执行 → 证据'}</h3><p>逐条回到你的原始要求，查看检查依据与尚未覆盖的内容。</p></div>${!preview && coverage.run_id ? `<a class="text-button" href="/api/verify/runs/${encodeURIComponent(coverage.run_id)}/artifacts/requirement-coverage.json">下载关联数据</a>` : ''}</div>
    <div class="va-coverage-stats">${[['需求片段',s.total],['已验证',s.verified],['发现问题',s.failed],['未覆盖',s.uncovered],['部分未关联',s.partial],['受阻',s.blocked],['待澄清',s.unclear],['未执行',s.not_run]].filter(([,n],i)=>i<4 || n>0).map(([label,n])=>`<span>${label}<b>${n}</b></span>`).join('')}</div>
    <p class="va-coverage-note">按原文引用关联，方便追溯检查与漏项；不代表全部业务语义已验证。</p><details class="va-coverage-method"><summary>了解关联范围与判断方式</summary><p>${esc(coverage.note)}</p></details>${!coverage.integrity_ok ? '<p role="alert">冻结清单完整性核对失败，不能据此认定需求已验证。</p>' : ''}
    <div class="va-coverage-filters" role="group" aria-label="筛选需求状态"><button type="button" data-coverage-filter="all" aria-pressed="true">全部</button><button type="button" data-coverage-filter="gaps" aria-pressed="false">未覆盖 / 部分未关联</button><button type="button" data-coverage-filter="problems" aria-pressed="false">问题 / 受阻 / 待澄清</button></div>
    <div class="va-coverage-rows">${coverage.requirements.map(r=>`<details class="va-coverage-row" data-coverage-state="${esc(r.state)}" ${['failed','uncovered','partial','blocked','unclear'].includes(r.state) ? 'open' : ''}><summary><span class="va-coverage-state ${esc(r.state)}">${esc(r.label)}</span><strong>${esc(r.id.replace('req-', ''))}. ${esc(r.text)}</strong></summary><p>${esc(r.reason)}</p>${r.unlinked_text && ['partial','uncovered'].includes(r.state) ? `<p>尚未直接关联的文字：<mark>${esc(r.unlinked_text)}</mark></p>` : ''}${r.checks.length ? r.checks.map(card).join('') : '<p>请返回检查清单，补充可执行的结果检查后生成新版本。</p>'}</details>`).join('')}</div><p class="va-coverage-empty" hidden>这个筛选下没有需求片段。</p>`;
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
