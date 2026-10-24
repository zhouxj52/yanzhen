import asyncio
import json
import uuid
import zipfile

import pytest

from yanzhen import adapters
from yanzhen.adapters import get_adapter, list_adapters, register_adapter
from yanzhen.engine import create_run
from yanzhen.exports import make_export, verify_evidence
from yanzhen.jobs import QueueFullError, RunManager
from yanzhen.models import AnalyzeRequest, DEFAULT_REQUIREMENTS, Run, RunRequest, now
from yanzhen.planner import analyze
from yanzhen.store import freeze_bundle, load_run, run_dir, save_bundle, save_run


def frozen_request():
    bundle = asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    save_bundle(bundle)
    freeze_bundle(bundle.id, bundle.digest)
    return RunRequest(bundle_id=bundle.id, browser=False)


def test_unknown_or_incompatible_target_is_rejected_before_execution(monkeypatch):
    request = frozen_request()
    with pytest.raises(ValueError, match="未知目标"):
        create_run(request.model_copy(update={"target": "not-registered"}))

    class Limited:
        key = "limited"
        label = "Test target"
        supported_kinds = frozenset({"own_record"})

    monkeypatch.setattr(adapters, "_adapters", dict(adapters._adapters))
    register_adapter(Limited())
    with pytest.raises(ValueError, match="不支持契约"):
        create_run(request.model_copy(update={"target": "limited"}))
    with pytest.raises(ValueError, match="已注册"):
        register_adapter(Limited())


def test_target_preparation_failure_does_not_leave_an_orphan_queue_item(monkeypatch):
    from yanzhen.models import CATALOG
    from yanzhen.store import list_runs

    class BrokenTarget:
        key = "setup-failure"
        label = "Setup failure"
        supported_kinds = frozenset(CATALOG)

        def prepare(self, run_id):
            raise RuntimeError("fixture could not be prepared")

    request = frozen_request()
    monkeypatch.setattr(adapters, "_adapters", dict(adapters._adapters))
    register_adapter(BrokenTarget())
    with pytest.raises(ValueError, match="目标准备失败"):
        create_run(request.model_copy(update={"target": "setup-failure"}))
    records = list_runs()
    assert len(records) == 1 and records[0]["status"] == "error"


def test_queue_limit_cancellation_and_terminal_state():
    request = frozen_request()

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        counts = {"active": 0, "maximum": 0}

        async def worker(identifier, origin):
            run = load_run(identifier)
            run.status = "running"
            save_run(run)
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
            entered.set()
            try:
                await release.wait()
                run.status = "completed"
                run.finished_at = now()
                make_export(run, origin)
                save_run(run)
                return run
            finally:
                counts["active"] -= 1

        manager = RunManager("http://fixture", concurrency=1, capacity=2, runner=worker)
        first = manager.start(request)
        second = manager.start(request)
        with pytest.raises(QueueFullError):
            manager.start(request)
        await entered.wait()
        assert load_run(second.id).status == "queued"
        queued_task = manager._tasks[second.id]
        manager.cancel(second.id)
        await asyncio.gather(queued_task, return_exceptions=True)
        await asyncio.sleep(0)
        assert load_run(second.id).status == "cancelled"
        assert not load_run(second.id).results
        running_task = manager._tasks[first.id]
        manager.cancel(first.id)
        await asyncio.gather(running_task, return_exceptions=True)
        await asyncio.sleep(0)
        assert load_run(first.id).status == "cancelled"
        assert counts["maximum"] == 1
        with pytest.raises(ValueError, match="已经结束"):
            manager.cancel(first.id)
        assert verify_evidence(run_dir(second.id) / "evidence.zip")["valid"]
        await manager.shutdown()

    asyncio.run(scenario())


def test_restart_recovers_active_jobs_older_than_the_history_page():
    identifiers = []
    for index in range(56):
        run = Run(id=uuid.uuid4().hex, bundle_id="a"*32, digest="test", scenario="healthy", browser_requested=False,
                  status="running" if index == 0 else "completed")
        save_run(run)
        identifiers.append(run.id)
    manager = RunManager("http://fixture")
    assert manager.recover() == 1
    recovered = load_run(identifiers[0])
    assert recovered.status == "error" and recovered.finished_at
    assert manager.recover() == 0


