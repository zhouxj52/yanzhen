from __future__ import annotations

from contextlib import asynccontextmanager
import os
import re

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__
from .demo import router as demo_router
from .adapters import list_adapters
from .exports import verify_evidence
from .jobs import QueueFullError, RunManager
from .models import AnalyzeRequest, CATALOG, DEFAULT_REQUIREMENTS, RunRequest, SCENARIOS, TODO_REQUIREMENTS, TODO_SCENARIOS, Bundle, Contract
from .guard import ExecutionPlan, review_execution_repair
from .todo_server import router as todo_router
from .planner import analyze
from .settings import ROOT, initialize, model_config
from .store import freeze_bundle, list_runs, load_bundle, load_run, report_bytes, run_dir, safe_id, save_bundle


def create_app() -> FastAPI:
    initialize()
    from .verifyagent.service import VerifyService
    from .verifyagent.api import router as verify_router
    verify_service = VerifyService()
    manager = RunManager(f"http://127.0.0.1:{os.getenv('YZ_PORT', '8765')}")

    @asynccontextmanager
    async def lifespan(app):
        manager.recover()
        verify_service.recover()
        yield
        await verify_service.close()
        await manager.shutdown()

    app = FastAPI(title="验真 · 软件验收工作台", version=__version__, lifespan=lifespan)
    app.state.jobs = manager
    app.state.verify_jobs = verify_service
    app.include_router(verify_router(verify_service))
    app.include_router(demo_router)
    app.include_router(todo_router)
    app.mount("/static", StaticFiles(directory=ROOT / "yanzhen" / "web"), name="static")

    def launch(request, parent=None):
        try:
            return manager.start(request, parent).model_dump(mode="json")
        except QueueFullError as exc:
            raise HTTPException(429, str(exc)) from None

    def report(identifier: str) -> dict:
        run = load_run(identifier)
        data = run.model_dump(mode="json")
        data["summary"] = run.summary()
        directory = run_dir(identifier)
        ready = (directory / "evidence.zip").is_file()
        if run.status == "completed" and not ready:
            data["status"] = "error"
            data["error"] = "证据包缺失，不能确认完整交付，请重新运行。"
        data["execution"] = {"target": run.target, "completed_checks": len(run.results)}
        data["artifacts"] = [p.name for p in directory.iterdir() if allowed_artifact(p.name) and (ready or p.name in {"report.json", "contract.json"}) and (not p.name.startswith("trace-") or p.with_suffix(".safe").exists())]
        if run.parent_run and data["status"] == "completed":
            original = load_run(run.parent_run)
            old = {r.contract_id: r.verdict for r in original.results}
            new = {r.contract_id: r.verdict for r in run.results}
            blocked = any(v.value in {"blocked", "unclear"} for v in new.values())
            data["replay_comparison"] = {
                "matches": original.status == "completed" and old == new and not blocked and run.digest == original.digest,
                "original_run": original.id,
                "fresh_fixture": True,
                "original_verdicts": old, "replayed_verdicts": new,
            }
        return data

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "指定的契约、运行或证据不存在"})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        detail = "输入或模型输出不符合验收契约格式" if isinstance(exc, ValidationError) else str(exc)
        payload={"detail":detail}
        if isinstance(exc,ValidationError):payload['validation_errors']=exc.errors(include_input=False,include_context=False)
        return JSONResponse(status_code=422, content=payload)

    @app.get("/")
    def index():
        return FileResponse(ROOT / "yanzhen" / "web" / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "scope": "local_reimbursement_and_todomvc"}

    @app.get("/api/config")
    def config():
        model = model_config()
        providers = {}
        for name, label in (("qwen","Qwen"),("deepseek","DeepSeek")):
            item = model_config(name)
            providers[name] = {"label":label,"model":item["model"],"enabled":item["enabled"],
                               "configured":item["enabled"] and (bool(item["key"]) or item["allow_no_key"])}
        return {"default_requirements": DEFAULT_REQUIREMENTS, "catalog": CATALOG, "scenarios": SCENARIOS,
                "model": model["model"], "model_enabled": model["enabled"], "model_configured": model["enabled"] and (bool(model["key"]) or model["allow_no_key"]),
                "providers":providers,
                "targets": {"reimbursement":{"label":"团队报销系统","requirements":DEFAULT_REQUIREMENTS,"scenarios":SCENARIOS}, "todomvc":{"label":"TodoMVC 官方开源任务管理示例","requirements":TODO_REQUIREMENTS,"scenarios":TODO_SCENARIOS}},
                "scope": "适配内置报销系统与固定版本 TodoMVC；不代表支持任意网站。"}

    @app.get("/api/targets")
    def targets():
        return list_adapters()

    @app.post("/api/analyze")
    async def plan(request: AnalyzeRequest):
        try:
            bundle = await analyze(request)
        except Exception as exc:
            import httpx
            if isinstance(exc, httpx.HTTPError):
                raise HTTPException(502, "模型接口连接失败；未自动切换为离线结果。")
            raise
        save_bundle(bundle)
        return bundle.model_dump(mode="json")

    @app.get("/api/bundles/{identifier}")
    def get_bundle(identifier: str):
        return load_bundle(identifier).model_dump(mode="json")

    @app.post("/api/bundles/{identifier}/freeze")
    def freeze(identifier: str, request: dict = Body(...)):
        return freeze_bundle(identifier, str(request.get("digest", ""))).model_dump(mode="json")

    @app.post("/api/runs")
    async def run(request: RunRequest):
        return launch(request)

    @app.get("/api/runs")
    def history():
        return list_runs()

    @app.get("/api/runs/{identifier}")
    def get_run(identifier: str):
        return report(identifier)

    @app.post("/api/runs/{identifier}/cancel", status_code=202)
    async def cancel(identifier: str):
        try:
            manager.cancel(identifier)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"id": identifier, "cancel_requested": True}

    @app.get("/api/runs/{identifier}/integrity")
    def integrity(identifier: str):
        path = run_dir(identifier) / "evidence.zip"
        if not path.is_file():
            raise HTTPException(409, "证据包尚未生成")
        return verify_evidence(path)

    @app.post("/api/runs/{identifier}/replay")
    async def replay(identifier: str):
        original = load_run(identifier)
        if original.status != "completed":
            raise HTTPException(409, "原运行尚未完成，无法重放")
        frozen_path = run_dir(identifier) / "contract.json"
        from .models import Bundle
        original_bundle = Bundle.model_validate_json(frozen_path.read_text(encoding="utf-8"))
        original_bundle.assert_frozen()
        current = load_bundle(original.bundle_id)
        current.assert_frozen()
        if current.digest != original_bundle.digest:
            raise HTTPException(409, "原契约已更改，拒绝重放")
        request = RunRequest(bundle_id=original.bundle_id, target=original.target, scenario=original.scenario, browser=original.browser_requested)
        return launch(request, parent=original.id)

    def archived_contract(identifier, contract_id):
        run = load_run(identifier)
        bundle = Bundle.model_validate_json((run_dir(identifier) / "contract.json").read_text(encoding="utf-8"))
        bundle.assert_frozen()
        if run.digest != bundle.digest:
            raise ValueError("运行摘要与冻结契约不一致")
        contract = next((c for c in bundle.contracts if c.id == contract_id),None)
        if contract is None:
            raise HTTPException(404,"契约不存在")
        return run, contract

    @app.post("/api/runs/{identifier}/repair-review/{contract_id}")
    def repair_review(identifier: str, contract_id: str, request: dict = Body(...)):
        run, contract = archived_contract(identifier,contract_id)
        result=next((r for r in run.results if r.contract_id==contract_id),None)
        witness=next((e.data.get('business_action','') for e in (result.evidence if result else []) if e.kind=='observation' and e.data.get('executor') in {'reimbursement','todomvc'} and e.data.get('role')==contract.role and e.data.get('business_action')==contract.kind),'')
        review=review_execution_repair(contract,ExecutionPlan.model_validate(request.get("original",{})),ExecutionPlan.model_validate(request.get("candidate",{})),witness)
        review['scope']='归档执行器见证的受限计划审查；忽略调用方 witnessed_action，不自动应用候选'
        return review

    @app.post("/api/runs/{identifier}/reproduce/{contract_id}")
    async def reproduce(identifier: str, contract_id: str):
        import asyncio
        import httpx
        from .reproduce import reimbursement_trial, todo_trial
        run, contract = archived_contract(identifier,contract_id)
        recipe = next((r for r in run.reproductions if r["contract_id"] == contract_id and r["status"] == "verified"),None)
        if run.status != "completed" or recipe is None:
            raise HTTPException(409,"没有经过验证的精简复现步骤")
        browser = driver = None
        async with manager._semaphore:
            try:
                async with asyncio.timeout(30):
                    async with httpx.AsyncClient(timeout=10,trust_env=False) as client:
                        if run.target == "todomvc":
                            from playwright.async_api import async_playwright
                            driver = await async_playwright().start()
                            browser = await driver.chromium.launch(headless=True)
                            trial = await todo_trial(run,contract,recipe["steps"],manager.origin,browser)
                        else:
                            trial = await reimbursement_trial(run,contract,recipe["steps"],manager.origin,client)
                        return {**trial.payload(),"matches":trial.outcome == "reproduced" and trial.fingerprint == recipe["fingerprint"],"contract_digest":run.digest,"steps":recipe["steps"]}
            except TimeoutError:
                raise HTTPException(504,"精简步骤复现超时") from None
            finally:
                if browser:
                    await browser.close()
                if driver:
                    await driver.stop()

    @app.get("/api/runs/{identifier}/artifacts/{filename}")
    def artifact(identifier: str, filename: str):
        safe_id(identifier)
        if not allowed_artifact(filename):
            raise HTTPException(404, "该文件不属于可导出证据")
        path = run_dir(identifier) / filename
        if not path.is_file():
            raise HTTPException(404, "证据尚未生成")
        if filename not in {"report.json", "contract.json"} and not (run_dir(identifier) / "evidence.zip").is_file():
            raise HTTPException(409, "证据仍在写入，完成后即可导出")
        if filename.startswith("trace-") and not path.with_suffix(".safe").exists():
            raise HTTPException(404, "该 trace 未完成脱敏，不能导出")
        if filename == "report.json":
            from fastapi.responses import Response
            return Response(report_bytes(identifier), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="report.json"'})
        return FileResponse(path, filename=filename)

    return app


def allowed_artifact(name: str) -> bool:
    return name in {"report.json", "contract.json", "manifest.json", "evidence.zip", "replay.py", "reproduce.py", "reproduction.json", "README.md"} or bool(re.fullmatch(r"[A-Za-z0-9_-]{1,60}\.png|trace-(alice|bob|admin)\.zip", name))


app = create_app()
