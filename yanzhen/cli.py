from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

from .settings import initialize


def wait(client: httpx.Client, identifier: str, timeout: int = 180) -> dict:
    for _ in range(timeout):
        response = client.get(f"/api/runs/{identifier}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"completed", "error", "cancelled"}:
            return data
        time.sleep(1)
    raise TimeoutError("运行超过等待时间；服务中的任务仍可通过工作台查询")


def main():
    initialize()
    parser = argparse.ArgumentParser(description="验真 · 软件验收工作台")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=int(os.getenv("YZ_PORT", "8765")))
    run = sub.add_parser("demo")
    run.add_argument("--scenario", choices=["healthy", "broken", "auth_bug", "state_bug", "persistence_bug", "locator_drift", "environment_down", "upstream"])
    run.add_argument("--target", choices=["reimbursement","todomvc"],default="reimbursement")
    run.add_argument("--api-only", action="store_true")
    run.add_argument("--provider", choices=["offline", "qwen", "deepseek"], default="offline")
    run.add_argument("--origin", default="http://127.0.0.1:8765")
    verify = sub.add_parser("verify-evidence")
    verify.add_argument("path")
    generic = sub.add_parser('verify-demo',help='Run the controlled generic-kernel demo; manual is explicitly not autonomous inference')
    generic.add_argument('--origin',default='http://127.0.0.1:8767')
    generic.add_argument('--target-origin',default='http://127.0.0.1:8771')
    generic.add_argument('--case',choices=['authorization','persistence'],default='persistence')
    generic.add_argument('--variant',choices=['healthy','auth_bug','persistence_bug','both','drift'],default='persistence_bug')
    generic.add_argument('--provider',choices=['manual','deepseek','qwen','jiuwenswarm'],default='manual')
    generic.add_argument('--approve-local-fixture-writes',action='store_true')
    generic.add_argument('--allow-model',action='store_true')
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        os.environ["YZ_PORT"] = str(args.port)
        uvicorn.run("yanzhen.app:app", host="127.0.0.1", port=args.port, log_level="info")
    elif args.command == 'verify-demo':
        from .verifyagent.demo import run_demo
        result=run_demo(args.origin,args.target_origin,args.case,args.variant,provider=args.provider,approve_fixture_writes=args.approve_local_fixture_writes,allow_model=args.allow_model)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result['status']!='completed':sys.exit(1)
    elif args.command == "verify-evidence":
        from .exports import verify_evidence
        result = verify_evidence(args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["valid"]:
            sys.exit(1)
    elif args.command == "demo":
        from .models import DEFAULT_REQUIREMENTS, TODO_REQUIREMENTS
        with httpx.Client(base_url=args.origin, timeout=100, trust_env=False) as client:
            response = client.post("/api/analyze", json={"requirements": TODO_REQUIREMENTS if args.target=="todomvc" else DEFAULT_REQUIREMENTS, "provider": args.provider, "target":args.target})
            response.raise_for_status()
            bundle = response.json()
            response = client.post(f"/api/bundles/{bundle['id']}/freeze", json={"digest": bundle["digest"]})
            response.raise_for_status()
            response = client.post("/api/runs", json={"bundle_id": bundle["id"], "scenario": args.scenario or ("upstream" if args.target=="todomvc" else "broken"), "browser": not args.api_only, "target":args.target})
            response.raise_for_status()
            report = wait(client, response.json()["id"])
            print(json.dumps({"id": report["id"], "status": report["status"], "summary": report["summary"], "results": [{"contract": r["contract_id"], "verdict": r["verdict"], "summary": r["summary"]} for r in report["results"]]}, ensure_ascii=False, indent=2))
            if report["status"] != "completed" or report["summary"]["blocked"]:
                sys.exit(1)


if __name__ == "__main__":
    main()
