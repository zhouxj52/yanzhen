"""Real local HTTP and Chromium integration; no model mock on execution paths."""
import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from examples.verifyagent.app import app as target_app
from examples.verifyagent.cases import authorization, persistence, target, AUTH_REQUIREMENT, SAVE_REQUIREMENT
from yanzhen.exports import verify_evidence
from yanzhen.settings import initialize
from yanzhen.verifyagent.schema import Bundle, RunInput, Run, Decision, Action
from yanzhen.verifyagent import repository as repo
from yanzhen.verifyagent.engine import execute
from yanzhen.verifyagent.security import TargetPolicy


@pytest.fixture(scope="module")
def origin():
    initialize()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(target_app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{port}'
    server.should_exit=True;thread.join(timeout=5);sock.close()


def setup_case(monkeypatch,origin,kind='auth',variant='healthy',api_only=True):
    monkeypatch.setenv('YZ_VERIFY_ALLOWED_ORIGINS',origin)
    monkeypatch.setenv('YZ_VERIFY_SECRET_ALICE','fixture-alice-credential')
    monkeypatch.setenv('YZ_VERIFY_SECRET_BOB','fixture-bob-credential')
    t=target(origin,variant,'api' if api_only else 'web')
    # API observation uses a real application-provided schema endpoint.
    if api_only:t.base_url+='api/schema'
    # Relative probes use the application root, not the schema document directory.
    if api_only:t.base_url=origin+'/app/'+variant+'/'
    TargetPolicy(t);repo.save_target(t)
    c,actions=authorization() if kind=='auth' else persistence(api_only=api_only)
    requirements=AUTH_REQUIREMENT if kind=='auth' else SAVE_REQUIREMENT
    bundle=Bundle(requirements=requirements,target_id=t.id,provider='manual',contracts=[c])
    bundle.digest=bundle.calculate_digest();repo.save_bundle(bundle)
    bundle=repo.freeze(bundle.id,bundle.digest,'integration-test',True)
    request=RunInput(bundle_id=bundle.id,planner='manual',manual_actions=actions,max_seconds=80)
    run=Run(bundle_id=bundle.id,target_id=t.id,contract_digest=bundle.digest,planner='manual')
    from yanzhen.store import write_json
    write_json(repo.path('runs',run.id)/'contract.json',bundle.model_dump(mode='json'))
    repo.save_run(run)
    return bundle,request,run


async def approved_fixture_only(run,action):
    # This test harness explicitly authorizes disposable local fixture mutations.
    return True


def test_project_connection_check_uses_real_http_without_saving_contracts(monkeypatch,origin):
    from fastapi.testclient import TestClient
    from yanzhen.app import create_app
    from yanzhen import store
    monkeypatch.setenv('YZ_VERIFY_ALLOWED_ORIGINS',origin)
    monkeypatch.setenv('YZ_VERIFY_SECRET_ALICE','fixture-alice-credential')
    monkeypatch.setenv('YZ_VERIFY_SECRET_BOB','fixture-bob-credential')
    t=target(origin,'healthy','web')
    with TestClient(create_app()) as client:
        checked=client.post('/api/verify/targets/check',json=t.model_dump(mode='json'))
        assert checked.status_code==200 and checked.json()['ready'],checked.text
        assert checked.json()['http_status']==200 and checked.json()['model_calls']==0
        assert not (store.ARTIFACTS/'verifyagent'/'bundles').exists()
        assert not (store.ARTIFACTS/'verifyagent'/'targets'/t.id/'target.json').exists()
        t.base_url='https://example.com/'
        unsupported=client.post('/api/verify/targets/check',json=t.model_dump(mode='json')).json()
        # Public staging is supported now, but still needs explicit server authorization.
        assert not unsupported['ready'] and unsupported['state']=='not_allowed'
        t.base_url='http://127.0.0.1:59999/'
        denied=client.post('/api/verify/targets/check',json=t.model_dump(mode='json')).json()
        assert not denied['ready'] and denied['state']=='not_allowed'


def test_project_connection_check_distinguishes_auth_service_error_and_unreachable(monkeypatch,origin):
    from fastapi.testclient import TestClient
    from yanzhen.app import create_app
    from yanzhen.verifyagent.schema import Target
    monkeypatch.setenv('YZ_VERIFY_ALLOWED_ORIGINS',origin)
    t=Target(name='Read-only entry check',base_url=origin+'/inventory/unavailable/stock',interface='api',environment='local',authorized=True)
    with TestClient(create_app()) as client:
        unavailable=client.post('/api/verify/targets/check',json=t.model_dump(mode='json')).json()
        assert not unavailable['ready'] and unavailable['http_status']==503
        t.base_url=origin+'/app/healthy/api/orders/1';t.namespace_header='X-Verify-Sandbox'
        unauthorized=client.post('/api/verify/targets/check',json=t.model_dump(mode='json')).json()
        assert not unauthorized['ready'] and unauthorized['state']=='needs_identity'
        with socket.socket() as closed_listener:
            closed_listener.bind(('127.0.0.1',0))
            t.base_url='http://127.0.0.1:'+str(closed_listener.getsockname()[1])+'/'
            monkeypatch.setenv('YZ_VERIFY_ALLOWED_ORIGINS',t.base_url)
            unreachable=client.post('/api/verify/targets/check',json=t.model_dump(mode='json')).json()
            assert not unreachable['ready'] and unreachable['state']=='unreachable'


@pytest.mark.parametrize('variant,expected',[('healthy','pass'),('auth_bug','fail')])
def test_authentication_boundaries_from_actual_http(monkeypatch,origin,variant,expected):
    bundle,request,run=setup_case(monkeypatch,origin,variant=variant)
    result=asyncio.run(execute(run,request,approved_fixture_only))
    assert result.status=='completed',result.error
    assert result.results[0]['verdict']==expected,result.results
    assert {r['action']['actor'] for r in result.trace}=={'alice'}
    assert verify_evidence(repo.path('runs',run.id)/'evidence.zip')['valid']
    exported=(repo.path('runs',run.id)/'report.json').read_text(encoding='utf-8')
    assert 'fixture-alice-credential' not in exported
    assert 'fixture-bob-credential' not in exported


@pytest.mark.parametrize('variant,expected',[('healthy','pass'),('persistence_bug','fail')])
def test_real_browser_ui_api_refresh_conflict(monkeypatch,origin,variant,expected):
    bundle,request,run=setup_case(monkeypatch,origin,kind='save',variant=variant,api_only=False)
    result=asyncio.run(execute(run,request,approved_fixture_only))
    assert result.status=='completed',result.error
    assert result.results[0]['verdict']==expected,result.results
    assert any(e.source_type=='http_response' and e.observed_value['status']==200 for e in result.evidence)
    assert any(e.artifact_reference for e in result.evidence)
    if expected=='fail':
        assert any(edge['relation']=='contradicts' for edge in result.graph['edges'])
        failed=next(a for a in result.results[0]['assertions'] if a['assertion_id']=='ui_vs_api')
        assert len(failed['evidence_ids'])==2 and failed['actual']!=failed['expected']


@pytest.mark.parametrize('variant',['drift','live_drift'])
def test_replan_receives_real_locator_failure_and_changed_page(monkeypatch,origin,variant):
    bundle,request,run=setup_case(monkeypatch,origin,kind='save',variant=variant,api_only=False)
    actions=request.manual_actions
    old=actions[1].model_copy(update={'id':'old-save','timeout_ms':300})
    fixed=Action.model_validate({**actions[1].model_dump(),'id':'new-save','locator':{'by':'role','role':'button','value':'应用更改'}})
    reload=actions[2].model_copy(update={'depends_on':['new-save']})

    class FeedbackPlanner:
        # Explicit unit/integration test double; production always uses ModelPlanner.
        def __init__(self):self.calls=0;self.seen_error=False
        async def next(self,contract,observation,trace):
            self.calls+=1
            if not trace:return Decision(action=actions[0])
            if len(trace)==1:return Decision(action=old)
            if len(trace)==2:
                self.seen_error=not trace[-1]['ok'] and '应用更改' in json.dumps(observation,ensure_ascii=False)
                assert self.seen_error
                return Decision(action=fixed)
            if len(trace)==3:return Decision(action=reload)
            return Decision(finished=True)

    planner=FeedbackPlanner()
    result=asyncio.run(execute(run,request,approved_fixture_only,planner=planner))
    assert result.status=='completed',result.error
    assert planner.seen_error
    assert result.results[0]['verdict']=='pass',result.results
    assert any(e['phase']=='replan' for e in result.events)


def test_trace_minimization_does_not_delete_the_required_write(monkeypatch,origin):
    from yanzhen.verifyagent.replay import reduce_run
    bundle,request,run=setup_case(monkeypatch,origin,kind='save',variant='persistence_bug',api_only=True)
    result=asyncio.run(execute(run,request,approved_fixture_only))
    assert result.results[0]['verdict']=='fail'
    with pytest.raises(ValueError,match='approval'):
        asyncio.run(reduce_run(run.id,bundle.contracts[0].id,confirmed=False))
    minimized=asyncio.run(reduce_run(run.id,bundle.contracts[0].id,confirmed=True,budget=10))
    assert minimized['status']=='verified',minimized
    assert minimized['required_confirmations']==minimized['confirmations']==2
    assert [a['id'] for a in minimized['actions']]==['save']
    assert any(t['outcome']=='blocked' for t in minimized['trials'])
    assert all(o['contract_digest']==bundle.digest for t in minimized['trials'] for o in t.get('observations',[]))


def test_premature_finish_replans_from_independent_missing_operation_feedback(monkeypatch,origin):
    bundle,request,run=setup_case(monkeypatch,origin,kind='save',variant='persistence_bug',api_only=True)
    class PrematurePlanner:
        # Explicit test double for the real-model integration failure observed in development.
        def __init__(self):self.calls=0
        async def next(self,contract,observation,trace):
            self.calls+=1
            if self.calls==1:return Decision(finished=True)
            if self.calls==2:
                assert observation['verification_feedback']['status']=='blocked'
                return Decision(action=request.manual_actions[0])
            return Decision(finished=True)
    result=asyncio.run(execute(run,request,approved_fixture_only,planner=PrematurePlanner()))
    assert result.status=='completed' and result.results[0]['verdict']=='fail'
    assert result.contract_digest==bundle.digest
    assert any(e['phase']=='replan' and 'verification_feedback' in e for e in result.events)


def test_approvals_bind_to_exact_action_and_repair_keeps_original_oracle(monkeypatch,origin):
    from fastapi.testclient import TestClient
    from yanzhen.app import create_app
    bundle,request,_=setup_case(monkeypatch,origin,kind='save',variant='persistence_bug',api_only=True)
    with TestClient(create_app()) as client:
        response=client.post('/api/verify/runs',json=request.model_dump(mode='json'))
        assert response.status_code==200,response.text
        identifier=response.json()['id']
        def wait_for_job(identifier,approve=True):
            for _ in range(300):
                report=client.get('/api/verify/runs/'+identifier).json()
                if report['status']=='waiting_approval':
                    if not approve:return report
                    pending=report['pending_approval']
                    accepted=client.post('/api/verify/runs/'+identifier+'/approve',json={'digest':pending['digest'],'approved':True,'reviewer':'fixture-test'})
                    assert accepted.status_code==200,accepted.text
                if report['status'] in {'completed','error','cancelled'}:return report
                time.sleep(.02)
            raise AssertionError('Job did not finish')
        pending=wait_for_job(identifier,False)
        assert not pending['trace']
        assert client.post('/api/verify/runs/'+identifier+'/approve',json={'digest':'wrong','approved':True}).status_code==422
        result=wait_for_job(identifier)
        assert result['status']=='completed' and result['results'][0]['verdict']=='fail',result
        assert result['approvals'][0]['approved']
        healthy=target(origin,'healthy','api')
        repo.save_target(healthy)
        rejected=client.post('/api/verify/runs/'+identifier+'/repair/durable-note',json={'kind':'external_target','candidate_target_id':healthy.id,'contract_digest':'changed'})
        assert rejected.status_code==422
        repaired=client.post('/api/verify/runs/'+identifier+'/repair/durable-note',json={'kind':'external_target','candidate_target_id':healthy.id,'contract_digest':bundle.digest})
        assert repaired.status_code==200,repaired.text
        report=wait_for_job(repaired.json()['run']['id'])
        assert report['repair_validation']['verified'],report
        assert report['contract_digest']==bundle.digest
        assert not repaired.json()['review']['source_patch_applied']


def test_repair_review_rejects_caller_forged_execution_witness(monkeypatch,origin):
    from yanzhen.verifyagent.replay import trusted_actions
    from yanzhen.verifyagent.repair import review
    bundle,request,run=setup_case(monkeypatch,origin,kind='save',variant='persistence_bug',api_only=True)
    result=asyncio.run(execute(run,request,approved_fixture_only))
    candidates=trusted_actions(result,'durable-note')
    assert not review(run.id,'durable-note',candidates,bundle.digest)['accepted']
    result.trace[0]['action']['method']='GET'
    repo.save_run(result)
    with pytest.raises(ValueError,match='binding'):
        trusted_actions(repo.load_run(run.id),'durable-note')
