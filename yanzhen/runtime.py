from __future__ import annotations

import asyncio

from .models import Run, now
from .store import save_run


class InfrastructureError(Exception):
    pass


def event(run: Run, phase: str, message: str) -> None:
    run.events.append({"time": now(), "phase": phase, "message": message})
    save_run(run)


async def cleanup(operation, run: Run, label: str, timeout: float = 10) -> bool:
    try:
        await asyncio.wait_for(operation, timeout=timeout)
        return True
    except Exception as exc:
        event(run, "cleanup", f"{label}未完成：{type(exc).__name__}；已有判定和证据继续保留")
        return False
