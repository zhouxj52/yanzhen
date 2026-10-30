"""Four-role openJiuwen execution: three metered model roles and a deterministic auditor."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from .schema import Strict, Decision, GenericContract, Target, digest, now
from .oracle import operation_gaps


class Analysis(Strict):
    probe_ids: list[str] = Field(max_length=30)
    business_goal: str = Field(min_length=1, max_length=800)


class Challenge(Strict):
    focus: Literal['persistence', 'authorization', 'boundary', 'consistency', 'general']
    probe_ids: list[str] = Field(max_length=30)
    concern: str = Field(min_length=1, max_length=800)


async def complete(parent, task, data, schema):
    from .. import store
    from .planning import ModelClient, ModelUnavailable
    from .jiuwen import availability, SDK_VERSION
    status = availability()
    if not status['ready']:
        raise ModelUnavailable('openJiuwen 多角色模式需要固定版本 SDK 和已启用的真实模型；不会切换成人工响应')
    if task not in {'exploration', 'exploration_schema_repair'} or schema is not Decision:
        raise ValueError('Multi-role execution consumes an already frozen contract; draft with the normal openJiuwen provider')
    from openjiuwen.core.common.logging.log_config import log_config
    log_config.load_from_dict({'log_path':str(store.ARTIFACTS/'verifyagent/openjiuwen-logs'), 'level':'ERROR',
                              'output':['file'], 'interface_output':['file'], 'performance_output':['file']})
    from openjiuwen.core.workflow import Workflow, WorkflowCard, WorkflowComponent, create_workflow_session
    contract = GenericContract.model_validate(data['frozen_contract'])
    target_info = data.get('effective_target', {})
    target = Target(name='Anonymous authorized target', base_url=target_info['base_url'], environment='test', authorized=True)
    remaining = parent.max_calls - parent.actual_call_count() + 1  # Replace this just-created wrapper with actual role calls.
    if remaining < 1:
        raise ModelUnavailable('Shared per-run model-call budget exhausted before role execution')
    inner = ModelClient(status['model_provider'], max_calls=remaining, client=parent.client)
    entry = parent.calls[-1]
    entry['underlying_calls'] = inner.calls  # All roles count towards the SAME cap.
    cached = getattr(parent, 'team_context', {})
    parent.team_context = cached
    key = digest({'contract':contract.model_dump(mode='json'), 'target':target_info})
    context = dict(cached.get(key, {}))
    events = []
    workflow_id = 'verify-team-' + uuid.uuid4().hex
    metadata = {'framework':'openjiuwen', 'sdk_version':SDK_VERSION, 'workflow_id':workflow_id, 'nodes':events,
                'model_provider':status['model_provider'], 'native_tools':[],
                'roles':{'requirements':'metered_model', 'challenger':'metered_model', 'executor':'metered_model', 'evidence_auditor':'deterministic'},
                'scope':'Role workflow plans bounded tools; the independent frozen oracle alone computes acceptance'}
    entry['runtime'] = metadata
    decision = None
    original_error = None
    allowed_probes = {p.id for p in contract.probes}

    def record(role, state, **values):
        item = {'role':role, 'node':role, 'state':state, 'timestamp':now(), 'workflow_id':workflow_id, **values}
        events.append(item)
        callback = getattr(parent, 'on_role_event', None)
        if callback: callback(item)

    def validate_refs(value):
        if not set(value.probe_ids) <= allowed_probes:
            raise ValueError('A role invented a probe outside the frozen contract')
        return value

    async def executor_revision(feedback):
        record('evidence_auditor', 'handoff', target_role='executor', summary='必须操作尚未执行，要求执行者补充证据', feedback=feedback)
        revised = await inner.complete('team.executor.revision', {**data, 'role_instruction':'Revise the next action using the auditor feedback. Never edit the frozen contract.',
                                               'analyst':context['analysis'], 'challenge':context['challenge'], 'auditor_feedback':feedback}, Decision)
        record('executor', 'revision', summary=revised.explanation)
        return revised

    class Role(WorkflowComponent):
        def __init__(self, role):
            super().__init__()
            self.role = role

        async def invoke(self, inputs, session, model_context):
            nonlocal decision, original_error
            record(self.role, 'started')
            try:
                reused = False
                if self.role == 'requirements':
                    reused = 'analysis' in context
                    if not reused:
                        value = validate_refs(await inner.complete('team.requirements', {
                            'role_instruction':'Identify the business goal and the exact frozen probe IDs needed to check it. Do not propose new requirements or verdicts.',
                            'frozen_contract':data['frozen_contract']}, Analysis))
                        context['analysis'] = value.model_dump(mode='json')
                    summary = context['analysis']['business_goal']
                elif self.role == 'challenger':
                    reused = 'challenge' in context
                    if not reused:
                        value = validate_refs(await inner.complete('team.challenger', {
                            'role_instruction':'Challenge shallow acceptance: identify a realistic way success feedback could disagree with the business state. Use only existing probe IDs. No source mutation metadata is available to this execution role.',
                            'frozen_contract':data['frozen_contract'], 'analyst':context['analysis']}, Challenge))
                        context['challenge'] = value.model_dump(mode='json')
                    summary = context['challenge']['concern']
                elif self.role == 'executor':
                    decision = await inner.complete('team.executor', {**data,
                        'role_instruction':'Choose one bounded action from the actual observation, or finish. Fulfil every remaining obligation; the auditor may ask for more evidence.',
                        'analyst':context['analysis'], 'challenge':context['challenge']}, Decision)
                    summary = decision.explanation
                elif self.role == 'evidence_auditor':
                    gaps = operation_gaps(contract, data.get('executed_actions', []), target)
                    if decision.finished and gaps:
                        decision = await executor_revision({'missing_operations':gaps})
                    if decision.action:
                        if decision.action.kind in contract.constraints.forbidden_actions:
                            raise ValueError('Auditor rejected an action forbidden by the frozen contract')
                        if decision.action.actor not in target_info.get('actors', ['anonymous']):
                            raise ValueError('Auditor rejected an undeclared test identity')
                    summary = '只审核操作约束与证据义务；终态探针和最终判定交由独立内核执行'
                else:
                    summary = '协作交接完成'
                record(self.role, 'completed', cached=reused, summary=summary)
                return {'role':self.role, 'completed':True}
            except Exception as exc:
                original_error = exc
                record(self.role, 'error', error_type=type(exc).__name__)
                raise

    flow = Workflow(card=WorkflowCard(id=workflow_id, name='VerifyAgent role collaboration', version='1.0'))
    flow.set_start_comp('requirements', Role('requirements'))
    for role in ('challenger', 'executor', 'evidence_auditor'):
        flow.add_workflow_comp(role, Role(role), max_retries=0)
    flow.set_end_comp('return', Role('return'))
    order = ['requirements', 'challenger', 'executor', 'evidence_auditor', 'return']
    for a,b in zip(order, order[1:]): flow.add_connection(a,b)
    try:
        output = await flow.invoke({'request_type':'frozen_contract_execution'}, create_workflow_session(session_id=workflow_id))
        if decision is None or not any(e['role']=='return' and e['state']=='completed' for e in events):
            raise ModelUnavailable('Role workflow did not complete')
        cached[key] = {k:context[k] for k in ('analysis','challenge')}
        metadata['state'] = str(output.state)
        usage = {k:sum(c.get('usage',{}).get(k,0) for c in inner.calls) for k in ('prompt_tokens','completion_tokens')}
        parent.last_candidate = decision.model_dump(mode='json')
        return parent.last_candidate, usage
    except Exception:
        if original_error: raise original_error
        raise
