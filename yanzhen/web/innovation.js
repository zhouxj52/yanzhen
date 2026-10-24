function configureTarget(target, reset = false) {
  const config = state.config.targets[target];
  $("#target").value = target;
  $("#target-name").textContent = config.label;
  $("#target-help").textContent =
    target === "todomvc"
      ? "固定版本官方示例；上游原版与本地持久化修复版分别运行。此目标需要浏览器。"
      : "内置报销场景；精简复现使用新数据库与真实接口，不包含浏览器步骤。";
  $("#scenario").innerHTML = Object.entries(config.scenarios)
    .map(
      ([key, label]) =>
        '<option value="' + key + '">' + escapeText(label) + "</option>",
    )
    .join("");
  $("#scenario").value = target === "todomvc" ? "upstream" : "broken";
  $("#browser").checked = true;
  $("#browser").disabled = target === "todomvc";
  if (reset) {
    ++state.opening;
    clearTimeout(state.poll);
    state.run = null;
    state.selected = null;
    $("#requirements").value = config.requirements;
    dirty();
    renderBundle();
    resetRun();
    setStep(1);
  }
}

function renderConflicts(result) {
  if (!result.conflicts?.length) return;
  const section = document.createElement("section");
  section.className = "conflict-callout";
  section.innerHTML =
    "<strong>发现证据冲突</strong>" +
    result.conflicts
      .map(
        (c) =>
          "<p>" +
          escapeText(c.title) +
          "</p><small>证据引用：" +
          c.evidence_ids.map(escapeText).join(" ↔ ") +
          "</small>",
      )
      .join("");
  $("#evidence").prepend(section);
}

function renderInnovations() {
  const reports = state.run?.reproductions || [];
  $("#reproductions").hidden = !reports.length;
  $("#repair-panel").hidden =
    !state.bundle || state.run?.status !== "completed";
  $("#reproductions").innerHTML =
    '<div class="innovation-heading"><div><h2>经过执行验证的精简复现</h2><p>每次尝试使用新环境，保持冻结契约和缺陷判定条件不变。</p></div>' +
    (state.run?.artifacts?.includes("reproduce.py")
      ? '<a class="button secondary" href="/api/runs/' +
        state.run.id +
        '/artifacts/reproduce.py">下载精简复现脚本</a>'
      : "") +
    "</div>" +
    reports
      .map((r) => {
        const verified = r.status === "verified";
        const status =
          {
            verified: "独立确认通过",
            unstable: "结果不稳定",
            unconfirmed: "未能确认",
            unsupported: "尚无动作适配",
          }[r.status] || r.status;
        return (
          '<article class="reproduction-item"><div class="reproduction-heading"><strong>' +
          escapeText(r.contract_id) +
          '</strong><span class="status-pill ' +
          (verified ? "success" : "neutral") +
          '">' +
          escapeText(status) +
          '</span><span class="muted">' +
          (r.original_steps
            ? r.original_steps.length +
              " → " +
              r.steps.length +
              " 步 · " +
              (r.mode === "api" ? "接口复现" : "浏览器复现")
            : "") +
          "</span></div>" +
          (r.steps
            ? '<ol class="recipe-steps">' +
              r.steps.map((s) => "<li>" + escapeText(s) + "</li>").join("") +
              '</ol><p class="reproduction-note">固定前置准备：' +
              escapeText(r.setup) +
              '</p><p class="reproduction-note">独立确认 ' +
              (r.confirmations || 0) +
              " / " +
              (r.required_confirmations || 2) +
              " · " +
              escapeText(r.minimality || r.reason || "") +
              '</p><details class="trial-history"><summary>查看 ' +
              (r.trials?.length || 0) +
              " 次实际试验</summary>" +
              (r.trials || [])
                .map(
                  (t, i) =>
                    '<div class="trial-row"><b>' +
                    (i + 1) +
                    "</b><span>" +
                    escapeText(t.steps.join(" → ")) +
                    '</span><span class="verdict ' +
                    (t.matched ? "pass" : "blocked") +
                    '">' +
                    (t.matched
                      ? "同一缺陷重现"
                      : {
                          invalid: "缺少必要步骤",
                          blocked: "执行受阻",
                          not_reproduced: "未重现",
                          reproduced: "不同缺陷",
                        }[t.outcome] || "未确认") +
                    '</span></div><details class="trial-observations"><summary>实际观察</summary><pre>' +
                    escapeText(JSON.stringify(t.observations, null, 2)) +
                    "</pre></details>",
                )
                .join("") +
              "</details>"
            : "<p>" + escapeText(r.reason) + "</p>") +
          (verified
            ? '<button class="button secondary verify-recipe" data-reproduce="' +
              escapeText(r.contract_id) +
              '">在新环境验证精简步骤</button>'
            : "") +
          "</article>"
        );
      })
      .join("");
  $("#reproductions")
    .querySelectorAll("[data-reproduce]")
    .forEach((button) => {
      button.onclick = async () => {
        const runId = state.run.id;
        button.disabled = true;
        try {
          const report = await post(
            "/api/runs/" + runId + "/reproduce/" + button.dataset.reproduce,
            {},
          );
          toast(
            report.matches
              ? "精简步骤已在新环境复现同一缺陷。"
              : "精简步骤未重现同一缺陷，请检查结果。",
            !report.matches,
          );
        } catch (e) {
          toast(e.message, true);
        } finally {
          button.disabled = false;
        }
      };
    });
}

async function reviewRepairCandidate() {
  const contract = state.bundle?.contracts.find(
    (c) => c.id === state.run?.results?.[state.selected ?? 0]?.contract_id,
  );
  if (!contract || contract.kind === "unclear") {
    toast("请选择一个明确的验收项。");
    return;
  }
  const original = {
    contract_id: contract.id,
    role: contract.role,
    action: contract.kind,
    assertions: [contract.expected],
    locator: "original-locator",
    wait_ms: 0,
    skip: false,
  };
  const candidate = {
    ...original,
    locator: "stable-business-locator",
    wait_ms: 500,
  };
  const change = $("#repair-case").value;
  if (change === "assertion") candidate.assertions = ["always_pass"];
  if (change === "role")
    candidate.role = contract.role === "admin" ? "alice" : "admin";
  if (change === "skip") candidate.skip = true;
  $("#review-repair").disabled = true;
  try {
    const report = await post(
      "/api/runs/" + state.run.id + "/repair-review/" + contract.id,
      { original, candidate, witnessed_action: contract.kind },
    );
    $("#repair-verdict").className = report.accepted
      ? "repair-approved"
      : "repair-rejected";
    $("#repair-verdict").textContent =
      contract.id +
      " · " +
      (report.accepted
        ? "受限计划审查通过；尚未应用或执行候选。"
        : "已拦截：" + report.violations.join("、"));
  } catch (e) {
    toast(e.message, true);
  } finally {
    $("#review-repair").disabled = false;
  }
}
