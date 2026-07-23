import re
from dataclasses import asdict
from typing import Any

from .models import Detection


CATEGORY_LABELS = {
    "porn": "色情低俗",
    "violence": "暴力威胁",
    "ad": "广告引流",
    "sensitive": "敏感话术",
    "abuse": "低俗辱骂",
    "illegal": "违法违规",
    "self_harm": "自伤自杀",
    "privacy": "隐私泄露",
    "normal": "正常",
}


STANDARD_RESPONSES = {
    "porn": "抱歉，该回复包含不适宜的低俗或色情内容，已被系统拦截。请改用健康、合规的表达方式。",
    "violence": "抱歉，该回复包含暴力威胁或伤害性内容，已被系统拦截。建议以理性、非暴力方式沟通。",
    "ad": "抱歉，该回复包含广告引流或诱导联系内容，已被系统处理。请避免发布推广、拉群、返利或私聊引导信息。",
    "sensitive": "抱歉，该回复包含敏感或规避监管的话术，已被系统拦截。请围绕合法合规、安全可控的内容进行交流。",
    "abuse": "抱歉，该回复包含辱骂或人身攻击内容，已被系统处理。请使用理性、尊重的表达方式。",
    "illegal": "抱歉，该回复涉及违法违规风险，已被系统拦截。请遵守法律法规和平台安全规范。",
    "self_harm": "抱歉，该回复涉及自伤风险，已被系统拦截。如你或他人正处于危机中，请尽快联系身边可信任的人或当地紧急援助渠道。",
    "mixed": "抱歉，该回复包含多类不合规风险，已被系统拦截。请使用安全、合法、尊重他人的表达方式。",
}


PRIVACY_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"), "[手机号]"),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱]"),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证号]"),
    ("bank_card", re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)"), "[银行卡号]"),
    ("url", re.compile(r"https?://[^\s，。；、]+|www\.[^\s，。；、]+", re.I), "[链接]"),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP地址]"),
    ("wechat", re.compile(r"(?:微信|VX|vx|v信|V信)[:： ]?[A-Za-z0-9_-]{5,20}"), "[微信号]"),
    ("qq", re.compile(r"QQ[:： ]?[1-9]\d{4,11}", re.I), "[QQ号]"),
]


EXTRA_HIGH_RISK = {
    "porn": ["约炮", "裸聊", "卖淫", "嫖娼"],
    "violence": ["杀了你", "砍死", "炸学校", "制造炸弹", "投毒"],
    "ad": ["加我微信", "加微信", "刷单返现", "私聊返利", "开户链接"],
    "sensitive": ["绕过审核", "规避监管", "逃避检测", "诈骗话术", "钓鱼网站"],
    "illegal": ["贩毒", "买卖身份证", "伪造证件", "盗号教程", "入侵服务器"],
    "self_harm": ["自杀方法", "怎么自杀", "割腕教程"],
}


