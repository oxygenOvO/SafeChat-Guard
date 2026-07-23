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
        return f"Mock model reply: I received your message: {message}"

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "ready": True,
            "mode": "offline_mock",
            "model": "mock",
            "key_configured": False,
        }


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
        status = self.status()
        if not status["endpoint_valid"]:
            raise LLMClientError("llm endpoint is not a valid HTTPS URL")
        if not status["key_configured"]:
            raise LLMClientError(f"llm api key environment variable is not configured: {self.api_key_env}")
        if not self.model:
            raise LLMClientError("llm model is not configured")

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": message}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
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
