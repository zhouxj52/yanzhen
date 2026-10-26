"""Real stdio MCP tools for legacy and bounded generic verification APIs."""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

from .settings import initialize

server = FastMCP("yanzhen")


async def api(method: str, path: str, body: dict | None = None):
    origin = f"http://127.0.0.1:{os.getenv('YZ_PORT', '8765')}"
    async with httpx.AsyncClient(base_url=origin, timeout=100, trust_env=False) as client:
        response = await client.request(method, path, json=body)
        if response.status_code >= 400:
            return {"error": True, "status": response.status_code, "detail": response.json().get("detail", "请求失败")}
        return response.json()


@server.tool()
async def analyze_requirements(requirements: str, provider: str = "offline", target: str = "reimbursement") -> dict:
    """Draft contracts. offline uses rules; qwen/deepseek call explicitly enabled model services."""
    return await api("POST", "/api/analyze", {"requirements": requirements, "provider": provider, "target":target})


@server.tool()
async def freeze_contracts(bundle_id: str, digest: str) -> dict:
    """Freeze reviewed contract content. Show the contracts to the user before calling."""
    return await api("POST", f"/api/bundles/{bundle_id}/freeze", {"digest": digest})


@server.tool()
async def run_acceptance(bundle_id: str, scenario: str = "broken", browser: bool = True, target: str = "reimbursement") -> dict:
    """Start acceptance on a fresh local fixture. Returns a run id; poll get_acceptance_report."""
    return await api("POST", "/api/runs", {"bundle_id": bundle_id, "target": target, "scenario": scenario, "browser": browser})


@server.tool()
async def cancel_acceptance(run_id: str) -> dict:
    """Request cancellation of a queued/running task; preserve completed checks."""
    return await api("POST", f"/api/runs/{run_id}/cancel")


@server.tool()
async def verify_acceptance_evidence(run_id: str) -> dict:
    """Verify evidence package completeness and SHA-256 content hashes."""
    return await api("GET", f"/api/runs/{run_id}/integrity")


@server.tool()
async def get_acceptance_report(run_id: str) -> dict:
    """Read actual evidence and pass/fail/blocked/unclear verdicts. Never invent a result."""
    return await api("GET", f"/api/runs/{run_id}")


@server.tool()
async def replay_defects(run_id: str, contract_id: str | None = None) -> dict:
    """Replay the unchanged frozen contracts in a new fixture, preserving the original run."""
    if contract_id:
        return await api("POST", f"/api/runs/{run_id}/reproduce/{contract_id}")
    return await api("POST", f"/api/runs/{run_id}/replay")


def main():
    initialize()
    server.run(transport="stdio")


@server.tool()
async def register_verification_target(target: dict) -> dict:
    """Register an operator-authorized test target; the server's exact-origin allowlist is enforced."""
    return await api('POST','/api/verify/targets',target)


@server.tool()
async def draft_verification_contracts(request: dict) -> dict:
    """Draft generic contracts using an explicit real provider or supplied/manual mode. Human freeze is in the UI."""
    return await api('POST','/api/verify/analyze',request)


@server.tool()
async def run_verification(request: dict) -> dict:
    """Run already human-frozen generic contracts. Writes pause for human UI approval; this tool cannot approve them."""
    return await api('POST','/api/verify/runs',request)


@server.tool()
async def get_verification_report(run_id: str) -> dict:
    """Read real generic plans, trace, evidence and deterministic verdicts; never fabricate progress."""
    return await api('GET','/api/verify/runs/'+run_id)


if __name__ == "__main__":
    main()
