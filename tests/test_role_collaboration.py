import asyncio
import json

import httpx
import pytest

from yanzhen.verifyagent.planning import ModelClient, ModelUnavailable
from yanzhen.verifyagent.schema import Decision, GenericContract


def data():
    contract=GenericContract.model_validate({'id':'new-business','title':'Saved note remains after reload',
        'probes':[{'id':'persisted','source_type':'dom_text','locator':{'by':'css','value':'#saved'}}],
        'constraints':{'required_actions':['reload']},
        'postconditions':[{'id':'saved-value','left':'persisted','expected':'example','source':{'quote':'Saved note remains after reload'}}]})
    return {'frozen_contract':contract.model_dump(mode='json'),'executed_actions':[],
            'effective_target':{'base_url':'http://127.0.0.1:9876/','actors':['anonymous']},
            'observation':{'text':'Saved note','elements':[{'tag':'button','text':'Save'}]}}


def configure(monkeypatch):
    pytest.importorskip('openjiuwen')
    monkeypatch.setenv('YZ_ENABLE_MODEL','1')
    monkeypatch.setenv('YZ_OPENJIUWEN_MODEL_PROVIDER','deepseek')
    monkeypatch.setenv('YZ_DEEPSEEK_API_KEY','explicit-protocol-fixture')


def response(payload):
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(payload)},'finish_reason':'stop'}],
                                   'usage':{'prompt_tokens':10,'completion_tokens':5}})


def test_actual_sdk_routes_roles_and_auditor_demands_missing_action(monkeypatch):
    configure(monkeypatch)
    requests=[]
    def handle(request):
        payload=json.loads(json.loads(request.content)['messages'][1]['content'])
        requests.append(payload)
        if payload['task']=='team.requirements': return response({'probe_ids':['persisted'],'business_goal':'Persistence must be observed'})
        if payload['task']=='team.challenger': return response({'focus':'persistence','probe_ids':['persisted'],'concern':'Success text alone is insufficient'})
        if payload['task']=='team.executor': return response({'finished':True,'explanation':'Premature fixture decision'})
        assert payload['task']=='team.executor.revision' and payload['auditor_feedback']['missing_operations']
        return response({'action':{'id':'reload-proof','kind':'reload'},'explanation':'Collect missing reload evidence'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            model=ModelClient('openjiuwen_team',client=client,max_calls=4)
            decision=await model.complete('exploration',data(),Decision)
            assert decision.action.kind=='reload' and model.actual_call_count()==4
            runtime=model.calls[-1]['runtime']
            assert runtime['roles']['evidence_auditor']=='deterministic'
            assert any(e['state']=='handoff' and e['target_role']=='executor' for e in runtime['nodes'])
            assert [e['role'] for e in runtime['nodes'] if e['state']=='completed']==['requirements','challenger','executor','evidence_auditor','return']
            with pytest.raises(ModelUnavailable,match='budget'):
                await model.complete('exploration',data(),Decision)
    asyncio.run(scenario())
    assert len(requests)==4 and all('assignment_commitment' not in json.dumps(r) for r in requests)


def test_shared_role_limit_blocks_before_extra_model_request(monkeypatch):
    configure(monkeypatch)
    tasks=[]
    def handle(request):
        task=json.loads(json.loads(request.content)['messages'][1]['content'])['task'];tasks.append(task)
        if task=='team.requirements': return response({'probe_ids':['persisted'],'business_goal':'Business goal'})
        if task=='team.challenger': return response({'focus':'persistence','probe_ids':['persisted'],'concern':'Check reload'})
        return response({'finished':True,'explanation':'Missing required reload'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            model=ModelClient('openjiuwen_team',client=client,max_calls=3)
            with pytest.raises(ModelUnavailable,match='budget'):
                await model.complete('exploration',data(),Decision)
            assert model.actual_call_count()==3
    asyncio.run(scenario());assert len(tasks)==3


def test_valid_role_briefs_are_reused_without_repeated_paid_analysis(monkeypatch):
    configure(monkeypatch)
    tasks=[]
    def handle(request):
        task=json.loads(json.loads(request.content)['messages'][1]['content'])['task'];tasks.append(task)
        if task=='team.requirements': return response({'probe_ids':['persisted'],'business_goal':'Business goal'})
        if task=='team.challenger': return response({'focus':'persistence','probe_ids':['persisted'],'concern':'Check reload'})
        return response({'action':{'id':'reload','kind':'reload'},'explanation':'Perform required reload'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            model=ModelClient('openjiuwen_team',client=client,max_calls=5)
            await model.complete('exploration',data(),Decision)
            await model.complete('exploration',data(),Decision)
            assert model.actual_call_count()==4
            assert any(e.get('cached') for e in model.calls[-1]['runtime']['nodes'])
    asyncio.run(scenario());assert tasks.count('team.requirements')==1 and tasks.count('team.challenger')==1


def test_role_cannot_invent_a_probe_or_turn_a_budget_rejection_into_a_call(monkeypatch):
    configure(monkeypatch)
    requests=[]
    def handle(request):
        requests.append(request)
        return response({'probe_ids':['invented-oracle'],'business_goal':'Invalid role fixture'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            model=ModelClient('openjiuwen_team',client=client,max_calls=3)
            with pytest.raises(ValueError,match='invented'):
                await model.complete('exploration',data(),Decision)
            assert model.actual_call_count()==1 and model.dispatched_call_count()==1
    asyncio.run(scenario());assert len(requests)==1
