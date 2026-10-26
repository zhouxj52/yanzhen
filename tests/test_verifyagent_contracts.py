import asyncio
import pytest
from pydantic import ValidationError

from examples.verifyagent.cases import authorization, AUTH_REQUIREMENT, target
from yanzhen.verifyagent.schema import Bundle, Action, Evidence, Predicate
from yanzhen.verifyagent import repository as repo
from yanzhen.verifyagent.oracle import evaluate
from yanzhen.verifyagent.security import TargetPolicy, PolicyError, origin


def test_generic_contract_not_bound_to_business_catalog():
    contract, _ = authorization()
    contract.id = "previously-unlisted-order-business"
    bundle = Bundle(requirements=AUTH_REQUIREMENT,target_id="a"*32,provider="manual",contracts=[contract])
    bundle.digest=bundle.calculate_digest()
    repo.save_bundle(bundle)
    with pytest.raises(ValueError,match="assumptions"):
        repo.freeze(bundle.id,bundle.digest,"reviewer")
    frozen=repo.freeze(bundle.id,bundle.digest,"reviewer",True)
    frozen.assert_frozen()
    with pytest.raises(ValueError,match="overwritten"):
        repo.save_bundle(frozen)
    frozen.contracts[0].postconditions[0].expected=403
    with pytest.raises(ValueError,match="changed"):
        frozen.assert_frozen()


def test_fabricated_sources_unsafe_actions_and_invalid_probe_bindings():
    c,_=authorization()
    with pytest.raises(ValidationError,match="verbatim"):
        Bundle(requirements="an unrelated requirement",target_id="a"*32,provider="manual",contracts=[c])
    for data in ({"id":"x","kind":"eval","value":"1+1"},{"id":"x","kind":"click"},{"id":"x","kind":"http_request","url":"/","method":"DELETE","retries":1}):
        with pytest.raises(ValidationError):Action.model_validate(data)
    data=c.model_dump();data['postconditions'][0]['left']='made-up'
    with pytest.raises(ValidationError,match="undefined"):
        type(c).model_validate(data)


def test_ambiguous_requirement_can_request_clarification_without_fake_contract():
    b=Bundle(requirements='系统应该表现良好。',target_id='a'*32,provider='manual',clarification_questions=['请说明可量化的业务要求。'])
    b.digest=b.calculate_digest();repo.save_bundle(b)
    with pytest.raises(ValueError,match='clarification'):
        repo.freeze(b.id,b.digest,'reviewer',True)


def test_checkpoint_acknowledgement_cannot_replace_final_business_observation():
    from yanzhen.verifyagent.schema import GenericContract
    c,_=authorization()
    data=c.model_dump()
    data['probes'].append({'id':'ack','source_type':'http_status','url':'api/orders/alice-1','phase':'checkpoint','after_action':'click'})
    data['postconditions'].append({'id':'ack_ok','left':'ack','expected':200,'source':{'quote':AUTH_REQUIREMENT}})
    assert GenericContract.model_validate(data).postconditions[-1].left=='ack'
    data['postconditions']=data['postconditions'][-1:]
    with pytest.raises(ValidationError,match='final observation'):
        GenericContract.model_validate(data)


@pytest.mark.parametrize("url",["http://169.254.169.254/latest/meta-data","http://0.0.0.0/","http://8.8.8.8/","http://example.com/","file:///etc/passwd","http://user:pass@127.0.0.1/"])
def test_ssrf_and_non_test_targets_rejected(url):
    with pytest.raises(PolicyError):origin(url)


def test_allowlist_redirects_and_control_plane(monkeypatch):
    t=target("http://127.0.0.1:8771")
    with pytest.raises(PolicyError,match="allow|ALLOW"):
        TargetPolicy(t,allowed="")
    policy=TargetPolicy(t,allowed="http://127.0.0.1:8771")
    assert policy.validate('api/note')=='http://127.0.0.1:8771/app/healthy/api/note'
    for url in ('http://127.0.0.1:9999/','http://169.254.169.254/','javascript:alert(1)'):
        with pytest.raises(PolicyError):policy.validate(url)


def test_oracle_never_accepts_missing_forged_or_incompatible_evidence():
    p=Predicate(id="required",left="observed",expected=1,source={"quote":"must be one"})
    assert evaluate(p,{})['verdict']=='blocked'
    e=Evidence(run_id='r',contract_id='c',action_id='a',source_type='http_json',observed_value=True,provenance={'ok':True}).seal()
    assert evaluate(p,{'observed':e})['verdict']=='fail'
    e.observed_value=1
    assert evaluate(p,{'observed':e})['verdict']=='blocked'
    e.seal()
    assert evaluate(p,{'observed':e})['verdict']=='pass'


def test_required_urls_use_authorized_target_resolution_without_changing_oracle(monkeypatch):
    from yanzhen.verifyagent.oracle import operation_gaps
    from yanzhen.verifyagent.schema import RequiredOperation
    c,_=authorization();c.constraints.required_operations=[RequiredOperation(kind='navigate',url='.')]
    t=target('http://127.0.0.1:8771','live_drift')
    monkeypatch.setenv('YZ_VERIFY_ALLOWED_ORIGINS','http://127.0.0.1:8771')
    trace=[{'ok':True,'action':Action(id='nav',kind='navigate',url=t.base_url).model_dump()}]
    assert not operation_gaps(c,trace,t)
    trace[0]['action']['url']='http://127.0.0.1:8771/app/healthy/'
    assert operation_gaps(c,trace,t)
