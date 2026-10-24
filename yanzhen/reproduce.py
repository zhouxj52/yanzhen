"""Bounded deletion minimization with fresh fixtures and a fixed failure oracle."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import uuid
from typing import Awaitable, Callable

from .models import Contract, Run, Verdict, now
from .runtime import event
from .store import save_run


@dataclass
class Trial:
    outcome: str
    fingerprint: str = ""
    observations: list[dict] = field(default_factory=list)
    reason: str = ""

    def payload(self):
        return {"outcome":self.outcome,"fingerprint":self.fingerprint,"observations":self.observations,"reason":self.reason}


async def minimize(steps: list[str], evaluate: Callable[[list[str]], Awaitable[Trial]], fingerprint: str, *, budget=16, confirmations=2) -> dict:
    """Single deletion pass to a fixed point within a trial budget; not global minimality."""
    history = []
    current = list(steps)

    async def attempt(candidate, phase):
        try:
            async with asyncio.timeout(20):
                trial = await evaluate(list(candidate))
        except TimeoutError:
            trial = Trial("blocked", reason="试验超时")
        except Exception as exc:
            trial = Trial("blocked", reason=type(exc).__name__)
        matched = trial.outcome == "reproduced" and trial.fingerprint == fingerprint
        history.append({"phase":phase,"steps":list(candidate),"matched":matched,**trial.payload()})
        return matched

    baseline = await attempt(current, "baseline")
    if not baseline:
        return {"status":"unconfirmed","original_steps":steps,"steps":current,"trials":history,"reason":"原步骤未能在新环境重现同一缺陷"}
    index = 0
    while index < len(current) and len(history) < budget - confirmations:
        candidate = current[:index] + current[index+1:]
        if candidate and await attempt(candidate, "deletion"):
            current = candidate
            index = 0
        else:
            index += 1
    confirmed = 0
    for _ in range(confirmations):
        confirmed += await attempt(current, "confirmation")
    return {"status":"verified" if confirmed == confirmations else "unstable","fingerprint":fingerprint,"original_steps":steps,"steps":current,"removed":len(steps)-len(current),"confirmations":confirmed,"required_confirmations":confirmations,"trials":history,"budget":budget,"minimality":"仅在给定动作集合和试验预算内验证，不承诺全局最小","fresh_fixture_each_trial":True}


async def reimbursement_trial(run: Run, contract: Contract, steps: list[str], origin, client) -> Trial:
    from .demo import seed
    from .adapters.reimbursement import Executor
    trial = Run(id=uuid.uuid4().hex,bundle_id=run.bundle_id,digest=run.digest,scenario=run.scenario,browser_requested=False,target=run.target,internal_trial=True)
    save_run(trial)
    seed(trial.id)
    executor = Executor(trial,origin,client)
    evidence = []
    observed = []
    marker = "repro-" + uuid.uuid4().hex
    response = after = None
    try:
        # Preconditions are fixed setup, outside the deletable operation sequence.
        record = 3 if contract.kind == "foreign_record" else 1 if contract.kind == "approved_locked" else 2
        owner = "bob" if record == 3 else "alice"
        before = await executor.request(evidence,owner,"GET",f"/records/{record}")
        if before.status_code != 200 or before.json().get("owner") != owner or (record == 1 and before.json().get("status") != "approved"):
            return Trial("invalid",reason="独立验证的资源归属或前置状态不成立")
        for step in steps:
            if step == "查看本人列表":
                await executor.request(evidence,"alice","GET","/records")
            elif step == "查询原记录":
                await executor.request(evidence,owner,"GET",f"/records/{record}")
            elif step == "读取他人记录":
                response = await executor.request(evidence,"alice","GET","/records/3")
            elif step == "提交已审批记录":
                response = await executor.request(evidence,"alice","POST","/records/1/submit")
            elif step == "保存唯一说明":
                response = await executor.request(evidence,"alice","PATCH","/records/2",{"note":marker})
            elif step == "重新查询记录":
                after = await executor.request(evidence,"alice","GET",f"/records/{record}")
            else:
                return Trial("invalid",reason="未知动作")
        for e in evidence:
            observed.append({"method":e.data["method"],"path":e.data["path"],"status":e.data["status"],"response":e.data["response"]})
        if response is None:
            return Trial("invalid",observations=observed,reason="未执行被验收的业务动作")
        if contract.kind == "foreign_record":
            if response.status_code != 200 or response.json().get("owner") != "bob":
                return Trial("not_reproduced",observations=observed)
        else:
            if after is None:
                return Trial("invalid",observations=observed,reason="缺少操作后的观察")
            if contract.kind == "approved_locked":
                failed = response.status_code == 200 and after.json().get("status") != "approved"
            else:
                failed = response.status_code == 200 and after.json().get("note") != marker
            if not failed:
                return Trial("not_reproduced",observations=observed)
        return Trial("reproduced",contract.kind,observed)
    finally:
        trial.status = "completed"
        trial.finished_at = now()
        save_run(trial)


async def todo_trial(run, contract, steps, origin, browser) -> Trial:
    if browser is None:
        return Trial("blocked",reason="浏览器不可用")
    context = await browser.new_context()
    try:
        page = await context.new_page()
        page.set_default_timeout(3500)
        response = await page.goto(f"{origin}/targets/todomvc/{run.id}/index.html")
        if response.status != 200:
            return Trial("blocked",reason="目标资源不可用")
        marker = "repro-" + uuid.uuid4().hex
        observations = []
        created = False
        refreshed = False
        for step in steps:
            if step == "新增任务":
                await page.locator(".new-todo").fill(marker)
                await page.locator(".new-todo").press("Enter")
                created = await page.locator(".todo-list li").filter(has_text=marker).count() == 1
                observations.append({"stage":"after_add","count":int(created)})
            elif step == "切换活动筛选":
                await page.locator('.filters a[href="#/active"]').click()
            elif step == "切换全部筛选":
                await page.locator('.filters a[href="#/"]').click()
            elif step == "刷新页面":
                await page.reload()
                await page.locator(".new-todo").wait_for()
                refreshed = True
            else:
                return Trial("invalid",reason="未知动作")
        count = await page.locator(".todo-list li").filter(has_text=marker).count()
        observations.append({"stage":"final","count":count})
        if not created or not refreshed:
            return Trial("invalid",observations=observations,reason="缺少新增成功或刷新操作")
        return Trial("reproduced" if count == 0 else "not_reproduced","todo_persists" if count == 0 else "",observations)
    finally:
        await context.close()


async def reproduce_failures(run, bundle, executor, origin, client):
    contracts = {c.id:c for c in bundle.contracts}
    recipes = {
        "foreign_record":["查看本人列表","查询原记录","读取他人记录"],
        "approved_locked":["查看本人列表","查询原记录","提交已审批记录","重新查询记录"],
        "save_persists":["查看本人列表","查询原记录","保存唯一说明","重新查询记录"],
        "todo_persists":["新增任务","切换活动筛选","切换全部筛选","刷新页面"],
    }
    for result in run.results:
        if result.verdict != Verdict.FAIL:
            continue
        if result.kind not in recipes:
            run.reproductions.append({"contract_id":result.contract_id,"status":"unsupported","reason":"该检查尚无可执行精简动作适配"})
            continue
        contract = contracts[result.contract_id]
        event(run,"minimize",f"{contract.id} 开始在新环境验证和精简复现步骤")
        async def evaluate(steps):
            bundle.assert_frozen()
            if run.target == "todomvc":
                return await todo_trial(run,contract,steps,origin,executor.browser)
            return await reimbursement_trial(run,contract,steps,origin,client)
        report = await minimize(recipes[result.kind],evaluate,result.kind)
        report.update({"contract_id":contract.id,"contract_digest":run.digest,"target":run.target,"scenario":run.scenario,"recipe_source":"目标适配器提供的初始动作方案；不是从任意 trace 自动提取","setup":"每次使用独立浏览器上下文或新数据库；接口试验固定登录身份并验证资源归属与初始状态。","mode":"browser" if run.target=="todomvc" else "api"})
        run.reproductions.append(report)
        event(run,"minimize",f"{contract.id} 精简结束：{report['status']}，{len(report['original_steps'])} → {len(report['steps'])} 步")
