"""Observe -> Plan -> Act -> Verify -> Replan, with persisted human approvals."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

from .schema import Action, Bundle, Run, RunInput, now, digest
from .repository import path, load_bundle, load_target, save_run, event
from .executor import ToolExecutor
from .security import TargetPolicy
from .planning import ManualPlanner, ModelClient, ModelPlanner
from .oracle import decide, evaluate, evidence_graph, operation_gaps


async def execute(run: Run, request: RunInput, approve: Callable, *, planner=None):
    bundle = Bundle.model_validate_json((path("runs", run.id) / "contract.json").read_text(encoding="utf-8"))
    bundle.assert_frozen()
    target = load_target(run.target_id)
    executor = ToolExecutor(target, run, TargetPolicy(target))
    model = ModelClient(request.planner, max_calls=request.max_model_calls) if request.planner != "manual" else None
    planner = planner or (ModelPlanner(model,target) if model else ManualPlanner(request.manual_actions))
    run.status = "running"
    started = time.monotonic()
    try:
        async with asyncio.timeout(request.max_seconds):
            for contract in bundle.contracts:
                bundle.assert_frozen()
                executor.current_contract = contract.id
                event(run, "observe", "Collecting actual target state", contract_id=contract.id)
                observations, invariant_results = {}, []

                async def collect(phase, kind=None):
                    for probe in contract.probes:
                        if probe.phase == phase or (phase == "checkpoint" and probe.phase == "always"):
                            if phase == "checkpoint" and probe.phase == "checkpoint" and probe.after_action != kind:
                                continue
                            evidence = await executor.probe(probe)
                            observations[probe.id] = evidence
                    if phase in {"always", "checkpoint"}:
                        invariant_results.extend(evaluate(p, observations) for p in contract.invariants)

                await collect("before")
                await collect("always")
                prerequisites = [evaluate(p, observations, prerequisite=True) for p in contract.preconditions]
                if any(p["verdict"] != "pass" for p in prerequisites):
                    run.results.append({"contract_id":contract.id,"title":contract.title,"verdict":"blocked","assertions":prerequisites,"reason":"Preconditions are not established","fingerprint":""})
                    event(run, "verify", "Preconditions blocked execution", contract_id=contract.id)
                    continue
                seen = set()
                finished = False
                completion_feedback = None
                for _ in range(contract.constraints.max_steps):
                    bundle.assert_frozen()
                    # Also check the persisted version, not only the in-memory object.
                    current = load_bundle(bundle.id)
                    current.assert_frozen()
                    if current.digest != run.contract_digest:
                        raise ValueError("Frozen contract changed during execution")
                    trace = [r for r in run.trace if r["contract_id"] == contract.id]
                    observation = await executor.observe(trace[-1]['action']['actor'] if trace else 'anonymous')
                    if completion_feedback:
                        observation['verification_feedback']=completion_feedback
                    event(run, "plan", "Planning from fresh observations", contract_id=contract.id)
                    decision = await planner.next(contract, observation, trace)
                    event(run, "plan", executor.redact(decision.explanation), contract_id=contract.id, decision=executor.redact(decision.model_dump(mode="json")))
                    if decision.finished:
                        gaps=operation_gaps(contract,trace,target)
                        if gaps and not isinstance(planner,ManualPlanner):
                            completion_feedback={'status':'blocked','reason':'Cannot finish with unwitnessed frozen action constraints; do not change the contract','remaining_operation_obligations':gaps}
                            event(run,'replan','Independent verification found missing required operations',contract_id=contract.id,verification_feedback=completion_feedback)
                            continue
                        finished = True
                        break
                    action = decision.action
                    if action.id in seen:
                        raise ValueError("Planner repeated an action identifier")
                    if action.kind in contract.constraints.forbidden_actions:
                        raise ValueError("Planner proposed an action forbidden by the frozen contract")
                    if not set(action.depends_on) <= {r["action"]["id"] for r in trace if r["ok"]}:
                        raise ValueError("Action dependencies have not been established")
                    seen.add(action.id)
                    approved = False
                    if executor.needs_approval(action):
                        approved = await approve(run, action)
                    event(run, "act", "Executing a bounded tool action", contract_id=contract.id, action=executor.redact(action.model_dump(mode="json")))
                    row = await executor.act(action, approved)
                    await collect("checkpoint", action.kind)
                    event(run, "replan" if not row["ok"] else "observe", "Tool failed; next decision will receive actual error" if not row["ok"] else "Tool action completed", contract_id=contract.id, action_id=action.id, ok=row["ok"])
                await collect("after")
                await collect("always")
                trace = [r for r in run.trace if r["contract_id"] == contract.id]
                result = decide(contract, observations, trace, invariant_results,target=target)
                if not finished:
                    # A partial exploration is not a completed verification.
                    result.update(verdict="blocked", reason="Execution step budget exhausted before the planner finished", fingerprint="")
                run.results.append(result)
                event(run, "verify", "Independent oracle: " + result["verdict"], contract_id=contract.id)
            run.status = "completed"
    except asyncio.CancelledError:
        run.status, run.error = "cancelled", "Execution cancelled; unfinished checks have no acceptance verdict"
    except Exception as exc:
        run.status, run.error = "error", executor.redact(type(exc).__name__ + ": " + str(exc))[:800]
        for contract in bundle.contracts:
            if not any(r['contract_id']==contract.id for r in run.results):
                run.results.append({'contract_id':contract.id,'title':contract.title,'verdict':'blocked','assertions':[], 'fingerprint':'','reason':run.error})
        event(run, "error", run.error)
    finally:
        try:
            await asyncio.wait_for(executor.close(), timeout=10)
        except Exception as exc:
            event(run, "cleanup", "Cleanup incomplete: " + type(exc).__name__)
        run.pending_approval = None
        run.finished_at = now()
        run.graph = evidence_graph(run.evidence, run.results, run.trace)
        run.usage = model.usage() if model else {"calls":[],"prompt_tokens":0,"completion_tokens":0,"mode":"explicit_manual","estimated_cost_usd":0}
        run.usage["wall_time_ms"] = round((time.monotonic()-started)*1000)
        save_run(run)
        from .exports import export
        export(run)
    return run
