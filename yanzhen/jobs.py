"""Process-local bounded scheduling, persistent terminal states, and restart recovery."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .engine import create_run, execute
from .exports import make_export
from .models import Run, RunRequest, now
from .store import list_runs, load_run, save_run

ACTIVE = frozenset({"queued", "running", "finalizing"})
TERMINAL = frozenset({"completed", "error", "cancelled"})


class QueueFullError(ValueError):
    pass


class RunManager:
    def __init__(self, origin: str, concurrency: int = 2, capacity: int = 8,
                 runner: Callable[..., Awaitable[Run]] = execute):
        if concurrency < 1 or capacity < concurrency:
            raise ValueError("队列容量必须不小于并发数，且并发数至少为 1")
        self.origin = origin
        self.capacity = capacity
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: dict[str, asyncio.Task] = {}
        self._runner = runner

    def recover(self) -> int:
        recovered = 0
        for item in list_runs(limit=None, include_internal=True):
            if item["status"] in ACTIVE:
                run = load_run(item["id"])
                run.status = "error"
                run.error = "服务重启中断了执行；已完成结果保留，请重新创建运行。"
                run.finished_at = now()
                run.events.append({"time": now(), "phase": "recovery", "message": run.error})
                save_run(run)
                recovered += 1
        return recovered

    def start(self, request: RunRequest, parent: str | None = None) -> Run:
        if len(self._tasks) >= self.capacity:
            raise QueueFullError("等待中的运行较多，请稍后再试")
        run = create_run(request, parent)
        task = asyncio.create_task(self._work(run.id), name=f"acceptance-{run.id}")
        self._tasks[run.id] = task
        task.add_done_callback(lambda finished: self._finish(run.id, finished))
        return run

    async def _work(self, identifier: str):
        async with self._semaphore:
            return await self._runner(identifier, self.origin)

    def _finish(self, identifier: str, task: asyncio.Task):
        self._tasks.pop(identifier, None)
        if task.cancelled():
            # Also covers cancellation before the coroutine got its first time slice.
            run = load_run(identifier)
            if run.status not in TERMINAL:
                run.status = "cancelled"
                run.finished_at = now()
                run.events.append({"time": now(), "phase": "cancel", "message": "任务已取消，未执行的检查不作判定"})
                save_run(run)
                make_export(run, self.origin)
        elif task.exception() is not None:
            run = load_run(identifier)
            run.status = "error"
            run.error = "后台执行未完成：" + type(task.exception()).__name__
            run.finished_at = now()
            save_run(run)

    def cancel(self, identifier: str) -> None:
        run = load_run(identifier)
        task = self._tasks.get(identifier)
        if run.status not in {"queued", "running"} or task is None or task.done():
            raise ValueError("任务正在整理证据或已经结束，不能取消")
        task.cancel()

    async def shutdown(self):
        current = list(self._tasks.values())
        for identifier, task in list(self._tasks.items()):
            if load_run(identifier).status != "finalizing":
                task.cancel()
        if current:
            _, pending = await asyncio.wait(current, timeout=30)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=10)
