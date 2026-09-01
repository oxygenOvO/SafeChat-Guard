import json
import logging
import socket
import ssl
from pathlib import Path
from urllib.error import HTTPError

import pytest

from frontend.management_views import CONNECTION_MESSAGES
from safechat_guard.llm_client import LLMClientError, OpenAICompatibleLLMClient
from safechat_guard.model_registry import ModelRegistry
from safechat_guard.provider_diagnostics import (
    classify_provider_error,
    sanitize_provider_error,
)


ROOT = Path(__file__).resolve().parents[1]


class StatusError(Exception):
    def __init__(self, status_code: int, message: str = "provider rejected request"):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (400, "bad_request"),
        (401, "authentication_failed"),
        (403, "permission_denied"),
        (404, "not_found"),
        (429, "rate_limited"),
    ],
)
def test_structured_http_status_classification(status_code, category):
    diagnostic = classify_provider_error(StatusError(status_code))

    assert diagnostic.http_status == status_code
    assert diagnostic.category == category


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (TimeoutError("slow upstream"), "timeout"),
        (ConnectionError("connection refused"), "network_error"),
        (socket.gaierror("dns failed"), "network_error"),
        (ssl.SSLError("certificate verify failed"), "ssl_error"),
        (RuntimeError("unexpected provider failure"), "unknown_error"),
    ],
)
def test_exception_type_classification(error, category):
    assert classify_provider_error(error).category == category


def test_llm_client_preserves_safe_structured_http_diagnostic(monkeypatch):
    config = {
        "provider": "qwen",
        "api_key_env": "TEST_PROVIDER_KEY",
        "base_url": "https://example.invalid/chat/completions",
        "model": "qwen-plus",
        "timeout_seconds": 3,
    }
    monkeypatch.setenv("TEST_PROVIDER_KEY", "environment-secret")

    def fail_request(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Authorization: Bearer transport-secret",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("safechat_guard.llm_client.urlopen", fail_request)
    client = OpenAICompatibleLLMClient(config)
    with pytest.raises(LLMClientError) as captured:
        client.chat("Reply with OK.")

    assert captured.value.category == "authentication_failed"
    assert captured.value.http_status == 401
    assert "transport-secret" not in str(captured.value.safe_summary)


def test_provider_error_redaction_is_case_insensitive_and_bounded():
    raw = (
        "DASHSCOPE_API_KEY=test-secret-key "
        "authorization: Bearer test-secret-token "
        "api-key: another-secret Cookie=session-secret "
        "headers={'X-Api-Key': 'header-secret'} "
        "https://example.com/chat?token=query-secret"
    )

    sanitized = sanitize_provider_error(raw)

    for secret in (
        "test-secret-key",
        "test-secret-token",
        "another-secret",
        "session-secret",
        "header-secret",
        "query-secret",
    ):
        assert secret not in sanitized
    assert "[REDACTED]" in sanitized
    assert "\n" not in sanitized
    for label in (
        "authorization",
        "bearer",
        "api-key",
        "cookie",
        "headers",
        "dashscope_api_key",
    ):
        assert label not in sanitized.lower()
    assert len(sanitized) <= 240



@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("authentication_failed", "认证失败，请检查 API Key 配置"),
        ("permission_denied", "当前凭据无权访问该模型或服务"),
        ("not_found", "模型或接口地址不可用"),
        ("rate_limited", "请求受限，请稍后重试或检查账户额度"),
        ("timeout", "连接超时，请检查网络或稍后重试"),
    ],
)
def test_ui_connection_messages_are_safe_and_specific(category, expected):
    assert CONNECTION_MESSAGES[category] == expected


@pytest.fixture
def product_config():
    return json.loads((ROOT / "config.yaml").read_text(encoding="utf-8"))



def test_missing_qwen_key_is_not_configured(tmp_path, product_config, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    result = registry.test_connection("qwen")

    assert result["status"] == "not_configured"
    assert result["latency_ms"] is not None


def test_mock_connection_remains_available(tmp_path, product_config):
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    result = registry.test_connection("mock")

    assert result["status"] == "available"


@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
def test_remote_provider_logs_only_redacted_structured_diagnostics(
    provider, tmp_path, product_config, monkeypatch, caplog
):
    env_name = product_config["llm"]["providers"][provider]["api_key_env"]
    monkeypatch.setenv(env_name, "environment-secret")
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    class FailingAdapter:
        def status(self):
            return {
                "provider": provider,
                "model": product_config["llm"]["providers"][provider]["model"],
                "ready": True,
                "key_configured": True,
            }

        def chat(self, message):
            raise StatusError(
                401,
                "Authorization: Bearer test-secret-token "
                "api_key=test-secret-key headers={'Cookie': 'cookie-secret'}",
            )

    monkeypatch.setattr(
        "safechat_guard.model_registry.LLMAdapterFactory.create",
        lambda config: FailingAdapter(),
    )
    with caplog.at_level(logging.WARNING, logger="safechat.provider"):
        result = registry.test_connection(provider)

    log_text = caplog.text
    assert result["status"] == "authentication_failed"
    assert result["latency_ms"] is not None
    assert "category=authentication_failed" in log_text
    assert "http_status=401" in log_text
    assert f"provider={provider}" in log_text
    assert "[REDACTED]" in log_text
    for secret in (
        "environment-secret",
        "test-secret-token",
        "test-secret-key",
        "cookie-secret",
    ):
        assert secret not in log_text
