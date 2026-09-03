from __future__ import annotations

import pytest

from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.normalization.base import NormalizationResult
from safechat_guard.pipeline import MAX_HISTORY_TURNS, SafeChatPipeline


class IdentityNormalizer:
    @staticmethod
    def normalize(text):
        return text

    @staticmethod
    def normalize_with_trace(text):
        return NormalizationResult(
            original_text=text, normalized_text=text, steps=[]
        )


class EmptyDetector:
    @staticmethod
    def detect(_text):
        return []

    @staticmethod
    def score_text(_text):
        return {"loaded": False, "scores": {}, "error": None}

    @staticmethod
    def status():
        return {"loaded": True, "error": None}


class SequenceRouter:
    def __init__(self, *results):
        self.results = list(results)

    def route(self, original_text, normalized_text, rules, semantics):
        result = self.results.pop(0)
        return dict(result)


class CountingSanitizerStub:
    def __init__(self, result):
        self.result = result

    def sanitize(self, text, matches):
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


def routed(action, *, reason="TEST_ROUTE"):
    category = "normal" if action == "pass" else "ad"
    return {
        "action": action,
        "category": category,
        "risk_level": "none" if action == "pass" else "medium",
        "confidence": 0.9,
        "reason_codes": [reason],
        "hard_block": action == "block",
        "risk_score": 0 if action == "pass" else 60,
        "matched_rule_ids": [],
        "sanitize_matches": [],
        "evidence": [],
    }


@pytest.fixture
def pipeline(production_config_without_model):
    value = SafeChatPipeline.from_config(str(production_config_without_model))
    value.normalizer = IdentityNormalizer()
    value.rule_filter = EmptyDetector()
    value.semantic_classifier = EmptyDetector()
    value.llm = CountingLLM()
    return value


def test_history_is_forwarded_to_llm_as_message_list(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": "第一条消息"},
        {"role": "assistant", "content": "第一条回复"},
    ]

    result = pipeline.handle_chat("第二条消息", persist=False, history=history)

    assert result["model_forwarded"] is True
    assert pipeline.llm.calls == [
        [
            {"role": "user", "content": "第一条消息"},
            {"role": "assistant", "content": "第一条回复"},
            {"role": "user", "content": "第二条消息"},
        ]
    ]


def test_no_history_keeps_single_string_call(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    pipeline.handle_chat("单独消息", persist=False)

    assert pipeline.llm.calls == ["单独消息"]


def test_history_is_passed_after_input_sanitization(pipeline):
    pipeline.action_router = SequenceRouter(
        routed("sanitize", reason="SANITIZE"),
        routed("pass", reason="RECHECK_PASS"),
    )
    pipeline.sanitizer = CountingSanitizerStub("已脱敏的安全文本")
    history = [{"role": "user", "content": "历史消息"}]

    pipeline.handle_chat("带风险的消息", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert sent[-1] == {"role": "user", "content": "已脱敏的安全文本"}
    assert sent[0] == {"role": "user", "content": "历史消息"}


def test_invalid_history_role_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="role"):
        pipeline.handle_chat("消息", persist=False, history=[{"role": "system", "content": "x"}])


def test_invalid_history_content_raises_value_error(pipeline):
    with pytest.raises(ValueError, match="content"):
        pipeline.handle_chat(
            "消息", persist=False, history=[{"role": "user", "content": " "}]
        )


def test_history_longer_than_limit_is_truncated(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    history = [
        {"role": "user", "content": f"消息{i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"回复{i}"}
        for i in range(MAX_HISTORY_TURNS + 10)
    ]

    pipeline.handle_chat("新消息", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert len(sent) == MAX_HISTORY_TURNS + 1
    assert sent[0] == {"role": "user", "content": f"消息{10}"}
    assert sent[-1] == {"role": "user", "content": "新消息"}


def test_history_none_is_valid(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))

    result = pipeline.handle_chat("消息", persist=False, history=None)

    assert result["model_forwarded"] is True


def test_frontend_adapter_passes_history_through(pipeline):
    pipeline.action_router = SequenceRouter(routed("pass"))
    adapter = FrontendPipelineAdapter(pipeline)
    history = [{"role": "user", "content": "历史"}]

    adapter.analyze("新输入", persist=False, history=history)

    sent = pipeline.llm.calls[0]
    assert sent[0] == {"role": "user", "content": "历史"}
    assert sent[-1] == {"role": "user", "content": "新输入"}
