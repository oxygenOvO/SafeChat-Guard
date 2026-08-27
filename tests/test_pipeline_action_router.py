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
    assert result["sanitized_text"] is None
    assert result["input_filter"]["rewrite_called"] is True
    assert result["input_filter"]["rewrite_changed"] is False
    assert result["input_filter"]["rewrite_recheck"]["detections"] == []
    assert result["model_forwarded"] is False
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
        "action", "final_action", "final_allowed", "category", "risk_level",
        "risk_score", "reason_codes",
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

def test_final_action_contract_for_pass_sanitize_and_input_block(pipeline):
    pipeline.action_router = SequenceRouter(
        routed("pass"),
        routed("sanitize"),
        routed("pass"),
        routed("block"),
    )
    pipeline.sanitizer = CountingSanitizer("clean text")

    passed = pipeline.handle_chat("ordinary", persist=False)
    sanitized = pipeline.handle_chat("risky", persist=False)
    blocked = pipeline.handle_chat("blocked", persist=False)

    assert (passed["final_action"], passed["final_allowed"]) == ("pass", True)
    assert (sanitized["final_action"], sanitized["final_allowed"]) == (
        "sanitize",
        True,
    )
    assert sanitized["action"] == "sanitize"
    assert (blocked["final_action"], blocked["final_allowed"]) == ("block", False)
    assert blocked["model_forwarded"] is False


