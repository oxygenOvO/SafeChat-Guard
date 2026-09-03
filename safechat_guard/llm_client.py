"""LLM 底层客户端：Mock 客户端与 OpenAI-compatible HTTP 客户端。

这是模型接入的最底层封装，上层（llm_adapters 的 Adapter、pipeline）都
最终调用到这里：

- ``MockLLMClient``：离线假模型，固定返回安全回复。用于零配置演示、
  自动化测试与断网环境，绝不产生真实网络调用。
- ``OpenAICompatibleLLMClient``：通用 OpenAI Chat Completions 协议客户端
  （基于标准库 urllib，无第三方依赖）。DeepSeek / DashScope Qwen /
  NSCC Qwen3.5 等所有真实 Provider 共用这一个实现，仅配置不同。

安全要点：
- API Key 只从 ``api_key_env`` 指定的环境变量读取，不落盘、不进日志；
  调用前与使用前各校验一次，避免环境变量被移除导致的裸 KeyError；
- 请求失败通过 provider_diagnostics 归一化为分类错误（超时/认证失败/
  限流/连接失败等），抛出的 LLMClientError 不携带密钥或请求正文，
  保证异常信息可以安全地展示给前端。
"""

import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .provider_diagnostics import (
    classify_provider_error,
    sanitize_provider_error,
)


class LLMClientError(RuntimeError):
    """LLM 调用失败的统一异常。

    携带脱敏后的分类诊断信息（category/http_status/safe_summary），
    上层据此决定用户提示文案与 Fail-Closed 行为，原始异常不外泄。
    """

    def __init__(
        self,
        message: str,
        *,
        category: str | None = None,
        http_status: int | None = None,
        error_type: str | None = None,
        safe_summary: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.error_type = error_type
        self.safe_summary = safe_summary


class MockLLMClient:
    """离线假模型：零配置演示与自动化测试专用，固定返回安全回复。"""

    provider = "mock"

    def chat(self, message: str) -> str:
        return "Mock model reply: request processed safely."

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "ready": True,
            "mode": "offline_mock",
            "model": "mock",
            "key_configured": False,
        }


class OpenAICompatibleLLMClient:
    """通用 OpenAI Chat Completions 协议客户端（纯标准库实现）。

    所有真实 Provider（DeepSeek / DashScope Qwen / NSCC Qwen3.5）共用，
    差异只在配置：base_url、model、api_key_env、timeout_seconds。
    """

    def __init__(self, config: dict):
        self.provider = str(config.get("provider", "openai_compatible"))
        self.model = str(config.get("model", "")).strip()
        self.api_key_env = str(config.get("api_key_env", "QWEN_API_KEY")).strip()
        self.base_url = str(config.get("base_url", "")).strip()
        self.timeout_seconds = float(config.get("timeout_seconds", 30))

    @property
    def chat_completions_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def status(self) -> dict:
        parsed = urlparse(self.base_url)
        endpoint_valid = parsed.scheme == "https" and bool(parsed.netloc)
        key_configured = bool(self.api_key_env and os.getenv(self.api_key_env))
        return {
            "provider": self.provider,
            "ready": bool(endpoint_valid and key_configured and self.model),
            "mode": "remote_api",
            "model": self.model,
            "key_configured": key_configured,
            "endpoint_valid": endpoint_valid,
        }

    def chat(
        self,
        messages: str | list[dict[str, str]],
        **kwargs,
    ) -> str:
        """执行一次 Chat Completions 调用并返回助手回复文本。

        messages 传字符串时按单条 user 消息处理；传列表时按 OpenAI
        消息数组处理（多轮对话）。调用前逐项校验 endpoint/密钥/模型，
        网络与解析异常统一转换为脱敏分类的 LLMClientError。
        """
        status = self.status()
        if not status["endpoint_valid"]:
            raise LLMClientError("llm endpoint is not a valid HTTPS URL")
        if not status["key_configured"]:
            raise LLMClientError(f"llm api key environment variable is not configured: {self.api_key_env}")
        if not self.model:
            raise LLMClientError("llm model is not configured")

        request_messages = (
            [{"role": "user", "content": messages}]
            if isinstance(messages, str)
            else messages
        )
        if not isinstance(request_messages, list) or not request_messages:
            raise LLMClientError("llm messages are not configured")
        request_payload = {"model": self.model, "messages": request_messages}
        if kwargs.get("max_tokens") is not None:
            request_payload["max_tokens"] = int(kwargs["max_tokens"])
        payload = json.dumps(
            request_payload,
            ensure_ascii=False,
        ).encode("utf-8")
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise LLMClientError(
                f"llm api key environment variable is not configured: {self.api_key_env}"
            )
        request = Request(
            self.chat_completions_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, socket.timeout, UnicodeDecodeError, json.JSONDecodeError) as exc:
            diagnostic = classify_provider_error(exc)
            raise LLMClientError(
                "llm request failed",
                category=diagnostic.category,
                http_status=diagnostic.http_status,
                error_type=diagnostic.error_type,
                safe_summary=diagnostic.safe_summary,
            ) from None

        try:
            choice = document["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMClientError(
                "llm response schema is invalid",
                category="response_error",
                error_type="InvalidLLMResponse",
                safe_summary="llm response schema is invalid",
            ) from None
        if not isinstance(choice, dict) or not isinstance(message, dict):
            raise LLMClientError(
                "llm response schema is invalid",
                category="response_error",
                error_type="InvalidLLMResponse",
                safe_summary="llm response schema is invalid",
            )

        content = message.get("content")
        extracted = self._extract_text_content(content)
        if extracted is None:
            raise self._empty_response_error(document, choice, message, content)
        return extracted

    @staticmethod
    def _extract_text_content(content) -> str | None:
        if isinstance(content, str):
            return content if content.strip() else None
        if not isinstance(content, list):
            return None

        parts = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type not in {None, "text", "output_text"}:
                continue
            text = item.get("text")
            if isinstance(text, dict):
                text = text.get("value")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        return "\n".join(parts) if parts else None

    @staticmethod
    def _empty_response_error(
        document: dict,
        choice: dict,
        message: dict,
        content,
    ) -> LLMClientError:
        finish_reason = sanitize_provider_error(
            choice.get("finish_reason") or "unavailable",
            max_length=40,
        )
        reasoning = message.get("reasoning_content")
        reasoning_length = len(reasoning) if isinstance(reasoning, str) else 0
        usage = document.get("usage")
        completion_count = (
            usage.get("completion_tokens")
            if isinstance(usage, dict)
            else None
        )
        safe_summary = (
            "llm response has no final content "
            f"finish_reason={finish_reason} "
            f"content_type={type(content).__name__} "
            f"reasoning_present={reasoning_length > 0} "
            f"reasoning_chars={reasoning_length} "
            f"completion_count={completion_count if isinstance(completion_count, int) else 'unavailable'}"
        )
        return LLMClientError(
            "llm response content is empty",
            category="response_error",
            error_type="EmptyLLMResponse",
            safe_summary=safe_summary,
        )



class LLMClientFactory:
    @staticmethod
    def create(config: dict):
        provider = str(config.get("provider", "mock")).lower()
        if provider == "mock":
            return MockLLMClient()
        if provider in {"qwen", "nscc_qwen", "deepseek", "openai_compatible"}:
            return OpenAICompatibleLLMClient(config)
        raise ValueError(f"unsupported llm provider: {provider}")
