from __future__ import annotations

import time
import uuid

import httpx

from ..demo import seed
from ..guard import approve_locator_repair
from ..models import REIMBURSEMENT_KINDS, CheckResult, Contract, Evidence, Run, Verdict
from ..runtime import InfrastructureError, event
from ..store import run_dir


class Executor:
    def __init__(self, run: Run, origin: str, client: httpx.AsyncClient):
        self.run = run
        self.origin = origin.rstrip("/")
        self.base = self.origin + f"/demo/{run.id}/api"
        self.client = client
        self.sessions = {}
        self.browser = None
        self.pages = {}
        self.browser_error = None
        self.redactions = set()

    async def request(self, evidence: list, role: str, method: str, path: str, body: dict | None = None) -> httpx.Response:
        if role not in self.sessions:
            login = await self.client.post(self.base + "/login", json={"username": role})
            if login.status_code != 200:
                raise InfrastructureError(f"演示登录失败：HTTP {login.status_code}")
            self.sessions[role] = login.json()["token"]
            self.redactions.add(self.sessions[role])
        response = await self.client.request(method, self.base + path, headers={"Authorization": "Bearer " + self.sessions[role]}, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {"non_json": True}
        evidence.append(Evidence(id=f"ev-{uuid.uuid4().hex[:10]}", kind="http", description=f"{role} · {method} {path}", data={"role": role, "method": method, "path": path, "request_body": body, "status": response.status_code, "response": payload}))
        if response.status_code >= 500 or response.status_code == 401:
            raise InfrastructureError(f"依赖服务或会话不可用：HTTP {response.status_code}")
        return response

    async def page(self, role: str):
        if self.browser is None:
            raise InfrastructureError(self.browser_error or "浏览器不可用")
        if role not in self.pages:
            context = await self.browser.new_context(viewport={"width": 1180, "height": 850}, locale="zh-CN")
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = await context.new_page()
            page.set_default_timeout(5000)
            await page.goto(self.origin + f"/demo/{self.run.id}")
            await page.get_by_label("演示身份").select_option(role)
            await page.get_by_role("button", name="进入工作台").click()
            await page.locator("#workspace").wait_for(state="visible")
            token = await page.evaluate("key => sessionStorage.getItem(key)", f"yz-demo-{self.run.id}")
            if token:
                self.redactions.add(token)
            self.pages[role] = page
        return self.pages[role]

    async def screenshot(self, role: str, contract: Contract, evidence: list):
        if not self.run.browser_requested or self.browser is None:
            return
        try:
            page = await self.page(role)
            await page.reload()
            await page.locator("#workspace").wait_for(state="visible")
            filename = f"{contract.id}.png"
            await page.screenshot(path=str(run_dir(self.run.id) / filename), full_page=True)
            evidence.append(Evidence(id=f"ev-{uuid.uuid4().hex[:10]}", kind="screenshot", description="当前测试身份的页面状态；权限结论同时参考接口证据", file=filename))
        except Exception as exc:
            evidence.append(Evidence(id=f"capture-{contract.id}", kind="observation",
                description="辅助截图未获取，接口判定保持原结果",
                data={"capture_error": type(exc).__name__}))
            event(self.run, "evidence", f"{contract.id} 辅助截图失败：{type(exc).__name__}")


    async def check(self, contract: Contract) -> CheckResult:
        started = time.perf_counter()
        evidence = []
        steps = []
        verdict = Verdict.BLOCKED
        summary = "未执行"
        try:
            if contract.kind == "unclear":
                verdict, summary = Verdict.UNCLEAR, contract.rationale or "需求不明确或缺少适配，不能自动判定通过。"
            elif contract.kind in {"own_record", "foreign_record", "admin_record"}:
                record_id = 3 if contract.kind != "own_record" else 2
                # Establish the resource ownership independently before the negative check.
                reference = await self.request(evidence, "bob" if record_id == 3 else "alice", "GET", f"/records/{record_id}")
                if reference.status_code != 200 or reference.json().get("owner") != ("bob" if record_id == 3 else "alice"):
                    raise InfrastructureError("测试数据归属或前置条件不成立")
                response = await self.request(evidence, contract.role, "GET", f"/records/{record_id}")
                if contract.expected == "denied":
                    ok = response.status_code == 403
                    summary = "接口拒绝读取他人记录。" if ok else f"成员可读取 Bob 的报销单，接口返回 HTTP {response.status_code}。"
                else:
                    ok = response.status_code == 200 and response.json().get("id") == record_id
                    summary = "按角色和资源归属成功读取记录。" if ok else "合法读取未获得需求规定的记录。"
                verdict = Verdict.PASS if ok else Verdict.FAIL
                steps = ["新建独立测试环境，准备 Alice 与 Bob 的记录。", f"登录 {contract.role}。", f"GET /records/{record_id}，核对状态码及归属，预期 {contract.expected}。"]
                await self.screenshot(contract.role, contract, evidence)
            elif contract.kind == "approved_locked":
                before = await self.request(evidence, "alice", "GET", "/records/1")
                if before.status_code != 200 or before.json().get("status") != "approved":
                    raise InfrastructureError("前置条件不成立：记录必须已经审批")
                response = await self.request(evidence, "alice", "POST", "/records/1/submit")
                after = await self.request(evidence, "alice", "GET", "/records/1")
                if after.status_code != 200:
                    raise InfrastructureError("无法读取操作后的状态")
                ok = response.status_code == 409 and after.json().get("status") == "approved"
                verdict = Verdict.PASS if ok else Verdict.FAIL
                summary = "重复提交被拒绝，已审批状态保持不变。" if ok else "已审批记录被重复提交，或拒绝后状态发生变化。"
                steps = ["新建独立测试环境，确认 Alice 的记录 1 已审批。", "以 Alice 身份 POST /records/1/submit。", "重新读取记录；预期 HTTP 409 且状态保持 approved。"]
                await self.screenshot("alice", contract, evidence)
            elif contract.kind == "save_persists":
                marker = f"验真持久化检查-{self.run.id[:8]}"
                before = await self.request(evidence, "alice", "GET", "/records/2")
                if before.status_code != 200:
                    raise InfrastructureError("无法读取待修改的记录")
                if self.run.browser_requested:
                    page = await self.page("alice")
                    await page.get_by_label("报销说明").fill(marker)
                    button = page.get_by_role("button", name="保存说明", exact=True)
                    if await button.count() != 1:
                        fallback = page.get_by_test_id("save-note")
                        if await fallback.count() != 1:
                            raise InfrastructureError("定位器失效，缺少唯一的替代动作证据")
                        witnessed = await fallback.get_attribute("data-action")
                        repair = approve_locator_repair(contract, contract, action_before="save-note", action_after="save-note", witnessed_action=witnessed or "")
                        evidence.append(Evidence(id=f"repair-{contract.id}", kind="repair", description="按钮名称改变，依据稳定业务动作调整定位器，契约保持不变", data=repair))
                        button = fallback
                    async with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/api/records/2")) as saved:
                        await button.click()
                    write_response = await saved.value
                    evidence.append(Evidence(id=f"ui-save-{contract.id}", kind="http", description="浏览器真实提交保存请求", data={"role": "alice", "method": "PATCH", "path": "/records/2", "status": write_response.status, "request_body": {"note": marker}, "response": await write_response.json()}))
                    if write_response.status >= 500:
                        raise InfrastructureError("保存接口不可用")
                    await page.get_by_role("status").filter(has_text="保存成功").wait_for()
                    await page.reload()
                    await page.locator("#workspace").wait_for(state="visible")
                    await page.get_by_label("报销说明").wait_for(state="visible")
                    visible = await page.get_by_label("报销说明").input_value()
                    evidence.append(Evidence(id=f"ui-refresh-{contract.id}", kind="observation", description="刷新后的输入框内容", data={"expected_note": marker, "visible_note": visible}))
                else:
                    response = await self.request(evidence, "alice", "PATCH", "/records/2", {"note": marker})
                    if response.status_code != 200:
                        raise InfrastructureError("保存请求未成功")
                    visible = None
                after = await self.request(evidence, "alice", "GET", "/records/2")
                if after.status_code != 200:
                    raise InfrastructureError("保存后无法重新查询")
                ok = after.json().get("note") == marker and (visible is None or visible == marker)
                verdict = Verdict.PASS if ok else Verdict.FAIL
                summary = "重新查询" + ("和页面刷新" if visible is not None else "（本次仅接口检查）") + "后内容一致。" if ok else "保存返回成功，但重新查询或刷新后修改丢失。"
                steps = ["新建独立环境，以 Alice 登录。", "将本人记录 2 的说明改为唯一测试标记并保存。", "刷新页面并重新 GET /records/2；两处均应保持该标记。"]
                await self.screenshot("alice", contract, evidence)
        except (InfrastructureError, httpx.HTTPError) as exc:
            summary = f"执行受阻：{exc}"
            verdict = Verdict.BLOCKED
        except Exception as exc:
            # A tool failure is never evidence that the product passed or failed its requirement.
            summary = f"执行工具受阻：{type(exc).__name__}。详细信息见运行事件。"
            event(self.run, "blocked", f"{contract.id}: {type(exc).__name__}: {str(exc)[:300]}")
            verdict = Verdict.BLOCKED
        if verdict in {Verdict.PASS,Verdict.FAIL}:
            evidence.append(Evidence(id='action-witness-'+contract.id,kind='observation',description='受信执行器归档的业务动作见证',data={'business_action':contract.kind,'role':contract.role,'executor':'reimbursement','evidence_ids':[e.id for e in evidence]}))
        return CheckResult(contract_id=contract.id, kind=contract.kind, title=contract.title, verdict=verdict, summary=summary, evidence=evidence, replay_steps=steps, duration_ms=int((time.perf_counter()-started)*1000))


class ReimbursementAdapter:
    key = "reimbursement"
    label = "报销系统（隔离测试环境）"
    supported_kinds = REIMBURSEMENT_KINDS

    def prepare(self, run_id: str) -> None:
        seed(run_id)

    def create_executor(self, run: Run, origin: str, client: httpx.AsyncClient) -> Executor:
        return Executor(run, origin, client)
