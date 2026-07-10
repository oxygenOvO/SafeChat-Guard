from safechat_guard.pipeline import SafeChatPipeline


def make_pipeline() -> SafeChatPipeline:
    return SafeChatPipeline.from_config("config.yaml")


def test_normal_message_passes():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("你好，请介绍一下人工智能安全竞赛的比赛流程。")

    assert result["input_filter"]["action"] == "pass"


def test_ad_message_sanitized():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("想领取课程资料可以加微信私聊。")

    assert result["input_filter"]["action"] == "sanitize"
    assert result["input_filter"]["detections"][0]["category"] == "ad"


def test_phone_number_is_actually_sanitized():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("请联系 13812345678 获取资料。")

    assert result["input_filter"]["action"] == "sanitize"
    assert "13812345678" not in result["input_filter"]["sanitized_text"]
    assert "***" in result["input_filter"]["sanitized_text"]


def test_email_is_actually_sanitized():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("请发送到 user_name+tag@example.com。")

    assert result["input_filter"]["action"] == "sanitize"
    assert "user_name+tag@example.com" not in result["input_filter"]["sanitized_text"]
    assert "***" in result["input_filter"]["sanitized_text"]


def test_porn_message_blocked():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("这个成人网站包含色情内容。")

    assert result["input_filter"]["action"] == "block"
    assert result["input_filter"]["detections"][0]["category"] == "porn"


def test_violence_message_blocked():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("你再这样我就打死你。")

    assert result["input_filter"]["action"] == "block"
    assert result["input_filter"]["detections"][0]["category"] == "violence"


def test_sensitive_message_sanitized():
    pipeline = make_pipeline()

    result = pipeline.handle_chat("不要传播谣言或者煽动对立。")

    assert result["input_filter"]["action"] == "sanitize"
    assert result["input_filter"]["detections"][0]["category"] == "sensitive"
