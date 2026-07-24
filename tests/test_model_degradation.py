from __future__ import annotations

import json
from pathlib import Path

import pytest

from safechat_guard.pipeline import SafeChatPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_runtime(tmp_path: Path, *, required: bool) -> Path:
    semantic = json.loads(
        (PROJECT_ROOT / "config/semantic_thresholds_v1.json").read_text(encoding="utf-8")
    )
    semantic["model_path"] = "models/missing.joblib"
    semantic["model_sha256"] = "0" * 64
    semantic_path = tmp_path / "config/semantic_thresholds_v1.json"
    semantic_path.parent.mkdir(parents=True)
    semantic_path.write_text(json.dumps(semantic), encoding="utf-8")
    config = {
        "app": {"name": "SafeChat-Guard"},
        "risk": {"block_threshold": 80, "sanitize_threshold": 40},
        "semantic": {
            "config_path": "config/semantic_thresholds_v1.json",
            "required": required,
        },
        "llm": {"provider": "mock"},
        "logging": {"path": str(tmp_path / "events.jsonl")},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_optional_missing_model_degrades_but_rules_still_run(tmp_path):
    pipeline = SafeChatPipeline.from_config(str(write_runtime(tmp_path, required=False)))

    result = pipeline.detect_text("contact 13812345678")
    status = pipeline.stats()["semantic_classifier"]

    assert status["loaded"] is False
    assert status["error"] == "model file not found"
    assert result["action"] == "sanitize"
    assert any(item["source"] == "regex" for item in result["detections"])


def test_required_missing_model_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="semantic classifier unavailable"):
        SafeChatPipeline.from_config(str(write_runtime(tmp_path, required=True)))


def test_runtime_report_data_contains_no_developer_absolute_path():
    from scripts.verify_runtime import verify

    result = verify(PROJECT_ROOT / "config.yaml", iterations=1)
    document = json.dumps(result, ensure_ascii=False)

    assert str(PROJECT_ROOT.resolve()).lower() not in document.lower()
    assert result["semantic_classifier"]["model_path"] == "models/semantic_model_v2.joblib"
    assert result["semantic_classifier"]["config_path"] == "config/semantic_thresholds_v1.json"
