/* A narrated UI around actual API execution. No generated or fixture result data. */
const showcase = {
  chapter: 0,
  reached: 0,
  busy: false,
  bundle: null,
  original: null,
  fixed: null,
  live: null,
  error: null,
  stopped: false,
  generation: 0,
  startedAt: null,
  timer: null,
};
const demoCopy = [
  "先说清楚什么叫正确：任务新增、完成、刷新后保留。标准经审阅冻结，后续执行始终使用同一份契约。",
  "验真正在隔离的浏览器环境中执行检查。执行日志直接来自验收服务；工具或环境失败会单独报告。",
  "这两张图片来自同一次真实执行。新增时任务可见，刷新后消失，页面观察与冻结的持久化要求发生冲突。",
  "删掉无关操作后，还能重现同一问题吗？每次尝试都开新环境；最终保留的步骤还要独立确认两次。",
  "把本地持久化修复对照版放到同一份冻结标准下，再检查一次。通过数和失败数取自两次真实运行。",
];
const demoSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function demoCheck(generation) {
  if (generation !== showcase.generation) throw new Error("DEMO_STOPPED");
}
function demoContract() {
  return showcase.bundle?.contracts.find((c) => c.kind === "todo_persists");
}
function demoFailure() {
  return showcase.original?.results.find((r) => r.kind === "todo_persists");
}
function demoRecipe() {
  return showcase.original?.reproductions.find(
    (r) => r.contract_id === demoContract()?.id,
  );
}
function demoImage(file, run = showcase.original) {
  return (
    "/api/runs/" +
    encodeURIComponent(run.id) +
    "/artifacts/" +
    encodeURIComponent(file)
  );
}
function demoIcon(name) {
  return icon(name);
}
function demoSummary(run) {
  return run?.summary || { pass: 0, fail: 0, blocked: 0, unclear: 0 };
}
function demoHeading(number, title, description) {
  return (
    '<div class="scene-eyebrow">ACT ' +
    number +
    ' / A REAL ACCEPTANCE STORY</div><h2 class="scene-heading">' +
    escapeText(title) +
    '</h2><p class="scene-description">' +
    escapeText(description) +
    "</p>"
  );
}
function proofFrame(title, file, description, after = false) {
  return (
    '<section class="proof-frame ' +
    (after ? "after" : "") +
    '"><header><span>' +
    title +
    "</span><b>" +
    (after ? "AFTER REFRESH" : "BEFORE REFRESH") +
    '</b></header><div class="proof-image">' +
    (file
      ? '<a target="_blank" rel="noopener" href="' +
        demoImage(file) +
        '"><img src="' +
        demoImage(file) +
        '" alt="' +
        escapeText(description) +
        '"></a>'
      : '<div class="proof-missing">本次未获取截图，请查看原始观察记录</div>') +
    "</div><footer>" +
    escapeText(description) +
    "</footer></section>"
  );
}
function renderDemoScene() {
  const d = showcase,
    chapter = d.chapter,
    report = d.original,
    result = demoFailure(),
    recipe = demoRecipe();
  let scene = "";
  $("#demo-provider").disabled = d.busy;
  const source = d.bundle?.provider || $("#demo-provider").value;
  $("#demo-model-note").textContent =
    source === "offline"
      ? "浏览器执行连接本地引擎。当前需求采用离线规则解析。"
      : "需求采用 " +
        (source === "deepseek" ? "DeepSeek" : "Qwen") +
        " API 解析，浏览器检查与取证仍连接本地引擎。";
  if (chapter === 0) {
    scene =
      demoHeading(
        "01",
        "先有标准，\n再有答案。",
        "演示项目：TodoMVC 任务管理。我们重点检查一个很容易被忽略的要求。",
      ) +
      '<div class="requirement-paper"><div class="paper-label"><span>' +
      demoIcon("file-text") +
      " ACCEPTANCE REQUIREMENT</span><span>" +
      (d.bundle?.frozen ? "已冻结" : "待开始确认") +
      "</span></div><blockquote>“新增任务后，<br>刷新页面仍然存在。”</blockquote></div>" +
      '<div class="scene-contracts">' +
      ["新增后可见", "完成后可筛选", "刷新后保留"]
        .map(
          (s) =>
            '<span class="scene-contract">' +
            demoIcon("list-check") +
            s +
            "</span>",
        )
        .join("") +
      "</div>" +
      '<div class="scene-meta"><span>' +
      demoIcon("lock") +
      " " +
      (d.bundle?.frozen ? "验收标准已锁定" : "开始后按当前示例确认并冻结标准") +
      "</span>" +
      (d.bundle
        ? "<code>SHA-256 " +
          escapeText(d.bundle.digest.slice(0, 18)) +
          "…</code>"
        : "") +
      "</div>" +
      '<div class="scene-flow"><span>' +
      demoIcon("file-text") +
      " 定义需求</span><b>→</b><span>" +
      demoIcon("flask") +
      " 真实执行</span><b>→</b><span>" +
      demoIcon("shield-check") +
      " 证据复核</span><b>→</b><span>" +
      demoIcon("rotate") +
      " 独立复现</span></div>";
  } else if (chapter === 1) {
    const live = d.live || report;
    const finished =
      live && !["queued", "running", "finalizing"].includes(live.status);
    scene =
      demoHeading(
        "02",
        "让浏览器，真正做一次检查。",
        finished
          ? "这次检查已结束。每条判定都能打开对应的原始报告。"
          : "正在新环境中新增任务、切换完成状态、刷新页面，并收集证据。",
      ) +
      '<div class="live-execution"><div class="execution-preview">' +
      (finished
        ? demoIcon("shield-check")
        : '<div class="execution-pulse"></div>') +
      "<strong>" +
      (finished ? "真实执行已完成" : "正在运行本地验收引擎") +
      '</strong><small>Chromium · TodoMVC · 隔离上下文</small></div><div class="execution-log">' +
      ((live?.events || [])
        .slice(-6)
        .map(
          (e) =>
            "<div><time>" +
            escapeText(dateText(e.time, true)) +
            "</time><span>" +
            escapeText(e.message) +
            "</span></div>",
        )
        .join("") || "<div><span>正在向验收服务提交任务…</span></div>") +
      "</div></div>" +
      (finished
        ? '<div class="scene-checks">' +
          live.results
            .map(
              (r) =>
                '<div class="scene-check"><span>' +
                demoIcon(r.verdict === "pass" ? "shield-check" : "info") +
                escapeText(r.title) +
                '</span><span class="verdict ' +
                escapeText(r.verdict) +
                '">' +
                escapeText(verdicts[r.verdict]) +
                "</span></div>",
            )
            .join("") +
          "</div>"
        : "");
  } else if (chapter === 2) {
    const before = result?.evidence.find((e) => e.id === "before-screen");
    const after = result?.evidence.find(
      (e) => e.kind === "screenshot" && e.id !== "before-screen",
    );
    const initial = result?.evidence.find((e) => e.data?.stage === "after_add");
    const reloaded = result?.evidence.find(
      (e) => e.data?.stage === "after_reload",
    );
    scene =
      demoHeading(
        "03",
        "看起来成功，未必真的保存。",
        "从同一次执行中取出刷新前后的截图，并对照真实 DOM 观察。",
      ) +
      '<div class="proof-pair">' +
      proofFrame(
        "新增后",
        before?.file,
        "观察到 " + (initial?.data.count ?? "未知") + " 条匹配任务",
      ) +
      proofFrame(
        "刷新后",
        after?.file,
        "观察到 " + (reloaded?.data.count ?? "未知") + " 条匹配任务",
        true,
      ) +
      "</div>" +
      '<div class="proof-summary">' +
      demoIcon("info") +
      "<span>" +
      escapeText(
        result?.conflicts?.[0]?.title || result?.summary || "尚无结果",
      ) +
      "</span></div>" +
      '<div class="scene-meta"><span>证据引用：' +
      escapeText((result?.conflicts?.[0]?.evidence_ids || []).join(" ↔ ")) +
      "</span><span>结论：" +
      escapeText(verdicts[result?.verdict] || "尚未判定") +
      "</span></div>";
  } else if (chapter === 3) {
    const original = recipe?.original_steps || [],
      reduced = recipe?.steps || [],
      verified = recipe?.status === "verified";
    scene =
      demoHeading(
        "04",
        "留下必要步骤，让问题再次出现。",
        "初始复现动作由适配器提供。每次删减，都重新执行并检查是否仍为同一缺陷。",
      ) +
      '<div class="reduction-showcase"><div class="reduction-recipe"><header>初始复现方案<b>' +
      original.length +
      "</b></header><ol>" +
      original
        .map(
          (s) =>
            '<li class="' +
            (reduced.includes(s) ? "" : "removed") +
            '">' +
            escapeText(s) +
            "</li>",
        )
        .join("") +
      '</ol></div><div class="reduction-arrow">→</div><div class="reduction-recipe reduced"><header>经过验证的精简方案<b>' +
      reduced.length +
      "</b></header><ol>" +
      reduced.map((s) => "<li>" + escapeText(s) + "</li>").join("") +
      "</ol></div></div>" +
      '<div class="confirmation-strip"><span>' +
      demoIcon("history") +
      (recipe?.trials?.length || 0) +
      " 次实际试验</span><span>" +
      demoIcon("shield-check") +
      "独立确认 " +
      (recipe?.confirmations || 0) +
      " / " +
      (recipe?.required_confirmations || 2) +
      "</span><span>" +
      escapeText(verified ? "同一缺陷复现成功" : recipe?.status || "尚未精简") +
      "</span></div>" +
      '<details class="trial-preview"><summary>查看逐次试验记录</summary><div>' +
      (recipe?.trials || [])
        .map(
          (t, i) =>
            "<p>" +
            escapeText(i + 1 + ". " + t.steps.join(" → ")) +
            "<span>" +
            escapeText(
              t.matched
                ? "同一缺陷重现"
                : t.outcome === "invalid"
                  ? "缺少必要步骤"
                  : "未重现",
            ) +
            "</span></p>",
        )
        .join("") +
      "</div></details>" +
      '<div class="scene-meta">仅对当前动作集合和预算进行精简，不承诺全局最小。</div>';
  } else {
    const old = demoSummary(d.original),
      fixed = demoSummary(d.fixed);
    const matching =
      !!d.fixed &&
      d.fixed.digest === d.original.digest &&
      d.fixed.status === "completed";
    scene =
      demoHeading(
        "05",
        d.fixed ? "用同一份标准，验证这次修复。" : "修复之后，也要重新验证。",
        d.fixed
          ? "原版与本地持久化修复对照分别执行，标准和来源保持一致。"
          : "正在对本地持久化修复版运行相同的冻结契约，不自动改动上游产品代码。",
      ) +
      '<div class="comparison-board"><section class="comparison-side original"><small>UPSTREAM / 内存存储</small><h3>原版验收结果</h3><div class="comparison-numbers"><span><b>' +
      old.pass +
      "</b>通过</span><span><b>" +
      old.fail +
      '</b>缺陷</span></div><p>页面创建成功，刷新后任务丢失</p></section><section class="comparison-side fixed"><small>LOCAL REPAIR / 持久化</small><h3>' +
      (d.fixed ? "修复对照版结果" : "正在执行修复版") +
      '</h3><div class="comparison-numbers"><span><b>' +
      (d.fixed ? fixed.pass : "—") +
      "</b>通过</span><span><b>" +
      (d.fixed ? fixed.fail : "—") +
      "</b>缺陷</span></div><p>" +
      (d.fixed ? "结果来自本次真实执行" : "等待真实检查结果") +
      "</p></section></div>" +
      '<div class="same-standard">' +
      demoIcon("lock") +
      escapeText(
        matching
          ? "两次契约 SHA-256 摘要一致，验收标准未改变。"
          : "修复版将使用原冻结契约，不放宽验收标准。",
      ) +
      "</div>" +
      (d.fixed
        ? '<div class="demo-guard-action"><button id="demo-guard">尝试放宽验收标准</button><span id="demo-guard-result">看看系统如何审查错误修复</span></div>'
        : "");
  }
  if (d.error)
    scene += '<div class="demo-error">' + escapeText(d.error) + "</div>";
  $("#demo-scene").dataset.chapter = String(chapter);
  $("#demo-scene").innerHTML = scene;
  $("#demo-caption").textContent = d.stopped
    ? "演示已停止，已创建运行和已完成证据会保留。"
    : demoCopy[chapter];
  $("#demo-session-state").textContent = d.error
    ? "执行遇到问题"
    : d.stopped
      ? "已停止"
      : d.busy
        ? "真实执行中"
        : d.fixed
          ? "本次演示已完成"
          : d.bundle
            ? "标准已冻结"
            : "等待开始";
  $$("[data-chapter]").forEach((button) => {
    const index = Number(button.dataset.chapter);
    button.disabled = index > d.reached;
    button.classList.toggle("current", index === chapter);
    button.classList.toggle("available", index <= d.reached);
    button.setAttribute("aria-current", index === chapter ? "step" : "false");
  });
  $("#demo-start").innerHTML =
    demoIcon(d.busy ? "square" : "play") +
    (d.busy
      ? "停止演示"
      : d.fixed || d.error || d.stopped
        ? "重新运行演示"
        : "开始真实演示");
  $("#demo-back").disabled = chapter === 0;
  $("#demo-next").disabled = chapter >= d.reached;
  $("#demo-delivery").hidden = !d.fixed;
  if (d.fixed) {
    $("#demo-delivery-actions").innerHTML =
      '<button class="button secondary" id="demo-open-original">查看缺陷报告</button><button class="button secondary" id="demo-open-fixed">查看修复版报告</button><a class="button primary" href="/api/runs/' +
      d.original.id +
      '/artifacts/evidence.zip">' +
      demoIcon("download") +
      "下载真实证据包</a>";
    $("#demo-open-original").onclick = () => openRun(d.original.id);
    $("#demo-open-fixed").onclick = () => openRun(d.fixed.id);
  }
  if ($("#demo-guard")) $("#demo-guard").onclick = runDemoGuard;
}
function setDemoChapter(chapter, force = false) {
  showcase.reached = Math.max(showcase.reached, chapter);
  if (force || $("#demo-autoplay").checked) showcase.chapter = chapter;
  renderDemoScene();
}
async function demoHold(generation, milliseconds = 3000) {
  if ($("#demo-autoplay").checked) await demoSleep(milliseconds);
  demoCheck(generation);
}
async function demoPoll(id, generation) {
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    demoCheck(generation);
    const run = await api("/api/runs/" + id);
    demoCheck(generation);
    showcase.live = run;
    if (showcase.chapter === 1) renderDemoScene();
    if (["completed", "error", "cancelled"].includes(run.status)) {
      if (run.status !== "completed")
        throw new Error(run.error || "本次运行未完成：" + run.status);
      if (run.results.some((r) => ["blocked", "unclear"].includes(r.verdict)))
        throw new Error("本次运行有受阻或待澄清检查，请打开报告查看原因。");
      return run;
    }
    await demoSleep(700);
  }
  throw new Error("运行等待超时，后台任务仍可在运行记录中查看。");
}
async function runShowcase() {
  if (showcase.busy) return stopShowcase();
  const d = showcase,
    generation = ++d.generation;
  Object.assign(d, {
    chapter: 0,
    reached: 0,
    busy: true,
    bundle: null,
    original: null,
    fixed: null,
    live: null,
    error: null,
    stopped: false,
    startedAt: Date.now(),
  });
  clearInterval(d.timer);
  d.timer = setInterval(() => {
    $("#demo-elapsed").textContent =
      "真实演示用时 " + Math.floor((Date.now() - d.startedAt) / 1000) + " 秒";
  }, 500);
  renderDemoScene();
  try {
    const requirements = state.config.targets.todomvc.requirements;
    const provider = $("#demo-provider").value;
    let bundle = await post("/api/analyze", {
      requirements,
      provider,
      target: "todomvc",
    });
    demoCheck(generation);
    bundle = await post("/api/bundles/" + bundle.id + "/freeze", {
      digest: bundle.digest,
    });
    demoCheck(generation);
    d.bundle = bundle;
    renderDemoScene();
    await demoHold(generation, 3000);
    setDemoChapter(1);
    const original = await post("/api/runs", {
      bundle_id: bundle.id,
      target: "todomvc",
      scenario: "upstream",
      browser: true,
    });
    if (generation !== d.generation) {
      if (["queued", "running"].includes(original.status))
        await post("/api/runs/" + original.id + "/cancel", {});
      throw new Error("DEMO_STOPPED");
    }
    demoCheck(generation);
    d.live = original;
    renderDemoScene();
    d.original = await demoPoll(original.id, generation);
    const failure = demoFailure();
    if (failure?.verdict !== "fail" || !failure.conflicts.length)
      throw new Error("本次结果未呈现预期的证据冲突，保留真实报告供复查。");
    await demoHold(generation, 1500);
    setDemoChapter(2);
    await demoHold(generation, 5500);
    if (demoRecipe()?.status !== "verified")
      throw new Error("精简步骤没有完成独立确认，请检查实际试验记录。");
    setDemoChapter(3);
    await demoHold(generation, 5000);
    setDemoChapter(4);
    const fixed = await post("/api/runs", {
      bundle_id: bundle.id,
      target: "todomvc",
      scenario: "healthy",
      browser: true,
    });
    if (generation !== d.generation) {
      if (["queued", "running"].includes(fixed.status))
        await post("/api/runs/" + fixed.id + "/cancel", {});
      throw new Error("DEMO_STOPPED");
    }
    demoCheck(generation);
    d.live = fixed;
    d.fixed = await demoPoll(fixed.id, generation);
    if (d.fixed.digest !== d.original.digest)
      throw new Error("修复对照的契约摘要发生变化，无法确认同标准比较。");
    if (d.fixed.results.some((r) => r.verdict !== "pass"))
      throw new Error("修复对照仍存在未通过检查，请查看真实报告。");
    demoCheck(generation);
    d.busy = false;
    setDemoChapter(4);
    await refreshHistory();
  } catch (error) {
    if (generation !== d.generation) return;
    d.error = error.message;
    d.busy = false;
    renderDemoScene();
  } finally {
    if (generation === d.generation) {
      clearInterval(d.timer);
      $("#demo-elapsed").textContent =
        "本次真实演示用时 " +
        Math.floor((Date.now() - d.startedAt) / 1000) +
        " 秒";
      renderDemoScene();
    }
  }
}
async function stopShowcase() {
  const run = showcase.live;
  ++showcase.generation;
  showcase.busy = false;
  showcase.stopped = true;
  clearInterval(showcase.timer);
  renderDemoScene();
  if (run && ["queued", "running"].includes(run.status)) {
    try {
      await post("/api/runs/" + run.id + "/cancel", {});
    } catch (error) {
      toast("已停止讲解；任务状态：" + error.message, true);
    }
  }
}
async function runDemoGuard() {
  const contract = demoContract();
  const original = {
    contract_id: contract.id,
    role: contract.role,
    action: contract.kind,
    assertions: [contract.expected],
    locator: ".new-todo",
    wait_ms: 0,
    skip: false,
  };
  const candidate = { ...original, assertions: ["always_pass"] };
  $("#demo-guard").disabled = true;
  try {
    const review = await post(
      "/api/runs/" + showcase.original.id + "/repair-review/" + contract.id,
      { original, candidate, witnessed_action: contract.kind },
    );
    $("#demo-guard-result").textContent = review.accepted
      ? "审查结果：通过"
      : "已拦截：" + review.violations.join("、");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if ($("#demo-guard")) $("#demo-guard").disabled = false;
  }
}
function initShowcase() {
  $("#demo-provider").onchange = () => {
    if (!showcase.busy && !showcase.bundle) renderDemoScene();
  };
  $("#demo-start").onclick = runShowcase;
  $$("[data-chapter]").forEach(
    (button) =>
      (button.onclick = () => {
        showcase.chapter = Number(button.dataset.chapter);
        renderDemoScene();
      }),
  );
  $("#demo-back").onclick = () => {
    showcase.chapter = Math.max(0, showcase.chapter - 1);
    renderDemoScene();
  };
  $("#demo-next").onclick = () => {
    showcase.chapter = Math.min(showcase.reached, showcase.chapter + 1);
    renderDemoScene();
  };
  $("#demo-fullscreen").onclick = () => {
    const focused = document.body.classList.toggle("focus-demo");
    $("#demo-fullscreen").innerHTML =
      demoIcon("external") + (focused ? "退出专注" : "专注演示");
    window.scrollTo(0, 0);
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.body.classList.remove("focus-demo");
      $("#demo-fullscreen").innerHTML = demoIcon("external") + "专注演示";
    }
  });
  renderDemoScene();
}
