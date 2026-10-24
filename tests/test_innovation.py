import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from yanzhen.app import app, allowed_artifact
from yanzhen.engine import create_run, execute
from yanzhen.guard import ExecutionPlan, review_execution_repair
from yanzhen.models import AnalyzeRequest, DEFAULT_REQUIREMENTS, TODO_REQUIREMENTS, RunRequest
from yanzhen.planner import analyze
from yanzhen.reproduce import Trial, minimize
from yanzhen.store import freeze_bundle, list_runs, load_run, save_bundle


def test_minimization_reexecutes_and_requires_same_failure_and_confirmations():
    calls=[]
    async def evaluator(steps):
        calls.append(steps)
        if "write" not in steps:
            return Trial("invalid",reason="No write")
        if "read" not in steps:
            return Trial("reproduced","different-defect")
        return Trial("reproduced","lost-write",[{"actually_observed":True}])
    result=asyncio.run(minimize(["noise","write","read"],evaluator,"lost-write"))
    assert result["status"]=="verified"
    assert result["steps"]==["write","read"]
    assert result["confirmations"]==2
    assert calls[-2:]==[["write","read"],["write","read"]]
    assert any(t["outcome"]=="invalid" and not t["matched"] for t in result["trials"])
    assert any(t["fingerprint"]=="different-defect" and not t["matched"] for t in result["trials"])


def test_failed_baseline_or_unstable_confirmation_never_claims_verified():
    async def blocked(steps): return Trial("blocked",reason="Network unavailable")
    result=asyncio.run(minimize(["write","read"],blocked,"lost-write"))
    assert result["status"]=="unconfirmed"
    calls=0
    async def unstable(steps):
        nonlocal calls
        calls+=1
        return Trial("reproduced","failure") if calls==1 else Trial("not_reproduced")
    assert asyncio.run(minimize(["only"],unstable,"failure"))["status"]=="unstable"


@pytest.mark.parametrize("change",[{"role":"admin"},{"assertions":["always_pass"]},{"skip":True},{"action":"other-action"},{"contract_id":"OTHER"}])
def test_guard_rejects_semantic_changes(change):
    bundle=asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    contract=bundle.contracts[0]
    original=ExecutionPlan(contract_id=contract.id,role=contract.role,action="read-own",assertions=[contract.expected],locator="old")
    candidate=ExecutionPlan.model_validate({**original.model_dump(),**change})
    assert not review_execution_repair(contract,original,candidate,"read-own")["accepted"]


def test_guard_accepts_only_execution_changes_and_rejects_missing_assertions():
    bundle=asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    contract=bundle.contracts[0]
    original=ExecutionPlan(contract_id=contract.id,role=contract.role,action="read-own",assertions=[contract.expected],locator="old")
    candidate=original.model_copy(update={"locator":"new","wait_ms":200})
    assert review_execution_repair(contract,original,candidate,"read-own")["accepted"]
    assert not review_execution_repair(contract,original,candidate,"wrong-action")["accepted"]
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate({**original.model_dump(),"assertions":[]})


def test_persistence_conflict_and_reduction_are_based_on_actual_requests():
    async def scenario():
        bundle=await analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS))
        save_bundle(bundle)
        freeze_bundle(bundle.id,bundle.digest)
        run=create_run(RunRequest(bundle_id=bundle.id,scenario="persistence_bug",browser=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://fixture") as client:
            report=await execute(run.id,"http://fixture",client)
            assert len(list_runs())==1  # Internal experiments do not pollute real history.
            assert len(list_runs(include_internal=True))>1
            persistence=next(r for r in report.results if r.kind=="save_persists")
            assert persistence.conflicts[0]["rule"]=="write_ack_vs_readback"
            ids={e.id for e in persistence.evidence}
            assert set(persistence.conflicts[0]["evidence_ids"]) <= ids
            reduction=report.reproductions[0]
            assert reduction["status"]=="verified"
            assert reduction["steps"]==["保存唯一说明","重新查询记录"]
            assert reduction["confirmations"]==2
            assert all(t["observations"] for t in reduction["trials"] if t["matched"])
            for trial in list_runs(include_internal=True):
                assert load_run(trial["id"]).status=="completed"
    asyncio.run(scenario())


def test_target_contract_separation_and_upstream_restrictions():
    bundle=asyncio.run(analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc")))
    assert {c.kind for c in bundle.contracts}=={"todo_add","todo_complete","todo_persists"}
    save_bundle(bundle)
    freeze_bundle(bundle.id,bundle.digest)
    with pytest.raises(ValueError,match="不支持契约"):
        create_run(RunRequest(bundle_id=bundle.id,target="reimbursement"))
    with pytest.raises(ValueError,match="不支持该场景"):
        create_run(RunRequest(bundle_id=bundle.id,target="todomvc",scenario="auth_bug"))
    for name in ("reproduce.py","reproduction.json"):
        assert allowed_artifact(name)
    unknown=asyncio.run(analyze(AnalyzeRequest(requirements="任务不能新增或保存",target="todomvc")))
    assert all(c.kind=="unclear" for c in unknown.contracts)


def test_upstream_sources_are_pinned_and_unmodified():
    root=Path(__file__).resolve().parents[1]/"third_party"/"todomvc"
    manifest=json.loads((root/"SOURCE.json").read_text())
    assert len(manifest["revision"])==40
    for name,expected in manifest["sha256"].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected
    assert "Permission is hereby granted" in (root/"LICENSE").read_text()


def test_browser_required_target_does_not_fake_api_success():
    async def scenario():
        bundle=await analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc"))
        save_bundle(bundle)
        freeze_bundle(bundle.id,bundle.digest)
        run=create_run(RunRequest(bundle_id=bundle.id,target="todomvc",scenario="upstream",browser=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://fixture") as client:
            report=await execute(run.id,"http://fixture",client)
        assert report.summary()=={"pass":0,"fail":0,"blocked":3,"unclear":0}
        assert not report.reproductions
    asyncio.run(scenario())