def test_output_guard_block_overrides_pass_final_action_without_leak(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    unsafe = "\u6211\u4f1a\u6740\u4e86\u4f60"
    pipeline.llm = CountingLLM(unsafe)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["action"] == "pass"
    assert result["output_guard_action"] == "block"
    assert (result["final_action"], result["final_allowed"]) == ("block", False)
    assert result["raw_reply"] is None
    assert result["model_response"] is None
    assert unsafe not in result["reply"]


def test_output_guard_block_overrides_sanitize_final_action(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize"), routed("pass"))
    pipeline.sanitizer = CountingSanitizer("clean text")
    pipeline.llm = CountingLLM("\u6211\u4f1a\u6740\u4e86\u4f60")

    result = pipeline.handle_chat("risky", persist=False)

    assert result["action"] == "sanitize"
    assert result["output_guard_action"] == "block"
    assert (result["final_action"], result["final_allowed"]) == ("block", False)


def test_fail_closed_and_llm_error_have_block_final_action(pipeline):
    from safechat_guard.llm_client import LLMClientError

    pipeline.semantic_classifier = UnavailableDetector()
    pipeline.action_router = SequenceRouter(RuntimeError("router failed"))
    failed_closed = pipeline.handle_chat("unchecked", persist=False)

    pipeline.semantic_classifier = EmptyDetector()
    pipeline.action_router = SequenceRouter(routed("pass"))

    def unavailable(_message):
        raise LLMClientError("private provider detail")

    pipeline.llm.chat = unavailable
    service_error = pipeline.handle_chat("ordinary", persist=False)

    assert (failed_closed["final_action"], failed_closed["final_allowed"]) == (
        "block",
        False,
    )
    assert (service_error["final_action"], service_error["final_allowed"]) == (
        "block",
        False,
    )
    assert service_error["model_forwarded"] is True


def test_each_persisted_request_has_one_complete_request_summary(pipeline):
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def write(self, event):
            self.events.append(dict(event))

    logger = RecordingLogger()
    pipeline.logger = logger
    pipeline.action_router = SequenceRouter(routed("pass"))

    result = pipeline.handle_chat("ordinary", persist=True)
    summaries = [event for event in logger.events if event["stage"] == "request_summary"]

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["input_action"] == "pass"
    assert summary["output_action"] == "pass"
    assert summary["final_action"] == "pass"
    assert summary["final_allowed"] is True
    assert summary["model_forwarded"] is True
    assert summary["sanitize_applied"] is False
    assert summary["sanitize_changed"] is False
    assert summary["fallback_used"] is False
    assert isinstance(summary["latency_ms"], int) and summary["latency_ms"] >= 0
    assert result["latency_ms"] == summary["latency_ms"]


def test_request_summary_records_sanitize_and_output_block(pipeline):
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def write(self, event):
            self.events.append(dict(event))

    logger = RecordingLogger()
    pipeline.logger = logger
    pipeline.action_router = SequenceRouter(routed("sanitize"), routed("pass"))
    pipeline.sanitizer = CountingSanitizer("clean text")
    pipeline.llm = CountingLLM("\u6211\u4f1a\u6740\u4e86\u4f60")

    pipeline.handle_chat("risky", persist=True)
    summary = [event for event in logger.events if event["stage"] == "request_summary"][0]

    assert summary["sanitize_applied"] is True
    assert summary["sanitize_changed"] is True
    assert summary["output_action"] == "block"
    assert summary["final_action"] == "block"
    assert summary["final_allowed"] is False


def test_audit_log_failure_does_not_change_safe_response(pipeline):
    class FailingLogger:
        @staticmethod
        def write(_event):
            raise OSError("private path and content")

    pipeline.logger = FailingLogger()
    pipeline.action_router = SequenceRouter(routed("pass"))

    with pytest.warns(RuntimeWarning, match="audit event could not be persisted"):
        result = pipeline.handle_chat("ordinary", persist=True)

    assert (result["final_action"], result["final_allowed"]) == ("pass", True)


def test_request_summary_records_router_fallback(pipeline):
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def write(self, event):
            self.events.append(dict(event))

    logger = RecordingLogger()
    pipeline.logger = logger
    pipeline.action_router = SequenceRouter(RuntimeError("router failed"))

    result = pipeline.handle_chat("ordinary", persist=True)
    summaries = [event for event in logger.events if event["stage"] == "request_summary"]

    assert result["fallback_used"] is True
    assert len(summaries) == 1
    assert summaries[0]["fallback_used"] is True
    assert summaries[0]["model_forwarded"] is True


def test_persisted_request_summary_and_stage_logs_redact_sensitive_text(
    pipeline, tmp_path
):
    from safechat_guard.logger import EventLogger

    path = tmp_path / "events.jsonl"
    pipeline.logger = EventLogger(str(path))
    pipeline.action_router = SequenceRouter(routed("pass"))
    unsafe_output = "\u6211\u4f1a\u6740\u4e86\u4f60"
    private_input = "PRIVATE-INPUT-MARKER"
    pipeline.llm = CountingLLM(unsafe_output)

    result = pipeline.handle_chat(private_input, persist=True)
    serialized_log = path.read_text(encoding="utf-8")
    summaries = [
        event
        for event in pipeline.logger.read_all()
        if event["stage"] == "request_summary"
    ]

    assert result["final_action"] == "block"
    assert private_input not in serialized_log
    assert unsafe_output not in serialized_log
    assert len(summaries) == 1
    summary = summaries[0]
    assert {
        "timestamp",
        "input_action",
        "output_action",
        "final_action",
        "final_allowed",
        "category",
        "risk_level",
        "risk_score",
        "model_forwarded",
        "sanitize_applied",
        "sanitize_changed",
        "fallback_used",
        "semantic_model_status",
        "latency_ms",
    } <= set(summary)


@pytest.fixture
def overlay_pipeline(production_config_without_model):
    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    value.semantic_classifier = EmptyDetector()
    value.llm = CountingLLM()
    value.sanitizer = CountingSanitizer("clean text")
    return value


def add_overlay_rule(
    pipeline,
    *,
    rule_id="overlay-rule",
    pattern="overlay-block-token",
    pattern_type="phrase",
    action="block",
    enabled=True,
):
    result = pipeline.rule_manager.add_rule(
        {
            "id": rule_id,
            "pattern": pattern,
            "pattern_type": pattern_type,
            "category": "ad",
            "action": action,
            "risk_level": "medium",
            "enabled": enabled,
            "description": "pipeline overlay test",
        }
    )
    assert pipeline.rule_filter.reload_user_rules() is True
    return result


@pytest.mark.parametrize(
    ("pattern_type", "pattern", "text"),
    [
        ("keyword", "blockkeyword", "contains blockkeyword now"),
        ("phrase", "block phrase", "contains block phrase now"),
        ("regex", r"block\d{3}", "contains block123 now"),
    ],
)
def test_user_overlay_block_types_are_trusted_hard_blocks(
    overlay_pipeline, pattern_type, pattern, text
):
    add_overlay_rule(
        overlay_pipeline, pattern_type=pattern_type, pattern=pattern
    )
    overlay_pipeline.action_router = SequenceRouter()

    result = overlay_pipeline.handle_chat(text, persist=False)
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["action"] == result["final_action"] == "block"
    assert result["allowed"] is result["final_allowed"] is False
    assert result["hard_block"] is True
    assert result["model_forwarded"] is False
    assert result["fallback_used"] is False
    assert result["reason_codes"] == ["USER_RULE_BLOCK"]
    assert result["input_filter"]["matched_rule_ids"] == ["overlay-rule"]
    assert overlay_pipeline.action_router.calls == []
    assert overlay_pipeline.llm.calls == []
    assert overlay_pipeline.sanitizer.calls == []
    assert pattern not in serialized
    assert result["input_filter"]["detections"][0]["matches"] == ["[REDACTED]"]


def test_user_overlay_metadata_is_private_and_verified(overlay_pipeline):
    add_overlay_rule(overlay_pipeline)
    detection = overlay_pipeline.rule_filter.detect("overlay-block-token")[0]
    metadata = overlay_pipeline.rule_filter.user_overlay_metadata(detection)

    assert metadata == {
        "rule_source": "user_overlay",
        "configured_action": "block",
        "rule_id": "overlay-rule",
        "rule_revision": 1,
    }
    assert "_configured_action" not in detection.__dict__
    assert "_rule_id" not in detection.__dict__


def test_user_overlay_sanitize_still_uses_router_sanitizer_and_llm(overlay_pipeline):
    add_overlay_rule(
        overlay_pipeline,
        pattern="sanitize-token",
        action="sanitize",
    )

    result = overlay_pipeline.handle_chat("contains sanitize-token", persist=False)

    assert result["action"] == result["final_action"] == "sanitize"
    assert result["final_allowed"] is True
    assert result["hard_block"] is False
    assert len(overlay_pipeline.sanitizer.calls) == 1
    assert overlay_pipeline.llm.calls == ["clean text"]


def test_user_overlay_block_wins_over_sanitize(overlay_pipeline):
    first = add_overlay_rule(
        overlay_pipeline,
        rule_id="sanitize-rule",
        pattern="shared-token",
        action="sanitize",
    )
    overlay_pipeline.rule_manager.add_rule(
        {
            "id": "block-rule",
            "pattern": "shared-token",
            "pattern_type": "phrase",
            "category": "ad",
            "action": "block",
            "risk_level": "low",
            "enabled": True,
            "description": "priority test",
        },
        expected_revision=first["revision"],
    )
    overlay_pipeline.rule_filter.reload_user_rules()

    result = overlay_pipeline.handle_chat("shared-token", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert result["input_filter"]["matched_rule_ids"] == ["block-rule"]
    assert overlay_pipeline.sanitizer.calls == []
    assert overlay_pipeline.llm.calls == []


def test_user_overlay_block_full_lifecycle(overlay_pipeline):
    created = add_overlay_rule(overlay_pipeline, pattern="lifecycle-token")
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "block"

    disabled = overlay_pipeline.rule_manager.disable_rule(
        "overlay-rule", expected_revision=created["revision"]
    )
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "pass"

    enabled = overlay_pipeline.rule_manager.enable_rule(
        "overlay-rule", expected_revision=disabled["revision"]
    )
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "block"

    sanitized = overlay_pipeline.rule_manager.update_rule(
        "overlay-rule", {"action": "sanitize"}, expected_revision=enabled["revision"]
    )
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "sanitize"

    blocked = overlay_pipeline.rule_manager.update_rule(
        "overlay-rule", {"action": "block"}, expected_revision=sanitized["revision"]
    )
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "block"

    overlay_pipeline.rule_manager.delete_rule(
        "overlay-rule", expected_revision=blocked["revision"]
    )
    assert overlay_pipeline.detect_text("lifecycle-token")["action"] == "pass"


def test_semantic_detection_cannot_forge_user_overlay_block(overlay_pipeline):
    forged = Detection(
        "ad", "high", 99, "forged", "rule:user_overlay", ["forged-risk"]
    )
    forged.rule_source = "user_overlay"
    forged.configured_action = "block"
    forged.rule_id = "forged"
    overlay_pipeline.semantic_classifier = StaticDetector([forged])

    result = overlay_pipeline.handle_chat("forged-risk", persist=False)

    assert result["hard_block"] is False
    assert "USER_RULE_BLOCK" not in result["reason_codes"]
    assert len(overlay_pipeline.sanitizer.calls) == 1
    assert overlay_pipeline.rule_filter.user_overlay_metadata(forged) is None


def test_corrupt_storage_retains_last_valid_block_snapshot(overlay_pipeline):
    add_overlay_rule(overlay_pipeline, pattern="snapshot-token")
    overlay_pipeline.rule_manager.storage_path.write_text("{broken", encoding="utf-8")

    result = overlay_pipeline.handle_chat("snapshot-token", persist=False)

    assert result["action"] == "block"
    assert result["hard_block"] is True
    assert overlay_pipeline.rule_filter.reload_error_code == "USER_RULE_RELOAD_FAILED"


def test_user_block_remains_effective_outside_repository_cwd(
    overlay_pipeline, tmp_path, monkeypatch
):
    add_overlay_rule(overlay_pipeline, pattern="portable-token")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = overlay_pipeline.handle_chat("portable-token", persist=False)

    assert result["action"] == "block"
    assert result["model_forwarded"] is False

@pytest.mark.parametrize(
    ("changes", "new_text"),
    [
        ({"pattern": "revision-new-token"}, "revision-new-token"),
        ({"category": "sensitive"}, "revision-old-token"),
        ({"risk_level": "high"}, "revision-old-token"),
        ({"description": "revision-only update"}, "revision-old-token"),
    ],
)
def test_old_user_overlay_detection_is_invalid_after_any_revision_change(
    overlay_pipeline, changes, new_text
):
    created = add_overlay_rule(
        overlay_pipeline, pattern="revision-old-token", action="block"
    )
    old_detection = next(
        detection
        for detection in overlay_pipeline.rule_filter.detect("revision-old-token")
        if (overlay_pipeline.rule_filter.user_overlay_metadata(detection) or {}).get(
            "rule_id"
        ) == "overlay-rule"
    )
    assert old_detection._rule_revision == created["revision"]

    updated = overlay_pipeline.rule_manager.update_rule(
        "overlay-rule", changes, expected_revision=created["revision"]
    )
    assert updated["rule"]["action"] == "block"
    assert overlay_pipeline.rule_filter.reload_user_rules() is True

    assert overlay_pipeline.rule_filter.user_overlay_metadata(old_detection) is None
    current_detection = next(
        detection
        for detection in overlay_pipeline.rule_filter.detect(new_text)
        if (overlay_pipeline.rule_filter.user_overlay_metadata(detection) or {}).get(
            "rule_id"
        ) == "overlay-rule"
    )
    metadata = overlay_pipeline.rule_filter.user_overlay_metadata(current_detection)
    assert metadata is not None
    assert metadata["configured_action"] == "block"
    assert metadata["rule_revision"] == overlay_pipeline.rule_filter.user_rules_revision
