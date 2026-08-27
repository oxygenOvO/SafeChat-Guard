from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .action_models_v3 import ActionModelBundleV3, ActionScoresV3


CATEGORIES = ("ad", "porn", "violence", "sensitive")
_ACTION_PRIORITY = {"pass": 0, "sanitize": 1, "block": 2}

_CATEGORY_TERMS = {
    "ad": (
        "返利", "押金", "保证金", "刷流水", "刷量", "账号", "发票",
        "短链", "收款账户", "返佣", "补贴", "私域", "团购群", "隐藏价",
        "客户名单", "内部价", "团购入口", "私下转账",
        "银行卡", "会员", "导流", "优惠",
    ),
    "porn": (
        "裸露", "裸照", "裸聊", "成人视频", "露骨", "色情", "不雅影像",
        "约炮", "上门服务", "偷拍", "私密影像", "不雅照片", "成人内容",
        "成人直播", "付费自拍", "成人聊天室",
    ),
    "violence": (
        "爆炸", "炸药", "炸弹", "枪支", "武器", "纵火", "袭击", "围殴",
        "伤害", "血的代价", "烧毁", "推你", "打谁", "踹你", "威胁",
        "耳光", "收拾你",
    ),
    "sensitive": (
        "自杀", "轻生", "自残", "病历", "医疗档案", "身份信息", "性取向",
        "迷幻药", "违禁药", "吸毒", "失去意识", "定位", "住址", "门牌",
        "治疗中", "独居", "服药状态", "诊疗情况", "亲密关系",
    ),
}

_EVIDENCE_TERMS = {
    "risk_entity": tuple(
        dict.fromkeys(term for terms in _CATEGORY_TERMS.values() for term in terms)
    ),
    "operation_intent": (
        "出售", "售卖", "购买", "求购", "提供", "制作", "完整步骤", "方法",
        "交易", "传播", "组织", "招募", "攻击", "报复", "教唆", "鼓励",
        "号召", "安排", "发货", "实施", "尝试", "规避检测", "绕过",
        "曝光", "逼迫", "集中购买", "长期合作", "代转", "代开",
        "领取", "加入", "私信", "扫码",
    ),
    "real_target": (
        "未成年人", "师生", "同学", "邻居", "受害者", "患者", "读者",
        "他家", "公共场所", "车站", "学校", "个人", "陌生人", "住户",
    ),
    "execution_condition": (
        "今晚", "立即", "马上", "现在", "现场", "上门", "预付", "价格",
        "报酬", "提成", "时间", "地址", "匿名快递", "菜单", "提取码",
        "数量不限", "每天到账", "分成", "邮寄",
    ),
    "severe_direct_evidence": (
        "自杀方法", "鼓励自残", "催促实施", "爆炸物完整步骤", "炸药制作",
        "枪支交易", "纵火烧毁", "公共场所制造爆炸", "车站实施袭击",
        "未成年人裸露", "未成年人不雅影像", "窃取的医疗档案",
        "违禁迷幻药交易", "伤害学校师生", "围殴同学",
    ),
    "safe_context": (
        "新闻", "报道", "教学", "课堂", "研究", "论文", "反诈", "提醒",
        "拒绝", "禁止", "不要", "不应", "不得", "审核", "引用",
        "治理", "上报", "封禁", "移交处理", "安全手册", "安全培训",
        "法规", "合规", "脱敏", "虚构", "演示", "示例", "拦截",
        "违规", "标记", "识别", "处置", "不会", "不再提供", "比喻",
    ),
    "benign_analysis_context": (
        "预防措施", "防范建议", "安全教育", "风险分析", "危害分析",
        "治理措施", "伦理规范", "防护建议", "保护措施", "合规措施",
        "预防建议", "治理建议",
    ),
}

_UNSAFE_OVERRIDE_TERMS = (
    "请提供", "请给出", "告诉我", "列出", "写出", "完整步骤", "可操作",
    "现在出售", "正在出售", "继续传播", "安排发货", "安排上门", "立即尝试",
    "今晚", "马上", "价格", "菜单", "提取码", "预付", "接受定制", "实际",
    "后文仍", "正文继续", "仍要", "转而实施",
)
_LOW_SEVERITY_OPERATIONS = {"领取", "加入", "私信", "扫码"}
_OPERATION_NEGATIONS = (
    "拒绝", "禁止", "不要", "不应", "不得", "停止", "劝阻", "不会",
)


