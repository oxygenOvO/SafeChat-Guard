import hashlib
import string
from pathlib import Path

from .config_utils import DEFAULT_SEMANTIC_THRESHOLDS
from .models import Detection

try:
    import joblib
except ImportError:
    joblib = None


class SemanticClassifier:
    def __init__(
        self,
        model_path="models/semantic_model.pkl",
        thresholds: dict[str, float] | None = None,
        expected_sha256: str | None = None,
        expected_classes: list[str] | tuple[str, ...] | None = None,
    ):
        self.model_path = str(model_path)
        self.expected_sha256 = (
            expected_sha256.strip().lower() if expected_sha256 else None
        )
        self.expected_classes = (
            [str(item) for item in expected_classes] if expected_classes else None
        )
        self.actual_sha256 = None
        self.model_size_bytes = None
        self.integrity_verified = None
        self.classes_valid = None
        self.thresholds = dict(DEFAULT_SEMANTIC_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)
        self.model = None
        self._error = None
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
        project_root = Path(__file__).parent.parent
        requested_path = Path(model_path)
        full_path = requested_path if requested_path.is_absolute() else project_root / requested_path

        if not full_path.exists():
            self._error = "model file not found"
        elif joblib is None:
            self._error = "model dependency missing: joblib"
        elif self.expected_sha256 and not self._valid_sha256(self.expected_sha256):
            self._error = "model sha256 invalid"
        else:
            try:
                self.model_size_bytes = full_path.stat().st_size
                self.actual_sha256 = self._sha256_file(full_path)
                if self.expected_sha256:
                    self.integrity_verified = self.actual_sha256 == self.expected_sha256
                    if not self.integrity_verified:
                        self._error = "model sha256 mismatch"
                        return

                candidate = joblib.load(full_path)
                if not hasattr(candidate, "predict_proba") or not hasattr(candidate, "classes_"):
                    self._error = "model interface invalid"
                    return

                actual_classes = [str(item) for item in candidate.classes_]
                if self.expected_classes:
                    self.classes_valid = set(actual_classes) == set(self.expected_classes)
                    if not self.classes_valid:
                        self._error = "model classes mismatch"
                        return
                self.model = candidate
            except Exception as exc:
                self._error = f"model load failed: {type(exc).__name__}"

    def status(self) -> dict:
        return {
            "enabled": self.model is not None,
            "loaded": self.model is not None,
            "model_path": self.model_path,
            "model_type": "sklearn_pipeline" if self.model is not None else None,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "integrity_verified": self.integrity_verified,
            "model_size_bytes": self.model_size_bytes,
            "classes": [
                str(item) for item in getattr(self.model, "classes_", [])
            ] if self.model is not None else [],
            "expected_classes": self.expected_classes or [],
            "classes_valid": self.classes_valid,
            "thresholds": dict(self.thresholds),
            "error": self._error,
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _valid_sha256(value: str) -> bool:
        return len(value) == 64 and all(char in string.hexdigits for char in value)

    def predict_scores(self, text: str) -> dict[str, float]:
        if self.model is None:
            return {"normal": 1.0}
        probabilities = self.model.predict_proba([text])[0]
        return {
            str(label): float(probability)
            for label, probability in zip(self.model.classes_, probabilities)
        }

    def detect(self, text: str) -> list[Detection]:
        if self.model is None:
            return []

        scores = self.predict_scores(text)
        risk_scores = {
            str(label): float(probability)
            for label, probability in scores.items()
            if label != "normal"
            and float(probability) >= self.thresholds.get(str(label), 1.0)
        }
        if not risk_scores:
            return []
        label, max_prob = max(risk_scores.items(), key=lambda item: item[1])

        score = self.category_to_score.get(label, 50)
        if max_prob > 0.85:
            score = min(score + 10, 100)
        elif max_prob < self.thresholds.get(label, 0.65):
            score = max(score - 10, 0)

        return [Detection(
            category=str(label),
            level="high" if score >= 80 else "medium",
            score=score,
            reason=f"语义分类器判定为 {self.cn_map.get(label, label)}，置信度 {max_prob:.2%}",
            source="semantic_ml",
            matches=[f"{label}: {max_prob:.2%}"],
        )]
