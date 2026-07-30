from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

try:
    import joblib
except ImportError:
    joblib = None


@dataclass(frozen=True)
class ActionScoresV3:
    risk_probability: float
    block_probability: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ActionModelBundleV3:
    """Load independently trained risk-presence and block-severity models."""

    def __init__(
        self,
        risk_model_path: str | Path,
        block_model_path: str | Path,
        *,
        expected_risk_sha256: str | None = None,
        expected_block_sha256: str | None = None,
    ):
        self.risk_model_path = Path(risk_model_path)
        self.block_model_path = Path(block_model_path)
        self.expected_risk_sha256 = self._normalize_hash(expected_risk_sha256)
        self.expected_block_sha256 = self._normalize_hash(expected_block_sha256)
        self.actual_risk_sha256: str | None = None
        self.actual_block_sha256: str | None = None
        self.risk_model = None
        self.block_model = None
        self.error: str | None = None
        self._load()

    @staticmethod
    def _normalize_hash(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ValueError("expected model sha256 must be 64 lowercase hex chars")
        return normalized

    def _load(self) -> None:
        if joblib is None:
            self.error = "model dependency missing: joblib"
            return
        for kind, path, expected in (
            ("risk", self.risk_model_path, self.expected_risk_sha256),
            ("block", self.block_model_path, self.expected_block_sha256),
        ):
            if not path.is_file():
                self.error = f"{kind} model file not found"
                return
            actual = sha256_file(path)
            setattr(self, f"actual_{kind}_sha256", actual)
            if expected is not None and actual != expected:
                self.error = f"{kind} model sha256 mismatch"
                return
        try:
            self.risk_model = joblib.load(self.risk_model_path)
            self.block_model = joblib.load(self.block_model_path)
        except (OSError, TypeError, ValueError) as exc:
            self.error = f"action model load failed: {type(exc).__name__}"
            self.risk_model = None
            self.block_model = None
            return
        for kind, model in (
            ("risk", self.risk_model),
            ("block", self.block_model),
        ):
            if not callable(getattr(model, "predict_proba", None)):
                self.error = f"{kind} model lacks predict_proba"
                self.risk_model = None
                self.block_model = None
                return

    @property
    def loaded(self) -> bool:
        return self.risk_model is not None and self.block_model is not None

    @staticmethod
    def _positive_probability(model: Any, text: str) -> float:
        probabilities = model.predict_proba([text])[0]
        classes = [str(value) for value in model.classes_]
        positive_index = next(
            (
                index
                for index, value in enumerate(classes)
                if value in {"1", "risky", "block", "true"}
            ),
            None,
        )
        if positive_index is None:
            raise ValueError("binary action model has no positive class")
        value = float(probabilities[positive_index])
        return max(0.0, min(1.0, value))

    def predict(self, text: str) -> ActionScoresV3:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not self.loaded:
            raise RuntimeError(self.error or "action models unavailable")
        return ActionScoresV3(
            risk_probability=self._positive_probability(self.risk_model, text),
            block_probability=self._positive_probability(self.block_model, text),
        )

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self.loaded,
            "error": self.error,
            "risk_model_path": str(self.risk_model_path),
            "block_model_path": str(self.block_model_path),
            "risk_sha256_expected": self.expected_risk_sha256,
            "risk_sha256_actual": self.actual_risk_sha256,
            "block_sha256_expected": self.expected_block_sha256,
            "block_sha256_actual": self.actual_block_sha256,
            "hashes_verified": (
                self.loaded
                and self.expected_risk_sha256 is not None
                and self.expected_block_sha256 is not None
                and self.actual_risk_sha256 == self.expected_risk_sha256
                and self.actual_block_sha256 == self.expected_block_sha256
            ),
        }
