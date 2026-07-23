from pathlib import Path

import pytest

from safechat_guard.models import Detection
from safechat_guard.output_guard import OutputGuard
from safechat_guard.pipeline import SafeChatPipeline


def make_pipeline(tmp_path: Path | None = None) -> SafeChatPipeline:
    log_dir = tmp_path or Path(".test_tmp")
    return SafeChatPipeline(
        {
            "risk": {"block_threshold": 80, "sanitize_threshold": 40},
            "llm": {"provider": "mock"},
            "logging": {"path": str(log_dir / "security-events.jsonl")},
        }
    )


def test_required_safety_action_matrix(tmp_path):
    pipeline = make_pipeline(tmp_path)

    assert pipeline.handle_chat("hello", persist=False)["input_filter"]["action"] == "pass"

    medium = pipeline.handle_chat("contact 13812345678", persist=False)
    assert medium["input_filter"]["action"] == "sanitize"
    assert medium["safe_input"] != "contact 13812345678"

    high = pipeline.handle_chat("我要杀了你", persist=False)
    assert high["input_filter"]["action"] == "block"
    assert high["allowed"] is False
    assert high["raw_reply"] is None

    abuse = pipeline.handle_chat("你这个方案太蠢了", persist=False)
    assert abuse["input_filter"]["action"] == "sanitize"

    severe_abuse = pipeline.handle_chat("你这个人真 e 心，赶紧gun", persist=False)
    assert severe_abuse["input_filter"]["action"] == "block"


def test_semantic_sanitize_never_returns_unchanged_text(tmp_path, monkeypatch):
    pipeline = make_pipeline(tmp_path)
    monkeypatch.setattr(
        pipeline.semantic_classifier,
        "predict_scores",
        lambda text: {"normal": 0.3, "ad": 0.7},
    )
    monkeypatch.setattr(
        pipeline.semantic_classifier,
        "detect",
        lambda text: [Detection("ad", "medium", 70, "test", "semantic_ml", ["ad:70%"])]
    )

    result = pipeline._filter_text("semantic-only unsafe text", stage="input")

    assert result["action"] == "sanitize"
    assert result["sanitized_text"] != result["original_text"]


def test_output_semantic_sanitize_never_returns_unchanged_text():
    raw = "semantic-only unsafe output"
    result = OutputGuard().process(
        raw,
        raw,
        [Detection("ad", "medium", 70, "test", "semantic_ml", ["ad:70%"])]
    )

    assert result["action"] == "sanitize"
    assert result["final_text"] != raw


@pytest.mark.parametrize("invalid", [None, [], {}, 0])
def test_invalid_inputs_fail_cleanly(tmp_path, invalid):
    pipeline = make_pipeline(tmp_path)

    with pytest.raises(TypeError, match="message must be a string"):
        pipeline.handle_chat(invalid, persist=False)


def test_logs_redact_sensitive_original_text(tmp_path):
    pipeline = make_pipeline(tmp_path)
    marker = "SECRET-MARKER-13812345678"
    pipeline.handle_chat(marker)

    log_path = tmp_path / "security-events.jsonl"
    assert marker not in log_path.read_text(encoding="utf-8")
    event = pipeline.logger.read_all()[0]
    assert event["input"] == "[REDACTED]"
    assert event["input_filter"]["original_text"] == "[REDACTED]"


def test_filtered_model_output_is_not_returned_raw(tmp_path):
    pipeline = make_pipeline(tmp_path)
    phone = "call 13812345678"

    result = pipeline.handle_chat("hello", raw_reply_override=phone, persist=False)

    assert result["output_filter"]["action"] == "sanitize"
    assert result["raw_reply"] is None
    assert phone not in result["reply"]
