import json

import pytest

import safechat_guard.llm_client as llm_module
from safechat_guard.llm_client import (
    LLMClientError,
    LLMClientFactory,
    OpenAICompatibleLLMClient,
)
from safechat_guard.pipeline import SafeChatPipeline


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def qwen_config() -> dict:
    return {
        "provider": "qwen",
        "api_key_env": "TEST_QWEN_API_KEY",
        "base_url": "https://example.invalid/v1/chat/completions",
        "model": "qwen-plus",
        "timeout_seconds": 5,
    }


def test_qwen_compatible_client_sends_request_without_logging_key(monkeypatch):
    monkeypatch.setenv("TEST_QWEN_API_KEY", "test-secret-value")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"choices": [{"message": {"content": "安全回复"}}]})

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    client = OpenAICompatibleLLMClient(qwen_config())

    assert client.chat("测试消息") == "安全回复"
    assert captured["authorization"] == "Bearer test-secret-value"
    assert captured["payload"]["messages"][0]["content"] == "测试消息"
    assert captured["timeout"] == 5
    assert client.status()["key_configured"] is True


def test_remote_client_fails_safely_without_key(monkeypatch):
    monkeypatch.delenv("TEST_QWEN_API_KEY", raising=False)
    client = OpenAICompatibleLLMClient(qwen_config())

    with pytest.raises(LLMClientError, match="environment variable is not configured"):
        client.chat("测试消息")
    assert client.status()["ready"] is False


def test_remote_client_rejects_non_https_endpoint(monkeypatch):
    monkeypatch.setenv("TEST_QWEN_API_KEY", "test-secret-value")
    config = qwen_config()
    config["base_url"] = "http://example.invalid/v1/chat/completions"
    client = OpenAICompatibleLLMClient(config)

    with pytest.raises(LLMClientError, match="valid HTTPS URL"):
        client.chat("测试消息")


def test_unknown_provider_does_not_silently_fall_back_to_mock():
    with pytest.raises(ValueError, match="unsupported llm provider"):
        LLMClientFactory.create({"provider": "unknown-provider"})


def test_pipeline_returns_safe_service_error_when_remote_llm_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("TEST_QWEN_API_KEY", raising=False)
    pipeline = SafeChatPipeline(
        {
            "risk": {"block_threshold": 80, "sanitize_threshold": 40},
            "semantic_thresholds": {},
            "llm": qwen_config(),
            "logging": {"path": str(tmp_path / "events.jsonl")},
        }
    )

    result = pipeline.handle_chat("请给我学习建议", persist=False)

    assert result["allowed"] is False
    assert result["service_error"] == "llm_unavailable"
    assert result["raw_reply"] is None
    assert "TEST_QWEN_API_KEY" not in result["reply"]
