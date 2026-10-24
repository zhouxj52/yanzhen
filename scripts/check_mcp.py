"""Verify a real MCP stdio handshake and tool calls, without a model or JiuwenSwarm runtime."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from yanzhen.models import DEFAULT_REQUIREMENTS
from yanzhen.settings import ARTIFACTS, ROOT, initialize


async def main():
    initialize()
    params = StdioServerParameters(command=sys.executable, args=["-m", "yanzhen.mcp_server"], cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {"analyze_requirements", "freeze_contracts", "run_acceptance", "get_acceptance_report", "replay_defects", "cancel_acceptance", "verify_acceptance_evidence"}
            assert expected == names

            async def call(name, args):
                result = await session.call_tool(name, args)
                assert not result.isError, result
                data = result.structuredContent
                if data is None:
                    data = json.loads(next(item.text for item in result.content if item.type == "text"))
                assert not data.get("error"), data
                return data

            bundle = await call("analyze_requirements", {"requirements": DEFAULT_REQUIREMENTS, "provider": "offline"})
            assert len(bundle["contracts"]) == 5
            frozen = await call("freeze_contracts", {"bundle_id": bundle["id"], "digest": bundle["digest"]})
            assert frozen["frozen"]
            run = await call("run_acceptance", {"bundle_id": bundle["id"], "scenario": "broken", "browser": False})
            for _ in range(60):
                report = await call("get_acceptance_report", {"run_id": run["id"]})
                if report["status"] in {"completed", "error"}:
                    break
                await asyncio.sleep(.5)
            assert report["status"] == "completed" and report["summary"]["fail"] == 3
            replay = await call("replay_defects", {"run_id": run["id"]})
            for _ in range(60):
                repeated = await call("get_acceptance_report", {"run_id": replay["id"]})
                if repeated["status"] in {"completed", "error"}:
                    break
                await asyncio.sleep(.5)
            assert repeated.get("replay_comparison", {}).get("matches")
            integrity = await call("verify_acceptance_evidence", {"run_id": run["id"]})
            assert integrity["valid"] and integrity["files_checked"] >= 4
            cancelled = await call("run_acceptance", {"bundle_id": bundle["id"], "scenario": "healthy", "browser": True})
            result = await call("cancel_acceptance", {"run_id": cancelled["id"]})
            assert result["cancel_requested"]
            for _ in range(60):
                partial = await call("get_acceptance_report", {"run_id": cancelled["id"]})
                if partial["status"] == "cancelled":
                    break
                await asyncio.sleep(.5)
            assert partial["status"] == "cancelled"
            outcome = {"status": "passed", "transport": "stdio", "tools": sorted(names), "run_id": run["id"], "replay_id": replay["id"], "scope": "MCP integration tested; full JiuwenSwarm + real LLM orchestration not tested"}
            (ARTIFACTS / "mcp-check.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
