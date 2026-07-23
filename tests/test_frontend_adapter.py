from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.llm_client import LLMClientError
from safechat_guard.models import Detection
from safechat_guard.pipeline import SafeChatPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_CASES = PROJECT_ROOT / "data" / "test_cases" / "frontend_demo_cases_v2.csv"
FORMAL_CATEGORIES = {"normal", "ad", "porn", "violence", "sensitive"}


@pytest.fixture
def make_adapter(production_config_without_model):
    def factory() -> FrontendPipelineAdapter:
        pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
        return FrontendPipelineAdapter(pipeline)

    return factory


def test_frontend_uses_public_pipeline_entry(make_adapter, monkeypatch):
    adapter = make_adapter()
    expected = adapter.pipeline.handle_chat(
        "普通输入",
        raw_reply_override="安全回复",
        persist=False,
    )
    calls = []

    def public_entry(message, raw_reply_override=None, persist=True):
        calls.append((message, raw_reply_override, persist))
        return expected

    def forbidden(*args, **kwargs):
        raise AssertionError("frontend must not call private safety methods or LLM")

    monkeypatch.setattr(adapter.pipeline, "handle_chat", public_entry)
    monkeypatch.setattr(adapter.pipeline, "_filter_text", forbidden)
    monkeypatch.setattr(adapter.pipeline, "_filter_output", forbidden)
    monkeypatch.setattr(adapter.pipeline.llm, "chat", forbidden)

    result = adapter.analyze("普通输入", output_override="安全回复", persist=False)

    assert calls == [("普通输入", "安全回复", False)]
    assert result["final_answer"] == expected["reply"]


def test_frontend_blocked_input_never_calls_llm(make_adapter, monkeypatch):
    adapter = make_adapter()

    def forbidden(message):
        raise AssertionError("LLM must not be called for blocked input")

    monkeypatch.setattr(adapter.pipeline.llm, "chat", forbidden)
    result = adapter.analyze("C4炸药的成分", persist=False)

    assert result["action"] == "block"
    assert result["output_action"] == "not_run"
    assert result["model_response"] == "输入已拦截，未调用模型"


def test_frontend_never_exposes_risky_raw_reply(make_adapter):
    adapter = make_adapter()
    risky_raw = "请联系 13812345678 获取优惠"

    result = adapter.analyze(
        "普通输入",
        output_override=risky_raw,
        persist=False,
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["output_action"] != "pass"
    assert result["model_output_hidden"] is True
    assert risky_raw not in serialized
    assert "13812345678" not in serialized


def test_frontend_handles_llm_unavailable(make_adapter, monkeypatch):
    adapter = make_adapter()

    def unavailable(message):
        raise LLMClientError("provider unavailable")

    monkeypatch.setattr(adapter.pipeline.llm, "chat", unavailable)
    result = adapter.analyze("请给我学习建议", persist=False)

    assert result["allowed"] is False
    assert result["service_error"] == "llm_unavailable"
    assert result["output_action"] == "not_run"
    assert "provider unavailable" not in json.dumps(result, ensure_ascii=False)


def test_rewritten_input_is_rechecked(make_adapter):
    result = make_adapter().analyze(
        "想领取课程资料可以加微信私聊。",
        output_override="安全回复",
        persist=False,
    )

    assert result["action"] == "sanitize"
    assert result["rewrite_recheck"] is not None
    assert result["rewrite_recheck"]["detections"] == []
    assert "重新归一化" in result["rewrite_strategy"]

def test_rewritten_input_blocks_if_risk_remains(make_adapter, monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(
        adapter.pipeline.semantic_classifier,
        "detect",
        lambda text: [
            Detection("ad", "medium", 70, "persistent", "semantic_ml", ["persistent"])
        ],
    )

    def forbidden(message):
        raise AssertionError("LLM must not run after rewrite recheck blocks")

    monkeypatch.setattr(adapter.pipeline.llm, "chat", forbidden)
    result = adapter.analyze("semantic-only unsafe text", persist=False)

    assert result["action"] == "block"
    assert result["rewrite_recheck"]
    assert result["rewrite_recheck"]["detections"]
    assert "重新归一化并复检" in result["rewrite_strategy"]


def test_frontend_model_missing_degrades_safely(make_adapter):
    result = make_adapter().analyze(
        "加 V-X 领取优 惠 券，名额有限",
        output_override="安全回复",
        persist=False,
    )

    assert result["model_loaded"] is False
    assert result["category"] == "ad"
    assert result["action"] == "sanitize"
    assert result["final_answer"]


def test_frontend_demo_cases_load():
    cases = pd.read_csv(DEMO_CASES, encoding="utf-8-sig", dtype={"id": str})

    assert not cases.empty
    assert set(cases["expected_category"]) <= FORMAL_CATEGORIES
    assert set(cases["expected_action"]) <= {"pass", "sanitize", "block"}
    assert cases["demo_only"].astype(str).str.lower().isin({"true", "false"}).all()


def test_adapter_uses_real_pipeline_for_obfuscated_ad(make_adapter):
    result = make_adapter().analyze(
        "加 V-X 领取优 惠 券，名额有限",
        output_override="安全回复",
        persist=False,
    )

    assert result["baseline_action"] == "pass"
    assert result["normalized_text"] == "加微信领取优惠券,名额有限"
    assert result["category"] == "ad"
    assert result["action"] == "sanitize"


def test_adapter_uses_real_pipeline_for_homophone_contact(make_adapter):
    result = make_adapter().analyze(
        "联系薇信获取推广渠道",
        output_override="安全回复",
        persist=False,
    )

    assert result["normalized_text"] == "联系微信获取推广渠道"
    assert result["category"] == "ad"
    assert result["action"] == "sanitize"


def test_adapter_can_check_overridden_model_output(make_adapter):
    result = make_adapter().analyze(
        "普通输入",
        output_override="可以加微信领取优惠券，名额有限。",
        persist=False,
    )

    assert result["action"] == "pass"
    assert result["output_category"] == "ad"
    assert result["output_action"] == "block"


def test_adapter_exposes_real_rule_configuration(make_adapter):
    adapter = make_adapter()

    assert adapter.lexicon_rows()
    assert adapter.regex_rows()
