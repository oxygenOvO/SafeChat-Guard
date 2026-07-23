from pathlib import Path
import hashlib

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


def test_sha_mismatch_is_rejected_before_deserialization(monkeypatch, tmp_path):
    model_file = tmp_path / "untrusted.joblib"
    model_file.write_bytes(b"not trusted")
    load_called = False

    def fail_if_loaded(path):
        nonlocal load_called
        load_called = True
        raise AssertionError("joblib.load must not run before integrity verification")

    monkeypatch.setattr(semantic_module.joblib, "load", fail_if_loaded)
    classifier = SemanticClassifier(
        model_path=str(model_file),
        expected_sha256="0" * 64,
    )

    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model sha256 mismatch"
    assert classifier.status()["integrity_verified"] is False
    assert classifier.status()["actual_sha256"] == hashlib.sha256(b"not trusted").hexdigest()
    assert load_called is False


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
