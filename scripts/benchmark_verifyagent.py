"""Measured local kernel regression. Model comparisons are explicitly NOT RUN."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

from yanzhen.settings import ROOT
from yanzhen.verifyagent.demo import call, prepare, wait


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',default='http://127.0.0.1:8767')
    parser.add_argument('--target-origin',default='http://127.0.0.1:8771')
    parser.add_argument('--approve-local-fixture-writes',action='store_true')
    args=parser.parse_args()
    if not args.approve_local_fixture_writes:
        parser.error('This benchmark repeats local fixture writes; pass --approve-local-fixture-writes explicitly')
    rows=[]
    with httpx.Client(base_url=args.origin,timeout=220,trust_env=False) as client:
        for kind,variant,expected in [('authorization','healthy','pass'),('authorization','auth_bug','fail'),('persistence','healthy','pass'),('persistence','persistence_bug','fail')]:
            bundle,request=prepare(client,args.target_origin,kind,variant,api_only=True)
            start=time.monotonic();run=wait(client,call(client,'/runs',request)['id'],True)
            rows.append({'case':kind+'/'+variant,'expected':expected,'actual':run['results'][0]['verdict'],'run_id':run['id'],'bundle_id':bundle['id'],'contract_digest':bundle['digest'],
                         'elapsed_ms':round((time.monotonic()-start)*1000),'target_version':'local-orders-notes-v1','mode':'explicit_manual_plan_actual_tools'})
        # Same generic schema/executor, new domain and URLs; no new adapter code.
        for variant,expected in [('healthy','pass'),('negative','fail'),('unavailable','blocked')]:
            t=call(client,'/targets',{'name':'Inventory development holdout '+variant,'base_url':args.target_origin+'/inventory/'+variant+'/', 'interface':'api','environment':'local','authorized':True})
            c={'id':'stock-boundary','title':'可用库存非负','probes':[{'id':'stock','source_type':'http_json','url':'stock','pointer':'/available'}],
               'postconditions':[{'id':'nonnegative','left':'stock','op':'gte','expected':0,'source':{'quote':'可用库存不能为负数。'}}]}
            b=call(client,'/analyze',{'requirements':'可用库存不能为负数。','target_id':t['id'],'provider':'manual','supplied':{'contracts':[c]}})
            call(client,'/bundles/'+b['id']+'/freeze',{'digest':b['digest'],'confirmed':True,'reviewer':'development-holdout-protocol'})
            start=time.monotonic();run=wait(client,call(client,'/runs',{'bundle_id':b['id'],'planner':'manual','manual_actions':[{'id':'read-stock','kind':'http_request','url':'stock'}]})['id'],True)
            rows.append({'case':'inventory-holdout/'+variant,'expected':expected,'actual':run['results'][0]['verdict'],'run_id':run['id'],'elapsed_ms':round((time.monotonic()-start)*1000),'target_version':'holdout-inventory-v1','mode':'explicit_manual_plan_actual_tools'})
        failed=next(r for r in rows if r['case']=='persistence/persistence_bug')
        reduction=call(client,'/runs/'+failed['run_id']+'/minimize/durable-note',{'confirmed':True,'budget':10})
        # Audit the same witnessed source; a digest change must be refused.
        report=call(client,'/runs/'+failed['run_id'])
        bad=[t['action'] for t in report['trace']]
        review=call(client,'/runs/'+failed['run_id']+'/repair-review/durable-note',{'actions':bad,'contract_digest':'tampered'})
        from yanzhen.verifyagent.examples import target as fixture_target
        healthy_target=call(client,'/targets',fixture_target(args.target_origin,'healthy','api').model_dump(mode='json'))
        repair=call(client,'/runs/'+failed['run_id']+'/repair/durable-note',{'kind':'external_target','candidate_target_id':healthy_target['id'],'contract_digest':failed['contract_digest']})
        repaired=wait(client,repair['run']['id'],True)
    bugs=[r for r in rows if r['expected']=='fail'];normal=[r for r in rows if r['expected']=='pass']
    output={'status':'passed' if all(r['expected']==r['actual'] for r in rows) and reduction['status']=='verified' and repaired.get('repair_validation',{}).get('verified') else 'failed',
            'scope':'Controlled manual-plan kernel regression, not an autonomous LLM benchmark or real-world generalization study',
            'cases':rows,'metrics':{'contract_generation_validity':{'status':'NOT RUN','reason':'No real model inference'},'requirement_coverage':{'status':'NOT RUN','reason':'No independently labeled natural-language corpus'},
            'controlled_defect_detection_rate':sum(r['actual']=='fail' for r in bugs)/len(bugs),'controlled_false_positive_rate':sum(r['actual']=='fail' for r in normal)/len(normal),
            'reproduction_success':{'successful':int(reduction['status']=='verified'),'attempted_cases':1,'independent_confirmations':reduction['confirmations']},
            'planned_step_reduction_rate':1-reduction['reduced_planned_steps']/reduction['original_planned_steps'],'invalid_repair_interception':{'blocked':int(not review['accepted']),'tested':1},
            'mean_execution_ms':statistics.mean(r['elapsed_ms'] for r in rows),'llm_tokens':0,'estimated_llm_cost':0},
            'reduction':reduction,'repair_run_id':repaired['id'],'same_oracle_repair':repaired.get('repair_validation'),
            'comparisons':{'baseline_A':{'status':'RUN','definition':'Fixed human-authored DSL plan through the deterministic kernel; freeze/probes retained'},'baseline_B':{'status':'NOT RUN','reason':'Real LLM static-plan baseline not implemented/run in this slice'},'full_agent':{'status':'NOT RUN','reason':'Separate comparative protocol not run; live DeepSeek and bounded Swarm smoke runs are recorded separately'}},
            'ablations':{key:{'status':'NOT RUN','reason':'Requires a separately reviewed real-model experiment protocol'} for key in ('no_replanning','no_cross_layer_evidence','no_minimization','no_repair_review')}}
    destination=ROOT/'.artifacts'/'verifyagent-benchmark.json';destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':output['status'],'cases':len(rows),'metrics':output['metrics'],'report':str(destination)},ensure_ascii=False,indent=2))
    raise SystemExit(0 if output['status']=='passed' else 1)


if __name__=='__main__':main()
