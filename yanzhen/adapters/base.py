from __future__ import annotations

from typing import Any, Protocol

import httpx

from ..models import CheckResult, Contract, Run


class AcceptanceExecutor(Protocol):
    browser: Any
    browser_error: str | None
    pages: dict[str, Any]
    redactions: set[str]

    async def check(self, contract: Contract) -> CheckResult: ...


class TargetAdapter(Protocol):
    key: str
    label: str
    supported_kinds: frozenset[str]

    def prepare(self, run_id: str) -> None:
        """Prepare a fresh target fixture. Production adapters must isolate writes."""
        ...

    def create_executor(self, run: Run, origin: str, client: httpx.AsyncClient) -> AcceptanceExecutor: ...
