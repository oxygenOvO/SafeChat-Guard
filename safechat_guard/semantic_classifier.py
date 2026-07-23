from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
from typing import Any

from .models import Detection

try:
    import joblib
except ImportError:
    joblib = None


DEFAULT_CATEGORY_THRESHOLDS = {
    "ad": 0.65,
    "porn": 0.55,
    "violence": 0.55,
    "sensitive": 0.65,
}
DEFAULT_MIN_MARGIN = 0.10


def _validated_thresholds(
    category_thresholds: Mapping[str, float] | None,
) -> dict[str, float]:
    thresholds = dict(DEFAULT_CATEGORY_THRESHOLDS)
    if category_thresholds is not None:
        unknown = set(category_thresholds) - set(DEFAULT_CATEGORY_THRESHOLDS)
        if unknown:
            raise ValueError(f"unknown semantic threshold categories: {sorted(unknown)}")
        thresholds.update(
            {label: float(value) for label, value in category_thresholds.items()}
        )
    if any(not 0.0 <= value <= 1.0 for value in thresholds.values()):
        raise ValueError("semantic category thresholds must be between 0 and 1")
    return thresholds


def select_risk_prediction(
    classes: Sequence[Any],
    probabilities: Sequence[float],
    category_thresholds: Mapping[str, float],
    min_margin: float,
) -> tuple[str, float, float] | None:
    """Apply the production semantic gate to one probability vector."""
    pairs = [
        (str(label), float(probability))
        for label, probability in zip(classes, probabilities, strict=True)
    ]
    if not pairs:
        return None
    top_label, top_probability = max(pairs, key=lambda item: item[1])
    if top_label == "normal":
        return None

    threshold = category_thresholds.get(top_label)
    if threshold is None or top_probability < threshold:
        return None
    normal_probability = next(
        (probability for label, probability in pairs if label == "normal"),
        0.0,
    )
    if top_probability - normal_probability < min_margin:
        return None
    return top_label, top_probability, normal_probability


class SemanticClassifier:
    def __init__(
        self,
        model_path: str = "models/semantic_model.pkl",
        *,
        category_thresholds: Mapping[str, float] | None = None,
        min_margin: float = DEFAULT_MIN_MARGIN,
        expected_model_sha256: str | None = None,
    ):
        self.model_path = model_path
        self.model = None
        self._error = None
        self.expected_model_sha256 = (
            expected_model_sha256.lower() if expected_model_sha256 else None
        )
        self.actual_model_sha256 = None
        self.category_thresholds = _validated_thresholds(category_thresholds)
        self.min_margin = float(min_margin)
        if not 0.0 <= self.min_margin <= 1.0:
            raise ValueError("semantic minimum margin must be between 0 and 1")

        project_root = Path(__file__).parent.parent
        full_path = project_root / model_path
        if not full_path.is_file():
            self._error = "model file not found"
        elif self.expected_model_sha256 is not None:
            try:
                digest = hashlib.sha256()
                with full_path.open("rb") as model_file:
                    for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                self.actual_model_sha256 = digest.hexdigest()
            except OSError as exc:
                self._error = f"model hash failed: {type(exc).__name__}"
            if (
                self._error is None
                and self.actual_model_sha256 != self.expected_model_sha256
            ):
                self._error = "model sha256 mismatch"
        if self._error is None and joblib is None:
            self._error = "model dependency missing: joblib"
        elif self._error is None:
            try:
                self.model = joblib.load(full_path)
            except (OSError, ValueError, TypeError) as exc:
                self._error = f"model load failed: {type(exc).__name__}"

        self.category_to_score = {
            "porn": 85,
            "violence": 85,
            "ad": 70,
            "sensitive": 70,
            "normal": 10,
        }
        self.cn_map = {
            "porn": "色情低俗",
            "violence": "暴力威胁",
            "ad": "广告引流",
            "sensitive": "敏感话术",
            "normal": "正常",
        }

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.model is not None,
            "loaded": self.model is not None,
            "model_path": self.model_path,
            "model_sha256_expected": self.expected_model_sha256,
            "model_sha256_actual": self.actual_model_sha256,
            "model_sha256_verified": (
                self.expected_model_sha256 is not None
                and self.actual_model_sha256 == self.expected_model_sha256
            ),
            "model_type": "sklearn_pipeline" if self.model is not None else None,
            "classes": [
                str(item) for item in getattr(self.model, "classes_", [])
            ] if self.model is not None else [],
            "category_thresholds": dict(self.category_thresholds),
            "min_margin": self.min_margin,
            "error": self._error,
        }

    def detect(self, text: str) -> list[Detection]:
        if self.model is None:
            return []

        probabilities = self.model.predict_proba([text])[0]
        selected = select_risk_prediction(
            self.model.classes_,
            probabilities,
            self.category_thresholds,
            self.min_margin,
        )
        if selected is None:
            return []
        label, probability, normal_probability = selected

        score = self.category_to_score.get(label, 50)
        if probability > 0.85:
            score = min(score + 10, 100)
        elif probability < 0.6:
            score = max(score - 10, 0)

        detection = Detection(
            category=label,
            level="high" if score >= 80 else "medium",
            score=score,
            reason=(
                f"语义分类器判定为 {self.cn_map.get(label, label)}，"
                f"置信度 {probability:.2%}，相对normal差值 "
                f"{probability - normal_probability:.2%}"
            ),
            source="semantic_ml",
            matches=[f"{label}: {probability:.2%}"],
        )
        return [detection]
