"""Model protocol unit tests use explicit HTTP mocks; no real inference is claimed."""
import asyncio
import json

import httpx
import pytest

from examples.verifyagent.cases import authorization, AUTH_REQUIREMENT
from yanzhen.verifyagent.schema import ContractSet, Decision
from yanzhen.verifyagent.planning import ModelClient, ModelUnavailable


def test_unlisted_generic_schema_is_sent_to_real_provider_protocol(monkeypatch):
    monkeypatch.setenv('YZ_ENABLE_MODEL','1');monkeypatch.setenv('YZ_DEEPSEEK_API_KEY','mock-unit-key')
    monkeypatch.setenv('YZ_VERIFY_PRICED_MODEL','deepseek-flash')
    monkeypatch.setenv('YZ_VERIFY_INPUT_CNY_PER_MILLION','2')
    monkeypatch.setenv('YZ_VERIFY_OUTPUT_CNY_PER_MILLION','8')
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY','5')
    c,_=authorization()
    def respond(request):
        body=json.loads(request.content)
        assert 'required_operations' in body['messages'][0]['content']
        assert 'CATALOG' not in body['messages'][0]['content']
        assert request.headers['authorization']=='Bearer mock-unit-key'
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'contracts':[c.model_dump()]})},'finish_reason':'stop'}],'usage':{'prompt_tokens':200,'completion_tokens':300}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model=ModelClient('deepseek',client=client,max_calls=1)
            result=await model.complete('specification',{'requirements':AUTH_REQUIREMENT},ContractSet)
            assert result.contracts[0].id=='order-access'
            assert model.usage()['completion_tokens']==300
            with pytest.raises(ModelUnavailable,match='budget'):
                await model.complete('exploration',{},Decision)
    asyncio.run(scenario())


def test_no_model_key_or_invalid_output_never_becomes_manual_mode(monkeypatch):
    monkeypatch.setenv('YZ_ENABLE_MODEL','0')
    model=ModelClient('deepseek')
    with pytest.raises(ModelUnavailable,match='disabled'):
        asyncio.run(model.complete('exploration',{},Decision))
    assert model.calls[0]['status']=='error'
    assert model.calls[0]['error_type']=='ModelUnavailable'


def test_runtime_uses_official_swarm_schema_and_codec(monkeypatch):
    # This is a WebSocket protocol fixture, not a real JiuwenSwarm agent/model.
    pytest.importorskip('jiuwenswarm')
    from jiuwenswarm.common.e2a.models import E2AEnvelope
    from jiuwenswarm.common.e2a.wire_codec import encode_agent_chunk_for_wire
    from jiuwenswarm.common.schema.agent import AgentResponseChunk
    from websockets.asyncio.server import serve
    monkeypatch.setenv('YZ_ENABLE_MODEL','1')
    monkeypatch.setenv('YZ_SWARM_PLANNING_ONLY','1')
    monkeypatch.setenv('YZ_SWARM_AGENT_ID','verify-test-planner')
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY','0')

    async def scenario():
        observed=[]
        async def server(socket):
            await socket.send(json.dumps({'type':'event','event':'connection.ack'}))
            request=E2AEnvelope.from_dict(json.loads(await socket.recv()))
            observed.append(request)
            assert request.method=='chat.send' and request.params['mode']=='agent.plan'
            assert 'D:' in request.params['project_dir'] or '/' in request.params['project_dir']
            payload={'event_type':'chat.final','content':json.dumps({'finished':True,'explanation':'Explicit protocol fixture'})}
            chunk=AgentResponseChunk(request_id=request.request_id,channel_id='web',payload=payload,is_complete=True)
            wire=encode_agent_chunk_for_wire(chunk,response_id=request.request_id,sequence=0)
            await socket.send(json.dumps(wire))
        async with serve(server,'127.0.0.1',0) as host:
            monkeypatch.setenv('YZ_SWARM_WS_URL',f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}')
            model=ModelClient('jiuwenswarm')
            decision=await model.complete('exploration',{'actual_observation':{'buttons':['save']}},Decision)
            assert decision.finished and len(observed)==1
            assert not model.usage()['usage_complete']
    asyncio.run(scenario())


def test_capped_swarm_rejects_unmetered_runtime_before_sending_query(monkeypatch):
    # Explicit transport fixture: it must not be able to trigger a paid query.
    pytest.importorskip('jiuwenswarm')
    from websockets.asyncio.server import serve
    monkeypatch.setenv('YZ_ENABLE_MODEL','1')
    monkeypatch.setenv('YZ_SWARM_PLANNING_ONLY','1')
    monkeypatch.setenv('YZ_SWARM_AGENT_ID','bounded-planner')
    monkeypatch.setenv('YZ_SWARM_LOCAL_RUNTIME','1')
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY','5')
    async def scenario():
        queries=[]
        async def server(socket):
            await socket.send(json.dumps({'event':'connection.ack','runtime_profile':'unmetered-stock-agentserver','native_tools':['shell']}))
            try:queries.append(await socket.recv())
            except Exception:pass
        async with serve(server,'127.0.0.1',0) as host:
            monkeypatch.setenv('YZ_SWARM_WS_URL',f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}')
            with pytest.raises(ModelUnavailable,match='share this cost ledger'):
                await ModelClient('jiuwenswarm').complete('exploration',{},Decision)
        assert not queries
    asyncio.run(scenario())
