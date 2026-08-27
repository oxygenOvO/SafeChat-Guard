import json

import pytest

import frontend.streamlit_app as frontend_app
import safechat_guard.llm_client as llm_module
from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.llm_client import OpenAICompatibleLLMClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    @staticmethod
    def read():
        return b'{"choices":[{"message":{"content":"{}"}}]}'


def client_config():
    return {
        "provider": "openai_compatible",
        "api_key_env": "TEST_JUDGE_API_KEY",
        "base_url": "https://example.invalid/v1/chat/completions",
        "model": "test-model",
    }


def test_json_mode_is_opt_in_and_business_chat_payload_is_unchanged(monkeypatch):
    monkeypatch.setenv("TEST_JUDGE_API_KEY", "secret")
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    client = OpenAICompatibleLLMClient(client_config())

    client.chat("普通业务请求")
    client.chat_messages(
        [{"role": "user", "content": "Judge request"}],
        response_format={"type": "json_object"},
    )

    assert "response_format" not in payloads[0]
    assert payloads[1]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("initialization", "Judge服务未就绪"),
        ("http", "Judge服务调用失败"),
        ("response_text", "Judge返回文本不可用"),
        ("json_parse", "Judge返回内容无法解析"),
        ("schema_validation", "Judge结果未通过格式校验"),
    ],
)
def test_judge_failure_ui_uses_specific_stage_message(stage, expected):
    message = frontend_app.judge_failure_message(stage, "invalid_action")

    assert expected in message
    assert "未知" not in message
    assert "已采用本地安全策略" in message


def test_schema_validation_code_is_exposed_only_for_schema_failure():
    base = {
        "input_judge_used": True,
        "input_decision_source": "local_fallback",
        "input_judge_error_stage": "schema_validation",
        "input_judge_error_code": "invalid_category",
    }

    schema_view = FrontendPipelineAdapter._judge_view(
        base, {"enabled": True, "available": True}, None
    )
    http_view = FrontendPipelineAdapter._judge_view(
        {**base, "input_judge_error_stage": "http"},
        {"enabled": True, "available": True},
        None,
    )

    assert schema_view["validation_error_code"] == "invalid_category"
    assert http_view["validation_error_code"] is None
