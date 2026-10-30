"""Offline protocol/metric tests; upstream applications are exercised by the CLI."""
from copy import deepcopy
import json

import pytest

from scripts import benchmark_upstream as benchmark


def test_registered_projects_sources_and_unique_cases():
    cases=benchmark.expanded_inventory()
    assert len(cases)==49 and len({c['id'] for c in cases})==49
    assert len({c['project'] for c in cases})==5
    defects=[benchmark.label_row(c) for c in cases if c['expected']=='fail']
    assert len(defects)==6 and len({c['defect_group'] for c in defects})==2
    lock=benchmark.static_lock()
    assert {r['commit'] for r in lock['repositories']}=={'adc66a181a67049fb413c8862181ddc6c45ba22b','21973263ba859ff3477919087b488157f9d618a6'}
    for case in cases:
        assert all(p.source.quote in case['requirement'] for p in case['contract'].postconditions)


def test_unexecuted_and_blocked_cases_cannot_inflate_scores():
    rows=[]
    for identifier,expected,actual,executed,status,group in [
        ('healthy','pass','pass',True,'completed',None),('false-positive','pass','fail',True,'completed',None),
        ('down','pass','blocked',False,'not_started',None),('bug','fail','fail',True,'completed','shared-bug'),
        ('bug-again','fail','blocked',True,'error','shared-bug'),('miss','fail','pass',True,'completed','other-bug')]:
        rows.append({'id':identifier,'actual':actual,'executed':executed,'run_status':status,
                     'label':{'expected_verdict':expected,'defect_group':group}})
    summary=benchmark.summarize_expanded(rows)
    assert summary['registered_cases']==6 and summary['executed_cases']==5 and summary['completed_cases']==4
    assert summary['detection_fraction']=={'numerator':1,'denominator':3}
    assert summary['false_positive_fraction']=={'numerator':1,'denominator':3}
    assert summary['blocked_or_unclear']==2 and summary['labelled_defect_groups']==2
    assert summary['autonomous_success_rate'] is None


def test_preregistered_labels_and_denominator_are_audited(tmp_path):
    from yanzhen.verifyagent.schema import digest
    protocol={'cases':[{'id':'unavailable','label':{'expected_verdict':'pass','defect_group':None}}]}
    (tmp_path/'protocol.json').write_text(json.dumps(protocol),encoding='utf-8')
    report={'protocol_digest':digest(protocol),'cases':[{'id':'unavailable','actual':'pass','label':protocol['cases'][0]['label']}], 'summary':{}}
    file=tmp_path/'report.json';file.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(ValueError,match='Unexecuted'):benchmark.audit_expanded(file)
    report['cases'][0]['label']={'expected_verdict':'fail','defect_group':None}
    file.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(ValueError,match='Ground-truth'):benchmark.audit_expanded(file)
    report['cases']=[];file.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(ValueError,match='denominator'):benchmark.audit_expanded(file)
