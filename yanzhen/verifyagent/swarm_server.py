"""Optional JiuwenSwarm facade host for the bounded, metered JSON planning adapter.

This deliberately does not start Swarm's general coding/browser AgentServer.
The real 0.2.3 facade manages request/session queues and history; our adapter
implements its published AgentAdapter protocol and exposes no native tools.
All target actions remain in VerifyAgent's separately approved tool kernel.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from importlib.metadata import version
import json
import os
import re
from pathlib import Path

from pydantic import RootModel

from ..settings import ROOT, initialize
from .planning import ModelClient
from .budget import destination

PROFILE='yanzhen-metered-json-planner/1'


class PlanningObject(RootModel[dict]):
    pass


def initialize_runtime():
    if version('jiuwenswarm')!='0.2.3':
        raise ValueError('The optional facade host is pinned to jiuwenswarm==0.2.3')
    state=ROOT/'.artifacts'/'swarm-runtime'
    os.environ['JIUWENSWARM_DATA_DIR']=str(state)
    os.environ['JIUWENSWARM_CONFIG_DIR']=str(state/'config')
    os.environ.setdefault('HF_HOME',str(ROOT/'.cache'/'huggingface'))
    (state/'config').mkdir(parents=True,exist_ok=True)
    # A dedicated profile: no memory extraction, skills, A2UI, proactive tasks,
    # default deep adapter, or tool registration. Never overwrite user config.
    config=state/'config'/'config.yaml'
    if not config.exists():
        config.write_text('preferred_language: en\nauto_memory_enabled: false\nmemory:\n  mode: local\n  engine: none\na2ui:\n  enabled: false\nmodes:\n  agent:\n    plan:\n      memory:\n        enabled: false\n    fast:\n      memory:\n        enabled: false\n  code:\n    memory:\n      enabled: false\n',encoding='utf-8')
    initialize()


def create_facade():
    # Imports are deferred until every SDK-owned data location is on D:.
    from jiuwenswarm.server.runtime.agent_adapter.interface import JiuWenSwarm
    from jiuwenswarm.server.runtime.agent_adapter.agent_adapters import AgentAdapter
    from jiuwenswarm.common.schema.agent import AgentResponse, AgentResponseChunk

    class JsonPlanningAdapter:
        """Actual AgentAdapter implementation, with no browser/file/shell tools."""
        async def create_instance(self,config=None,*,mode='agent',sub_mode=None):pass
        async def reload_agent_config(self,config_base=None,env_overrides=None,target_session_id=None):
            raise ValueError('Runtime profile cannot be reconfigured over E2A')
        async def process_message_impl(self,request,inputs):
            model=ModelClient('deepseek',max_calls=1)
            # Query contains the upstream strict schema and fresh observations.
            # Final schema validation is also performed by the calling kernel.
            answer=await model.complete('bounded_swarm_planning',{'planning_request':request.params['query']},PlanningObject)
            return AgentResponse(request_id=request.request_id,channel_id=request.channel_id,
                payload={'event_type':'chat.final','content':json.dumps(answer.model_dump(),ensure_ascii=False),'usage':model.usage(), 'runtime_profile':PROFILE})
        async def process_message_stream_impl(self,request,inputs):
            result=await self.process_message_impl(request,inputs)
            yield AgentResponseChunk(request_id=request.request_id,channel_id=request.channel_id,payload=result.payload,is_complete=True)
        async def process_interrupt(self,request):
            raise ValueError('Cancel the calling kernel job to close its planning request')
        async def handle_user_answer(self,request):
            raise ValueError('Approvals belong to the VerifyAgent tool kernel')
        async def handle_heartbeat(self,request):return None

    class RestrictedFacade(JiuWenSwarm):
        # The SDK factory currently selects only general harness/pi adapters.
        # This version-pinned protected hook injects the documented protocol;
        # no monkeypatch or SDK source modification is performed.
        def _ensure_adapter(self,*,mode='agent'):
            if self._adapter is None:
                adapter=JsonPlanningAdapter()
                assert isinstance(adapter,AgentAdapter)
                self._adapter=adapter
                self._sdk_name='yanzhen-json-planner'
            return self._adapter
    return RestrictedFacade()


async def serve(port=8774):
    initialize_runtime()
    from jiuwenswarm.common.e2a.models import E2AEnvelope
    from jiuwenswarm.common.e2a.wire_codec import encode_agent_chunk_for_wire
    from jiuwenswarm.common.schema.agent import AgentRequest, AgentResponseChunk
    from jiuwenswarm.common.schema.message import ReqMethod
    from websockets.asyncio.server import serve as websocket_serve
    key=os.getenv('YZ_SWARM_PROXY_KEY','')
    if len(key)<32 or os.getenv('YZ_ENABLE_MODEL')!='1':
        raise ValueError('Set a private YZ_SWARM_PROXY_KEY and explicitly enable the model')
    config_file=ROOT/'.artifacts'/'swarm-runtime'/'config'/'config.yaml'
    import yaml
    configured=yaml.safe_load(config_file.read_text(encoding='utf-8'))
    if configured.get('auto_memory_enabled') or configured.get('memory',{}).get('mode')!='local' or configured.get('memory',{}).get('engine')!='none' or configured.get('a2ui',{}).get('enabled'):
        raise ValueError('This dedicated profile requires disabled memory and A2UI')
    config_hash=hashlib.sha256(config_file.read_bytes()).hexdigest()
    facade=create_facade()
    limiter=asyncio.Semaphore(2)

    async def handle(socket):
        if not hmac.compare_digest(socket.request.headers.get('Authorization',''),'Bearer '+key):
            await socket.close(code=1008,reason='Private planning credential required');return
        await socket.send(json.dumps({'type':'event','event':'connection.ack','runtime_profile':PROFILE,'native_tools':[],
            'budget_ledger_hash':hashlib.sha256(str(destination()).encode()).hexdigest(),'budget_limit_cny':os.getenv('YZ_VERIFY_BUDGET_CNY','0')}))
        async for wire in socket:
            envelope=E2AEnvelope.from_dict(json.loads(wire))
            try:
                params=envelope.params or {}
                if envelope.method!='chat.send' or params.get('mode')!='agent.plan' or not isinstance(params.get('query'),str):
                    raise ValueError('This profile accepts bounded JSON planning chat.send only')
                if len(params['query'].encode())>100000 or not re.fullmatch(r'yanzhen-[a-f0-9]{32}',envelope.session_id or '') or not re.fullmatch(r'[a-f0-9]{32}',envelope.request_id or ''):
                    raise ValueError('Invalid bounded planning request')
                if hashlib.sha256(config_file.read_bytes()).hexdigest()!=config_hash:
                    raise ValueError('Runtime profile changed; restart after reviewing configuration')
                # Only a fixed D: workspace and query cross the facade boundary.
                request=AgentRequest(request_id=envelope.request_id,session_id=envelope.session_id,channel_id='web',req_method=ReqMethod.CHAT_SEND,
                    params={'query':params['query'],'mode':'agent.plan','project_dir':str(ROOT/'.artifacts'/'swarm-workspace')},enable_memory=False,agent_ref=envelope.agent_ref)
                async with limiter,asyncio.timeout(80):
                    response=await facade.process_message(request)
                payload=response.payload if response.ok else {'error':'Swarm facade rejected planning request'}
            except Exception as exc:
                # Detailed metered call records are already stored privately.
                payload={'error':type(exc).__name__}
            chunk=AgentResponseChunk(request_id=envelope.request_id,channel_id='web',payload=payload,is_complete=True,agent_ref=envelope.agent_ref)
            await socket.send(json.dumps(encode_agent_chunk_for_wire(chunk,response_id=envelope.request_id,sequence=0),ensure_ascii=False))

    async with websocket_serve(handle,'127.0.0.1',port,max_size=150000):
        print(json.dumps({'runtime_profile':PROFILE,'listen':f'ws://127.0.0.1:{port}','sdk_version':'0.2.3','native_tools':[],'cost_ledger_shared':True}),flush=True)
        await asyncio.Event().wait()


if __name__=='__main__':
    asyncio.run(serve(int(os.getenv('YZ_SWARM_PORT','8774'))))
