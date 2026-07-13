from pathlib import Path

from .models import Detection

try:
    import joblib
except ImportError:
    joblib = None


class SemanticClassifier:
    def __init__(self, model_path="models/semantic_model.pkl"):
        self.model_path = model_path
        self.model = None
        self._error = None
        project_root = Path(__file__).parent.parent
        full_path = project_root / model_path

        if not full_path.exists():
            self._error = "model file not found"
        elif joblib is None:
            self._error = "model dependency missing: joblib"
        else:
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

    def status(self) -> dict:
        return {
            "enabled": self.model is not None,
            "loaded": self.model is not None,
            "model_path": self.model_path,
            "model_type": "sklearn_pipeline" if self.model is not None else None,
            "classes": [
                str(item) for item in getattr(self.model, "classes_", [])
            ] if self.model is not None else [],
            "error": self._error,
        }

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
        sorted_probs = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_label, top_prob = sorted_probs[0]

        if top_prob < 0.15:
            return []

        if top_label != "normal":
            label = top_label
            max_prob = top_prob
        else:
            return []

        score = self.category_to_score.get(label, 50)
        if max_prob > 0.85:
            score = min(score + 10, 100)
        elif max_prob < 0.6:
            score = max(score - 10, 0)

        return [Detection(
            category=str(label),
            level="high" if score >= 80 else "medium",
            score=score,
            reason=f"语义分类器判定为 {self.cn_map.get(label, label)}，置信度 {max_prob:.2%}",
            source="semantic_ml",
            matches=[f"{label}: {max_prob:.2%}"],
        )]
