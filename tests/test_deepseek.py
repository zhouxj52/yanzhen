"""Protocol tests use mocked HTTP responses, never real credentials or inference."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from yanzhen.app import app
from yanzhen.models import AnalyzeRequest, TODO_REQUIREMENTS
from yanzhen.planner import analyze, offline_contracts
from yanzhen.settings import model_config


def setup_deepseek(monkeypatch):
    monkeypatch.setenv("YZ_ENABLE_MODEL","1")
    monkeypatch.setenv("YZ_DEEPSEEK_API_KEY","mock-deepseek-secret")
    monkeypatch.setenv("YZ_LLM_API_KEY","mock-other-provider-secret")
    monkeypatch.setenv("YZ_DEEPSEEK_BASE_URL","https://api.deepseek.com")
    monkeypatch.setenv("YZ_DEEPSEEK_MODEL","deepseek-flash")


def test_deepseek_uses_its_own_endpoint_key_json_mode_and_records_provider(monkeypatch):
    setup_deepseek(monkeypatch)
    contracts=[c.model_dump() for c in offline_contracts(TODO_REQUIREMENTS,"todomvc")]
    def respond(request):
        assert str(request.url)=="https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"]=="Bearer mock-deepseek-secret"
        body=json.loads(request.content)
        assert body["model"]=="deepseek-flash"
        assert body["thinking"]=={"type":"disabled"}
        assert body["response_format"]=={"type":"json_object"}
        assert "json" in body["messages"][0]["content"]
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps({"contracts":contracts},ensure_ascii=False)},"finish_reason":"stop"}],"usage":{"total_tokens":321}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc",provider="deepseek"),client)
    bundle=asyncio.run(run())
    assert bundle.provider=="deepseek" and bundle.model=="deepseek-flash"
    assert bundle.usage["total_tokens"]==321
    assert len(bundle.contracts)==3
    assert bundle.digest==bundle.calculate_digest()


def test_deepseek_missing_key_does_not_reuse_other_provider_key(monkeypatch):
    setup_deepseek(monkeypatch)
    monkeypatch.delenv("YZ_DEEPSEEK_API_KEY")
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    assert model_config("deepseek")["key"]==""
    with pytest.raises(ValueError,match="YZ_DEEPSEEK_API_KEY"):
        asyncio.run(analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc",provider="deepseek")))


def test_deepseek_disabled_gate_blocks_calls_even_with_a_key(monkeypatch):
    setup_deepseek(monkeypatch)
    monkeypatch.setenv("YZ_ENABLE_MODEL","0")
    with pytest.raises(ValueError,match="未启用"):
        asyncio.run(analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc",provider="deepseek")))


def test_public_config_never_exposes_provider_secrets(monkeypatch):
    setup_deepseek(monkeypatch)
    with TestClient(app) as client:
        response=client.get("/api/config")
    data=response.json()
    assert data["providers"]["deepseek"]=={"label":"DeepSeek","model":"deepseek-flash","enabled":True,"configured":True}
    assert "mock-deepseek-secret" not in response.text
    assert "mock-other-provider-secret" not in response.text
    assert "key" not in data["providers"]["deepseek"]


@pytest.mark.parametrize("variant,match",[("unauthorized","HTTP 401"),("empty","空内容"),("none","空内容"),("truncated","截断"),("invalid","有效验收契约"),("no_choices","有效验收契约")])
def test_deepseek_errors_do_not_silently_return_rule_results(monkeypatch,variant,match):
    setup_deepseek(monkeypatch)
    def respond(request):
        if variant=="unauthorized":
            return httpx.Response(401,json={"error":{"message":"invalid key"}})
        if variant=="no_choices":
            return httpx.Response(200,json={"choices":[]})
        content={"empty":"","none":None,"truncated":"{","invalid":"not json"}[variant]
        return httpx.Response(200,json={"choices":[{"message":{"content":content},"finish_reason":"length" if variant=="truncated" else "stop"}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await analyze(AnalyzeRequest(requirements=TODO_REQUIREMENTS,target="todomvc",provider="deepseek"),client)
    with pytest.raises(ValueError,match=match):
        asyncio.run(run())
