from __future__ import annotations

import json
from pathlib import Path

import pytest

from safechat_guard.models import Detection
from safechat_guard.pipeline import SafeChatPipeline


class IdentityNormalizer:
    @staticmethod
    def normalize(text):
        return text


class EmptyDetector:
    @staticmethod
    def detect(_text):
        return []

    @staticmethod
    def status():
        return {"loaded": True, "error": None}


class UnavailableDetector(EmptyDetector):
    @staticmethod
    def status():
        return {"loaded": False, "error": "synthetic unavailable"}


class StaticDetector(EmptyDetector):
    def __init__(self, detections):
        self.detections = detections

    def detect(self, _text):
        return list(self.detections)


class SequenceRouter:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def route(self, original_text, normalized_text, rules, semantics):
        self.calls.append((original_text, normalized_text, rules, semantics))
        if not self.results:
            raise AssertionError("unexpected router call")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return dict(result)


class CountingSanitizer:
    def __init__(self, result="clean text", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def sanitize(self, text, matches):
        self.calls.append((text, list(matches)))
        if self.error is not None:
            raise self.error
        return self.result


class CountingLLM:
    def __init__(self, response="fixed safe model response"):
        self.response = response
        self.calls = []

    def chat(self, message):
        self.calls.append(message)
        return self.response

    @staticmethod
    def status():
        return {"provider": "test", "ready": True}


def routed(action, *, reason="TEST_ROUTE", category=None, hard_block=None):
    category = category or ("normal" if action == "pass" else "ad")
    hard_block = action == "block" if hard_block is None else hard_block
    return {
        "action": action,
        "category": category,
        "risk_level": "high" if action == "block" else (
            "medium" if action == "sanitize" else "none"
        ),
        "confidence": 0.9,
        "reason_codes": [reason],
        "hard_block": hard_block,
        "risk_score": 90 if action == "block" else (
            60 if action == "sanitize" else 0
        ),
        "matched_rule_ids": ["TEST_RULE"] if action != "pass" else [],
        "sanitize_matches": ["risky"] if action == "sanitize" else [],
        "evidence": [],
    }


def risk_detection(*, source="semantic_ml", level="medium", score=70):
    return Detection("ad", level, score, "synthetic risk", source, ["risky"])


@pytest.fixture
def pipeline(production_config_without_model):
    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    value.rule_filter = EmptyDetector()
    value.semantic_classifier = EmptyDetector()
    value.llm = CountingLLM()
    return value


def test_router_hard_block_never_calls_sanitizer_or_llm(pipeline):
    pipeline.action_router = SequenceRouter(routed("block", reason="HARD_STOP"))
    pipeline.sanitizer = CountingSanitizer()

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert result["model_forwarded"] is False
    assert pipeline.llm.calls == []
    assert pipeline.sanitizer.calls == []


def test_existing_high_rule_evidence_fails_closed_without_llm(pipeline):
    pipeline.rule_filter = StaticDetector(
        [risk_detection(source="keyword", level="high", score=90)]
    )
    pipeline.action_router = SequenceRouter(RuntimeError("router failed"))

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert result["fallback_used"] is True
    assert pipeline.llm.calls == []


def test_high_rule_only_router_fallback_remains_explicit_hard_block(pipeline):
    pipeline.rule_filter = StaticDetector(
        [risk_detection(source="keyword", level="high", score=80)]
    )
    pipeline.action_router = SequenceRouter(
        routed("sanitize", reason="RULE_RISK_EVIDENCE", category="violence")
    )

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert "LEGACY_EXPLICIT_HARD_BLOCK" in result["reason_codes"]
    assert pipeline.llm.calls == []

def test_router_pass_calls_llm_once(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    result = pipeline.handle_chat("ordinary", persist=False)

    assert pipeline.llm.calls == ["ordinary"]
    assert result["model_forwarded"] is True
    assert result["output_guard_action"] == "pass"


def test_sanitize_recheck_pass_calls_llm_once(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize"), routed("pass"))
    pipeline.sanitizer = CountingSanitizer("clean text")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "sanitize"
    assert result["sanitized_text"] == "clean text"
    assert result["input_filter"]["recheck_action"] == "pass"
    assert pipeline.llm.calls == ["clean text"]


def test_sanitize_recheck_sanitize_never_calls_llm(pipeline):
    pipeline.action_router = SequenceRouter(
        routed("sanitize"), routed("sanitize", reason="STILL_RISKY")
    )
    pipeline.sanitizer = CountingSanitizer("still risky")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["input_filter"]["recheck_action"] == "sanitize"
    assert "REWRITE_RECHECK_SANITIZE" in result["reason_codes"]
    assert pipeline.llm.calls == []


def test_sanitize_recheck_block_never_calls_llm(pipeline):
    pipeline.action_router = SequenceRouter(
        routed("sanitize"), routed("block", reason="ESCALATED")
    )
    pipeline.sanitizer = CountingSanitizer("worse text")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["input_filter"]["recheck_action"] == "block"
    assert pipeline.llm.calls == []


def test_unchanged_sanitizer_result_never_calls_llm(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize"))
    pipeline.sanitizer = CountingSanitizer("risky")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert "SANITIZER_UNCHANGED" in result["reason_codes"]
    assert result["input_filter"]["rewrite_recheck"]["action"] == "block"
    assert result["input_filter"]["rewrite_recheck"]["detections"] == []
    assert pipeline.llm.calls == []


def test_empty_sanitizer_result_never_calls_llm(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize"))
    pipeline.sanitizer = CountingSanitizer("   ")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert "SANITIZER_EMPTY" in result["reason_codes"]
    assert pipeline.llm.calls == []


def test_sanitizer_exception_never_calls_llm(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize"))
    pipeline.sanitizer = CountingSanitizer(error=RuntimeError("secret details"))

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["reason_codes"][-1] == "SANITIZER_ERROR"
    assert "secret" not in json.dumps(result)
    assert pipeline.llm.calls == []


def test_router_exception_with_risk_evidence_never_calls_llm(pipeline):
    pipeline.semantic_classifier = StaticDetector([risk_detection()])
    pipeline.action_router = SequenceRouter(RuntimeError("sensitive stack"))

    result = pipeline.handle_chat("semantic risk", persist=False)

    assert result["action"] == "block"
    assert result["fallback_used"] is True
    assert result["reason_codes"] == [
        "ROUTER_ERROR", "DETECTION_EVIDENCE_FAIL_CLOSED"
    ]
    assert "sensitive stack" not in json.dumps(result)
    assert pipeline.llm.calls == []


def test_router_exception_without_evidence_passes_only_when_semantic_loaded(pipeline):
    pipeline.action_router = SequenceRouter(RuntimeError("router failed"))

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["action"] == "pass"
    assert result["semantic_model_status"] == "loaded"
    assert result["fallback_used"] is True
    assert "ROUTER_ERROR" in result["reason_codes"]
    assert "NO_DETECTION_EVIDENCE" in result["reason_codes"]
    assert pipeline.llm.calls == ["ordinary"]


def test_router_exception_and_semantic_unavailable_fail_closed(pipeline):
    pipeline.semantic_classifier = UnavailableDetector()
    pipeline.action_router = SequenceRouter(RuntimeError("router failed"))

    result = pipeline.handle_chat("unchecked", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is False
    assert result["model_forwarded"] is False
    assert result["fallback_used"] is True
    assert result["semantic_model_status"] == "unavailable"
    assert result["reason_codes"] == [
        "ROUTER_ERROR", "ROUTER_AND_SEMANTIC_UNAVAILABLE"
    ]
    assert pipeline.llm.calls == []


def test_router_initialization_failure_and_semantic_unavailable_fail_closed(pipeline):
    pipeline.semantic_classifier = UnavailableDetector()
    pipeline.action_router = None
    pipeline.action_router_error_code = "ROUTER_UNAVAILABLE"

    result = pipeline.handle_chat("unchecked", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is False
    assert result["model_forwarded"] is False
    assert result["fallback_used"] is True
    assert result["semantic_model_status"] == "unavailable"
    assert result["reason_codes"] == [
        "ROUTER_UNAVAILABLE", "ROUTER_AND_SEMANTIC_UNAVAILABLE"
    ]
    assert pipeline.llm.calls == []


def test_router_hard_block_cannot_be_downgraded_by_semantic_score(pipeline):
    pipeline.semantic_classifier = StaticDetector([risk_detection(score=99)])
    pipeline.action_router = SequenceRouter(routed("block", reason="ROUTER_BLOCK"))
    pipeline.llm = CountingLLM("unsafe model response")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "block"
    assert result["reason_codes"] == ["ROUTER_BLOCK"]
    assert pipeline.llm.calls == []


def test_reason_codes_are_preserved_in_pipeline_result(pipeline):
    pipeline.action_router = SequenceRouter(routed("block", reason="AUDIT_REASON"))

    result = pipeline.handle_chat("risky", persist=False)

    assert result["reason_codes"] == ["AUDIT_REASON"]
    assert result["input_filter"]["reason_codes"] == ["AUDIT_REASON"]


def test_model_forwarded_is_false_for_block_and_true_for_pass(pipeline):
    pipeline.action_router = SequenceRouter(routed("block"), routed("pass"))

    blocked = pipeline.handle_chat("first", persist=False)
    passed = pipeline.handle_chat("second", persist=False)

    assert blocked["model_forwarded"] is False
    assert passed["model_forwarded"] is True


def test_fallback_used_field_is_accurate(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"), RuntimeError("failed"))

    normal = pipeline.detect_text("first")
    fallback = pipeline.detect_text("second")

    assert normal["fallback_used"] is False
    assert fallback["fallback_used"] is True


def test_output_guard_still_sanitizes_model_output(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    pipeline.llm = CountingLLM("请联系 13812345678")

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "sanitize"
    assert "13812345678" not in result["reply"]
    assert result["model_response"] is None


def test_output_guard_block_does_not_return_unsafe_original(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    unsafe = "我会杀了你"
    pipeline.llm = CountingLLM(unsafe)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "block"
    assert result["allowed"] is False
    assert unsafe not in result["reply"]
    assert result["raw_reply"] is None
    assert result["model_response"] is None


def test_normal_text_keeps_compatible_response_fields(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["allowed"] is True
    assert {"reply", "input_filter", "output_filter", "safe_input"} <= set(result)
    assert {
        "action", "category", "risk_level", "risk_score", "reason_codes",
        "hard_block", "normalized_text", "sanitized_text", "model_forwarded",
        "model_response", "output_guard_action", "semantic_model_status",
        "fallback_used", "latency_ms",
    } <= set(result)


def test_explicit_router_rules_path_resolves_from_project_root(
    tmp_path, production_config_without_model
):
    config = json.loads(production_config_without_model.read_text(encoding="utf-8"))
    rules_dir = production_config_without_model.parent / "router-config"
    rules_dir.mkdir()
    source = Path(__file__).resolve().parents[1] / "config/action_rules_v1.json"
    target = rules_dir / "rules.json"
    target.write_bytes(source.read_bytes())
    config["action_router"] = {"rules_path": "router-config/rules.json"}
    production_config_without_model.write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )

    value = SafeChatPipeline.from_config(str(production_config_without_model))

    assert value.action_router is not None
    assert value.action_router.rules_path.resolve() == target.resolve()


def test_default_router_path_is_independent_of_current_working_directory(
    monkeypatch, tmp_path, production_config_without_model
):
    monkeypatch.chdir(tmp_path)

    value = SafeChatPipeline.from_config(str(production_config_without_model.resolve()))

    expected = Path(__file__).resolve().parents[1] / "config/action_rules_v1.json"
    assert value.action_router is not None
    assert value.action_router.rules_path.resolve() == expected.resolve()