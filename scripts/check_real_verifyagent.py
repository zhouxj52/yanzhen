"""Run one explicitly user-reviewed local demo contract with real model planning.

No model response, tool result, approval or verdict is fabricated here. The two
consent flags are intentional, and the script never creates or edits a contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--origin',default='http://127.0.0.1:8767')
    p.add_argument('--planner',choices=['deepseek','jiuwenswarm'],default='deepseek')
    p.add_argument('--output',type=Path,default=Path('.artifacts/real-model-run.json'))
    p.add_argument('--target-variant',choices=['live_drift'])
    p.add_argument('--parent-run')
    p.add_argument('--confirm-reviewed-contract',action='store_true')
    p.add_argument('--approve-local-note-writes',action='store_true')
    args=p.parse_args()
    if not args.confirm_reviewed_contract or not args.approve_local_note_writes:
        p.error('Both reviewed-contract confirmation and local-note-write consent are required')
    bundle=json.loads(args.candidate.read_text(encoding='utf-8'))
    with httpx.Client(base_url=args.origin,timeout=30,trust_env=False) as client:
        def api(path,body=None):
            r=client.request('GET' if body is None else 'POST','/api/verify'+path,json=body)
            r.raise_for_status();return r.json()
        target=api('/targets/'+bundle['target_id'])
        if urlsplit(target['base_url']).hostname not in {'127.0.0.1','localhost','::1'} or not target['namespace_header']:
            raise ValueError('This reviewed protocol only permits a namespaced loopback target')
        frozen=api('/bundles/'+bundle['id']+'/freeze',{'digest':bundle['digest'],'confirmed':True,'accept_assumptions':True,'reviewer':'human-user-explicitly-confirmed-2026-10-26'})
        request={'bundle_id':frozen['id'],'planner':args.planner,'max_model_calls':10,'max_seconds':240}
        if args.target_variant:
            if not args.parent_run or urlsplit(target['base_url']).path!='/app/persistence_bug/':
                raise ValueError('Live DOM drift test requires the witnessed original fixture run')
            from yanzhen.verifyagent.examples import target as fixture_target
            parsed=urlsplit(target['base_url'])
            candidate=api('/targets',fixture_target(f'{parsed.scheme}://{parsed.netloc}',args.target_variant,'web').model_dump(mode='json'))
            request.update(candidate_target_id=candidate['id'],parent_run=args.parent_run)
        job=api('/runs',request)
        print(json.dumps({'run_id':job['id'],'frozen_digest':frozen['digest'],'planner':args.planner},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+260
        while time.monotonic()<deadline:
            run=api('/runs/'+job['id'])
            if run['status']=='waiting_approval':
                pending=run['pending_approval'];a=pending['action'];loc=a.get('locator') or {}
                approved=a['actor']=='anonymous' and (
                    a['kind']=='fill' and a['value']=='验真独立验收' and (loc.get('value') in {'备注','#note','input[aria-label="备注"]'}) or
                    a['kind']=='click' and loc.get('value') in {'保存','应用更改','#save','button#save'}
                )
                api('/runs/'+job['id']+'/approve',{'digest':pending['digest'],'approved':approved,'reviewer':'human-approved-bounded-local-note-demo'})
                print(json.dumps({'action':a,'approved_under_user_scope':approved},ensure_ascii=False),flush=True)
            if run['status'] in {'completed','error','cancelled'}:
                destination=args.output
                destination.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'run_id':run['id'],'status':run['status'],'summary':run['summary'],'results':run['results'],'actions':len(run['trace']),'usage':run['usage'],'error':run['error'],'report':str(destination.resolve())},ensure_ascii=False,indent=2))
                raise SystemExit(0 if run['status']=='completed' else 1)
            time.sleep(.2)
        api('/runs/'+job['id']+'/cancel')
        raise TimeoutError('Reviewed real-model demo exceeded its wait budget')


if __name__=='__main__':main()
