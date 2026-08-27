import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class LLMClientError(RuntimeError):
    pass


class MockLLMClient:
    provider = "mock"

    def chat(self, message: str) -> str:
        return "Mock model reply: request processed safely."

    def chat_messages(
        self,
        messages: list[dict],
        *,
        temperature: float = 0,
        response_format: dict | None = None,
    ) -> str:
        self._validate_messages(messages, temperature)
        self._validate_response_format(response_format)
        return self.chat(messages[-1]["content"])

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "ready": True,
            "mode": "offline_mock",
            "model": "mock",
            "key_configured": False,
        }

    @staticmethod
    def _validate_messages(messages: list[dict], temperature: float) -> None:
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= float(temperature) <= 2
        ):
            raise ValueError("temperature must be numeric and in [0, 2]")
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError("each message must contain only role and content")
            if message["role"] not in {"system", "user", "assistant"}:
                raise ValueError("unsupported message role")
            if not isinstance(message["content"], str) or not message["content"].strip():
                raise ValueError("message content must be a non-empty string")

    @staticmethod
    def _validate_response_format(response_format: dict | None) -> None:
        if response_format is None:
            return
        if response_format != {"type": "json_object"}:
            raise ValueError(
                "response_format must be omitted or {'type': 'json_object'}"
            )


class OpenAICompatibleLLMClient:
    def __init__(self, config: dict):
        self.provider = str(config.get("provider", "openai_compatible"))
        self.model = str(config.get("model", "")).strip()
        self.api_key_env = str(config.get("api_key_env", "QWEN_API_KEY")).strip()
        self.base_url = str(config.get("base_url", "")).strip()
        self.timeout_seconds = float(config.get("timeout_seconds", 30))

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

    def chat(self, message: str) -> str:
        return self.chat_messages(
            [{"role": "user", "content": message}],
            temperature=0,
        )

    def chat_messages(
        self,
        messages: list[dict],
        *,
        temperature: float = 0,
        response_format: dict | None = None,
    ) -> str:
        MockLLMClient._validate_messages(messages, temperature)
        MockLLMClient._validate_response_format(response_format)
        status = self.status()
        if not status["endpoint_valid"]:
            raise LLMClientError("llm endpoint is not a valid HTTPS URL")
        if not status["key_configured"]:
            raise LLMClientError(f"llm api key environment variable is not configured: {self.api_key_env}")
        if not self.model:
            raise LLMClientError("llm model is not configured")

        request_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
        }
        # Opt-in only: ordinary business-model chat requests remain unchanged.
        if response_format is not None:
            request_payload["response_format"] = response_format
        payload = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {os.environ[self.api_key_env]}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, socket.timeout, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMClientError(f"llm request failed: {type(exc).__name__}") from None

        try:
            content = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMClientError("llm response schema is invalid") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("llm response content is empty")
        return content


class LLMClientFactory:
    @staticmethod
    def create(config: dict):
        provider = str(config.get("provider", "mock")).lower()
        if provider == "mock":
            return MockLLMClient()
        if provider in {"qwen", "openai_compatible"}:
            return OpenAICompatibleLLMClient(config)
        raise ValueError(f"unsupported llm provider: {provider}")