def test_completed_archive_has_terminal_report_and_detects_tampering():
    run = create_run(frozen_request())
    run.status = "completed"
    make_export(run, "http://fixture")
    path = run_dir(run.id) / "evidence.zip"
    assert verify_evidence(path)["valid"]
    with zipfile.ZipFile(path) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
        assert json.loads(content["report.json"])["status"] == "completed"
    content["report.json"] = b'{"status":"tampered"}'
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in content.items():
            archive.writestr(name, payload)
    result = verify_evidence(path)
    assert not result["valid"] and any("report.json" in error for error in result["errors"])


def test_missing_or_extra_archive_members_fail_integrity():
    run = create_run(frozen_request())
    make_export(run, "http://fixture")
    path = run_dir(run.id) / "evidence.zip"
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("unexpected.txt", b"extra")
    assert not verify_evidence(path)["valid"]


def test_corrupt_archive_is_reported_as_invalid(tmp_path):
    path = tmp_path / "bad.zip"
    path.write_bytes(b"broken archive")
    assert not verify_evidence(path)["valid"]


def test_report_download_is_the_archived_snapshot_not_the_live_api_view():
    from fastapi.testclient import TestClient
    from yanzhen.app import app

    run = create_run(frozen_request())
    run.status = "completed"
    make_export(run, "http://fixture")
    save_run(run)
    with zipfile.ZipFile(run_dir(run.id) / "evidence.zip") as archive:
        original = archive.read("report.json")
    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run.id}/artifacts/report.json")
        assert response.status_code == 200
        assert response.content == original


def test_auxiliary_screenshot_failure_does_not_erase_a_proven_defect():
    import httpx
    from yanzhen.app import app
    from yanzhen.adapters.reimbursement import Executor
    from yanzhen.planner import offline_contracts

    run = create_run(frozen_request().model_copy(update={"scenario": "auth_bug"}))
    run.browser_requested = True
    save_run(run)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            executor = Executor(run, "http://fixture", client)
            executor.browser = object()

            async def unavailable_page(role):
                raise RuntimeError("screenshot tool unavailable")

            executor.page = unavailable_page
            result = await executor.check(next(c for c in offline_contracts(DEFAULT_REQUIREMENTS) if c.kind == "foreign_record"))
            assert result.verdict == "fail"
            assert any(e.data.get("capture_error") == "RuntimeError" for e in result.evidence)

    asyncio.run(scenario())


def test_registered_executor_runs_without_preparing_the_builtin_demo(monkeypatch):
    from yanzhen.engine import execute
    from yanzhen.models import CheckResult, Evidence

    class CustomExecutor:
        browser = None
        browser_error = None
        pages = {}
        redactions = set()

        async def check(self, contract):
            return CheckResult(contract_id=contract.id, kind=contract.kind, title=contract.title,
                               verdict="pass", summary="custom target checked",
                               evidence=[Evidence(id="custom-observation", kind="observation", description="Custom target evidence")])

    class CustomTarget:
        key = "custom-test"
        label = "Custom target test double"
        supported_kinds = frozenset({"own_record"})

        def prepare(self, run_id):
            (run_dir(run_id) / "custom-prepared.txt").write_text("prepared")

        def create_executor(self, run, origin, client):
            assert (run_dir(run.id) / "custom-prepared.txt").exists()
            return CustomExecutor()

    monkeypatch.setattr(adapters, "_adapters", dict(adapters._adapters))
    register_adapter(CustomTarget())
    bundle = asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    bundle.contracts = [bundle.contracts[0]]
    bundle.digest = bundle.calculate_digest()
    save_bundle(bundle)
    freeze_bundle(bundle.id, bundle.digest)
    run = create_run(RunRequest(bundle_id=bundle.id, target="custom-test", browser=False))
    result = asyncio.run(execute(run.id, "http://fixture"))
    assert result.status == "completed" and result.summary()["pass"] == 1
    assert not (run_dir(run.id) / "demo.sqlite").exists()
    assert verify_evidence(run_dir(run.id) / "evidence.zip")["valid"]
