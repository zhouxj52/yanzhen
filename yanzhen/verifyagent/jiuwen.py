"""Official openJiuwen Workflow runtime with a budgeted, tool-disabled model node."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import os
import uuid

SDK_VERSION = '0.1.19.post2'


def availability():
    from ..settings import model_config
    provider = os.getenv('YZ_OPENJIUWEN_MODEL_PROVIDER', 'deepseek')
    try:
        installed = version('openjiuwen')
    except PackageNotFoundError:
        installed = None
    config = model_config(provider) if provider in {'deepseek', 'qwen'} else {}
    return {'sdk_version': installed, 'required_version': SDK_VERSION, 'installed': installed == SDK_VERSION,
            'model_provider': provider, 'enabled': bool(config.get('enabled')),
            'configured': bool(config.get('key')) or bool(config.get('allow_no_key')),
            'ready': installed == SDK_VERSION and bool(config.get('enabled')) and (bool(config.get('key')) or bool(config.get('allow_no_key'))),
            'scope': 'Official Workflow runtime; metered model planning; independent execution and acceptance oracle'}


async def complete(parent, task, data, schema):
    from .. import store
    from .planning import ModelClient, ModelUnavailable
    from .schema import now
    status = availability()
    if not status['installed']:
        raise ModelUnavailable(f'Install the competition runtime: uv pip install ".[openjiuwen]" (openjiuwen=={SDK_VERSION})')
    if not status['enabled'] or not status['configured']:
        raise ModelUnavailable('openJiuwen requires YZ_ENABLE_MODEL=1 and a configured YZ_OPENJIUWEN_MODEL_PROVIDER; no fallback was performed')
    # Configure before importing Workflow. The SDK only sees non-sensitive status
    # objects; requirements, credentials and model output stay in our metered node.
    from openjiuwen.core.common.logging.log_config import log_config
    log_config.load_from_dict({'log_path': str(store.ARTIFACTS / 'verifyagent' / 'openjiuwen-logs'),
                              'level': 'ERROR', 'output': ['file'], 'interface_output': ['file'], 'performance_output': ['file']})
    from openjiuwen.core.workflow import Workflow, WorkflowCard, WorkflowComponent, create_workflow_session

    workflow_id = 'verifyagent-' + uuid.uuid4().hex
    events, result, original_error = [], None, None
    inner = ModelClient(status['model_provider'], max_calls=1, client=parent.client)

    class Node(WorkflowComponent):
        def __init__(self, name):
            super().__init__()
            self.name = name

        async def invoke(self, inputs, session, context):
            nonlocal result, original_error
            events.append({'node': self.name, 'state': 'started', 'timestamp': now()})
            try:
                if self.name == 'model_planning':
                    result = await inner.complete(task, data, schema)
                elif self.name == 'schema_validation':
                    result = schema.model_validate(result.model_dump(mode='json'))
            except Exception as exc:
                original_error = exc
                events.append({'node': self.name, 'state': 'error', 'timestamp': now(), 'error_type': type(exc).__name__})
                raise
            events.append({'node': self.name, 'state': 'completed', 'timestamp': now()})
            return {'completed': True}

    flow = Workflow(card=WorkflowCard(id=workflow_id, name='VerifyAgent bounded planning', version='1.0'))
    flow.set_start_comp('request', Node('request'))
    flow.add_workflow_comp('model_planning', Node('model_planning'), max_retries=0)
    flow.add_workflow_comp('schema_validation', Node('schema_validation'), max_retries=0)
    flow.set_end_comp('return', Node('return'))
    for a, b in [('request', 'model_planning'), ('model_planning', 'schema_validation'), ('schema_validation', 'return')]:
        flow.add_connection(a, b)
    metadata = {'framework': 'openjiuwen', 'sdk_version': SDK_VERSION, 'workflow_id': workflow_id,
                'model_provider': status['model_provider'], 'nodes': events, 'native_tools': []}
    parent.calls[-1]['runtime'] = metadata
    try:
        output = await flow.invoke({'task': task}, create_workflow_session(session_id=workflow_id))
        if result is None or not any(e['node'] == 'return' and e['state'] == 'completed' for e in events):
            raise ModelUnavailable('openJiuwen workflow did not reach its return node')
        metadata['state'] = str(output.state)
        return result.model_dump(mode='json'), inner.calls[-1].get('usage', {})
    except Exception:
        if original_error:
            raise original_error
        raise
    finally:
        parent.last_candidate = inner.last_candidate
        parent.calls[-1]['underlying_call'] = inner.calls[-1] if inner.calls else None