@dataclass(frozen=True)
class ActionThresholdsV3:
    risk_sanitize_threshold: float
    category_block_thresholds: dict[str, float]
    evidence_block_threshold: float

    @classmethod
    def load(cls, path: str | Path) -> tuple["ActionThresholdsV3", dict[str, Any]]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = {
            "schema_version",
            "risk_sanitize_threshold",
            "category_block_thresholds",
            "evidence_block_threshold",
            "risk_model_path",
            "risk_model_sha256",
            "block_model_path",
            "block_model_sha256",
            "calibration_split",
        }
        if set(payload) != expected or payload["schema_version"] != 1:
            raise ValueError("invalid V3 action-threshold schema")
        categories = payload["category_block_thresholds"]
        if set(categories) != set(CATEGORIES):
            raise ValueError("V3 block thresholds must cover all risk categories")
        values = [
            payload["risk_sanitize_threshold"],
            payload["evidence_block_threshold"],
            *categories.values(),
        ]
        if any(type(value) not in {int, float} or not 0 <= value <= 1 for value in values):
            raise ValueError("V3 action thresholds must be numeric values in [0, 1]")
        if payload["calibration_split"] != "dev":
            raise ValueError("V3 thresholds must be calibrated on dev")
        return (
            cls(
                risk_sanitize_threshold=float(payload["risk_sanitize_threshold"]),
                category_block_thresholds={
                    key: float(value) for key, value in categories.items()
                },
                evidence_block_threshold=float(payload["evidence_block_threshold"]),
            ),
            payload,
        )


class RiskEvidenceExtractorV3:
    """Extract bounded, deduplicated evidence groups rather than sample rules."""

    @staticmethod
    def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
        return [term for term in terms if term in text]

    def extract(self, text: str) -> dict[str, list[str]]:
        return {
            group: list(dict.fromkeys(self._matches(text, terms)))
            for group, terms in _EVIDENCE_TERMS.items()
        }

    def infer_category(self, text: str, fallback: str = "normal") -> str:
        counts = {
            category: sum(term in text for term in terms)
            for category, terms in _CATEGORY_TERMS.items()
        }
        best = max(counts, key=lambda category: (counts[category], -CATEGORIES.index(category)))
        return best if counts[best] else fallback

    @staticmethod
    def has_local_pair(
        text: str,
        left_terms: list[str],
        right_terms: list[str],
        *,
        max_distance: int = 36,
    ) -> bool:
        left_spans = [
            (index, index + len(term))
            for term in left_terms
            for index in range(len(text))
            if text.startswith(term, index)
        ]
        right_spans = [
            (index, index + len(term))
            for term in right_terms
            for index in range(len(text))
            if text.startswith(term, index)
        ]
        return any(
            max(0, max(a_start, b_start) - min(a_end, b_end)) <= max_distance
            for a_start, a_end in left_spans
            for b_start, b_end in right_spans
        )

    @staticmethod
    def active_operation_terms(
        text: str, operation_terms: list[str], *, negation_window: int = 12
    ) -> list[str]:
        active = []
        for term in operation_terms:
            starts = [
                index for index in range(len(text))
                if text.startswith(term, index)
            ]
            if any(
                not any(
                    negation in text[max(0, index - negation_window):index]
                    for negation in _OPERATION_NEGATIONS
                )
                for index in starts
            ):
                active.append(term)
        return active


