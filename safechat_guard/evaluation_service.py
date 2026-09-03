"""安全评测服务：非持久化的多模式对比评估与批量指标计算。

支持六种检测模式（baseline / unnormalized_fusion / rule_only /
semantic_only / fusion / full_pipeline），可在同一文本上对比
"去掉归一化 / 只用规则 / 只用语义 / 完整管线"的差异，
直观展示每个组件的价值。

设计约束：
- 评测过程**不写审计日志**，与生产请求完全隔离；
- 批量评估的 Macro F1 同时给出两个口径：参与平均的类别集合
  （evaluated_labels）与固定核心五类（macro_f1_core），
  保证不同批次之间的指标可比性；
- CSV 导出对 `=+-@` 开头的单元格做公式注入防护。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any, Iterable

from .decision_explanation_service import DecisionExplanationService


EVALUATION_MODES = {
    "baseline", "unnormalized_fusion", "rule_only", "semantic_only",
    "fusion", "full_pipeline",
}
MAX_EVALUATION_BYTES = 1024 * 1024

# Fixed core training label space (see README): macro metrics over this set
# are comparable across batches regardless of which labels a batch contains.
CORE_CATEGORY_LABELS = ("normal", "ad", "porn", "violence", "sensitive")


class EvaluationInputError(ValueError):
    pass


class EvaluationService:
    """Run non-persistent evaluations through the production safety components."""

    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline
        self.explanations = DecisionExplanationService(pipeline)

    def analyze(
        self, text: str, *, mode: str = "full_pipeline", run_id: str | None = None
    ) -> dict[str, Any]:
        """单文本单模式评测：返回动作/类别/风险与决策解释（不写审计日志）。"""
        if not isinstance(text, str) or not text.strip():
            raise EvaluationInputError("text must be a non-empty string")
        if mode not in EVALUATION_MODES:
            raise EvaluationInputError("unsupported evaluation mode")
        run_id = run_id or uuid.uuid4().hex
        request_id = f"evaluation:{run_id}:{uuid.uuid4().hex[:8]}"
        result = self._run_mode(text, mode)
        explanation = self.explanations.explain(
            text, result, request_id=request_id,
            provider="not_called", model="not_called",
        )
        return {
            "event_type": "evaluation",
            "evaluation_run_id": run_id,
            "request_id": request_id,
            "mode": mode,
            "action": result["action"],
            "category": result.get("category", "normal"),
            "risk_level": result.get("risk_level", "none"),
            "risk_score": result.get("risk_score", 0),
            "rule_hit": bool(explanation["rule_filter"]["hits"]),
            "semantic_top_class": explanation["semantic_classifier"].get(
                "top_category"
            ),
            "explanation": explanation,
        }

    def compare(self, text: str) -> dict[str, Any]:
        """同一文本跑全部六种模式（同 run_id），直观对比各组件的贡献。"""
        run_id = uuid.uuid4().hex
        results = [
            self.analyze(text, mode=mode, run_id=run_id)
            for mode in (
                "baseline", "unnormalized_fusion", "rule_only",
                "semantic_only", "fusion", "full_pipeline",
            )
        ]
        return {
            "event_type": "evaluation",
            "evaluation_run_id": run_id,
            "results": results,
        }

    def batch(self, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """批量评测：可选 label/expected_action 标注齐全时才产出指标（全有全无）。

        标注不齐时 ground_truth_available=False、metrics=None，但计数与
        逐条结果仍然返回，方便先看分布再补标注。
        """
        prepared = list(rows)
        if not prepared:
            raise EvaluationInputError("evaluation input is empty")
        run_id = uuid.uuid4().hex
        results: list[dict[str, Any]] = []
        ground_truth = True
        for position, row in enumerate(prepared, start=1):
            if not isinstance(row, dict):
                raise EvaluationInputError(f"row {position} must be an object")
            text = row.get("text")
            if not isinstance(text, str) or not text.strip():
                raise EvaluationInputError(f"row {position} has invalid text")
            analyzed = self.analyze(text, run_id=run_id)
            label = row.get("label")
            expected_action = row.get("expected_action")
            ground_truth = ground_truth and isinstance(label, str) and bool(label) \
                and expected_action in {"pass", "sanitize", "block"}
            results.append({
                "index": position,
                "text": text,
                "label": label if isinstance(label, str) else "",
                "expected_action": expected_action if isinstance(expected_action, str) else "",
                "rule_hit": analyzed["rule_hit"],
                "semantic_top_class": analyzed["semantic_top_class"] or "unavailable",
                "category": analyzed["category"],
                "action": analyzed["action"],
                "request_id": analyzed["request_id"],
            })
        counts = {
            action: sum(row["action"] == action for row in results)
            for action in ("pass", "sanitize", "block")
        }
        metrics = self._metrics(results) if ground_truth else None
        return {
            "event_type": "evaluation",
            "evaluation_run_id": run_id,
            "total": len(results),
            "counts": counts,
            "rule_hit_count": sum(row["rule_hit"] for row in results),
            "ground_truth_available": ground_truth,
            "metrics": metrics,
            "results": results,
        }

    @staticmethod
    def parse_upload(content: bytes, *, format_name: str) -> list[dict[str, Any]]:
        """解析上传的评测文件（CSV 需含 text 列；JSONL 逐行 JSON 对象）。"""
        if not isinstance(content, bytes) or len(content) > MAX_EVALUATION_BYTES:
            raise EvaluationInputError("evaluation file is invalid or too large")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EvaluationInputError("evaluation file must use UTF-8") from exc
        if format_name == "csv":
            try:
                reader = csv.DictReader(io.StringIO(text, newline=""))
                if not reader.fieldnames or "text" not in reader.fieldnames:
                    raise EvaluationInputError("CSV requires a text column")
                return [dict(row) for row in reader]
            except csv.Error as exc:
                raise EvaluationInputError("CSV is malformed") from exc
        if format_name == "jsonl":
            rows = []
            for position, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EvaluationInputError(
                        f"JSONL line {position} is malformed"
                    ) from exc
                if not isinstance(item, dict):
                    raise EvaluationInputError(
                        f"JSONL line {position} must be an object"
                    )
                rows.append(item)
            return rows
        raise EvaluationInputError("format must be csv or jsonl")

    @staticmethod
    def to_csv(results: list[dict[str, Any]]) -> bytes:
        """结果导出为 CSV（UTF-8 BOM）；=+-@ 开头的单元格加前缀防公式注入。"""
        columns = [
            "index", "text", "label", "expected_action", "rule_hit",
            "semantic_top_class", "category", "action", "request_id",
        ]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            safe = dict(row)
            for key, value in safe.items():
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    safe[key] = "'" + value
            writer.writerow(safe)
        return buffer.getvalue().encode("utf-8-sig")

    def _run_mode(self, text: str, mode: str) -> dict[str, Any]:
        """按指定模式组合检测组件并路由（模拟 pipeline 各层开关）。

        full_pipeline 直接走生产入口 detect_text 保证一致性；
        其余模式手动组合：baseline/unnormalized_fusion 关闭归一化，
        rule_only/semantic_only 各自只开一层检测。
        """
        if mode == "full_pipeline":
            return self.pipeline.detect_text(text)
        views = self.pipeline.normalizer.normalize_views(text)
        normalized = views.normalized_text
        adversarial = views.adversarial_text or normalized
        if mode in {"baseline", "unnormalized_fusion"}:
            normalized = text.lower()
            adversarial = normalized
        rules = [] if mode == "semantic_only" else self.pipeline.rule_filter.detect(adversarial)
        semantics = [] if mode in {"baseline", "rule_only"} else self.pipeline.semantic_classifier.detect(normalized)
        semantic_explanation = (
            {
                "loaded": False, "scores": {}, "top_category": None,
                "top_score": None, "normal_score": None,
                "selected_category": None, "selected_score": None,
                "threshold": None,
                "category_thresholds": dict(
                    self.pipeline.semantic_classifier.category_thresholds
                ),
                "normal_margin": self.pipeline.semantic_classifier.min_margin,
                "protected_context": False,
                "error": "disabled for this evaluation mode",
            }
            if mode in {"baseline", "rule_only"}
            else self.pipeline.semantic_classifier.score_text(normalized)
        )
        routed, fallback = self.pipeline._route_input_all_versions(
            text, normalized, rules, semantics
        )
        detections = self.pipeline._deduplicate_detections([*rules, *semantics])
        return {
            "stage": f"evaluation:{mode}",
            "original_text": text,
            "normalized_text": normalized,
            "action": routed["action"],
            "category": routed["category"],
            "risk_score": int(routed["risk_score"]),
            "risk_level": routed["risk_level"],
            "reason_codes": list(routed.get("reason_codes") or []),
            "hard_block": bool(routed.get("hard_block")),
            "confidence": routed.get("confidence", 0.0),
            "matched_rule_ids": list(routed.get("matched_rule_ids") or []),
            "sanitized_text": None,
            "rewrite_called": False,
            "rewrite_changed": False,
            "rewrite_recheck": None,
            "detections": self.pipeline._serialize_detections(detections),
            "semantic_explanation": semantic_explanation,
            "fallback_used": fallback,
        }

    @staticmethod
    def _label_scores(label: str, rows: list[dict[str, Any]]) -> tuple[float, float]:
        true_positive = sum(
            row["label"] == label and row["category"] == label for row in rows
        )
        false_positive = sum(
            row["label"] != label and row["category"] == label for row in rows
        )
        false_negative = sum(
            row["label"] == label and row["category"] != label for row in rows
        )
        precision = true_positive / (true_positive + false_positive) \
            if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) \
            if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) \
            if precision + recall else 0.0
        return f1, recall

    @classmethod
    def _macro_scores(
        cls, labels: Iterable[str], rows: list[dict[str, Any]]
    ) -> tuple[float, float]:
        scores = [cls._label_scores(label, rows) for label in labels]
        if not scores:
            return 0.0, 0.0
        f1_values, recall_values = zip(*scores)
        return sum(f1_values) / len(f1_values), sum(recall_values) / len(recall_values)

    @classmethod
    def _metrics(cls, rows: list[dict[str, Any]]) -> dict[str, Any]:
        action_accuracy = sum(
            row["action"] == row["expected_action"] for row in rows
        ) / len(rows)
        category_accuracy = sum(
            row["category"] == row["label"] for row in rows
        ) / len(rows)
        labels = sorted({row["label"] for row in rows})
        macro_f1, macro_recall = cls._macro_scores(labels, rows)
        core_macro_f1, core_macro_recall = cls._macro_scores(
            CORE_CATEGORY_LABELS, rows
        )
        return {
            "action_accuracy": action_accuracy,
            "category_accuracy": category_accuracy,
            "macro_f1": macro_f1,
            "macro_recall": macro_recall,
            "evaluated_labels": labels,
            "core_labels": list(CORE_CATEGORY_LABELS),
            "macro_f1_core": core_macro_f1,
            "macro_recall_core": core_macro_recall,
        }
