"""输出侧二次校验（OutputGuard）——大模型回复的安全闸门。

模型返回的文本并不天然可信（可能包含违规内容或隐私泄露），
本模块对模型原始输出执行独立的复检链路：

1. 隐私掩码（mask_sensitive_info）：用预编译正则把手机号、邮箱、身份证、
   银行卡、链接、IP、微信号、QQ、地址等替换为 ``[手机号]`` 等占位符；
2. 高危词检测（detect_extra_high_risk）：对去空白压缩后的文本匹配
   EXTRA_HIGH_RISK 词库，命中即 90 分高风险；
3. 结合输入检测传入的 detections，按 80/40 双阈值决策：
   - risk_score >= block_threshold(80) → block，返回类别化拒绝话术；
   - risk_score >= sanitize_threshold(40) 或存在隐私掩码 → sanitize，
     把具体违禁词替换为 ``[已过滤:类别]``；无具体可替换词时退回通用安全提示；
   - 否则 pass，原文放行。

注意：输出侧不把结果重新送入 ActionRouter，阈值体系（80/40）与
输入侧 ActionRouter 配置相互独立，避免两侧策略耦合。
"""

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

_ADDRESS_PATTERN = re.compile(
    r"(?:"
    r"(?:(?:[\u4e00-\u9fff]{2,}(?:\u7701|\u81ea\u6cbb\u533a|\u5e02|\u81ea\u6cbb\u5dde|\u53bf|\u533a)){1,3}[\u4e00-\u9fffA-Za-z0-9]{0,20}(?:\u8def|\u8857|\u5df7|\u8857\u9053|\u5c0f\u533a|\u697c|\u5355\u5143)?\d+(?:\u53f7|\u5ba4)?)"
    r"|(?:[\u4e00-\u9fff]{2,}(?:\u8def|\u8857|\u5df7|\u8857\u9053)\d+(?:\u53f7|\u5f04)?)"
    r"|(?:[\u4e00-\u9fff]{2,}\u5c0f\u533a(?:\d+\u53f7?)?(?:\d+\u680b)?(?:\d+\u5355\u5143)?(?:\d+\u5ba4)?)"
    r")"
)


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
        """输出复检主入口。

        参数：
            raw_output: 模型原始回复；
            normalized_text: 归一化后的文本（用于高危词匹配）；
            detections: 输入侧传递下来的检测（如语义命中），与输出侧证据合并评分。

        决策规则：
            风险分 >= block 阈值(80) → 拦截，返回类别化拒绝话术；
            风险分 >= sanitize 阈值(40) 或存在隐私掩码 → 脱敏改写
            （无具体可替换词时退回通用安全提示，绝不回显风险原文）；
            否则放行原文。
        """
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
        """掩码文本中的个人隐私字段（手机号/邮箱/证件/银行卡/链接/IP/社交账号/地址）。

        返回 (掩码后文本, 隐私 Detection 列表)；每类命中字段记入 matches。
        即使无其他风险，存在隐私掩码也足以触发 sanitize 动作。
        """
        masked = text
        matches: list[str] = []
        for name, pattern, replacement in PRIVACY_PATTERNS:
            if pattern.search(masked):
                matches.append(name)
                masked = pattern.sub(replacement, masked)
        if _ADDRESS_PATTERN.search(masked):
            matches.append("address")
            masked = _ADDRESS_PATTERN.sub("[地址]", masked)
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
        """高危词库检测：命中即 90 分（直接达到 block 阈值）。

        匹配前先去空白并转小写，防止用空格/大小写变体绕过。
        """
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
        """执行脱敏改写：把具体违禁词替换为 [已过滤:类别] 占位。

        只替换"词形命中"（关键词/短语/高危词）；正则类命中的内容已由
        掩码阶段处理，语义类命中没有具体词形可替换——因此本方法可能
        返回与原文相同的文本，调用方据此回退到通用安全提示。
        """
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
        """把命中检测展开为规则级明细（类别/分数/来源/命中词），供审计与前端展示。"""
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
        """按风险类别选择标准拒绝话术；多类别用 mixed 话术。"""
        if len(categories) > 1:
            return STANDARD_RESPONSES["mixed"]
        if not categories:
            return "抱歉，该回复存在不合规风险，已被系统拦截。"
        return STANDARD_RESPONSES.get(categories[0], STANDARD_RESPONSES["mixed"])

    def _risk_level(self, score: int) -> str:
        """分数 → 等级映射：>=block 为 high，>=sanitize 为 medium，>0 为 low。"""
        if score >= self.block_threshold:
            return "high"
        if score >= self.sanitize_threshold:
            return "medium"
        if score > 0:
            return "low"
        return "none"


PRIVACY_REPLACEMENT_NAMES = {"phone", "email", "id_card", "bank_card", "url", "ip", "wechat", "qq", "address"}
