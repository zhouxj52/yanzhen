from __future__ import annotations

import asyncio
import uuid

import httpx

from .adapters import get_adapter
from .models import Bundle, Run, RunRequest, now
from .store import load_bundle, load_run, run_dir, save_run, write_json

from .runtime import cleanup, event
from .exports import make_export, sanitize_trace
from .verifier import conflicts_for
from .reproduce import reproduce_failures


def create_run(request: RunRequest, parent: str | None = None) -> Run:
    bundle = load_bundle(request.bundle_id)
    bundle.assert_frozen()
    adapter = get_adapter(request.target)
    supported_scenarios = getattr(adapter, "supported_scenarios", None)
    if (supported_scenarios is not None and request.scenario not in supported_scenarios) or (request.target == "reimbursement" and request.scenario == "upstream"):
        raise ValueError("目标不支持该场景")
    unsupported = {c.kind for c in bundle.contracts if c.kind != "unclear"} - adapter.supported_kinds
    if unsupported:
        raise ValueError("目标适配器不支持契约类型：" + ", ".join(sorted(unsupported)))
    run = Run(id=uuid.uuid4().hex, bundle_id=bundle.id, digest=bundle.digest, scenario=request.scenario, browser_requested=request.browser, parent_run=parent, target=request.target)
    if request.target == "todomvc":
        run.target_source = {"repository":"https://github.com/tastejs/todomvc","revision":"ff43b02e59dfa604386bb382034b2cd07c2bcd8a","example":"examples/javascript-es6/src","variant":"local_persistence_repair" if request.scenario=="healthy" else "upstream_business_logic","loading_adaptation":"Browser ES modules and local presentation CSS; business source hashes in third_party/todomvc/SOURCE.json"}
    save_run(run)
    try:
        write_json(run_dir(run.id) / "contract.json", bundle.model_dump(mode="json"))
        adapter.prepare(run.id)
    except Exception as exc:
        run.status = "error"
        run.error = "目标准备失败：" + type(exc).__name__
        run.finished_at = now()
        save_run(run)
        raise ValueError(run.error) from exc
    return run


async def execute(run_id: str, origin: str, client: httpx.AsyncClient | None = None) -> Run:
    run = load_run(run_id)
    run.status = "running"
    event(run, "contract", "验证冻结契约与内容摘要")
    playwright = None
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False)
    executor = get_adapter(run.target).create_executor(run, origin, client)
    outcome = "completed"
    try:
        bundle = Bundle.model_validate_json((run_dir(run.id) / "contract.json").read_text(encoding="utf-8"))
        bundle.assert_frozen()
        if run.digest != bundle.digest:
            raise ValueError("运行摘要与冻结契约不一致")
        if run.browser_requested:
            try:
                from playwright.async_api import async_playwright
                playwright = await async_playwright().start()
                executor.browser = await playwright.chromium.launch(headless=True)
                event(run, "browser", "Chromium 已启动，测试身份使用独立浏览器会话")
            except Exception as exc:
                executor.browser_error = f"浏览器未就绪：{type(exc).__name__}。请运行安装脚本。"
                event(run, "browser", executor.browser_error)
        for contract in bundle.contracts:
            event(run, "execute", f"开始检查：{contract.title}")
            result = await executor.check(contract)
            result.conflicts = conflicts_for(result)
            run.results.append(result)
            event(run, "verify", f"{contract.id} → {result.verdict.value}: {result.summary}")
        await reproduce_failures(run, bundle, executor, origin, client)
        run.status = "finalizing"
        event(run, "finalizing", "检查结束，正在整理证据")
    except asyncio.CancelledError:
        outcome = "cancelled"
        run.status = "finalizing"
        event(run, "cancel", "取消已接受，正在整理已完成结果")
    except Exception as exc:
        outcome = "error"
        run.status = "finalizing"
        run.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        event(run, "error", "执行异常，正在保留已有证据")
    finally:
        if executor.browser:
            for role, page in executor.pages.items():
                written = await cleanup(page.context.tracing.stop(path=str(run_dir(run.id) / f"trace-{role}.zip")), run, f"{role} trace 写入")
                if written:
                    sanitize_trace(run_dir(run.id) / f"trace-{role}.zip", executor.redactions)
                    (run_dir(run.id) / f"trace-{role}.safe").write_text("redacted", encoding="utf-8")
            await cleanup(executor.browser.close(), run, "浏览器关闭")
        if playwright:
            await cleanup(playwright.stop(), run, "浏览器驱动关闭")
        if owned_client:
            await client.aclose()
        run.finished_at = now()
        run.status = outcome
        make_export(run, origin)
        save_run(run)
    return run
