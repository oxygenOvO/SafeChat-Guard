from pathlib import Path

from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.semantic_classifier import SemanticClassifier
import safechat_guard.semantic_classifier as semantic_module


def test_missing_model_file_degrades_safely(tmp_path):
    classifier = SemanticClassifier(model_path=str(tmp_path / "missing.pkl"))

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model file not found"
    assert classifier.predict_scores("sample") == {"normal": 1.0}
    assert classifier.detect("sample") == []


def test_missing_joblib_degrades_safely(monkeypatch, tmp_path):
    model_file = tmp_path / "model.pkl"
    model_file.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(semantic_module, "joblib", None)

    classifier = SemanticClassifier(model_path=str(model_file))

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model dependency missing: joblib"


def test_damaged_model_file_degrades_safely(tmp_path):
    model_file = tmp_path / "damaged.pkl"
    model_file.write_bytes(b"not a valid joblib model")

    classifier = SemanticClassifier(model_path=str(model_file))

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] in {
        "model dependency missing: joblib",
        "model load failed: KeyError",
        "model load failed: UnpicklingError",
        "model load failed: ValueError",
        "model load failed: EOFError",
    }
    assert classifier.detect("sample") == []


def test_rule_filter_still_runs_when_semantic_model_unavailable(tmp_path):
    config = {
        "risk": {"block_threshold": 80, "sanitize_threshold": 40},
        "llm": {"provider": "mock"},
        "logging": {"path": str(tmp_path / "events.jsonl")},
        "semantic_thresholds": {"ad": 0.65},
    }
    pipeline = SafeChatPipeline(config)
    pipeline.semantic_classifier = SemanticClassifier(model_path=str(tmp_path / "missing.pkl"))

    result = pipeline._filter_text("please contact vx for details", stage="input")

    assert result["action"] == "sanitize"
    assert any(item["source"] == "regex" for item in result["detections"])
    stats = pipeline.stats()
    assert stats["model_loaded"] is False
    assert stats["model_error"] == "model file not found"
