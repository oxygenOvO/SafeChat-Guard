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
    assert result["masked_text"] is None
    assert result["processed_text"] == "未转发给模型"
    assert result["model_forwarded"] is False


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
    assert result["masked_text"] == result["processed_text"]
    assert result["masked_text"] != result["original_text"]
    assert result["rewrite_changed"] is True
    assert result["recheck_action"] == "pass"
    assert "重新归一化" in result["rewrite_strategy"]

def test_frontend_judge_not_triggered_is_explicit(make_adapter):
    result = make_adapter().analyze(
        "普通输入",
        output_override="安全回复",
        persist=False,
    )

    assert result["semantic_arbitration_status"] == "未触发"
    assert result["input_judge_used"] is False
    assert result["output_judge_used"] is False
    assert result["judge_decision_source_label"] == "本地安全策略"


def test_frontend_judge_fallback_and_reason_are_non_sensitive(
    make_adapter, monkeypatch
):
    adapter = make_adapter()
    pipeline_result = adapter.pipeline.handle_chat(
        "ordinary",
        raw_reply_override="safe reply",
        persist=False,
    )
    pipeline_result.update(
        {
            "input_judge_used": True,
            "input_judge_action": None,
            "input_judge_reason": None,
            "input_decision_source": "local_fallback",
            "input_judge_error_stage": "json_parse",
            "input_judge_error_code": "INVALID_JSON",
        }
    )
    monkeypatch.setattr(
        adapter.pipeline,
        "handle_chat",
        lambda *args, **kwargs: pipeline_result,
    )

    result = adapter.analyze("ordinary", persist=False)
    serialized = json.dumps(result, ensure_ascii=False).lower()

    assert result["semantic_arbitration_status"] == "不可用，已回退本地安全策略"
    assert result["judge_decision_source_label"] == "Judge不可用，采用本地安全策略"
    assert result["judge_error_stage"] == "json_parse"
    assert result["judge_error_code"] == "INVALID_JSON"
    assert "authorization" not in serialized
    assert "system prompt" not in serialized


def test_frontend_uses_raw_distribution_when_gate_emits_no_detection(
    make_adapter, monkeypatch
):
    adapter = make_adapter()
    monkeypatch.setattr(
        adapter.pipeline.semantic_classifier,
        "predict_distribution",
        lambda _text: {
            "available": True,
            "top_category": "normal",
            "top_probability": 0.46,
            "probabilities": {
                "normal": 0.46,
                "ad": 0.07,
                "porn": 0.04,
                "sensitive": 0.12,
                "violence": 0.31,
            },
            "risk_detection_emitted": False,
        },
    )

    result = adapter.analyze(
        "安全测试文本", output_override="安全回复", persist=False
    )

    assert result["semantic_available"] is True
    assert result["semantic_category"] == "normal"
    assert result["semantic_final_category"] == "normal"
    assert result["semantic_score"] == 0.46
    assert result["semantic_scores"] == {
        "normal": 0.46,
        "ad": 0.07,
        "porn": 0.04,
        "sensitive": 0.12,
        "violence": 0.31,
    }
    assert result["semantic_scores"]["normal"] != 1.0
    assert result["semantic_gate_triggered"] is False


