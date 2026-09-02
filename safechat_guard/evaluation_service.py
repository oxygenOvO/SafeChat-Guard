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
    def _metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
        action_accuracy = sum(
            row["action"] == row["expected_action"] for row in rows
        ) / len(rows)
        category_accuracy = sum(
            row["category"] == row["label"] for row in rows
        ) / len(rows)
        labels = sorted({row["label"] for row in rows})
        f1_values = []
        recall_values = []
        for label in labels:
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
            f1_values.append(
                2 * precision * recall / (precision + recall)
                if precision + recall else 0.0
            )
            recall_values.append(recall)
        return {
            "action_accuracy": action_accuracy,
            "category_accuracy": category_accuracy,
            "macro_f1": sum(f1_values) / len(f1_values),
            "macro_recall": sum(recall_values) / len(recall_values),
        }
