"""API-driven, repeatable local demos with explicit fixture-write consent."""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

import httpx

from .examples import authorization, persistence, target, AUTH_REQUIREMENT, SAVE_REQUIREMENT


def call(client, path, body=None):
    response=client.request('GET' if body is None else 'POST','/api/verify'+path,json=body)
    response.raise_for_status()
    return response.json()


def wait(client, identifier: str, approve_fixture_writes=False, timeout=180):
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        run=call(client,'/runs/'+identifier)
        if run['status']=='waiting_approval':
            if not approve_fixture_writes:
                raise ValueError('Action approval is pending in the workbench; no write was automatically approved')
            pending=run['pending_approval']
            call(client,'/runs/'+identifier+'/approve',{'digest':pending['digest'],'approved':True,'reviewer':'explicit-local-fixture-demo'})
        if run['status'] in {'completed','error','cancelled'}:return run
        time.sleep(.15)
    raise TimeoutError('Demo wait budget exhausted; inspect/cancel the recorded job')


def prepare(client, target_origin: str, kind: str, variant: str, *, api_only=False, provider='manual'):
    if urlsplit(target_origin).hostname not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('The built-in demo only operates on an explicitly authorized loopback fixture')
    t=target(target_origin,variant,'api' if api_only or kind=='authorization' else 'web')
    t=call(client,'/targets',t.model_dump(mode='json'))
    contract,actions=authorization() if kind=='authorization' else persistence(api_only=api_only)
    body={'requirements':AUTH_REQUIREMENT if kind=='authorization' else SAVE_REQUIREMENT,'target_id':t['id'],'provider':provider}
    if provider=='manual':body['supplied']={'contracts':[contract.model_dump(mode='json')]}
    bundle=call(client,'/analyze',body)
    if provider!='manual':
        print(json.dumps(bundle,ensure_ascii=False,indent=2))
        if input('Review all generated predicates and assumptions. Type FREEZE to confirm this version: ')!='FREEZE':
            raise ValueError('Generated contract was not confirmed')
    bundle=call(client,'/bundles/'+bundle['id']+'/freeze',{'digest':bundle['digest'],'confirmed':True,'accept_assumptions':True,'reviewer':'local-fixture-demo' if provider=='manual' else 'interactive-user'})
    request={'bundle_id':bundle['id'],'planner':provider,'manual_actions':[a.model_dump(mode='json') for a in actions] if provider=='manual' else []}
    return bundle,request


def run_demo(origin: str, target_origin: str, kind: str, variant: str, *, provider='manual', approve_fixture_writes=False, allow_model=False):
    if provider!='manual' and not allow_model:
        raise ValueError('Real model calls require the explicit --allow-model flag and configured credentials')
    with httpx.Client(base_url=origin,timeout=200,trust_env=False) as client:
        bundle,request=prepare(client,target_origin,kind,variant,provider=provider)
        job=call(client,'/runs',request)
        run=wait(client,job['id'],approve_fixture_writes)
        return {'run_id':run['id'],'status':run['status'],'planner':run['planner'],'contract_digest':bundle['digest'],'results':run['results'],
                'evidence_count':len(run['evidence']),'trusted_actions':len(run['trace']),'usage':run['usage'],'error':run['error']}
