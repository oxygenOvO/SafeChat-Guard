class MockLLMClient:
    def chat(self, message: str) -> str:
        return f"Mock model reply: I received your message: {message}"


class LLMClientFactory:
    @staticmethod
    def create(config: dict):
        provider = config.get("provider", "mock")
        if provider != "mock":
            # Keep the same interface for later Qwen/OpenAI-compatible API integration.
            return MockLLMClient()
        return MockLLMClient()
