import asyncio
import hashlib
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from yanzhen.app import create_app
from yanzhen.verifyagent import repository as repo
from yanzhen.verifyagent.challenges import Prepare, Launch, prepare, read, summarize, directory, baseline
from yanzhen.verifyagent.mutations import discover, apply, source_files
from yanzhen.verifyagent.schema import Bundle, Run, RunInput, Target, ContractSet, digest
from yanzhen.verifyagent.engine import execute


def test_real_ast_mutation_ignores_comments_and_strings():
    original = b'''// localStorage.setItem('fake', 'x');
const s="localStorage.setItem('fake','x')";
if (count >= 1) localStorage.setItem('note', value);'''
    files={'app.js':original}
    candidates,skipped=discover(files)
    assert len(candidates)==2 and not skipped
    changed=apply(files,next(c for c in candidates if c['operator']=='drop_storage_write'))
    assert changed['app.js'].count(b"localStorage.setItem(")==2
    assert b'(void 0)' in changed['app.js'] and files['app.js']==original
    assert next(c for c in candidates if c['operator']=='shift_boundary')['before']=='>='


def test_inline_script_offsets_unicode_and_unsupported_syntax():
    files={'index.html':'<h1>中文</h1><script>localStorage.setItem("note","中文")</script>'.encode()}
    choices,_=discover(files)
    modified=apply(files,choices[0])['index.html'].decode()
    assert modified=='<h1>中文</h1><script>(void 0)</script>'
    assert discover({'app.js':b'const v = a?.b;'})[1]


async def normal_run(service):
    from yanzhen.verifyagent.challenge_example import create_example
    from yanzhen.verifyagent.schema import Action
    sample=await create_example(service)
    target=Target(name='Original static project',base_url=sample['preview']['base_url'],environment='test',authorized=True,project_id=sample['project']['id'])
    repo.save_target(target)
    bundle=Bundle(requirements=sample['requirements'],target_id=target.id,provider='manual',**sample['supplied'])
    bundle.digest=bundle.calculate_digest();repo.save_bundle(bundle)
    bundle=repo.freeze(bundle.id,bundle.digest,'test-human-confirmation',True)
    run=Run(bundle_id=bundle.id,target_id=target.id,contract_digest=bundle.digest,planner='manual')
    from yanzhen.store import write_json
    write_json(repo.path('runs',run.id)/'contract.json',bundle.model_dump(mode='json'));repo.save_run(run)
    request=RunInput(bundle_id=bundle.id,planner='manual',manual_actions=[Action.model_validate(v) for v in sample['actions']])
    async def approve(run,action): return True  # Disposable fixture, explicit test authorization.
    await execute(run,request,approve)
    assert run.results[0]['verdict']=='pass'
    return run,sample


def test_blinded_campaign_runs_mutated_source_and_reveals_committed_assignment(monkeypatch):
    from yanzhen.verifyagent.service import VerifyService
    async def scenario():
        service=VerifyService()
        try:
            original,sample=await normal_run(service)
            before=source_files(sample['project']['id'])
            plan=prepare(Prepare(source_run_id=original.id))
            assert 'nonce' not in read(plan['id']) and not read(plan['id'])['revealed']
            with pytest.raises(ValueError):
                service.challenges.start(plan['id'],Launch(plan_digest='wrong',confirmed=True,approve_repeated_writes=True))
            from yanzhen.verifyagent.challenges import export
            with pytest.raises(ValueError,match='揭晓'):
                export(plan['id'])
            service.challenges.start(plan['id'],Launch(plan_digest=plan['digest'],confirmed=True,approve_repeated_writes=True))
            await service.challenges.tasks[plan['id']]
            report=read(plan['id'])
            assert report['state']=='completed' and report['integrity_verified']
            assert digest(report['assignment_reveal'])==plan['assignment_commitment']
            m=report['metrics']['trace']
            assert m['control_passed'] and m['detected']==1 and m['survived']==1 and m['actual_model_calls']==0
            assert source_files(sample['project']['id'])==before
            assert repo.load_bundle(original.bundle_id).digest==original.contract_digest
            for row in report['completed_trials']:
                run=repo.load_run(row['run_id']);target=repo.load_target(run.target_id)
                assert target.project_id is None and target.name=='匿名验收目标'
                assert run.contract_digest==original.contract_digest
                assert 'assignment_reveal' not in run.model_dump()
            with zipfile.ZipFile(directory(plan['id'])/'challenge.zip') as archive:
                manifest=json.loads(archive.read('manifest.json'))
                for name,item in manifest['files'].items(): assert hashlib.sha256(archive.read(name)).hexdigest()==item['sha256']
        finally: await service.close()
    asyncio.run(scenario())