class ActionRouterV3:
    def __init__(
        self,
        models: ActionModelBundleV3,
        thresholds: ActionThresholdsV3,
    ):
        if not models.loaded:
            raise RuntimeError(models.error or "V3 action models unavailable")
        self.models = models
        self.thresholds = thresholds
        self.extractor = RiskEvidenceExtractorV3()

    @classmethod
    def from_config(
        cls, project_root: str | Path, threshold_path: str | Path
    ) -> "ActionRouterV3":
        root = Path(project_root)
        threshold_file = Path(threshold_path)
        if not threshold_file.is_absolute():
            threshold_file = root / threshold_file
        thresholds, payload = ActionThresholdsV3.load(threshold_file)
        risk_path = root / payload["risk_model_path"]
        block_path = root / payload["block_model_path"]
        models = ActionModelBundleV3(
            risk_path,
            block_path,
            expected_risk_sha256=payload["risk_model_sha256"],
            expected_block_sha256=payload["block_model_sha256"],
        )
        return cls(models, thresholds)

    @staticmethod
    def _unsafe_intent(text: str, evidence: dict[str, list[str]]) -> bool:
        extractor = RiskEvidenceExtractorV3()
        active_operations = extractor.active_operation_terms(
            text, evidence["operation_intent"]
        )
        matching_overrides = [
            term for term in _UNSAFE_OVERRIDE_TERMS if term in text
        ]
        if evidence["severe_direct_evidence"]:
            return True
        if (
            matching_overrides
            and extractor.has_local_pair(
                text,
                evidence["risk_entity"],
                matching_overrides,
                max_distance=48,
            )
        ):
            return True
        explicit_operation = extractor.has_local_pair(
            text,
            evidence["risk_entity"],
            active_operations,
        ) or extractor.has_local_pair(
            text, active_operations, evidence["real_target"]
        )
        return explicit_operation

    @staticmethod
    def _evidence_score(
        text: str, evidence: dict[str, list[str]]
    ) -> float:
        groups = {group for group, matches in evidence.items() if matches}
        if "severe_direct_evidence" in groups:
            return 1.0
        extractor = RiskEvidenceExtractorV3()
        active_operations = extractor.active_operation_terms(
            text, evidence["operation_intent"]
        )
        entity_operation = extractor.has_local_pair(
            text, evidence["risk_entity"], active_operations
        )
        operation_target = extractor.has_local_pair(
            text, active_operations, evidence["real_target"]
        )
        operation_condition = extractor.has_local_pair(
            text, active_operations, evidence["execution_condition"],
            max_distance=48,
        )
        if entity_operation:
            if active_operations and set(active_operations) <= _LOW_SEVERITY_OPERATIONS:
                return 0.58
            return 0.9 if operation_condition else 0.86
        if operation_target:
            return 0.9
        if extractor.has_local_pair(
            text, evidence["risk_entity"], evidence["execution_condition"]
        ):
            return 0.58
        if "risk_entity" in groups or active_operations:
            return 0.32
        return 0.0

    @staticmethod
    def _public_evidence(evidence: dict[str, list[str]]) -> list[dict[str, Any]]:
        return [
            {"group": group, "terms": matches}
            for group, matches in evidence.items()
            if matches
        ]

    def route(
        self,
        original_text: str,
        normalized_text: str,
        *,
        category_hint: str = "normal",
        base_result: dict[str, Any] | None = None,
        scores: ActionScoresV3 | None = None,
    ) -> dict[str, Any]:
        text = normalized_text or original_text
        evidence = self.extractor.extract(text)
        category = (
            category_hint if category_hint in CATEGORIES
            else self.extractor.infer_category(text, "ad")
        )
        scores = scores or self.models.predict(text)
        evidence_score = self._evidence_score(text, evidence)
        unsafe_intent = self._unsafe_intent(text, evidence)
        explicit_safe_context = bool(
            evidence["safe_context"] or evidence["benign_analysis_context"]
        )
        safe_scope = (
            explicit_safe_context
            and not unsafe_intent
            and not evidence["severe_direct_evidence"]
            and evidence_score < self.thresholds.evidence_block_threshold
        )
        base_action = (base_result or {}).get("action", "pass")
        base_hard_block = bool((base_result or {}).get("hard_block", False))

        reasons: list[str] = []
        if base_action == "block" and base_hard_block:
            action = "block"
            reasons.append("V3_STRONG_RULE_BLOCK")
        elif evidence["severe_direct_evidence"] and not safe_scope:
            action = "block"
            reasons.append("V3_SEVERE_DIRECT_EVIDENCE")
        elif safe_scope:
            action = "pass"
            category = "normal"
            reasons.append("V3_SAFE_CONTEXT")
        else:
            block_threshold = self.thresholds.category_block_thresholds[category]
            if (
                (
                    scores.block_probability >= block_threshold
                    and evidence_score >= 0.58
                )
                or evidence_score >= self.thresholds.evidence_block_threshold
            ):
                action = "block"
                reasons.append("V3_BLOCK_MODEL_AND_EVIDENCE")
            elif base_action == "sanitize":
                action = "sanitize"
                reasons.append("V3_BASE_SANITIZE")
            elif (
                scores.risk_probability >= self.thresholds.risk_sanitize_threshold
                and bool(evidence["risk_entity"])
            ):
                action = "sanitize"
                reasons.append("V3_RISK_MODEL_AND_EVIDENCE")
            else:
                action = "pass"
                category = "normal"
                reasons.append("V3_NO_ACTION_THRESHOLD")

        return {
            "action": action,
            "category": category,
            "risk_level": (
                "high" if action == "block"
                else "medium" if action == "sanitize"
                else "none"
            ),
            "confidence": round(
                max(scores.risk_probability, scores.block_probability, evidence_score),
                6,
            ),
            "reason_codes": reasons,
            "hard_block": action == "block",
            "risk_score": (
                90 if action == "block"
                else 60 if action == "sanitize"
                else 0
            ),
            "matched_rule_ids": list((base_result or {}).get("matched_rule_ids", [])),
            "sanitize_matches": (
                list(
                    dict.fromkeys(
                        [
                            *(base_result or {}).get("sanitize_matches", []),
                            *evidence["risk_entity"],
                        ]
                    )
                ) if action == "sanitize"
                else []
            ),
            "evidence": self._public_evidence(evidence),
            "v3_scores": {
                "risk_probability": scores.risk_probability,
                "block_probability": scores.block_probability,
                "evidence_score": evidence_score,
            },
        }
