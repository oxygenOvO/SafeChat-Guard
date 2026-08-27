import json

import pytest

from safechat_guard.llm_safety_judge import LLMSafetyJudge, LLMSafetyJudgeError


def valid_result(**changes):
    result = {
        "action": "pass",
        "category": "normal",
        "risk_level": "none",
        "confidence": 0.95,
        "reason": "普通知识问答。",
        "sanitized_text": None,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"drop": "reason"}, "missing_field"),
        ({"extra": True}, "extra_field"),
        ({"action": "allow"}, "invalid_action"),
        ({"category": "other"}, "invalid_category"),
        ({"risk_level": "critical"}, "invalid_risk_level"),
        ({"confidence": "0.95"}, "invalid_confidence"),
        ({"reason": ""}, "invalid_reason"),
        ({"sanitized_text": "unexpected"}, "invalid_sanitized_text"),
    ],
)
def test_schema_validation_has_specific_non_sensitive_code(changes, code):
    result = valid_result()
    dropped = changes.pop("drop", None)
    if dropped:
        result.pop(dropped)
    result.update(changes)

    with pytest.raises(LLMSafetyJudgeError) as caught:
        LLMSafetyJudge.parse_result(json.dumps(result, ensure_ascii=False))

    assert caught.value.stage == "schema_validation"
    assert caught.value.validation_error_code == code
    assert caught.value.code == code
    assert "returned_keys" in caught.value.details
    assert "reason" not in caught.value.details


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_messages(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.responses.pop(0)

    @staticmethod
    def status():
        return {"provider": "fake", "ready": True}


def test_schema_failure_gets_exactly_one_repair_retry():
    client = SequenceClient([
        json.dumps({"action": "pass"}),
        json.dumps(valid_result(), ensure_ascii=False),
    ])

    result = LLMSafetyJudge(client).judge_input("普通安全文本")

    assert result["action"] == "pass"
    assert len(client.calls) == 2
    repair_messages = client.calls[1][0]
    assert repair_messages[-1]["content"] == "上一次结构不符合 Schema，请严格按照指定 JSON Schema 重新返回。"


def test_second_schema_failure_falls_back_after_two_total_calls():
    client = SequenceClient([
        json.dumps({"action": "pass"}),
        json.dumps({"action": "pass"}),
    ])

    with pytest.raises(LLMSafetyJudgeError) as caught:
        LLMSafetyJudge(client).judge_input("普通安全文本")

    assert caught.value.code == "missing_field"
    assert len(client.calls) == 2


def test_json_parse_failure_is_not_retried():
    client = SequenceClient(["not json"])

    with pytest.raises(LLMSafetyJudgeError) as caught:
        LLMSafetyJudge(client).judge_input("普通安全文本")

    assert caught.value.stage == "json_parse"
    assert len(client.calls) == 1


def test_json_mode_is_judge_only_and_explicit():
    client = SequenceClient([json.dumps(valid_result(), ensure_ascii=False)])

    LLMSafetyJudge(client, json_mode=True).judge_input("普通安全文本")

    assert client.calls[0][1]["response_format"] == {"type": "json_object"}


def test_sanitize_must_change_original_and_is_retried_once():
    unchanged = valid_result(
        action="sanitize",
        category="sensitive",
        risk_level="medium",
        sanitized_text="相同文本",
    )
    client = SequenceClient([json.dumps(unchanged), json.dumps(unchanged)])

    with pytest.raises(LLMSafetyJudgeError) as caught:
        LLMSafetyJudge(client).judge_input("相同文本")

    assert caught.value.code == "invalid_sanitized_text"
    assert len(client.calls) == 2
