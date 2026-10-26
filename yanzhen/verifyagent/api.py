from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from .schema import Bundle, ContractSet, Strict, Target, RunInput, Action
from . import repository as repo
from .planning import draft
from .security import TargetPolicy, Redactor
from .service import VerifyService


class DraftInput(Strict):
    requirements: str = Field(min_length=5,max_length=16000)
    target_id: str
    provider: str
    supplied: ContractSet | None = None


class Approval(Strict):
    digest: str
    approved: bool
    reviewer: str = "local-user"


def router(service: VerifyService):
    routes = APIRouter(prefix="/api/verify", tags=["VerifyAgent"])

    @routes.get("/capabilities")
    def capabilities():
        from importlib.util import find_spec
        from ..settings import model_config
        import os
        return {"contract_schema":Bundle.model_json_schema(),"action_schema":Action.model_json_schema(),"planner_modes":["manual","deepseek","qwen","jiuwenswarm"],
                "providers":{name:{"enabled":model_config(name)['enabled'],"configured":bool(model_config(name)['key']) or model_config(name)['allow_no_key']} for name in ('deepseek','qwen')},
                "allowed_origins":[v.strip() for v in os.getenv('YZ_VERIFY_ALLOWED_ORIGINS','').split(',') if v.strip()],
                "swarm_sdk_installed":find_spec("jiuwenswarm") is not None,"swarm_configured":os.getenv('YZ_ENABLE_MODEL')=='1' and bool(os.getenv('YZ_SWARM_WS_URL')) and os.getenv('YZ_SWARM_PLANNING_ONLY')=='1' and bool(os.getenv('YZ_SWARM_AGENT_ID')),"scope":"authorized literal-IP/localhost test environments; manual mode is not autonomous inference"}

    @routes.get('/examples/{kind}')
    def example(kind: str):
        # Static, explicitly human-written contracts. These contain no execution results.
        from .examples import authorization, persistence, AUTH_REQUIREMENT, SAVE_REQUIREMENT
        if kind not in {'authorization','persistence'}:raise HTTPException(404,'Unknown example')
        contract,actions=authorization() if kind=='authorization' else persistence()
        return {'source':'human_authored_fixture_example','requirements':AUTH_REQUIREMENT if kind=='authorization' else SAVE_REQUIREMENT,
                'supplied':{'contracts':[contract.model_dump(mode='json')]},'actions':[a.model_dump(mode='json') for a in actions],
                'identities':{'alice':{'header_env':{'X-Test-Actor':'YZ_VERIFY_SECRET_ALICE'}},'bob':{'header_env':{'X-Test-Actor':'YZ_VERIFY_SECRET_BOB'}}}}

    @routes.post("/targets")
    def target(request: Target):
        TargetPolicy(request)
        Redactor(request)  # Fail before registration if a test identity is unavailable.
        repo.save_target(request)
        return request.model_dump(mode="json")

    @routes.post('/targets/check')
    async def check_target(request: Target):
        from .preflight import check_target as check
        return await check(request)

    @routes.get('/targets/{identifier}')
    def get_target(identifier: str):
        return repo.load_target(identifier).model_dump(mode='json')

    @routes.post("/analyze")
    async def analyze(request: DraftInput):
        target = repo.load_target(request.target_id)
        TargetPolicy(target)
        if request.provider == "manual":
            if not request.supplied:
                raise ValueError("Manual mode requires reviewed structured input; no automatic rule parser is used")
            bundle = Bundle(requirements=request.requirements,target_id=target.id,provider="manual",**request.supplied.model_dump())
            bundle.digest = bundle.calculate_digest()
        else:
            if request.supplied or request.provider not in {"deepseek","qwen","jiuwenswarm"}:
                raise ValueError("Choose a real provider, or explicitly choose manual mode")
            bundle = await draft(request.requirements,target,request.provider)
        repo.save_bundle(bundle)
        return bundle.model_dump(mode="json")

    @routes.get("/bundles/{identifier}")
    def bundle(identifier: str):
        return repo.load_bundle(identifier).model_dump(mode="json")

    @routes.post("/bundles/{identifier}/versions")
    def version(identifier: str, request: DraftInput):
        parent = repo.load_bundle(identifier)
        if request.provider != "manual" or not request.supplied or request.target_id != parent.target_id:
            raise ValueError("An edited revision requires explicit structured input and the same target")
        revised = Bundle(requirements=request.requirements,target_id=parent.target_id,provider="manual",version=parent.version+1,parent_id=parent.id,**request.supplied.model_dump())
        revised.digest = revised.calculate_digest()
        repo.save_bundle(revised)
        return revised.model_dump(mode="json")

    @routes.post("/bundles/{identifier}/freeze")
    def freeze(identifier: str, request: dict=Body(...)):
        if request.get("confirmed") is not True:
            raise ValueError("Human confirmation of this exact contract is required")
        return repo.freeze(identifier,str(request.get("digest","")),str(request.get("reviewer","local-user")),request.get("accept_assumptions") is True).model_dump(mode="json")

    @routes.post("/runs")
    async def start(request: RunInput):
        return service.start(request).model_dump(mode="json")

    @routes.get("/runs")
    def history():
        return repo.list_runs()

    @routes.get("/runs/{identifier}")
    def report(identifier: str):
        run = repo.load_run(identifier)
        data = run.model_dump(mode="json")
        data["summary"] = {v:sum(r["verdict"]==v for r in run.results) for v in ("pass","fail","blocked","unclear")}
        if run.parent_run and run.status == "completed":
            parent = repo.load_run(run.parent_run)
            original_ids = {r["contract_id"] for r in parent.results}
            data["repair_validation"] = {"original_run":parent.id,"same_contract":run.contract_digest==parent.contract_digest,
                "all_regressions_pass":bool(run.results) and original_ids == {r["contract_id"] for r in run.results} and all(r["verdict"]=="pass" for r in run.results),
                "original_had_defect":any(r["verdict"]=="fail" for r in parent.results),"mode":"external target / executor revalidation; no automatic source patch was applied"}
            data["repair_validation"]["verified"] = all(data["repair_validation"][k] for k in ("same_contract","all_regressions_pass","original_had_defect"))
        return data

    @routes.post("/runs/{identifier}/approve")
    def approve(identifier: str, request: Approval):
        return service.approve(identifier,request.digest,request.approved,request.reviewer)

    @routes.post("/runs/{identifier}/cancel")
    def cancel(identifier: str):
        service.cancel(identifier)
        return {"cancel_requested":True}

    @routes.get("/runs/{identifier}/artifacts/{filename}")
    def artifact(identifier: str, filename: str):
        import re
        if filename not in {"report.json","contract.json","target.json","manifest.json","evidence.zip"} and not re.fullmatch(r"screen-[a-f0-9]{32}\.png",filename):
            raise HTTPException(404,"Not an exportable artifact")
        run = repo.load_run(identifier)
        if run.status not in {"completed","error","cancelled"}:
            raise HTTPException(409,"Evidence is still being written")
        file=repo.path("runs",identifier) / filename
        if not file.is_file():raise HTTPException(404,'Artifact has not been produced')
        return FileResponse(file, filename=filename)

    @routes.post("/runs/{identifier}/minimize/{contract_id}")
    async def minimize(identifier: str, contract_id: str, request: dict=Body(...)):
        from .replay import reduce_run
        async with service.semaphore:
            return await reduce_run(identifier,contract_id,confirmed=request.get("confirmed") is True,budget=int(request.get("budget",12)))

    @routes.post("/runs/{identifier}/repair-review/{contract_id}")
    def repair_review(identifier: str, contract_id: str, request: dict=Body(...)):
        from .repair import review
        return review(identifier,contract_id,[Action.model_validate(a) for a in request.get("actions",[])],str(request.get("contract_digest","")))

    @routes.post("/runs/{identifier}/repair/{contract_id}")
    async def repair(identifier: str, contract_id: str, request: dict=Body(...)):
        from .repair import review
        from .replay import trusted_actions
        original=repo.load_run(identifier)
        if request.get("kind")=="executor":
            result=review(identifier,contract_id,[Action.model_validate(a) for a in request.get("actions",[])],str(request.get("contract_digest","")))
            if not result['accepted']:return result
            actions=result['candidate_actions']
            candidate_target=original.target_id
        elif request.get("kind")=="external_target":
            if request.get("contract_digest") != original.contract_digest:
                raise ValueError("External repair cannot modify the original oracle")
            candidate_target=str(request.get("candidate_target_id",""))
            repo.load_target(candidate_target)
            actions=[a.model_dump(mode='json') for a in trusted_actions(original,contract_id)]
            result={'accepted':True,'kind':'external_target_revalidation','source_patch_applied':False,'scope':'Candidate deployment must already exist in an authorized isolated test environment'}
        else:
            raise ValueError("Choose executor or external_target; arbitrary source patches are not executed")
        job=service.start(RunInput(bundle_id=original.bundle_id,planner='manual',manual_actions=[Action.model_validate(a) for a in actions],candidate_target_id=candidate_target,parent_run=original.id))
        return {'review':result,'run':job.model_dump(mode='json')}

    return routes
