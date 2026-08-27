from __future__ import annotations

import json

import pytest

from safechat_guard.llm_client import LLMClientError
from safechat_guard.llm_safety_judge import LLMSafetyJudgeError
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


class ConditionalDetector(EmptyDetector):
    def __init__(self, predicate, detection):
        self.predicate = predicate
        self.detection = detection

    def detect(self, text):
        return [self.detection] if self.predicate(text) else []


class SequenceRouter:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def route(self, original_text, normalized_text, rules, semantics):
        self.calls.append((original_text, normalized_text, rules, semantics))
        if not self.results:
            raise AssertionError("unexpected router call")
        return dict(self.results.pop(0))


class RecordingLLM:
    def __init__(self, response="safe business response"):
        self.response = response
        self.calls = []

    def chat(self, message):
        self.calls.append(message)
        return self.response

    @staticmethod
    def status():
        return {"provider": "fake-business", "ready": True}


class CountingSanitizer:
    def __init__(self, rewritten="clean text"):
        self.rewritten = rewritten
        self.calls = []

    def sanitize(self, text, matches):
        self.calls.append((text, list(matches)))
        return self.rewritten


class FakeJudge:
    def __init__(self, *, inputs=(), outputs=()):
        self.inputs = list(inputs)
        self.outputs = list(outputs)
        self.input_calls = []
        self.output_calls = []

    def judge_input(self, text):
        self.input_calls.append(text)
        value = self.inputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return dict(value)

    def judge_output(self, text):
        self.output_calls.append(text)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return dict(value)

    @staticmethod
    def status():
        return {"enabled": True, "fallback": "local"}


def routed(action, *, reason="LOCAL", category=None, hard_block=None):
    category = category or ("normal" if action == "pass" else "sensitive")
    hard_block = action == "block" if hard_block is None else hard_block
    return {
        "action": action,
        "category": category,
        "risk_level": "high" if action == "block" else (
            "medium" if action == "sanitize" else "none"
        ),
        "confidence": 0.8,
        "reason_codes": [reason],
        "hard_block": hard_block,
        "risk_score": 90 if action == "block" else (60 if action == "sanitize" else 0),
        "matched_rule_ids": [],
        "sanitize_matches": ["private"] if action == "sanitize" else [],
        "evidence": [],
    }


def judged(action="pass", **changes):
    value = {
        "action": action,
        "category": "normal" if action == "pass" else "sensitive",
        "risk_level": "low" if action == "pass" else "medium",
        "confidence": 0.95,
        "reason": "属于安全教育与预防讨论。",
        "sanitized_text": "clean judge rewrite" if action == "sanitize" else None,
    }
    value.update(changes)
    return value


def detection(*, category="sensitive", source="semantic_ml", score=60, match="risky"):
    return Detection(category, "medium", score, "synthetic", source, [match])


@pytest.fixture
def pipeline(production_config_without_model):
    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    value.rule_filter = EmptyDetector()
    value.semantic_classifier = EmptyDetector()
    value.action_router_v3 = None
    value.llm = RecordingLLM()
    value.llm_judge_enabled = True
    value.llm_judge_input_enabled = True
    value.llm_judge_output_enabled = True
    return value


def test_input_safe_education_context_judge_passes_without_rewrite(pipeline):
    text = "讨论网络欺凌影响和学校预防措施。"
    pipeline.action_router = SequenceRouter(routed("sanitize"))
    pipeline.semantic_classifier = ConditionalDetector(
        lambda value: "欺凌" in value,
        detection(category="violence", match="欺凌"),
    )
    pipeline.llm_judge = FakeJudge(inputs=[judged("pass")])

    result = pipeline.handle_chat(text, persist=False)

    assert result["action"] == "pass"
    assert result["sanitized_text"] is None
    assert result["input_filter"]["rewrite_called"] is False
    assert result["model_forwarded"] is True
    assert pipeline.llm.calls == [text]
    assert result["input_decision_source"] == "llm_judge"


