from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RISK_LABELS = ("ad", "porn", "violence", "sensitive")
DEFAULT_PRODUCTION_CONFIG_PATH = Path("config/semantic_thresholds_v1.json")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SemanticRuntimeConfiguration:
    schema_version: int
    model_path: str
    model_sha256: str
    category_thresholds: dict[str, float]
    min_margin: float
    calibration_report_path: str
    config_path: Path
    resolved_model_path: Path

    def classifier_options(self) -> dict[str, Any]:
        return {
            "model_path": str(self.resolved_model_path),
            "category_thresholds": dict(self.category_thresholds),
            "min_margin": self.min_margin,
            "expected_model_sha256": self.model_sha256,
        }


def _resolve_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def load_semantic_runtime_configuration(
    project_root: Path,
    config_path: str | Path = DEFAULT_PRODUCTION_CONFIG_PATH,
) -> SemanticRuntimeConfiguration:
    project_root = project_root.resolve()
    resolved_config_path = _resolve_path(project_root, config_path)
    if not resolved_config_path.is_file():
        raise FileNotFoundError(
            f"semantic production config not found: {resolved_config_path}"
        )
    payload = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    expected_fields = {
        "schema_version",
        "model_path",
        "model_sha256",
        "category_thresholds",
        "min_margin",
        "calibration_report_path",
    }
    if set(payload) != expected_fields:
        raise ValueError(
            "semantic production config fields do not match schema: "
            f"expected={sorted(expected_fields)}, actual={sorted(payload)}"
        )
    if payload["schema_version"] != 1:
        raise ValueError("unsupported semantic production config schema_version")

    thresholds = payload["category_thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != set(RISK_LABELS):
        raise ValueError("semantic production config must define all risk thresholds")
    parsed_thresholds = {
        label: float(thresholds[label]) for label in RISK_LABELS
    }
    if any(not 0.0 <= value <= 1.0 for value in parsed_thresholds.values()):
        raise ValueError("semantic category thresholds must be between 0 and 1")

    min_margin = float(payload["min_margin"])
    if not 0.0 <= min_margin <= 1.0:
        raise ValueError("semantic minimum margin must be between 0 and 1")
    model_sha256 = str(payload["model_sha256"]).lower()
    if not _SHA256_PATTERN.fullmatch(model_sha256):
        raise ValueError("semantic model_sha256 must be a lowercase SHA-256 digest")

    model_path = str(payload["model_path"])
    calibration_report_path = str(payload["calibration_report_path"])
    return SemanticRuntimeConfiguration(
        schema_version=1,
        model_path=model_path,
        model_sha256=model_sha256,
        category_thresholds=parsed_thresholds,
        min_margin=min_margin,
        calibration_report_path=calibration_report_path,
        config_path=resolved_config_path,
        resolved_model_path=_resolve_path(project_root, model_path),
    )


def build_semantic_classifier(configuration: SemanticRuntimeConfiguration):
    from .semantic_classifier import SemanticClassifier

    return SemanticClassifier(**configuration.classifier_options())
