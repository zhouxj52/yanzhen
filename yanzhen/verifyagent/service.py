"""Bounded jobs, exact-action approvals and immutable run snapshots."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from ..store import write_json
from .schema import Run, RunInput, Action, digest, now
from .repository import path, load_bundle, load_target, load_run, save_run, list_runs, event
from .security import TargetPolicy


class VerifyService:
    def __init__(self):
        from .projects import ProjectPreviews
        self.previews = ProjectPreviews()
        from .challenges import ChallengeService
        self.challenges = ChallengeService(self)
        self.tasks = {}
        self.waiters = {}
        self.active = {}
        self.semaphore = asyncio.Semaphore(2)

    def recover(self):
        self.challenges.recover()
        for item in list_runs(limit=None):
            if item["status"] in {"queued", "running", "waiting_approval"}:
                run = load_run(item["id"])
                run.status, run.error, run.finished_at = "error", "Service restart interrupted the job; create a new run", now()
                run.pending_approval = None
                save_run(run)

    def start(self, request: RunInput):
        if len(self.tasks) >= 8:
            raise ValueError("Verification queue is full")
        bundle = load_bundle(request.bundle_id)
        bundle.assert_frozen()
        target_id = request.candidate_target_id or bundle.target_id
        target = load_target(target_id)
        TargetPolicy(target)
        if request.candidate_target_id and not request.parent_run:
            raise ValueError("A repair target must be tied to a completed original run")
        if request.parent_run:
            parent = load_run(request.parent_run)
            if parent.status != "completed" or parent.bundle_id != bundle.id or parent.contract_digest != bundle.digest:
                raise ValueError("Repair/replay must use the exact original frozen contract")
            previous_target=load_target(parent.target_id)
            if target.identities != previous_target.identities or target.namespace_header != previous_target.namespace_header:
                raise ValueError('Repair cannot replace test identities or the backend isolation protocol')
        run = Run(bundle_id=bundle.id, target_id=target_id, contract_digest=bundle.digest, planner=request.planner, parent_run=request.parent_run)
        directory = path("runs", run.id)
        write_json(directory / "contract.json", bundle.model_dump(mode="json"))
        write_json(directory / "request.json", request.model_dump(mode="json"))
        save_run(run)
        self.active[run.id] = run
        task = asyncio.create_task(self.work(run, request))
        self.tasks[run.id] = task
        task.add_done_callback(lambda job: self.finish(run.id, job))
        return run

    async def work(self, run, request):
        from .engine import execute
        async with self.semaphore:
            return await execute(run, request, self.require_approval)

    def finish(self, identifier, task):
        self.tasks.pop(identifier, None)
        self.active.pop(identifier, None)
        self.waiters.pop(identifier, None)
        run = load_run(identifier)
        if task.cancelled() and run.status not in {"completed", "error", "cancelled"}:
            run.status, run.finished_at = "cancelled", now()
            save_run(run)
        elif not task.cancelled() and task.exception():
            run.status, run.error, run.finished_at = "error", type(task.exception()).__name__, now()
            save_run(run)

    async def require_approval(self, run: Run, action: Action):
        token = digest({"run_id":run.id,"contract_digest":run.contract_digest,"target":run.target_id,"action":action.model_dump(mode="json")})
        pending = {"digest":token,"action":action.model_dump(mode="json"),"contract_digest":run.contract_digest,"target_id":run.target_id,
                   "expires_at":(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()}
        signal = asyncio.Event()
        self.waiters[run.id] = {"event":signal,"accepted":False}
        run.pending_approval, run.status = pending, "waiting_approval"
        event(run, "approval", "This exact action may write to the target; awaiting explicit approval")
        await asyncio.wait_for(signal.wait(),timeout=120)
        accepted = self.waiters.pop(run.id)["accepted"]
        run.pending_approval, run.status = None, "running"
        if not accepted:
            raise ValueError("Target action was denied")
        save_run(run)
        return True

    def approve(self, identifier, token: str, approved: bool, reviewer: str):
        run = self.active.get(identifier)
        pending = run.pending_approval if run else None
        if not pending or token != pending["digest"] or identifier not in self.waiters:
            raise ValueError("No matching pending action approval")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(pending["expires_at"]) or not reviewer.strip():
            raise ValueError("Approval expired or reviewer is missing")
        # First decision wins; requests cannot race a denial into an approval.
        waiter = self.waiters[identifier]
        if waiter["event"].is_set():
            raise ValueError("This action already has an approval decision")
        run.approvals.append({**pending,"approved":approved,"reviewer":reviewer[:120],"timestamp":now()})
        waiter["accepted"] = approved
        waiter["event"].set()
        save_run(run)
        return {"accepted":approved,"action_digest":token}

    def cancel(self, identifier):
        if identifier not in self.tasks:
            child = self.active.get(identifier)
            if child and child.challenge_id:
                return self.challenges.cancel(child.challenge_id)
            raise ValueError("Job is not active")
        self.tasks[identifier].cancel()

    async def close(self):
        await self.challenges.close()
        jobs = list(self.tasks.values())
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.wait(jobs,timeout=12)
        await asyncio.to_thread(self.previews.close)
