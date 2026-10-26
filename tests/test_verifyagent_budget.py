import json
import pytest
from yanzhen.verifyagent.budget import reserve, finish, destination, BudgetExceeded


def setup(monkeypatch,limit='5'):
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY',limit)
    monkeypatch.setenv('YZ_VERIFY_PRICED_MODEL','deepseek-flash')
    monkeypatch.setenv('YZ_VERIFY_INPUT_CNY_PER_MILLION','2')
    monkeypatch.setenv('YZ_VERIFY_OUTPUT_CNY_PER_MILLION','8')


def test_budget_is_reserved_before_call_and_not_refunded_after_unknown_failure(monkeypatch):
    setup(monkeypatch)
    entry=reserve('deepseek','deepseek-flash',[{'role':'user','content':'hello'}],4000)
    finish(entry,'error')
    ledger=json.loads(destination().read_text())
    assert float(ledger['reserved_upper_cny'])>0
    assert ledger['records'][0]['status']=='error'
    assert 'hello' not in destination().read_text()
    assert ledger['limit_cny']=='5'


def test_budget_blocks_before_sending_and_binds_price_to_model(monkeypatch):
    setup(monkeypatch,'0.001')
    with pytest.raises(BudgetExceeded,match='budget'):
        reserve('deepseek','deepseek-flash',[{'role':'user','content':'hello'}],4000)
    setup(monkeypatch)
    with pytest.raises(BudgetExceeded,match='bound'):
        reserve('deepseek','different-model',[],4000)
    with pytest.raises(BudgetExceeded,match='envelope'):
        reserve('deepseek','deepseek-flash',[{'content':'x'*120001}],4000)
