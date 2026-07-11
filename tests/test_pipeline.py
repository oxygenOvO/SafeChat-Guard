from safechat_guard.pipeline import SafeChatPipeline


def test_normal_message_passes():
    pipeline = SafeChatPipeline.from_config("config.yaml")
    result = pipeline.handle_chat("?????????????????")
    assert result["input_filter"]["action"] == "pass"


def test_ad_message_sanitized():
    pipeline = SafeChatPipeline.from_config("config.yaml")
    result = pipeline.handle_chat("??????????????")
    assert result["input_filter"]["action"] in {"sanitize", "block"}
