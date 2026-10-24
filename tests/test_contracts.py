import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from yanzhen.guard import approve_locator_repair
from yanzhen.models import AnalyzeRequest, Bundle, Contract, DEFAULT_REQUIREMENTS
from yanzhen.planner import analyze, offline_contracts
from yanzhen.store import freeze_bundle, load_bundle, save_bundle, write_json, bundle_path


def test_unknown_requirements_are_not_silently_accepted():
    result = offline_contracts(DEFAULT_REQUIREMENTS + "\n每天自动生成财务预测。")
    assert len([c for c in result if c.kind != "unclear"]) == 5
    assert any(c.kind == "unclear" and "财务预测" in c.source_quote for c in result)


def test_negative_requirements_do_not_become_positive_demo_contracts():
    result = offline_contracts("管理员不能查看全部成员的报销单。成员不能查看本人的报销单。")
    assert len(result) == 2
    assert all(c.kind == "unclear" for c in result)


def test_frozen_contract_detects_tampering_and_stale_approval():
    bundle = asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS)))
    save_bundle(bundle)
    with pytest.raises(ValueError, match="重新审阅"):
        freeze_bundle(bundle.id, "old-digest")
    frozen = freeze_bundle(bundle.id, bundle.digest)
    frozen.assert_frozen()
    payload = frozen.model_dump(mode="json")
    payload["contracts"][0]["source_quote"] = payload["requirements"]
    write_json(bundle_path(bundle.id), payload)
    with pytest.raises(ValueError, match="更改"):
        load_bundle(bundle.id).assert_frozen()


def test_repair_cannot_relax_assertions_or_change_identity():
    original = offline_contracts(DEFAULT_REQUIREMENTS)[1]
    changed = original.model_copy(update={"expected": "allowed"})
    with pytest.raises(ValueError, match="验收契约"):
        approve_locator_repair(original, changed, action_before="read", action_after="read", witnessed_action="read")
    with pytest.raises(ValueError, match="业务动作"):
        approve_locator_repair(original, original, action_before="read", action_after="delete", witnessed_action="delete")
    assert approve_locator_repair(original, original, action_before="read", action_after="read", witnessed_action="read")["unchanged_contract"]


def test_fabricated_source_and_unsupported_checks_are_rejected():
    original = offline_contracts(DEFAULT_REQUIREMENTS)[0]
    with pytest.raises(ValidationError):
        Contract(**{**original.model_dump(), "kind": "execute_shell"})
    with pytest.raises(ValidationError, match="原文"):
        Bundle(id="a"*32, requirements=DEFAULT_REQUIREMENTS, provider="offline", contracts=[original.model_copy(update={"source_quote": "并不存在的需求"})])


def test_real_provider_uses_http_and_validates_model_output(monkeypatch):
    monkeypatch.setenv("YZ_ENABLE_MODEL", "1")
    monkeypatch.setenv("YZ_LLM_API_KEY", "test-secret-not-a-real-key")
    contracts = [c.model_dump() for c in offline_contracts(DEFAULT_REQUIREMENTS)]
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret-not-a-real-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"contracts": contracts}, ensure_ascii=False)}}], "usage": {"total_tokens": 123}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS, provider="qwen"), client)
    result = asyncio.run(run())
    assert result.provider == "qwen" and result.usage["total_tokens"] == 123
    assert observed[0]["response_format"] == {"type": "json_object"}


def test_missing_provider_key_never_falls_back_to_offline(monkeypatch):
    monkeypatch.setenv("YZ_ENABLE_MODEL", "1")
    monkeypatch.delenv("YZ_LLM_API_KEY", raising=False)
    monkeypatch.setenv("YZ_LLM_ALLOW_NO_KEY", "0")
    with pytest.raises(ValueError, match="未配置"):
        asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS, provider="qwen")))


def test_foundation_mode_blocks_model_calls_even_if_a_key_is_present(monkeypatch):
    monkeypatch.setenv("YZ_ENABLE_MODEL", "0")
    monkeypatch.setenv("YZ_LLM_API_KEY", "test-unused-credential")
    with pytest.raises(ValueError, match="未启用"):
        asyncio.run(analyze(AnalyzeRequest(requirements=DEFAULT_REQUIREMENTS, provider="qwen")))
