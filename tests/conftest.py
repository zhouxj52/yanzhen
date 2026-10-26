import pytest

from yanzhen import store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ARTIFACTS", tmp_path)
    # Protocol mocks never spend money or share the real session's paid-call ledger.
    monkeypatch.setenv('YZ_VERIFY_BUDGET_CNY','0')
    return tmp_path
