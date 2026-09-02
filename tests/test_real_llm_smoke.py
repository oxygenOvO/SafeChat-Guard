import json
from pathlib import Path

from safechat_guard.pipeline import SafeChatPipeline
from scripts.smoke_real_llm import exercise_pipeline


ROOT = Path(__file__).resolve().parents[1]


class SafeFakeRemoteClient:
    provider = "test_openai_compatible"

    def chat(self, message: str) -> str:
        return "这是安全的简短回复。"

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "ready": True,
            "mode": "test_double",
            "model": "test-model",
            "key_configured": True,
        }


def test_real_llm_example_preserves_default_mock_and_exercises_safety_chain():
    default_config = json.loads((ROOT / "config.yaml").read_text(encoding="utf-8"))
    real_config = json.loads(
        (ROOT / "config.real_llm.example.yaml").read_text(encoding="utf-8")
    )

    assert default_config["llm"]["provider"] == "mock"
    assert "api_key" not in real_config["llm"]
    assert real_config["llm"]["provider"] == "nscc_qwen"
    assert real_config["llm"]["api_key_env"] == "NSCC_MAAS_API_KEY"
    assert real_config["llm"]["model"] == "Qwen3.5"

    pipeline = SafeChatPipeline(default_config, project_root=ROOT)
    result = exercise_pipeline(pipeline, SafeFakeRemoteClient())

    assert result["live_upstream_call_count"] == 2
    assert result["pass_forwarded"] is True
    assert result["block_not_forwarded"] is True
    assert result["sanitize_forwarded_after_redaction"] is True
    assert result["upstream_failure_closed_safely"] is True
    assert result["unsafe_output_blocked"] is True
