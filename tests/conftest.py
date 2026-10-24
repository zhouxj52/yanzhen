import pytest

from yanzhen import store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ARTIFACTS", tmp_path)
    return tmp_path
