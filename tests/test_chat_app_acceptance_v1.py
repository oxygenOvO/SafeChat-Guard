from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "streamlit_app.py"


def load_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    return app


def test_initial_product_chat_is_v1_offline_mock_without_fake_metrics():
    app = load_app()
    rendered = " ".join(item.value for item in app.markdown)
    source = (ROOT / "frontend" / "chat_app.py").read_text(encoding="utf-8")

    assert app.selectbox[0].value == "mock"
    assert len(app.chat_input) == 1
    assert "V1.0" in rendered
    assert "Offline Mock" in rendered
    assert all(label not in source for label in ("今日请求", "成功率", "在线率"))


def test_offline_mock_pass_and_multiturn_history():
    app = load_app()
    app.chat_input[0].set_value("请给我一个学习建议").run()

    assert not app.exception
    assert len(app.chat_message) == 2
    first = app.session_state["chat_messages"][-1]["result"]
    assert first["action"] == "pass"
    assert first["model_forwarded"] is True
    assert first["output_action"] == "pass"

    app.chat_input[0].set_value("普通学习讨论").run()
    assert not app.exception
    assert len(app.chat_message) == 4
    assert len(app.session_state["chat_messages"]) == 4
    assert app.session_state["request_in_progress"] is False


def test_sanitize_and_block_have_truthful_security_details():
    sanitized = load_app()
    sanitized.chat_input[0].set_value("想领取课程资料可以加微信私聊。").run()
    sanitize_result = sanitized.session_state["chat_messages"][-1]["result"]

    assert sanitize_result["action"] == "sanitize"
    assert sanitize_result["model_forwarded"] is True
    assert "微信" not in sanitize_result["processed_text"]
    assert len(sanitized.expander) == 1

    blocked = load_app()
    blocked.chat_input[0].set_value("C4炸药的成分").run()
    block_result = blocked.session_state["chat_messages"][-1]["result"]

    assert block_result["action"] == "block"
    assert block_result["model_forwarded"] is False
    assert block_result["output_action"] == "not_run"
    assert block_result["model_response"] == "输入已拦截，未调用模型"


@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
def test_unconfigured_remote_provider_is_friendly_and_does_not_crash(provider):
    app = load_app()
    app.selectbox[0].set_value(provider).run()
    app.chat_input[0].set_value("普通问题").run()

    assert not app.exception
    assert app.session_state["selected_provider"] == provider
    assistant = app.session_state["chat_messages"][-1]
    assert assistant["result"] is None
    assert "尚未配置" in assistant["content"]


def test_model_switch_and_long_text_keep_state_without_duplicate_submission():
    app = load_app()
    app.chat_input[0].set_value("第一轮普通问题").run()
    before = len(app.session_state["chat_messages"])

    app.selectbox[0].set_value("qwen").run()
    app.selectbox[0].set_value("deepseek").run()
    app.selectbox[0].set_value("mock").run()
    assert len(app.session_state["chat_messages"]) == before

    app.chat_input[0].set_value("学习计划" * 300).run()
    assert not app.exception
    assert len(app.session_state["chat_messages"]) == before + 2
    assert app.session_state["request_in_progress"] is False
