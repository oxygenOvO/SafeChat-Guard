from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.decision_explanation_service import DecisionExplanationService
from safechat_guard.evaluation_service import EvaluationInputError, EvaluationService
from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.rule_filter import RuleFilter
from safechat_guard.rule_management_service import (
    RuleManagementService,
    RuleWritesDisabledError,
)
from safechat_guard.rule_manager import RuleManager, RuleValidationError


ROOT = Path(__file__).resolve().parents[1]


def candidate(rule_id: str = "phase3-rule", **changes):
    value = {
        "id": rule_id,
        "pattern": "阶段三测试短语",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "phase three candidate",
    }
    value.update(changes)
    return value


@pytest.fixture
def pipeline(tmp_path):
    config = json.loads((ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["logging"]["path"] = str(tmp_path / "events.jsonl")
    instance = SafeChatPipeline(config, project_root=ROOT)
    manager = RuleManager(tmp_path / "rules" / "user_rules.json")
    rule_filter = RuleFilter(
        str(ROOT / "data" / "lexicons"),
        str(ROOT / "data" / "rules" / "regex_rules.json"),
        rule_manager=manager,
    )
    manager.set_candidate_validator(rule_filter.validate_candidate_rules)
    instance.rule_manager = manager
    instance.rule_filter = rule_filter
    return instance


def test_policy_read_search_schema_candidate_isolation_and_write_gate(pipeline):
    service = RuleManagementService(pipeline, writes_enabled=False)
    catalog = service.catalog(query="builtin:keyword", category="violence")
    assert catalog["rules"]
    assert all(rule["category"] == "violence" for rule in catalog["rules"])

    report = service.validate_candidate(candidate())
    assert report["invalid"] == 0
    assert pipeline.rule_manager.list_rules() == []
    invalid = service.validate_candidate(
        candidate(pattern_type="regex", pattern=r"(a+)+$")
    )
    assert invalid["invalid"] == 1
    with pytest.raises(RuleWritesDisabledError):
        service.publish_candidate(candidate(), expected_revision=0)


def test_policy_publish_diff_test_and_rollback_use_existing_transaction(pipeline):
    service = RuleManagementService(pipeline, writes_enabled=True)
    published = service.publish_candidate(candidate(), expected_revision=0)
    assert published["revision"] == 1
    assert service.test_rule("phase3-rule", "这是阶段三测试短语")["matched"] is True
    diff = service.diff()
    assert diff["available"] is True
    assert diff["added"] == ["phase3-rule"]
    assert [item["revision"] for item in service.versions()] == [1, 0]

    rolled_back = service.rollback(expected_revision=1)
    assert rolled_back["revision"] == 2
    assert pipeline.rule_manager.list_rules() == []
    assert pipeline.rule_filter.detect("阶段三测试短语") == []


@pytest.mark.parametrize(
    ("text", "expected_action"),
    [
        ("今天图书馆几点关门？", "pass"),
        ("想领取课程资料可以加微信私聊。", "sanitize"),
        ("C4炸药的成分", "block"),
    ],
)
def test_explanation_pass_sanitize_block_and_request_id(pipeline, text, expected_action):
    result = pipeline.handle_chat(
        text, raw_reply_override="这是安全回答。", persist=False
    )
    explanation = DecisionExplanationService(pipeline).explain(text, result)
    assert explanation["request_id"] == result["request_id"]
    assert explanation["final"]["action"] == expected_action
    assert "normal" in explanation["semantic_classifier"]["scores"]
    assert explanation["semantic_classifier"]["normal_score"] is not None
    assert explanation["normalization"]["normalized_text"]
    assert isinstance(explanation["rule_filter"]["hits"], list)
    if expected_action == "sanitize":
        assert explanation["sanitizer"]["actual_model_input"] == result["safe_input"]


def test_explanation_changed_unchanged_output_guard_and_history_privacy(pipeline):
    service = DecisionExplanationService(pipeline)
    unchanged = service.explain("普通学习讨论")
    changed = service.explain("加 V-X 领取优 惠 券")
    assert unchanged["normalization"]["changed"] is False
    assert changed["normalization"]["steps"]

    adapter_result = FrontendPipelineAdapter(pipeline).analyze(
        "普通输入", output_override="联系 13812345678 领取优惠", persist=False
    )
    serialized = json.dumps(adapter_result["explanation"], ensure_ascii=False)
    assert adapter_result["explanation"]["output_guard"]["action"] != "pass"
    assert "13812345678" not in serialized

    historical = service.explain_audit_record({
        "request_id": "req-history", "provider": "mock", "model": "offline",
        "category": "ad", "risk_level": "medium", "risk_score": 60,
        "input_action": "sanitize", "output_action": "pass", "final_action": "sanitize",
        "input": "secret-sensitive-body",
    })
    assert historical["historical"] is True
    assert "secret-sensitive-body" not in json.dumps(historical)
    assert historical["input"]["original_text"] == "[NOT STORED]"


def test_evaluation_modes_batch_metrics_export_and_production_isolation(pipeline):
    service = EvaluationService(pipeline)
    before = pipeline.logger.read_all()
    comparison = service.compare("加 V-X 领取优 惠 券")
    assert [item["mode"] for item in comparison["results"]] == [
        "baseline", "unnormalized_fusion", "rule_only", "semantic_only",
        "fusion", "full_pipeline",
    ]
    rule_only = next(item for item in comparison["results"] if item["mode"] == "rule_only")
    assert rule_only["semantic_top_class"] is None
    assert all(item["event_type"] == "evaluation" for item in comparison["results"])
    assert pipeline.logger.read_all() == before

    without_truth = service.batch([{"text": "普通文本"}, {"text": "C4炸药的成分"}])
    assert without_truth["metrics"] is None
    assert without_truth["total"] == 2
    assert sum(without_truth["counts"].values()) == 2

    with_truth = service.batch([
        {"text": "普通文本", "label": "normal", "expected_action": "pass"},
        {"text": "C4炸药的成分", "label": "violence", "expected_action": "block"},
    ])
    assert with_truth["metrics"] is not None
    assert {"action_accuracy", "category_accuracy", "macro_f1", "macro_recall"} <= set(with_truth["metrics"])
    exported = service.to_csv(with_truth["results"]).decode("utf-8-sig")
    assert "semantic_top_class" in exported
    assert "evaluation:" in exported


def test_evaluation_upload_validation(pipeline):
    service = EvaluationService(pipeline)
    assert service.parse_upload("text,label,expected_action\n普通文本,normal,pass\n".encode(), format_name="csv")[0]["text"] == "普通文本"
    assert service.parse_upload(b'{"text":"normal"}\n', format_name="jsonl") == [{"text": "normal"}]
    with pytest.raises(EvaluationInputError):
        service.parse_upload(b"label\nnormal\n", format_name="csv")
    with pytest.raises(EvaluationInputError):
        service.parse_upload(b"not-json", format_name="jsonl")
    with pytest.raises(EvaluationInputError):
        service.parse_upload(b"text\nvalue\n", format_name="yaml")