def test_input_ordinary_text_judge_passes(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    pipeline.llm_judge = FakeJudge(inputs=[judged("pass")])

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["action"] == "pass"
    assert pipeline.llm.calls == ["ordinary"]


def test_semantic_only_sanitize_can_be_downgraded_by_judge(pipeline):
    pipeline.action_router = SequenceRouter(routed("sanitize", reason="SEMANTIC_RISK_EVIDENCE"))
    pipeline.semantic_classifier = ConditionalDetector(
        lambda value: "analysis" in value,
        detection(match="analysis"),
    )
    pipeline.llm_judge = FakeJudge(inputs=[judged("pass")])
    pipeline.sanitizer = CountingSanitizer()

    result = pipeline.handle_chat("safe analysis", persist=False)

    assert result["action"] == "pass"
    assert pipeline.sanitizer.calls == []


def test_deterministic_privacy_sanitize_cannot_be_downgraded(pipeline):
    private = detection(source="regex", match="private")
    pipeline.rule_filter = ConditionalDetector(lambda text: "private" in text, private)
    pipeline.action_router = SequenceRouter(routed("sanitize"), routed("pass"))
    pipeline.sanitizer = CountingSanitizer("clean text")
    pipeline.llm_judge = FakeJudge(inputs=[judged("pass")])

    result = pipeline.handle_chat("private data", persist=False)

    assert result["action"] == "sanitize"
    assert result["safe_input"] == "clean text"
    assert "LLM_JUDGE_PASS_LOCAL_CONSTRAINT" in result["reason_codes"]


def test_deterministic_sensitive_detection_overrides_erroneous_local_pass(pipeline):
    private = detection(source="regex", match="private")
    pipeline.rule_filter = ConditionalDetector(lambda text: "private" in text, private)
    pipeline.action_router = SequenceRouter(routed("pass"), routed("pass"))
    pipeline.sanitizer = CountingSanitizer("clean text")
    pipeline.llm_judge = FakeJudge(inputs=[judged("pass")])

    result = pipeline.handle_chat("private data", persist=False)

    assert result["action"] == "sanitize"
    assert result["safe_input"] == "clean text"
    assert result["input_filter"]["recheck_action"] == "pass"
    assert "LLM_JUDGE_PASS_LOCAL_CONSTRAINT" in result["reason_codes"]


def test_hard_block_never_calls_judge_or_business_llm(pipeline):
    pipeline.action_router = SequenceRouter(routed("block", hard_block=True))
    judge = FakeJudge(inputs=[judged("pass")])
    pipeline.llm_judge = judge

    result = pipeline.handle_chat("blocked", persist=False)

    assert result["action"] == "block"
    assert judge.input_calls == []
    assert pipeline.llm.calls == []
    assert result["input_decision_source"] == "local_hard_block"


def test_judge_sanitize_requires_local_recheck_pass(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"), routed("pass"))
    pipeline.llm_judge = FakeJudge(
        inputs=[judged("sanitize", sanitized_text="clean judge rewrite")]
    )

    result = pipeline.handle_chat("needs local rewrite", persist=False)

    assert result["action"] == "sanitize"
    assert result["sanitized_text"] == "clean judge rewrite"
    assert result["input_filter"]["recheck_action"] == "pass"
    assert pipeline.llm.calls == ["clean judge rewrite"]


def test_judge_sanitize_unchanged_fails_closed(pipeline):
    text = "same text"
    pipeline.action_router = SequenceRouter(routed("pass"))
    pipeline.llm_judge = FakeJudge(
        inputs=[judged("sanitize", sanitized_text=text)]
    )

    result = pipeline.handle_chat(text, persist=False)

    assert result["action"] == "block"
    assert "SANITIZER_UNCHANGED" in result["reason_codes"]
    assert pipeline.llm.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        LLMSafetyJudgeError("invalid JSON"),
        LLMClientError("timeout"),
    ],
)
def test_input_judge_failure_falls_back_to_local(failure, pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    pipeline.llm_judge = FakeJudge(inputs=[failure])

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["action"] == "pass"
    assert result["input_decision_source"] == "local_fallback"
    assert pipeline.llm.calls == ["ordinary"]


def configure_output_case(pipeline, *, detector, output, judge):
    pipeline.action_router = SequenceRouter(routed("pass"))
    pipeline.llm_judge_input_enabled = False
    pipeline.semantic_classifier = detector
    pipeline.llm.response = output
    pipeline.llm_judge = judge


def test_output_education_false_positive_judge_restores_original(pipeline):
    output = "说明欺凌危害并提出预防建议。"
    detector = ConditionalDetector(
        lambda text: "欺凌" in text,
        detection(category="violence", match="欺凌"),
    )
    judge = FakeJudge(outputs=[judged("pass")])
    configure_output_case(pipeline, detector=detector, output=output, judge=judge)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["reply"] == output
    assert result["output_guard_action"] == "pass"
    assert result["output_judge_used"] is True
    assert result["output_decision_source"] == "llm_judge"


def test_output_privacy_cannot_be_downgraded(pipeline):
    judge = FakeJudge(outputs=[judged("pass")])
    configure_output_case(
        pipeline,
        detector=EmptyDetector(),
        output="联系 test@example.com",
        judge=judge,
    )

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "sanitize"
    assert "[邮箱]" in result["reply"]
    assert judge.output_calls == []


def test_output_high_risk_never_calls_judge(pipeline):
    judge = FakeJudge(outputs=[judged("pass")])
    configure_output_case(
        pipeline,
        detector=EmptyDetector(),
        output="加我微信abc12345",
        judge=judge,
    )

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "block"
    assert judge.output_calls == []


def test_local_output_block_never_calls_judge(pipeline):
    output = "abstract blocked phrase"
    detector = ConditionalDetector(
        lambda text: "blocked" in text,
        detection(category="violence", score=90, match="blocked"),
    )
    judge = FakeJudge(outputs=[judged("pass")])
    configure_output_case(pipeline, detector=detector, output=output, judge=judge)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "block"
    assert judge.output_calls == []


def test_output_judge_sanitize_is_rechecked_locally(pipeline):
    output = "contains flagged wording"
    detector = ConditionalDetector(
        lambda text: "flagged" in text,
        detection(match="flagged"),
    )
    judge = FakeJudge(
        outputs=[judged("sanitize", sanitized_text="clean educational wording")]
    )
    configure_output_case(pipeline, detector=detector, output=output, judge=judge)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "sanitize"
    assert result["reply"] == "clean educational wording"
    assert result["output_filter"]["rewrite_recheck"]["action"] == "pass"


def test_output_judge_failure_preserves_local_guard_result(pipeline):
    output = "contains flagged wording"
    detector = ConditionalDetector(
        lambda text: "flagged" in text,
        detection(match="flagged"),
    )
    judge = FakeJudge(outputs=[LLMClientError("timeout")])
    configure_output_case(pipeline, detector=detector, output=output, judge=judge)

    result = pipeline.handle_chat("ordinary", persist=False)

    assert result["output_guard_action"] == "sanitize"
    assert result["output_decision_source"] == "local_fallback"
    assert "flagged" not in result["reply"]


def test_judge_disabled_preserves_legacy_key_fields(production_config_without_model, tmp_path):
    original_config = json.loads(
        production_config_without_model.read_text(encoding="utf-8")
    )
    disabled_config = dict(original_config)
    disabled_config["llm_judge"] = {"enabled": False}
    original_config["logging"] = {"path": str(tmp_path / "missing.jsonl")}
    disabled_config["logging"] = {"path": str(tmp_path / "disabled.jsonl")}
    missing_path = tmp_path / "missing-config.json"
    disabled_path = tmp_path / "disabled-config.json"
    missing_path.write_text(json.dumps(original_config), encoding="utf-8")
    disabled_path.write_text(json.dumps(disabled_config), encoding="utf-8")
    legacy = SafeChatPipeline.from_config(str(missing_path)).handle_chat(
        "ordinary", raw_reply_override="safe reply", persist=False
    )
    disabled = SafeChatPipeline.from_config(str(disabled_path)).handle_chat(
        "ordinary", raw_reply_override="safe reply", persist=False
    )
    keys = {
        "action", "final_action", "final_allowed", "category", "risk_level",
        "risk_score", "reason_codes", "hard_block", "normalized_text",
        "sanitized_text", "model_forwarded", "output_guard_action",
        "semantic_model_status", "fallback_used", "safe_input", "reply",
    }

    assert {key: legacy[key] for key in keys} == {
        key: disabled[key] for key in keys
    }
    assert disabled["input_judge_used"] is False
    assert disabled["output_judge_used"] is False
