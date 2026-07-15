# safechat_guard/semantic_classifier.py
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
            'porn': 85,
            'violence': 85,
            'ad': 70,
            'sensitive': 70,
            'normal': 10,
        }

        self.cn_map = {
            'porn': '色情低俗',
            'violence': '暴力威胁',
            'ad': '广告引流',
            'sensitive': '敏感话术',
            'normal': '正常'
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

    def detect(self, text: str) -> list[Detection]:
        if self.model is None:
            return []

        # 获取预测标签和所有类别的概率
        proba = self.model.predict_proba([text])[0]
        classes = self.model.classes_

        # 按概率从高到低排序
        sorted_probs = sorted(zip(classes, proba), key=lambda x: x[1], reverse=True)
        top_label, top_prob = sorted_probs[0]
        second_label, second_prob = sorted_probs[1] if len(sorted_probs) > 1 else (None, 0)

        # 如果最高概率 < 0.3，返回 normal 类（低置信度）
        if top_prob < 0.3:
            detection = Detection(
                category='normal',
                level='low',
                score=10,
                reason=f"语义分类器判定为 正常，置信度 {top_prob:.2%}",
                source='semantic_ml',
                matches=[f"normal: {top_prob:.2%}"]
            )
            return [detection]

        # 情况1：最高概率对应的是违规类别
        if top_label != 'normal':
            label = top_label
            max_prob = top_prob
        else:
            # 情况2：最高是 normal —— 直接返回 normal，不再检查第二高
            # 这样避免了因模型置信度偏低而导致的误判（例如 normal 概率33%被第二高17%覆盖）
            detection = Detection(
                category='normal',
                level='low',
                score=10,
                reason=f"语义分类器判定为 正常，置信度 {top_prob:.2%}",
                source='semantic_ml',
                matches=[f"normal: {top_prob:.2%}"]
            )
            return [detection]

        # 计算风险分数（仅当选择了违规类别时）
        score = self.category_to_score.get(label, 50)
        if max_prob > 0.85:
            score = min(score + 10, 100)
        elif max_prob < 0.6:
            score = max(score - 10, 0)

        detection = Detection(
            category=label,
            level="high" if score >= 80 else "medium",
            score=score,
            reason=f"语义分类器判定为 {self.cn_map.get(label, label)}，置信度 {max_prob:.2%}",
            source="semantic_ml",
            matches=[f"{label}: {max_prob:.2%}"]
        )
        return [detection]