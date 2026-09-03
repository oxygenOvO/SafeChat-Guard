"""Provider 适配层：对 pipeline 暴露统一的模型调用契约。

``BaseLLMAdapter`` 是 pipeline 唯一消费的模型契约（chat/status）。
各 Provider 的 Adapter 是对底层 llm_client 的薄封装：

- ``MockAdapter``：离线假模型；
- ``QwenAdapter`` / ``NSCCQwenAdapter`` / ``DeepSeekAdapter``：均继承
  ``OpenAICompatibleAdapter``，仅 provider 标识不同；
- ``LLMAdapterFactory`` 按配置中的 provider 字符串创建对应 Adapter。

前端（模型管理页 / 运维控制台）在运行时通过该工厂创建 Adapter 并
热替换 ``pipeline.llm``，实现不重启切换模型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .llm_client import MockLLMClient, OpenAICompatibleLLMClient


# Provider 在前端展示时使用的友好名称
PROVIDER_LABELS = {
    "mock": "Offline Mock",
    "nscc_qwen": "Qwen3.5",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
}


class BaseLLMAdapter(ABC):
    """pipeline 消费的唯一模型契约。"""

    provider = "unknown"

    @abstractmethod
    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        """返回助手回复；接受纯文本（单轮）或消息列表（多轮对话历史）。"""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """返回就绪状态元数据；不得包含任何密钥明文。"""

    @staticmethod
    def user_text(messages: str | list[dict[str, str]]) -> str:
        """从消息中提取最后一条 user 文本（Mock 等"无状态"模型只看最新输入）。"""
        if isinstance(messages, str):
            return messages
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty string or list")
        for item in reversed(messages):
            if item.get("role") == "user" and isinstance(item.get("content"), str):
                return item["content"]
        raise ValueError("messages must include a user message")


class MockAdapter(BaseLLMAdapter):
    """离线假模型适配器：零配置演示与测试用，忽略多轮历史只看最新输入。"""

    provider = "mock"

    def __init__(self, config: dict[str, Any] | None = None):
        self._client = MockLLMClient()
        self.model = str((config or {}).get("model", "offline-mock"))

    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        return self._client.chat(self.user_text(messages))

    def status(self) -> dict[str, Any]:
        return {**self._client.status(), "model": self.model, "provider": self.provider}


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 兼容协议通用适配器：真实 Provider 的共同基类，直接委托底层客户端。"""

    provider = "openai_compatible"

    def __init__(self, config: dict[str, Any]):
        self._client = OpenAICompatibleLLMClient({**config, "provider": self.provider})

    def chat(self, messages: str | list[dict[str, str]], **kwargs: Any) -> str:
        return self._client.chat(messages, **kwargs)

    def status(self) -> dict[str, Any]:
        return self._client.status()


class QwenAdapter(OpenAICompatibleAdapter):
    provider = "qwen"


class NSCCQwenAdapter(OpenAICompatibleAdapter):
    provider = "nscc_qwen"


class DeepSeekAdapter(OpenAICompatibleAdapter):
    provider = "deepseek"


class LLMAdapterFactory:
    """按 provider 标识创建对应 Adapter 的工厂（前端运行时切换模型的入口）。"""

    ADAPTERS = {
        "mock": MockAdapter,
        "qwen": QwenAdapter,
        "nscc_qwen": NSCCQwenAdapter,
        "deepseek": DeepSeekAdapter,
    }

    @classmethod
    def create(cls, config: dict[str, Any]) -> BaseLLMAdapter:
        """按 config['provider'] 创建适配器；未知 provider 直接抛 ValueError。"""
        provider = str(config.get("provider", "mock")).lower()
        adapter = cls.ADAPTERS.get(provider)
        if adapter is None:
            raise ValueError(f"unsupported llm provider: {provider}")
        return adapter(config)
