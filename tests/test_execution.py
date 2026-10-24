import asyncio
import io
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from yanzhen.app import app, allowed_artifact
from yanzhen.engine import create_run, execute, sanitize_trace
from yanzhen.models import AnalyzeRequest, DEFAULT_REQUIREMENTS, Run, RunRequest
from yanzhen.planner import analyze
from yanzhen.store import freeze_bundle, run_dir, save_bundle, save_run


@pytest.mark.parametrize("scenario,failed", [
    ("healthy", set()),
    ("broken", {"foreign_record", "approved_locked", "save_persists"}),
    ("auth_bug", {"foreign_record"}),
    ("state_bug", {"approved_locked"}),
    ("persistence_bug", {"save_persists"}),
    ("locator_drift", set()),
])
def test_fixture_variants_are_detected_from_actual_responses(scenario, failed):
    async def run():
        bundle = await analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS))
        save_bundle(bundle)
        freeze_bundle(bundle.id, bundle.digest)
        task = create_run(RunRequest(bundle_id=bundle.id, scenario=scenario, browser=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            return await execute(task.id, "http://fixture", client)
    report = asyncio.run(run())
    assert report.status == "completed"
    assert {r.kind for r in report.results if r.verdict == "fail"} == failed
    assert not any(r.verdict in {"blocked", "unclear"} for r in report.results)
    assert all(r.evidence for r in report.results)
    with zipfile.ZipFile(run_dir(report.id) / "evidence.zip") as archive:
        assert {"contract.json", "report.json", "replay.py"}.issubset(archive.namelist())
        assert "demo.sqlite" not in archive.namelist()


def test_unavailable_environment_is_blocked_not_a_product_defect():
    async def run():
        bundle = await analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS))
        save_bundle(bundle)
        freeze_bundle(bundle.id, bundle.digest)
        task = create_run(RunRequest(bundle_id=bundle.id, scenario="environment_down", browser=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            return await execute(task.id, "http://fixture", client)
    report = asyncio.run(run())
    assert report.summary() == {"pass": 0, "fail": 0, "blocked": 5, "unclear": 0}


def test_execution_requires_a_frozen_contract():
    bundle = asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    save_bundle(bundle)
    with pytest.raises(ValueError, match="冻结"):
        create_run(RunRequest(bundle_id=bundle.id, browser=False))


def test_private_database_and_arbitrary_files_cannot_be_exported():
    assert not allowed_artifact("demo.sqlite")
    assert not allowed_artifact("../.env")
    assert not allowed_artifact("trace-admin.zip/../demo.sqlite")
    with TestClient(app) as client:
        response = client.get('/api/runs/' + 'a'*32 + '/artifacts/demo.sqlite')
        assert response.status_code == 404


def test_trace_resources_redact_tokens(tmp_path):
    path = tmp_path / "trace.zip"
    secret = "synthetic-session-secret"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("trace.network", '{"Authorization":"Bearer '+secret+'"}')
        archive.writestr("resources/login.json", '{"token":"'+secret+'"}')
    sanitize_trace(path, {secret})
    with zipfile.ZipFile(path) as archive:
        assert all(secret.encode() not in archive.read(name) for name in archive.namelist())


def test_missing_evidence_package_never_claims_success_or_hangs():
    run = Run(id="e"*32, bundle_id="c"*32, digest="test", scenario="healthy", browser_requested=False, status="completed")
    save_run(run)

    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            response = await client.get('/api/runs/' + run.id)
            assert response.status_code == 200
            assert response.json()["status"] == "error"
            assert "evidence.zip" not in response.json()["artifacts"]
    asyncio.run(read())


def test_trace_without_a_redaction_marker_is_not_downloadable():
    run = Run(id="f"*32, bundle_id="c"*32, digest="test", scenario="healthy", browser_requested=False, status="completed")
    save_run(run)
    (run_dir(run.id) / "trace-alice.zip").write_bytes(b"not yet redacted")
    (run_dir(run.id) / "evidence.zip").write_bytes(b"fixture")
    with TestClient(app) as client:
        response = client.get('/api/runs/' + run.id + '/artifacts/trace-alice.zip')
        assert response.status_code == 404