def test_frontend_semantic_unavailable_is_explicit(make_adapter, monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(
        adapter.pipeline.semantic_classifier,
        "predict_distribution",
        lambda _text: {"available": False, "error": "model unavailable"},
    )

    result = adapter.analyze(
        "安全测试文本", output_override="安全回复", persist=False
    )

    assert result["semantic_available"] is False
    assert result["semantic_category"] is None
    assert result["semantic_score"] is None
    assert result["semantic_note"] == "语义模型不可用，已回退规则检测。"
    assert result["semantic_error"] == "model unavailable"
    assert all(score == 0.0 for score in result["semantic_scores"].values())


def test_frontend_semantic_detection_display_matches_distribution(
    make_adapter, monkeypatch
):
    adapter = make_adapter()
    monkeypatch.setattr(
        adapter.pipeline.semantic_classifier,
        "predict_distribution",
        lambda _text: {
            "available": True,
            "top_category": "violence",
            "top_probability": 0.72,
            "probabilities": {
                "normal": 0.08,
                "ad": 0.06,
                "porn": 0.05,
                "sensitive": 0.09,
                "violence": 0.72,
            },
            "risk_detection_emitted": True,
        },
    )

    result = adapter.analyze(
        "安全测试文本", output_override="安全回复", persist=False
    )

    assert result["semantic_category"] == "violence"
    assert result["semantic_final_category"] == "violence"
    assert result["semantic_score"] == 0.72
    assert result["semantic_scores"]["violence"] == 0.72
    assert result["semantic_gate_triggered"] is True
    assert result["action"] == "pass"
    assert result["final_action"] == "pass"


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
    assert cases["demo_only"].astype(str).str.lower().eq("true").all()


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


def test_adapter_prefers_pipeline_final_fields(make_adapter, monkeypatch):
    adapter = make_adapter()
    pipeline_result = adapter.pipeline.handle_chat(
        "ordinary",
        raw_reply_override="safe reply",
        persist=False,
    )
    pipeline_result["final_action"] = "block"
    pipeline_result["final_allowed"] = False

    monkeypatch.setattr(
        adapter.pipeline,
        "handle_chat",
        lambda *args, **kwargs: pipeline_result,
    )
    result = adapter.analyze("ordinary", output_override="safe reply", persist=False)

    assert result["action"] == "pass"
    assert result["final_action"] == "block"
    assert result["final_allowed"] is False
    assert result["model_forwarded"] is pipeline_result["model_forwarded"]
    assert result["output_guard_action"] == pipeline_result["output_guard_action"]
    assert result["record"]["final_action"] == "block"


def test_adapter_has_safe_legacy_fallback_without_final_fields(
    make_adapter, monkeypatch
):
    adapter = make_adapter()
    pipeline_result = adapter.pipeline.handle_chat(
        "ordinary",
        raw_reply_override="\u6211\u4f1a\u6740\u4e86\u4f60",
        persist=False,
    )
    pipeline_result.pop("final_action")
    pipeline_result.pop("final_allowed")
    monkeypatch.setattr(
        adapter.pipeline,
        "handle_chat",
        lambda *args, **kwargs: pipeline_result,
    )

    result = adapter.analyze("ordinary", persist=False)

    assert result["final_action"] == "block"
    assert result["final_allowed"] is False


def test_adapter_rule_catalog_marks_builtins_read_only(make_adapter):
    adapter = make_adapter()
    catalog = adapter.rule_catalog()
    builtins = [rule for rule in catalog["rules"] if rule["origin"] == "builtin"]
    assert builtins
    assert all(rule["read_only"] is True for rule in builtins)
    assert catalog["user_count"] == 0


def test_adapter_user_rule_crud_reloads_filter(make_adapter):
    adapter = make_adapter()
    payload = {
        "id": "ui-rule-1",
        "pattern": "前端紫色词",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "UI test",
    }
    created = adapter.add_user_rule(payload, 0)
    assert adapter.pipeline.rule_filter.detect("包含前端紫色词")
    updated = adapter.update_user_rule(
        "ui-rule-1", {"description": "changed"}, created["revision"]
    )
    disabled = adapter.set_user_rule_enabled(
        "ui-rule-1", False, updated["revision"]
    )
    assert adapter.pipeline.rule_filter.detect("包含前端紫色词") == []
    adapter.delete_user_rule("ui-rule-1", disabled["revision"])
    assert adapter.rule_catalog()["user_count"] == 0


def test_pipeline_stats_survives_rule_create_and_delete_audits(make_adapter):
    adapter = make_adapter()
    payload = {
        "id": "stats-audit-rule",
        "pattern": "stats-audit-pattern",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "stats regression",
    }

    created = adapter.add_user_rule(payload, 0)
    assert adapter.pipeline.stats(portable_paths=True)["total_events"] == 1

    adapter.delete_user_rule("stats-audit-rule", created["revision"])
    stats = adapter.pipeline.stats(portable_paths=True)
    assert stats["total_events"] == 2
    assert stats["action_counts"] == {}


def test_adapter_daily_stats_zero_state(make_adapter):
    stats = make_adapter().daily_stats()
    assert stats["request_count"] == 0
    assert stats["violation_count"] == 0
    assert stats["source"] == "request_summary"

def test_adapter_rule_catalog_redacts_pattern_by_default(make_adapter):
    adapter = make_adapter()
    payload = {
        "id": "private-ui-rule",
        "pattern": "private-ui-pattern",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "private UI test",
    }
    created = adapter.add_user_rule(payload, 0)
    assert created["rule"]["pattern"] == "[REDACTED]"
    catalog = adapter.rule_catalog()
    user_rule = next(rule for rule in catalog["rules"] if rule["id"] == "private-ui-rule")
    assert user_rule["pattern"] == "[REDACTED]"
    assert user_rule["pattern_redacted"] is True
    assert catalog["pattern_access"] is False


def test_adapter_privileged_catalog_requires_token_and_supports_edit(
    make_adapter, monkeypatch
):
    adapter = make_adapter()
    token = "frontend-admin-token"
    monkeypatch.setenv("SAFECHAT_RULE_ADMIN_TOKEN", token)
    payload = {
        "id": "editable-ui-rule",
        "pattern": "editable-private-pattern",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "editable UI test",
    }
    created = adapter.add_user_rule(payload, 0)
    with pytest.raises(PermissionError):
        adapter.rule_catalog(include_pattern=True, admin_token="wrong")

    catalog = adapter.rule_catalog(include_pattern=True, admin_token=token)
    selected = next(rule for rule in catalog["rules"] if rule["id"] == "editable-ui-rule")
    assert selected["pattern"] == "editable-private-pattern"
    assert selected["pattern_redacted"] is False
    assert catalog["pattern_access"] is True

    updated = adapter.update_user_rule(
        "editable-ui-rule",
        {"pattern": "edited-private-pattern"},
        created["revision"],
    )
    assert updated["rule"]["pattern"] == "[REDACTED]"
    privileged = adapter.rule_catalog(include_pattern=True, admin_token=token)
    selected = next(rule for rule in privileged["rules"] if rule["id"] == "editable-ui-rule")
    assert selected["pattern"] == "edited-private-pattern"
    assert token not in adapter.pipeline.logger.path.read_text(encoding="utf-8")
