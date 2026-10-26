"""Browser adapter for a pinned, locally served upstream TodoMVC application."""
from __future__ import annotations

import time
import uuid

from ..models import CheckResult, Contract, Evidence, Run, Verdict
from ..runtime import InfrastructureError
from ..store import run_dir


class TodoExecutor:
    def __init__(self, run, origin, client):
        self.run, self.origin = run, origin.rstrip("/")
        self.browser = None
        self.browser_error = None
        self.pages = {}
        self.redactions = set()

    async def check(self, contract: Contract) -> CheckResult:
        started = time.perf_counter()
        evidence = []
        verdict, summary = Verdict.BLOCKED, "浏览器未就绪"
        try:
            if contract.kind == "unclear":
                return CheckResult(contract_id=contract.id, kind=contract.kind, title=contract.title, verdict=Verdict.UNCLEAR, summary=contract.rationale)
            if not self.browser:
                raise InfrastructureError(self.browser_error or "TodoMVC 需要真实浏览器，不能用接口检查代替")
            if "alice" not in self.pages:
                context = await self.browser.new_context()
                await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                self.pages["alice"] = await context.new_page()
            page = self.pages["alice"]
            page.set_default_timeout(4000)
            response = await page.goto(f"{self.origin}/targets/todomvc/{self.run.id}/index.html")
            if response.status != 200:
                raise InfrastructureError(f"TodoMVC 资源不可用：HTTP {response.status}")
            await page.evaluate("localStorage.clear()")
            await page.reload()
            marker = "验真任务-" + uuid.uuid4().hex[:10]
            entry = page.locator(".new-todo")
            await entry.fill(marker)
            await entry.press("Enter")
            created = await page.locator(".todo-list li").filter(has_text=marker).count()
            evidence.append(Evidence(id="created", kind="observation", description="新增后的真实 DOM", data={"stage":"after_add","expected_title":marker,"count":created}))
            if created != 1:
                raise InfrastructureError("任务创建前置条件不成立")
            if contract.kind == "todo_complete":
                await page.locator(".todo-list li .toggle").check()
                await page.locator('.filters a[href="#/completed"]').click()
                completed = await page.locator(".todo-list li.completed").filter(has_text=marker).count()
                ok = completed == 1
                evidence.append(Evidence(id="completed", kind="observation", description="已完成筛选中的真实 DOM", data={"count":completed}))
            elif contract.kind == "todo_persists":
                try:
                    before_file = contract.id + "-before.png"
                    await page.screenshot(path=str(run_dir(self.run.id) / before_file), full_page=True)
                    evidence.append(Evidence(id="before-screen",kind="screenshot",description="刷新前：任务已真实创建",file=before_file))
                except Exception as exc:
                    evidence.append(Evidence(id="before-capture-error",kind="observation",description="刷新前辅助截图失败",data={"error":type(exc).__name__}))
                await page.reload()
                await entry.wait_for()
                retained = await page.locator(".todo-list li").filter(has_text=marker).count()
                evidence.append(Evidence(id="reloaded", kind="observation", description="刷新后的真实 DOM", data={"stage":"after_reload","expected_title":marker,"count":retained}))
                ok = retained == 1
            else:
                ok = created == 1
            verdict = Verdict.PASS if ok else Verdict.FAIL
            summary = "实际页面行为符合冻结需求。" if ok else "任务在当前页面创建成功，但刷新后丢失。" if contract.kind == "todo_persists" else "标记完成后的展示不符合需求。"
            filename = contract.id + ".png"
            try:
                await page.screenshot(path=str(run_dir(self.run.id) / filename), full_page=True)
                evidence.append(Evidence(id="screen",kind="screenshot",description="TodoMVC 实际检查页面",file=filename))
            except Exception as exc:
                evidence.append(Evidence(id="capture-error",kind="observation",description="辅助截图失败",data={"error":type(exc).__name__}))
        except Exception as exc:
            verdict, summary = Verdict.BLOCKED, f"执行受阻：{type(exc).__name__}: {str(exc)[:120]}"
        return CheckResult(contract_id=contract.id,kind=contract.kind,title=contract.title,verdict=verdict,summary=summary,evidence=evidence,replay_steps=["打开独立浏览器环境。","新增唯一标题的任务。","按冻结契约核对新增、完成或刷新后的结果。"],duration_ms=int((time.perf_counter()-started)*1000))


class TodoAdapter:
    key = "todomvc"
    label = "TodoMVC（官方开源任务管理示例）"
    supported_kinds = frozenset({"todo_add", "todo_complete", "todo_persists"})
    supported_scenarios = frozenset({"upstream", "healthy", "environment_down"})

    def prepare(self, run_id):
        pass  # Every browser context starts with independent local storage.

    def create_executor(self, run: Run, origin, client):
        return TodoExecutor(run, origin, client)