class OutputGuard:
    """Output-side checker for member C."""

    def __init__(self, block_threshold: int = 80, sanitize_threshold: int = 40):
        self.block_threshold = block_threshold
        self.sanitize_threshold = sanitize_threshold

    def process(self, raw_output: str, normalized_text: str, detections: list[Detection]) -> dict[str, Any]:
        raw_output = raw_output or ""
        normalized_text = normalized_text or raw_output
        all_detections = list(detections)
        privacy_masked, privacy_detections = self.mask_sensitive_info(raw_output)
        all_detections.extend(privacy_detections)
        all_detections.extend(self.detect_extra_high_risk(normalized_text))

        risk_score = max([d.score for d in all_detections], default=0)
        categories = sorted({d.category for d in all_detections if d.category != "normal"})
        matched_rules = self._matched_rules(all_detections)

        if risk_score >= self.block_threshold:
            action = "block"
            blocked = True
            rewritten = False
            final_text = self._refusal(categories)
        elif risk_score >= self.sanitize_threshold or privacy_detections:
            action = "sanitize"
            blocked = False
            rewritten = True
            final_text = self._sanitize_output(privacy_masked, all_detections)
            if not final_text.strip() or final_text == raw_output:
                final_text = "模型回复包含风险内容，系统已进行安全改写。"
        else:
            action = "pass"
            blocked = False
            rewritten = False
            final_text = raw_output

        return {
            "stage": "output",
            "original_text": raw_output,
            "normalized_text": normalized_text,
            "action": action,
            "risk_score": risk_score,
            "risk_level": self._risk_level(risk_score),
            "risk_categories": categories,
            "risk_category_labels": [CATEGORY_LABELS.get(c, c) for c in categories],
            "blocked": blocked,
            "rewritten": rewritten,
            "sanitized_text": final_text if action in {"sanitize", "block"} else None,
            "final_text": final_text,
            "matched_rules": matched_rules,
            "detections": [asdict(d) for d in all_detections],
            "sanitized_raw_output": privacy_masked,
        }

    def mask_sensitive_info(self, text: str) -> tuple[str, list[Detection]]:
        masked = text
        matches: list[str] = []
        for name, pattern, replacement in PRIVACY_PATTERNS:
            if pattern.search(masked):
                matches.append(name)
                masked = pattern.sub(replacement, masked)
        address_pattern = re.compile(r"[\u4e00-\u9fa5]{2,}(?:省|市|区|县|镇|街道|路|小区|楼|单元|室)\d*号?")
        if address_pattern.search(masked):
            matches.append("address")
            masked = address_pattern.sub("[地址]", masked)
        if not matches:
            return masked, []
        return masked, [
            Detection(
                category="privacy",
                level="low",
                score=45,
                reason="output contains personal sensitive information",
                source="output_privacy_regex",
                matches=matches,
            )
        ]

    def detect_extra_high_risk(self, text: str) -> list[Detection]:
        detections: list[Detection] = []
        compact = re.sub(r"\s+", "", text).lower()
        for category, words in EXTRA_HIGH_RISK.items():
            matched = [word for word in words if word.lower() in compact]
            if matched:
                detections.append(
                    Detection(
                        category=category,
                        level="high",
                        score=90,
                        reason="matched output high-risk phrase",
                        source="output_high_risk",
                        matches=matched,
                    )
                )
        return detections

    def _sanitize_output(self, text: str, detections: list[Detection]) -> str:
        sanitized = text
        for detection in detections:
            label = CATEGORY_LABELS.get(detection.category, detection.category)
            for match in sorted(set(detection.matches), key=len, reverse=True):
                if not match or detection.source.endswith("regex"):
                    continue
                if match in PRIVACY_REPLACEMENT_NAMES:
                    continue
                sanitized = sanitized.replace(match, f"[已过滤:{label}]")
        return sanitized

    def _matched_rules(self, detections: list[Detection]) -> list[dict[str, Any]]:
        rules = []
        for detection in detections:
            for match in detection.matches:
                rules.append(
                    {
                        "category": detection.category,
                        "category_label": CATEGORY_LABELS.get(detection.category, detection.category),
                        "level": detection.level,
                        "score": detection.score,
                        "source": detection.source,
                        "match": match,
                        "reason": detection.reason,
                    }
                )
        return rules

    def _refusal(self, categories: list[str]) -> str:
        if len(categories) > 1:
            return STANDARD_RESPONSES["mixed"]
        if not categories:
            return "抱歉，该回复存在不合规风险，已被系统拦截。"
        return STANDARD_RESPONSES.get(categories[0], STANDARD_RESPONSES["mixed"])

    def _risk_level(self, score: int) -> str:
        if score >= self.block_threshold:
            return "high"
        if score >= self.sanitize_threshold:
            return "medium"
        if score > 0:
            return "low"
        return "none"


PRIVACY_REPLACEMENT_NAMES = {"phone", "email", "id_card", "bank_card", "url", "ip", "wechat", "qq", "address"}
