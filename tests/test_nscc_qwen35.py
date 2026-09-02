from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import safechat_guard.llm_client as llm_client
from safechat_guard.llm_adapters import (
    LLMAdapterFactory,
    NSCCQwenAdapter,
)
from safechat_guard.model_registry import ModelRegistry
from safechat_guard.pipeline import SafeChatPipeline


ROOT = Path(__file__).resolve().parents[1]
NSCC_ENDPOINT = "https://maas.nscc-cs.cn/external/api/v1/chat/completions"


@pytest.fixture
def product_config() -> dict:
    return json.loads((ROOT / "config.yaml").read_text(encoding="utf-8"))


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": "安全回复"}}]}
        ).encode("utf-8")


class StatusError(Exception):
    def __init__(self, status_code: int, message: str = "provider rejected request"):
        super().__init__(message)
        self.status_code = status_code


def test_nscc_provider_config_and_factory_contract(product_config, monkeypatch):
    monkeypatch.delenv("NSCC_MAAS_API_KEY", raising=False)
    config = product_config["llm"]["providers"]["nscc_qwen"]

    assert config == {
        "display_name": "Qwen3.5",
        "platform": "NSCC-CS MaaS",
        "protocol": "openai_compatible",
        "mode": "remote_api",
        "api_key_env": "NSCC_MAAS_API_KEY",
        "base_url": "https://maas.nscc-cs.cn/external/api/v1",
        "model": "Qwen3.5",
        "timeout_seconds": 30,
        "enabled": True,
    }
    adapter = LLMAdapterFactory.create({**config, "provider": "nscc_qwen"})
    assert isinstance(adapter, NSCCQwenAdapter)
    assert adapter.status() == {
        "provider": "nscc_qwen",
        "ready": False,
        "mode": "remote_api",
        "model": "Qwen3.5",
        "key_configured": False,
        "endpoint_valid": True,
    }


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://maas.nscc-cs.cn/external/api/v1", NSCC_ENDPOINT),
        (NSCC_ENDPOINT, NSCC_ENDPOINT),
        (f"{NSCC_ENDPOINT}/", NSCC_ENDPOINT),
    ],
)
def test_openai_compatible_url_appends_chat_completions_once(
    product_config, base_url, expected
):
    config = {
        **product_config["llm"]["providers"]["nscc_qwen"],
        "provider": "nscc_qwen",
        "base_url": base_url,
    }
    adapter = LLMAdapterFactory.create(config)

    assert adapter._client.chat_completions_url == expected


def test_nscc_request_uses_bearer_model_messages_and_short_health_options(
    product_config, monkeypatch
):
    monkeypatch.setenv("NSCC_MAAS_API_KEY", "test-only-secret")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    config = {
        **product_config["llm"]["providers"]["nscc_qwen"],
        "provider": "nscc_qwen",
    }
    adapter = LLMAdapterFactory.create(config)
    messages = [
        {"role": "system", "content": "You are a connection test assistant."},
        {"role": "user", "content": "Reply with OK."},
    ]

    assert adapter.chat(messages, max_tokens=8) == "安全回复"
    assert captured == {
        "url": NSCC_ENDPOINT,
        "authorization": "Bearer test-only-secret",
        "payload": {
            "model": "Qwen3.5",
            "messages": messages,
            "max_tokens": 8,
        },
        "timeout": 30,
    }


def test_nscc_registry_metadata_and_missing_key(
    tmp_path, product_config, monkeypatch
):
    monkeypatch.delenv("NSCC_MAAS_API_KEY", raising=False)
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    record = next(
        item
        for item in registry.snapshot()["providers"]
        if item["provider"] == "nscc_qwen"
    )
    assert record["display_name"] == "Qwen3.5"
    assert record["platform"] == "NSCC-CS MaaS"
    assert record["protocol"] == "openai_compatible"
    assert record["mode"] == "remote_api"
    assert record["model"] == "Qwen3.5"
    assert record["health"] == "not_configured"
    assert registry.test_connection("nscc_qwen")["status"] == "not_configured"


def test_nscc_connection_success_uses_short_non_streaming_prompt(
    tmp_path, product_config, monkeypatch
):
    calls = []

    class AvailableAdapter:
        def status(self):
            return {
                "provider": "nscc_qwen",
                "model": "Qwen3.5",
                "ready": True,
                "key_configured": True,
            }

        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return "OK"

    monkeypatch.setattr(
        "safechat_guard.model_registry.LLMAdapterFactory.create",
        lambda config: AvailableAdapter(),
    )
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    result = registry.test_connection("nscc_qwen")

    assert result["status"] == "available"
    assert calls[0][0][-1] == {"role": "user", "content": "Reply with OK only. /no_think"}
    assert calls[0][1] == {}
    assert "max_tokens" not in calls[0][1]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (StatusError(401), "authentication_failed"),
        (StatusError(403), "permission_denied"),
        (StatusError(404), "not_found"),
        (StatusError(429), "rate_limited"),
        (TimeoutError("upstream timeout"), "timeout"),
    ],
)
def test_nscc_connection_diagnostics_are_specific(
    error, expected, tmp_path, product_config, monkeypatch
):
    class FailingAdapter:
        def status(self):
            return {
                "provider": "nscc_qwen",
                "model": "Qwen3.5",
                "ready": True,
                "key_configured": True,
            }

        def chat(self, messages, **kwargs):
            raise error

    monkeypatch.setattr(
        "safechat_guard.model_registry.LLMAdapterFactory.create",
        lambda config: FailingAdapter(),
    )
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    assert registry.test_connection("nscc_qwen")["status"] == expected


