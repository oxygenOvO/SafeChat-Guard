from pathlib import Path

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


def test_pipeline_logs_member_c_fields():
    log_path = Path(".test_tmp/member_c_events.jsonl")
    log_path.parent.mkdir(exist_ok=True)
    config = {
        "risk": {"block_threshold": 80, "sanitize_threshold": 40},
        "llm": {"provider": "mock"},
        "logging": {"path": str(log_path)},
    }
    pipeline = SafeChatPipeline(config)
    result = pipeline.handle_chat("请测试")
    assert "output_filter" in result
    event = pipeline.logger.read_all()[-1]
    for key in ["raw_reply", "final_reply", "risk_categories", "risk_level", "blocked", "rewritten", "matched_rules"]:
        assert key in event
