"""Provider-neutral LLM adapters for the SafeChat-Guard pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .llm_client import MockLLMClient, OpenAICompatibleLLMClient


PROVIDER_LABELS = {
    "mock": "Offline Mock",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
}


class BaseLLMAdapter(ABC):
    """The only model contract consumed by the guarded pipeline."""

    provider = "unknown"

    @abstractmethod
    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        """Return an assistant response for a string or message list."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Return readiness metadata without secrets."""

    @staticmethod
    def user_text(messages: str | list[dict[str, str]]) -> str:
        if isinstance(messages, str):
            return messages
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty string or list")
        for item in reversed(messages):
            if item.get("role") == "user" and isinstance(item.get("content"), str):
                return item["content"]
        raise ValueError("messages must include a user message")


class MockAdapter(BaseLLMAdapter):
    provider = "mock"

    def __init__(self, config: dict[str, Any] | None = None):
        self._client = MockLLMClient()
        self.model = str((config or {}).get("model", "offline-mock"))

    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        return self._client.chat(self.user_text(messages))

    def status(self) -> dict[str, Any]:
        return {**self._client.status(), "model": self.model, "provider": self.provider}


class OpenAICompatibleAdapter(BaseLLMAdapter):
    provider = "openai_compatible"

    def __init__(self, config: dict[str, Any]):
        self._client = OpenAICompatibleLLMClient({**config, "provider": self.provider})

    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        return self._client.chat(self.user_text(messages))

    def status(self) -> dict[str, Any]:
        return self._client.status()


class QwenAdapter(OpenAICompatibleAdapter):
    provider = "qwen"


class DeepSeekAdapter(OpenAICompatibleAdapter):
    provider = "deepseek"


class LLMAdapterFactory:
    ADAPTERS = {
        "mock": MockAdapter,
        "qwen": QwenAdapter,
        "deepseek": DeepSeekAdapter,
    }

    @classmethod
    def create(cls, config: dict[str, Any]) -> BaseLLMAdapter:
        provider = str(config.get("provider", "mock")).lower()
        adapter = cls.ADAPTERS.get(provider)
        if adapter is None:
            raise ValueError(f"unsupported llm provider: {provider}")
        return adapter(config)
