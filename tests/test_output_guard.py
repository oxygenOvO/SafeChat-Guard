from safechat_guard.output_guard import OutputGuard
from safechat_guard.pipeline import SafeChatPipeline


def test_output_guard_blocks_ad_and_privacy():
    guard = OutputGuard()
    result = guard.process("加我微信abc12345，手机号是13812345678", "加我微信abc12345，手机号是13812345678", [])
    assert result["action"] == "block"
    assert result["blocked"] is True
    assert "ad" in result["risk_categories"]
    assert "privacy" in result["risk_categories"]


def test_output_guard_rewrites_privacy_only():
    guard = OutputGuard()
    result = guard.process("请发邮件到test@example.com", "请发邮件到test@example.com", [])
    assert result["action"] == "sanitize"
    assert result["rewritten"] is True
    assert "[邮箱]" in result["final_text"]


def test_pipeline_logs_input_output_and_final_separately(production_config_without_model):
    pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    result = pipeline.handle_chat("safe test")

    assert "output_filter" in result
    events = pipeline.logger.read_all()
    assert [event["stage"] for event in events[-3:]] == ["input", "output", "final"]
    output_result = events[-2]["result"]
    for key in [
        "risk_categories",
        "risk_level",
        "blocked",
        "rewritten",
        "matched_rules",
    ]:
        assert key in output_result
    assert events[-2]["raw_reply"] == "[REDACTED]"


def test_address_detection_avoids_common_suffix_false_positives():
    guard = OutputGuard()
    for text in ["\u601d\u8def", "\u6559\u5ba4", "\u529e\u516c\u5ba4", "\u804a\u5929\u5ba4"]:
        _, detections = guard.mask_sensitive_info(text)
        assert detections == []


def test_address_detection_still_masks_structured_addresses():
    guard = OutputGuard()
    masked, detections = guard.mask_sensitive_info("\u5e78\u798f\u8def88\u53f7")

    assert masked == "[\u5730\u5740]"
    assert detections and detections[0].matches == ["address"]
