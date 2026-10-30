"""Traceability must expose omitted requirements and reject unsupported PASS claims."""
from copy import deepcopy
import json
import zipfile

import pytest

from yanzhen.verifyagent.coverage import build_coverage, requirement_spans
from yanzhen.verifyagent.schema import Bundle, Evidence, Run, Action, digest
from yanzhen.verifyagent.oracle import decide


def sample(requirements='刷新后保存内容应保留。其他账户不可读取。附件应能上传。', quote='刷新后保存内容应保留。', required=False):
    contract = {'id':'save','title':'保存与刷新','probes':[{'id':'stored','source_type':'dom_text','locator':{'by':'css','value':'#saved'}}],
                'postconditions':[{'id':'persisted','left':'stored','expected':'验真','source':{'quote':quote}}],
                'constraints':{'required_actions':['reload'] if required else []}}
    bundle=Bundle(requirements=requirements,target_id='a'*32,provider='manual',contracts=[contract])
    bundle.frozen=True;bundle.digest=bundle.calculate_digest()
    run=Run(bundle_id=bundle.id,target_id=bundle.target_id,contract_digest=bundle.digest,planner='manual',status='completed')
    evidence=Evidence(run_id=run.id,contract_id='save',action_id='reload',source_type='dom_text',observed_value='验真',
                      provenance={'executor':'yanzhen.verifyagent.ToolExecutor/v1','probe_id':'stored','phase':'after','ok':True}).seal()
    run.evidence.append(evidence)
    run.results.append(decide(bundle.contracts[0],{'stored':evidence},[]))
    return bundle,run


def test_unquoted_requirements_remain_in_denominator():
    bundle,run=sample()
    report=build_coverage(bundle,run)
    assert report['summary']['total']==3 and report['summary']['verified']==1
    assert report['summary']['uncovered']==2
    assert [r['state'] for r in report['requirements']]==['verified','uncovered','uncovered']
    assert report['requirements'][0]['checks'][0]['evidence'][0]['value']=='验真'
    assert bundle.digest==bundle.calculate_digest()


def test_precondition_only_is_not_outcome_coverage():
    bundle,run=sample()
    c=bundle.contracts[0]
    c.probes.append(c.probes[0].model_copy(update={'id':'prerequisite','phase':'before'}))
    c.preconditions.append(c.postconditions[0].model_copy(update={'id':'pre','left':'prerequisite','source':{'quote':'其他账户不可读取。'}}))
    # Use the validated source type, not an unvalidated dict in model_copy.
    from yanzhen.verifyagent.schema import Source
    c.preconditions[-1].source=Source(quote='其他账户不可读取。')
    bundle.digest=bundle.calculate_digest();run.contract_digest=bundle.digest
    report=build_coverage(bundle,run)
    assert report['requirements'][1]['state']=='uncovered'
    assert report['requirements'][1]['checks'][0]['group']=='preconditions'


@pytest.mark.parametrize('tamper',['value','wrong_run','wrong_contract','wrong_probe','wrong_phase','missing_reference','frozen_contract'])
def test_tampered_or_unrelated_evidence_never_counts_verified(tamper):
    bundle,run=sample()
    evidence=run.evidence[0]
    if tamper=='value':evidence.observed_value='伪造'
    elif tamper=='wrong_run':evidence.run_id='another';evidence.seal()
    elif tamper=='wrong_contract':evidence.contract_id='another';evidence.seal()
    elif tamper=='wrong_probe':evidence.provenance['probe_id']='another';evidence.seal()
    elif tamper=='wrong_phase':evidence.provenance['phase']='before';evidence.seal()
    elif tamper=='missing_reference':run.results[0]['assertions'][0]['evidence_ids']=[]
    else:bundle.contracts[0].postconditions[0].expected='changed'
    report=build_coverage(bundle,run)
    assert report['requirements'][0]['state']=='blocked'
    assert report['summary']['verified']==0


def test_partial_quote_and_repeated_quotes_require_review():
    bundle,run=sample('刷新后保存内容应保留且能独立读取。','保存内容应保留')
    row=build_coverage(bundle,run)['requirements'][0]
    assert row['state']=='partial' and '独立读取' in row['unlinked_text']
    bundle,run=sample('保存应成功。保存应成功。','保存应成功。')
    assert [r['state'] for r in build_coverage(bundle,run)['requirements']]==['unclear','unclear']


def test_missing_or_fake_required_operation_blocks_a_passing_probe():
    bundle,run=sample(required=True)
    assert build_coverage(bundle,run)['requirements'][0]['state']=='blocked'
    run.trace=[{'contract_id':'save','action':Action(id='fake',kind='reload').model_dump(),'ok':True,'evidence_id':'no-witness','action_digest':'fake'}]
    assert build_coverage(bundle,run)['requirements'][0]['state']=='blocked'


def test_failed_pending_and_cancelled_requirements():
    bundle,run=sample()
    run.evidence[0].observed_value='';run.evidence[0].seal()
    run.results=[decide(bundle.contracts[0],{'stored':run.evidence[0]},[])]
    assert build_coverage(bundle,run)['requirements'][0]['state']=='failed'
    assert build_coverage(bundle)['requirements'][0]['state']=='not_run'
    run.results=[];run.status='cancelled'
    assert build_coverage(bundle,run)['requirements'][0]['state']=='blocked'


def test_original_offsets_unicode_urls_and_decimal_numbers():
    text='  保存 3.14 元。\n邮箱 a@example.test 应可见。最后一条! '
    rows=requirement_spans(text)
    assert len(rows)==3
    assert all(text[r['start']:r['end']]==r['text'] for r in rows)


def test_export_and_legacy_artifact_fallback(tmp_path):
    from fastapi.testclient import TestClient
    from yanzhen.app import create_app
    from yanzhen.store import write_json
    from yanzhen.verifyagent import repository as repo
    from yanzhen.verifyagent.exports import export
    from yanzhen.verifyagent.schema import Target
    bundle,run=sample()
    target=Target(id=bundle.target_id,name='Archived target',base_url='http://127.0.0.1:59999/',authorized=True,environment='local')
    repo.save_target(target)
    # Save before marking it frozen; frozen semantics stay intact afterwards.
    write_json(repo.path('bundles',bundle.id)/'bundle.json',bundle.model_dump(mode='json'))
    write_json(repo.path('runs',run.id)/'contract.json',bundle.model_dump(mode='json'));repo.save_run(run)
    export(run)
    with zipfile.ZipFile(repo.path('runs',run.id)/'evidence.zip') as z:
        coverage=json.loads(z.read('requirement-coverage.json'))
        assert coverage['summary']['uncovered']==2
        assert 'requirement-coverage.json' in json.loads(z.read('manifest.json'))['files']
    with TestClient(create_app()) as client:
        report=client.get('/api/verify/runs/'+run.id).json()
        assert report['coverage']['summary']==coverage['summary']
        assert client.get('/api/verify/bundles/'+bundle.id+'/coverage').json()['summary']['uncovered']==2
        (repo.path('runs',run.id)/'requirement-coverage.json').unlink()
        download=client.get('/api/verify/runs/'+run.id+'/artifacts/requirement-coverage.json')
        assert download.status_code==200 and download.json()['summary']==coverage['summary']
