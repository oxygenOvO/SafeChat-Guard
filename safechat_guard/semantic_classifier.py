from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Detection


@dataclass(frozen=True)
class SemanticRule:
    category: str
    level: str
    score: int
    reason: str
    phrases: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()


class SemanticClassifier:
    """Replaceable Chinese semantic safety classifier.

    This baseline intentionally avoids LLM calls. It provides a deterministic
    rule-based second layer for Chinese conversational safety filtering and
    keeps the public interface compatible: ``detect(text) -> list[Detection]``.
    A future model-based classifier can replace this class as long as it
    returns the same Detection objects.
    """

    CATEGORY_TO_SCORE = {
        "porn": 85,
        "violence": 85,
        "ad": 70,
        "sensitive": 70,
        "normal": 10,
    }
    CATEGORY_LABELS = {
        "porn": "色情低俗",
        "violence": "暴力威胁",
        "ad": "广告引流",
        "sensitive": "敏感话术",
        "normal": "正常",
    }

    def __init__(
        self,
        rules: list[SemanticRule] | None = None,
        model_path: str | Path | None = "models/semantic_model.pkl",
    ):
        self.rules = rules or self._default_rules()
        self.model = self._load_optional_model(model_path)

    def detect(self, text: str) -> list[Detection]:
        normalized_text = text.lower()
        detections: list[Detection] = []

        for rule in self.rules:
            matches = self._match_rule(normalized_text, rule)
            if not matches:
                continue
            detections.append(
                Detection(
                    category=rule.category,
                    level=rule.level,
                    score=rule.score,
                    reason=rule.reason,
                    source="semantic_rule",
                    matches=matches,
                )
            )

        model_detection = self._detect_with_model(text)
        if model_detection and not any(
            detection.category == model_detection.category
            for detection in detections
        ):
            detections.append(model_detection)

        return detections

    @staticmethod
    def _load_optional_model(model_path: str | Path | None) -> Any | None:
        if model_path is None:
            return None
        path = Path(model_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        if not path.exists():
            return None
        try:
            import joblib
        except ImportError:
            return None
        try:
            return joblib.load(path)
        except (OSError, ValueError, TypeError):
            return None

    def _detect_with_model(self, text: str) -> Detection | None:
        if self.model is None:
            return None
        try:
            probabilities = self.model.predict_proba([text])[0]
            classes = self.model.classes_
        except (AttributeError, TypeError, ValueError):
            return None

        ranked = sorted(
            zip(classes, probabilities),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            return None

        label, confidence = ranked[0]
        if label == "normal":
            if len(ranked) < 2 or confidence >= 0.6 or ranked[1][1] <= 0.15:
                return None
            label, confidence = ranked[1]
        elif confidence < 0.15:
            return None

        score = self.CATEGORY_TO_SCORE.get(label, 50)
        if confidence > 0.85:
            score = min(score + 10, 100)
        elif confidence < 0.6:
            score = max(score - 10, 0)

        return Detection(
            category=label,
            level="high" if score >= 80 else "medium",
            score=score,
            reason=(
                f"语义分类器判定为 {self.CATEGORY_LABELS.get(label, label)}，"
                f"置信度 {confidence:.2%}"
            ),
            source="semantic_ml",
            matches=[f"{label}: {confidence:.2%}"],
        )

    @staticmethod
    def _match_rule(text: str, rule: SemanticRule) -> list[str]:
        matches = [phrase for phrase in rule.phrases if phrase.lower() in text]
        for pattern in rule.patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                matches.append(pattern)
        return matches

    @staticmethod
    def _default_rules() -> list[SemanticRule]:
        return [
            SemanticRule(
                category="ad",
                level="medium",
                score=60,
                reason="疑似广告引流、私下联系或交易导流",
                phrases=(
                    "加微信",
                    "联系微信",
                    "加vx",
                    "加v",
                    "私聊",
                    "联系我",
                    "加qq",
                    "qq联系",
                    "扫码",
                    "进群",
                    "包过",
                    "代办",
                    "低价出售",
                    "内部渠道",
                    "返现",
                    "刷单",
                    "接单",
                    "兼职赚钱",
                    "课程资料",
                    "领取资料",
                    "领取优惠券",
                    "推广渠道",
                ),
            ),
            SemanticRule(
                category="porn",
                level="high",
                score=80,
                reason="疑似色情低俗或成人内容",
                phrases=(
                    "色情",
                    "低俗",
                    "成人网站",
                    "成人内容",
                    "约炮",
                    "裸聊",
                    "陪聊",
                    "特殊服务",
                    "黄色视频",
                    "成人视频",
                    "露骨",
                    "性暗示",
                ),
            ),
            SemanticRule(
                category="violence",
                level="high",
                score=85,
                reason="疑似暴力威胁、伤害表达或危险行为",
                phrases=(
                    "打死你",
                    "弄死你",
                    "杀了你",
                    "威胁你",
                    "报复你",
                    "砍人",
                    "捅人",
                    "炸掉",
                    "放火",
                    "伤害别人",
                    "人身威胁",
                    "暴力报复",
                ),
            ),
            SemanticRule(
                category="sensitive",
                level="medium",
                score=70,
                reason="疑似谣言、煽动、违规组织或敏感话术",
                phrases=(
                    "传播谣言",
                    "散布谣言",
                    "煽动对立",
                    "煽动仇恨",
                    "非法集会",
                    "违规组织",
                    "极端言论",
                    "制造恐慌",
                    "未经证实的消息",
                    "恶意攻击群体",
                ),
            ),
        ]