def test_tampered_assignment_is_rejected_before_execution():
    from yanzhen.verifyagent.service import VerifyService
    from yanzhen.store import write_json
    async def scenario():
        service=VerifyService()
        try:
            original,sample=await normal_run(service)
            plan=prepare(Prepare(source_run_id=original.id))
            private=read(plan['id'],'private');private['nonce']='forged'
            write_json(directory(plan['id'])/'private.json',private)
            with pytest.raises(ValueError,match='承诺'):
                service.challenges.start(plan['id'],Launch(plan_digest=plan['digest'],confirmed=True,approve_repeated_writes=True))
            assert read(plan['id'])['state']=='prepared'
        finally: await service.close()
    asyncio.run(scenario())


def test_failed_control_invalidates_score_and_blocked_is_not_detection():
    private={'slots':[{'slot':'a','kind':'control'},{'slot':'b','kind':'mutant'}]}
    rows=[{'slot':'a','arm':'trace','verdict':'fail','status':'completed','model_calls':0,'wall_time_ms':1},
          {'slot':'b','arm':'trace','verdict':'blocked','status':'error','model_calls':0,'wall_time_ms':1}]
    metric=summarize({'completed_trials':rows},private)['trace']
    assert not metric['control_passed'] and metric['control_false_alarms']==1
    assert metric['detected'] is None and metric['observed_mutation_detection_rate'] is None
    assert metric['blocked_or_unclear']==1


def test_challenge_api_requires_human_plan_confirmation_and_blocks_early_export():
    with TestClient(create_app()) as client:
        sample=client.post('/api/verify/challenges/example',json={}).json()
        assert sample['source'].startswith('human_authored_example')
        assert client.get('/api/verify/challenges/'+'0'*32+'/export').status_code==404
        assert client.post('/api/verify/challenges/example',headers={'Origin':'https://foreign.example'},json={}).status_code==403


def test_equal_budget_compare_uses_actual_tools_and_sdk_with_explicit_model_transport_fixture(monkeypatch):
    import httpx
    pytest.importorskip('openjiuwen')
    from yanzhen.verifyagent.service import VerifyService
    from yanzhen.verifyagent.planning import ModelClient
    configure={'YZ_ENABLE_MODEL':'1','YZ_OPENJIUWEN_MODEL_PROVIDER':'deepseek','YZ_DEEPSEEK_API_KEY':'explicit-test-transport'}
    for name,value in configure.items(): monkeypatch.setenv(name,value)
    payloads=[]
    def handle(request):
        payload=json.loads(json.loads(request.content)['messages'][1]['content']);payloads.append(payload)
        if payload['task']=='team.requirements': value={'probe_ids':['after-reload'],'business_goal':'Check persistence after reload'}
        elif payload['task']=='team.challenger': value={'focus':'persistence','probe_ids':['after-reload'],'concern':'Toast may be false'}
        else:
            kinds={row['action']['kind'] for row in payload.get('executed_actions',[]) if row['ok']}
            if 'fill' not in kinds: value={'action':{'id':'fill','kind':'fill','locator':{'by':'css','value':'#note'},'value':'验真协作'}}
            elif 'click' not in kinds: value={'action':{'id':'save','kind':'click','locator':{'by':'css','value':'#save'}}}
            elif 'reload' not in kinds: value={'action':{'id':'reload','kind':'reload'}}
            else: value={'finished':True}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':5}})
    async def scenario():
        service=VerifyService()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr('yanzhen.verifyagent.engine.ModelClient',lambda provider,**kw: ModelClient(provider,client=client,**kw))
            async def fixture_approval(run,action): return True  # Only disposable sources created by this test.
            service.require_approval=fixture_approval
            try:
                original,sample=await normal_run(service)
                values,_=discover(source_files(sample['project']['id']))
                chosen=next(c for c in values if c['operator']=='drop_storage_write')
                plan=prepare(Prepare(source_run_id=original.id,candidate_ids=[chosen['id']]))
                service.challenges.start(plan['id'],Launch(plan_digest=plan['digest'],confirmed=True,approve_repeated_writes=True,mode='compare'))
                await service.challenges.tasks[plan['id']]
                report=read(plan['id'])
                assert report['state']=='completed' and len(report['completed_trials'])==4,report
                for arm in ('single','team'):
                    assert report['metrics'][arm]['control_passed'] and report['metrics'][arm]['detected']==1
                    assert report['metrics'][arm]['not_executed_mutations']==0
                assert report['metrics']['single']['actual_model_calls']==8
                assert report['metrics']['team']['actual_model_calls']==12
                assert report['comparison']['paired_comparable_mutations']==1
                assert report['comparison']['detections_on_shared_mutations']=={'single':1,'team':1}
                assert all(row['contract_digest']==original.contract_digest for row in report['completed_trials'])
                assert all('assignment_reveal' not in payload and 'candidate_ids' not in payload for payload in payloads)
            finally: await service.close()
    asyncio.run(scenario())
