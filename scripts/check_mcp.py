"""Verify a real MCP stdio handshake and tool calls, without a model or JiuwenSwarm runtime."""
import asyncio
import json
import os
import sys

import httpx

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
            expected.update({'register_verification_target','draft_verification_contracts','run_verification','get_verification_report'})
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
            generic_target=await call('register_verification_target',{'target':{'name':'MCP read-only inventory fixture','base_url':'http://127.0.0.1:8771/inventory/healthy/','interface':'api','environment':'local','authorized':True}})
            generic_bundle=await call('draft_verification_contracts',{'request':{'requirements':'可用库存不能为负数。','target_id':generic_target['id'],'provider':'manual','supplied':{'contracts':[{'id':'mcp-stock','title':'库存非负','probes':[{'id':'stock','source_type':'http_json','url':'stock','pointer':'/available'}],'postconditions':[{'id':'nonnegative','left':'stock','op':'gte','expected':0,'source':{'quote':'可用库存不能为负数。'}}]}]}}})
            # Human-authored read-only integration protocol; the generic MCP
            # surface intentionally has no freeze or write-approval tool.
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{os.getenv('YZ_PORT','8765')}",trust_env=False) as review_client:
                reviewed=await review_client.post('/api/verify/bundles/'+generic_bundle['id']+'/freeze',json={'digest':generic_bundle['digest'],'confirmed':True,'reviewer':'read-only-MCP-integration-protocol'})
                reviewed.raise_for_status()
            generic_run=await call('run_verification',{'request':{'bundle_id':generic_bundle['id'],'planner':'manual','manual_actions':[{'id':'read-stock','kind':'http_request','url':'stock'}]}})
            for _ in range(60):
                generic_report=await call('get_verification_report',{'run_id':generic_run['id']})
                if generic_report['status'] in {'completed','error'}:break
                await asyncio.sleep(.2)
            assert generic_report['summary']['pass']==1 and generic_report['status']=='completed'
            outcome = {"status": "passed", "transport": "stdio", "tools": sorted(names), "run_id": run["id"], "replay_id": replay["id"], 'generic_read_only_run':generic_run['id'], "scope": "MCP tool integration only; Swarm/model validation is recorded separately"}
            (ARTIFACTS / "mcp-check.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
