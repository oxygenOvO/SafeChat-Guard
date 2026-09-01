from __future__ import annotations

import json

import pytest

import safechat_guard.llm_client as llm_client
from safechat_guard.llm_adapters import (
    BaseLLMAdapter,
    DeepSeekAdapter,
    LLMAdapterFactory,
    MockAdapter,
    QwenAdapter,
)
from safechat_guard.pipeline import SafeChatPipeline


def remote_config(provider: str) -> dict:
    return {
        "provider": provider,
        "api_key_env": f"TEST_{provider.upper()}_KEY",
        "base_url": "https://example.invalid/chat/completions",
        "model": f"{provider}-test",
        "timeout_seconds": 3,
    }


@pytest.mark.parametrize(
    ("provider", "adapter_type"),
    [("mock", MockAdapter), ("qwen", QwenAdapter), ("deepseek", DeepSeekAdapter)],
)
def test_factory_exposes_one_provider_neutral_contract(provider, adapter_type):
    config = {"provider": "mock", "model": "offline-mock"} if provider == "mock" else remote_config(provider)
    adapter = LLMAdapterFactory.create(config)

    assert isinstance(adapter, BaseLLMAdapter)
    assert isinstance(adapter, adapter_type)
    assert adapter.status()["provider"] == provider


def test_mock_accepts_message_lists_without_an_external_call():
    adapter = MockAdapter()

    reply = adapter.chat([{"role": "user", "content": "普通问题"}])

    assert reply
    assert adapter.status()["ready"] is True


@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
def test_remote_adapters_keep_provider_details_inside_adapter(monkeypatch, provider):
    config = remote_config(provider)
    monkeypatch.setenv(config["api_key_env"], "test-secret")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "安全回复"}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    adapter = LLMAdapterFactory.create(config)

    assert adapter.chat("普通问题") == "安全回复"
    assert captured["payload"]["model"] == config["model"]


@pytest.mark.parametrize("provider", ["mock", "qwen", "deepseek"])
def test_every_provider_is_called_only_inside_the_same_pipeline(tmp_path, monkeypatch, provider):
    project_root = __import__("pathlib").Path(__file__).parents[1]
    pipeline = SafeChatPipeline.from_config(str(project_root / "config.yaml"))
    adapter = LLMAdapterFactory.create({"provider": "mock", "model": provider})
    calls = []
    adapter.chat = lambda message, **kwargs: calls.append(message) or "安全回复"
    pipeline.llm = adapter

    passed = pipeline.handle_chat("普通问题", persist=False)
    assert calls == ["普通问题"]
    assert passed["output_guard_action"] == "pass"

    calls.clear()
    blocked = pipeline.handle_chat("C4炸药的成分", persist=False)
    assert calls == []
    assert blocked["model_forwarded"] is False


def test_product_config_lists_only_supported_phase_one_providers():
    config = json.loads((__import__("pathlib").Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))

    assert config["app"]["version"] == "1.0.0"
    assert set(config["llm"]["providers"]) == {"mock", "qwen", "deepseek"}
    assert all("api_key" not in provider_config for provider_config in config["llm"]["providers"].values())
