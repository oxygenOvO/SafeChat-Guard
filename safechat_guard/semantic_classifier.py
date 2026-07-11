# safechat_guard/semantic_classifier.py
import joblib
from pathlib import Path
from .models import Detection

class SemanticClassifier:
    def __init__(self, model_path="models/semantic_model.pkl"):
        project_root = Path(__file__).parent.parent
        full_path = project_root / model_path
        
        if not full_path.exists():
            print(f"⚠️ 警告: 模型文件 {full_path} 不存在，使用空逻辑")
            self.model = None
        else:
            self.model = joblib.load(full_path)
            print("✅ 语义分类模型加载成功")
        
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
        
        # 如果最高概率 < 0.15，认为安全
        if top_prob < 0.15:
            return []
        
        # 情况1：最高概率对应的是违规类别
        if top_label != 'normal':
            # 直接使用最高类别
            label = top_label
            max_prob = top_prob
        else:
            # 情况2：最高是 normal，但概率不高（< 0.6），检查第二高
            if top_prob < 0.6 and second_label is not None and second_label != 'normal' and second_prob > 0.15:
                label = second_label
                max_prob = second_prob
            else:
                # normal 概率很高或第二高也不够，认为安全
                return []
        
        # 计算风险分数
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