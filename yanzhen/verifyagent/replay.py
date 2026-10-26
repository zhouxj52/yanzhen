"""Minimize trusted planned actions with frozen setup/probes kept explicit and fixed."""
from __future__ import annotations

import asyncio
import time

from ..reproduce import Trial, minimize
from ..store import write_json
from .schema import Action, Bundle, Run, RunInput, digest
from .repository import path, load_run, load_target, save_run, event
from .executor import ToolExecutor
from .engine import execute
from .exports import export


def trusted_actions(run: Run, contract_id: str):
    actions=[]
    evidence={e.evidence_id:e for e in run.evidence}
    for row in run.trace:
        if row["contract_id"] != contract_id:continue
        action=Action.model_validate(row["action"])
        proof=evidence.get(row["evidence_id"])
        if proof is None or proof.content_hash != digest(proof.model_dump(exclude={"content_hash"})) or row["action_digest"] != digest(action) or proof.provenance.get("action_digest") != digest(action):
            raise ValueError("Trusted trace/evidence binding is invalid; caller strings cannot witness execution")
        actions.append(action)
    if len({a.id for a in actions}) != len(actions):
        raise ValueError("Duplicate action identifiers in trusted trace")
    return actions


async def reduce_run(identifier: str, contract_id: str, *, confirmed: bool, budget=12):
    original=load_run(identifier)
    if original.status != "completed" or not confirmed:
        raise ValueError("Replay requires a completed run and explicit repeated-action approval")
    failure=next((r for r in original.results if r["contract_id"]==contract_id and r["verdict"]=="fail"),None)
    if not failure:raise ValueError("No witnessed failure to minimize")
    target=load_target(original.target_id)
    actions=trusted_actions(original,contract_id)
    if any(ToolExecutor.needs_approval(a) for a in actions) and not target.namespace_header:
        raise ValueError("Mutating replay requires a declared fresh-backend namespace protocol")
    if not 4 <= budget <= 24:raise ValueError("Replay budget must be 4..24")
    frozen=Bundle.model_validate_json((path("runs",identifier)/"contract.json").read_text(encoding="utf-8"))
    frozen.assert_frozen()
    if len(frozen.contracts) != 1:
        raise ValueError("This replay slice requires one contract per bundle; multi-contract planning remains supported")
    contract=next(c for c in frozen.contracts if c.id==contract_id)
    # Keep the whole frozen bundle. Other contract checks are explicit regression/setup cost.
    mapping={a.id:a for a in actions}
    trial_ids=[]
    started=time.monotonic()

    async def evaluate(ids):
        trial=Run(bundle_id=frozen.id,target_id=target.id,contract_digest=frozen.digest,planner="manual",parent_run=original.id)
        write_json(path("runs",trial.id)/"contract.json",frozen.model_dump(mode="json"))
        request=RunInput(bundle_id=frozen.id,planner="manual",manual_actions=[mapping[k] for k in ids],max_seconds=20)
        save_run(trial);trial_ids.append(trial.id)
        async def scoped_approval(run,action):
            if action.id not in mapping or digest(mapping[action.id]) != digest(action):
                raise ValueError("Replay proposed a new or modified action")
            return True  # Explicit confirmed repeated-action approval above, not model consent.
        report=await execute(trial,request,scoped_approval)
        result=next((r for r in report.results if r['contract_id']==contract_id),{})
        outcome="reproduced" if report.status=="completed" and result.get('verdict')=='fail' else "blocked" if report.status!='completed' or result.get('verdict') in {'blocked','unclear'} else "not_reproduced"
        return Trial(outcome,result.get('fingerprint',''),[{"run_id":trial.id,"verdict":result.get('verdict'),"contract_digest":report.contract_digest}])

    event(original,"minimize","Replaying the executor-authored action trace with a frozen oracle",contract_id=contract_id)
    async with asyncio.timeout(180):
        result=await minimize([a.id for a in actions],evaluate,failure['fingerprint'],budget=budget,confirmations=2)
    result.update(contract_id=contract_id,source_run=original.id,source_trace_hash=digest(original.trace),trial_run_ids=trial_ids,
                  original_planned_steps=len(actions),reduced_planned_steps=len(result['steps']),replays=len(result['trials']),
                  elapsed_ms=round((time.monotonic()-started)*1000),actions=[mapping[k].model_dump(mode='json') for k in result['steps']],
                  fixed_probe_count=len(contract.probes),scope="Only planned actions are deleted. Frozen precondition, checkpoint and final probes remain part of every trial; they are not included in planned-step counts.",
                  backend_isolation=target.isolation_note)
    original.reproductions.append(result)
    for trial_id in trial_ids:
        original.graph['nodes'].append({'id':trial_id,'node_type':'replay','run_id':trial_id})
        if any(o.get('run_id')==trial_id for t in result['trials'] if t.get('matched') for o in t.get('observations',[])):
            original.graph['edges'].append({'source':trial_id,'target':contract_id,'relation':'reproduces'})
    save_run(original);export(original)
    return result
