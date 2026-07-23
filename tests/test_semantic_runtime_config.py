from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import pytest

from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.semantic_classifier import SemanticClassifier
from safechat_guard.semantic_config import load_semantic_runtime_configuration
from scripts.evaluate_system_v1 import _default_detectors


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_THRESHOLDS = {
    "ad": 0.25,
    "porn": 0.25,
    "violence": 0.55,
    "sensitive": 0.65,
}

FROZEN_MODEL_SHA256 = (
    "82d1b4d188844df7f0670422721a857f6e270ce7ab682859e2e0fd47547fcd7c"
)

class FixedProbabilityModel:
    classes_ = ("normal", "ad", "porn", "violence", "sensitive")

    def predict_proba(self, texts):
        return [[0.20, 0.35, 0.15, 0.15, 0.15] for _ in texts]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_runtime_config(tmp_path: Path, model_path: Path) -> Path:
    config_path = tmp_path / "semantic.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_path": str(model_path),
                "model_sha256": _sha256(model_path),
                "category_thresholds": FROZEN_THRESHOLDS,
                "min_margin": 0.05,
                "calibration_report_path": (
                    "reports/system_eval_v1/semantic_threshold_calibration.json"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _pipeline_config(config_path: Path, *, required: bool) -> dict:
    return {
        "risk": {"block_threshold": 80, "sanitize_threshold": 40},
        "semantic": {
            "config_path": str(config_path),
            "required": required,
        },
        "llm": {"provider": "mock"},
        "logging": {"path": str(config_path.parent / "events.jsonl")},
    }


def test_frozen_production_configuration_matches_calibration_contract():
    configuration = load_semantic_runtime_configuration(PROJECT_ROOT)

    assert configuration.model_path == "models/semantic_model_v2.joblib"
    assert configuration.resolved_model_path == (
        PROJECT_ROOT / "models/semantic_model_v2.joblib"
    ).resolve()
    assert configuration.model_sha256 == FROZEN_MODEL_SHA256
    assert configuration.category_thresholds == FROZEN_THRESHOLDS
    assert configuration.min_margin == 0.05
    assert configuration.calibration_report_path == (
        "reports/system_eval_v1/semantic_threshold_calibration.json"
    )


def test_default_production_pipeline_starts_without_ignored_model(
    production_config_without_model,
):
    production_config = json.loads(
        (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")
    )
    assert production_config["semantic"] == {
        "config_path": "config/semantic_thresholds_v1.json",
        "required": False,
    }
    assert "semantic" not in production_config["llm"]

    with pytest.warns(RuntimeWarning, match="model file not found"):
        pipeline = SafeChatPipeline.from_config(str(production_config_without_model))
    status = pipeline.stats()["semantic_classifier"]

    assert Path(status["model_path"]) == (
        production_config_without_model.parent / "models/semantic_model_v2.joblib"
    ).resolve()
    assert status["required"] is False
    assert status["loaded"] is False
    assert status["enabled"] is False
    assert status["error"] == "model file not found"
    assert status["model_sha256_expected"] == FROZEN_MODEL_SHA256
    assert status["category_thresholds"] == FROZEN_THRESHOLDS
    assert status["min_margin"] == 0.05
    assert status["model_sha256_verified"] is False


def test_pipeline_and_evaluator_use_identical_semantic_gate(tmp_path):
    model_path = tmp_path / "semantic_model_v2.joblib"
    joblib.dump(FixedProbabilityModel(), model_path)
    semantic_config_path = _write_runtime_config(tmp_path, model_path)

    pipeline = SafeChatPipeline(
        _pipeline_config(semantic_config_path, required=True),
        project_root=PROJECT_ROOT,
    )
    _, evaluator_detector = _default_detectors(
        PROJECT_ROOT,
        "semantic_only",
        model_path,
        semantic_config_path,
    )

    pipeline_status = pipeline.semantic_classifier.status()
    evaluator_status = evaluator_detector.status()
    assert pipeline_status["loaded"] is evaluator_status["loaded"] is True
    assert (
        pipeline_status["model_sha256_verified"]
        is evaluator_status["model_sha256_verified"]
        is True
    )
    assert pipeline_status["category_thresholds"] == evaluator_status[
        "category_thresholds"
    ] == FROZEN_THRESHOLDS
    assert pipeline_status["min_margin"] == evaluator_status["min_margin"] == 0.05
    assert pipeline.semantic_classifier.detect("相同概率向量") == (
        evaluator_detector.detect("相同概率向量")
    )


def test_missing_model_status_is_explicit_and_required_pipeline_fails(tmp_path):
    missing_model = tmp_path / "missing.joblib"
    config_path = tmp_path / "semantic.json"
    payload = {
        "schema_version": 1,
        "model_path": str(missing_model),
        "model_sha256": "0" * 64,
        "category_thresholds": FROZEN_THRESHOLDS,
        "min_margin": 0.05,
        "calibration_report_path": "reports/calibration.json",
    }
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    classifier = SemanticClassifier(
        model_path=str(missing_model), expected_model_sha256="0" * 64
    )
    assert classifier.status()["error"] == "model file not found"
    assert classifier.status()["model_sha256_verified"] is False

    with pytest.raises(RuntimeError, match="model file not found"):
        SafeChatPipeline(
            _pipeline_config(config_path, required=True),
            project_root=PROJECT_ROOT,
        )


def test_model_hash_mismatch_refuses_to_enable(tmp_path):
    model_path = tmp_path / "semantic_model_v2.joblib"
    joblib.dump(FixedProbabilityModel(), model_path)

    classifier = SemanticClassifier(
        model_path=str(model_path), expected_model_sha256="0" * 64
    )
    status = classifier.status()

    assert status["loaded"] is False
    assert status["enabled"] is False
    assert status["error"] == "model sha256 mismatch"
    assert status["model_sha256_actual"] == _sha256(model_path)
    assert status["model_sha256_verified"] is False