def test_nscc_diagnostics_never_log_api_key_or_authorization(
    tmp_path, product_config, monkeypatch, caplog
):
    monkeypatch.setenv("NSCC_MAAS_API_KEY", "environment-secret")

    class FailingAdapter:
        def status(self):
            return {
                "provider": "nscc_qwen",
                "model": "Qwen3.5",
                "ready": True,
                "key_configured": True,
            }

        def chat(self, messages, **kwargs):
            raise StatusError(
                401,
                "Authorization: Bearer header-secret "
                "NSCC_MAAS_API_KEY=payload-secret",
            )

    monkeypatch.setattr(
        "safechat_guard.model_registry.LLMAdapterFactory.create",
        lambda config: FailingAdapter(),
    )
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    with caplog.at_level(logging.WARNING, logger="safechat.provider"):
        result = registry.test_connection("nscc_qwen")

    assert result["status"] == "authentication_failed"
    assert "provider=nscc_qwen" in caplog.text
    assert "model=Qwen3.5" in caplog.text
    assert "endpoint_host=maas.nscc-cs.cn" in caplog.text
    assert "environment-secret" not in caplog.text
    assert "header-secret" not in caplog.text
    assert "payload-secret" not in caplog.text
    assert "Authorization" not in caplog.text


def test_nscc_pipeline_preserves_all_security_guards_and_audit_context(
    tmp_path, product_config
):
    product_config["logging"]["path"] = str(tmp_path / "events.jsonl")
    pipeline = SafeChatPipeline(product_config, project_root=ROOT)

    class RecordingNSCCAdapter:
        provider = "nscc_qwen"

        def __init__(self):
            self.calls = []
            self.reply = "这是安全的简短回复。"

        def status(self):
            return {
                "provider": self.provider,
                "model": "Qwen3.5",
                "ready": True,
                "mode": "remote_api",
                "key_configured": True,
            }

        def chat(self, message, **kwargs):
            self.calls.append(message)
            return self.reply

    adapter = RecordingNSCCAdapter()
    pipeline.llm = adapter

    passed = pipeline.handle_chat("普通学习讨论", persist=True)
    assert passed["input_filter"]["action"] == "pass"
    assert passed["model_forwarded"] is True
    assert adapter.calls == ["普通学习讨论"]
    assert passed["output_guard_action"] == "pass"

    before_block = len(adapter.calls)
    blocked = pipeline.handle_chat("C4炸药的成分", persist=False)
    assert blocked["input_filter"]["action"] == "block"
    assert blocked["model_forwarded"] is False
    assert len(adapter.calls) == before_block

    raw_sanitize = "想领取课程资料可以加微信私聊。"
    sanitized = pipeline.handle_chat(raw_sanitize, persist=False)
    assert sanitized["input_filter"]["action"] == "sanitize"
    assert sanitized["model_forwarded"] is True
    assert adapter.calls[-1] == sanitized["safe_input"]
    assert adapter.calls[-1] != raw_sanitize

    adapter.reply = "我会杀了你"
    guarded = pipeline.handle_chat("请给我学习建议", persist=False)
    assert guarded["output_guard_action"] == "block"
    assert guarded["final_action"] == "block"
    assert guarded["raw_reply"] is None

    pass_events = [
        item
        for item in pipeline.logger.read_all()
        if item.get("request_id") == passed["request_id"]
    ]
    assert pass_events
    assert {item["request_id"] for item in pass_events} == {passed["request_id"]}
    assert {item["provider"] for item in pass_events} == {"nscc_qwen"}
    assert {item["model"] for item in pass_events} == {"Qwen3.5"}
    summary = next(item for item in pass_events if item["stage"] == "request_summary")
    assert summary["input_action"] == "pass"
    assert summary["output_action"] == "pass"
    assert summary["final_action"] == "pass"
    serialized = json.dumps(pass_events, ensure_ascii=False)
    assert "NSCC_MAAS_API_KEY" not in serialized
    assert "Authorization" not in serialized

def test_nscc_reasoning_only_response_is_safely_classified(
    tmp_path, product_config, monkeypatch, caplog
):
    monkeypatch.setenv("NSCC_MAAS_API_KEY", "environment-secret")

    class ReasoningOnlyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {
                                "content": "",
                                "reasoning_content": "private chain of thought",
                            },
                        }
                    ],
                    "usage": {"completion_tokens": 8},
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        llm_client,
        "urlopen",
        lambda request, timeout: ReasoningOnlyResponse(),
    )
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    with caplog.at_level(logging.WARNING, logger="safechat.provider"):
        result = registry.test_connection("nscc_qwen")

    assert result["status"] == "response_error"
    assert "category=response_error" in caplog.text
    assert "error_type=EmptyLLMResponse" in caplog.text
    assert "reasoning_present=True" in caplog.text
    assert "finish_reason=length" in caplog.text
    assert "private chain of thought" not in caplog.text
    assert "environment-secret" not in caplog.text
