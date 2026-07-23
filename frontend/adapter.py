from __future__ import annotations

from datetime import datetime
from typing import Any

from safechat_guard.pipeline import SafeChatPipeline


class FrontendPipelineAdapter:
    """Convert public pipeline results into presentation-only view models."""

    def __init__(self, pipeline: SafeChatPipeline):
        self.pipeline = pipeline

    def analyze(
        self,
        text: str,
        output_override: str | None = None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        # The public chat entry is the only authority for the final safety action.
        chat_result = self.pipeline.handle_chat(
            text,
            raw_reply_override=output_override,
            persist=persist,
        )
        input_result = chat_result["input_filter"]
        output_result = chat_result.get("output_filter")
        input_summary = self._summarize_result(input_result)
        output_summary = self._summarize_output(output_result)

        # Baseline data is diagnostic only and never influences the safety action.
        trace = self.pipeline.normalizer.normalize_with_trace(text)
        baseline_detections = self.pipeline.rule_filter.detect(text.lower())
        baseline = self._summarize_detections(baseline_detections)
        semantic = self._semantic_summary(input_result.get("detections", []))
        normalization_steps = [
            f"{step.normalizer}: {step.before} -> {step.after}"
            for step in trace.steps
        ] or ["文本无需归一化"]

        processed_text = chat_result.get("safe_input") or "未转发给大模型"
        service_error = chat_result.get("service_error")
        model_status = self._model_status(chat_result, output_summary["action"])
        status = self.pipeline.stats(portable_paths=True)
        final_answer = chat_result["reply"]
        strategy = self._processing_strategy(
            input_result["action"],
            input_result.get("rewrite_recheck"),
        )

        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_text": "[REDACTED]",
            "normalized_text": "[REDACTED]",
            "category": input_summary["category"],
            "risk": input_summary["risk"],
            "risk_score": input_result["risk_score"],
            "action": input_result["action"],
            "output_category": output_summary["category"],
            "output_action": output_summary["action"],
            "final_answer": "[REDACTED]",
            "baseline_missed": (
                baseline["action"] == "pass"
                and input_result["action"] != "pass"
            ),
        }

        return {
            "original_text": text,
            "normalized_text": input_result["normalized_text"],
            "normalization_steps": normalization_steps,
            "baseline_text": text.lower(),
            "baseline_hits": baseline["hits"],
            "baseline_category": baseline["category"],
            "baseline_risk": baseline["risk"],
            "baseline_score": baseline["score"],
            "baseline_action": baseline["action"],
            "hits": input_summary["hits"],
            "rule_category": input_summary["category"],
            "category": input_summary["category"],
            "risk": input_summary["risk"],
            "risk_score": input_result["risk_score"],
            "action": input_result["action"],
            "comparison_note": self._comparison_note(
                baseline["action"],
                input_result["action"],
            ),
            "semantic_category": semantic["category"],
            "semantic_score": semantic["score"],
            "semantic_scores": semantic["scores"],
            "semantic_note": semantic["note"],
            "sentiment": "未评估",
            "masked_text": input_result.get("sanitized_text") or text,
            "rewrite_text": processed_text,
            "rewrite_strategy": strategy,
            "rewrite_recheck": input_result.get("rewrite_recheck"),
            "processed_text": processed_text,
            # Never place model raw text in a frontend view model.
            "model_response": model_status,
            "model_output_hidden": True,
            "output_category": output_summary["category"],
            "output_risk": output_summary["risk"],
            "output_action": output_summary["action"],
            "output_hits": output_summary["hits"],
            "output_recheck": (
                output_result.get("rewrite_recheck") if output_result else None
            ),
            "final_answer": final_answer,
            "allowed": chat_result["allowed"],
            "service_error": service_error,
            "model_loaded": bool(status.get("model_loaded")),
            "model_degradation": (
                None
                if status.get("model_loaded")
                else "语义模型不可用，规则层继续运行"
            ),
            "record": record,
        }

    def record(self, result: dict[str, Any]) -> None:
        """Compatibility no-op: handle_chat already writes redacted stage events."""

    def stats(self) -> dict[str, Any]:
        return self.pipeline.stats(portable_paths=True)

    def log_rows(self) -> list[dict[str, Any]]:
        """Return aggregate, non-sensitive audit rows from the public stats API."""
        stats = self.stats()
        rows: list[dict[str, Any]] = []
        for dimension, counts in (
            ("类别", stats.get("category_counts", {})),
            ("风险", stats.get("risk_level_counts", {})),
            ("动作", stats.get("action_counts", {})),
            ("阶段", stats.get("stage_counts", {})),
        ):
            for name, count in sorted(counts.items()):
                rows.append(
                    {
                        "dimension": dimension,
                        "name": name,
                        "count": int(count),
                    }
                )
        return rows

    def lexicon_rows(self) -> list[dict[str, str]]:
        return [
            {"category": category, "word": word}
            for category, words in sorted(self.pipeline.rule_filter.words.items())
            for word in words
        ]

    def regex_rows(self) -> list[dict[str, Any]]:
        return list(self.pipeline.rule_filter.regex_rules)

    def _summarize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        detections = result.get("detections", [])
        primary = self._primary_detection(detections)
        return {
            "category": primary.get("category", "normal"),
            "risk": result.get(
                "risk_level",
                self._risk_from_score(result.get("risk_score", 0)),
            ),
            "hits": self._detection_hits(detections),
        }

    def _summarize_detections(self, detections: list[Any]) -> dict[str, Any]:
        serialized = [
            detection.__dict__ if hasattr(detection, "__dict__") else detection
            for detection in detections
        ]
        primary = self._primary_detection(serialized)
        score = max((item.get("score", 0) for item in serialized), default=0)
        action = self._action_from_score(score)
        return {
            "category": primary.get("category", "normal"),
            "risk": self._risk_from_score(score),
            "score": score,
            "action": action,
            "hits": self._detection_hits(serialized),
        }

    def _summarize_output(
        self,
        result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if result is None:
            return {
                "category": "normal",
                "risk": "none",
                "action": "not_run",
                "hits": [],
            }
        detections = result.get("detections", [])
        primary = self._primary_detection(detections)
        return {
            "category": primary.get("category", "normal"),
            "risk": result.get(
                "risk_level",
                self._risk_from_score(result.get("risk_score", 0)),
            ),
            "action": result.get("action", "pass"),
            "hits": self._detection_hits(detections),
        }

    def _semantic_summary(
        self,
        detections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        semantic = [
            item
            for item in detections
            if str(item.get("source", "")).startswith("semantic")
        ]
        categories = {"normal", "porn", "violence", "ad", "sensitive"}
        scores = {category: 0.0 for category in categories}
        if not semantic:
            scores["normal"] = 1.0
            return {
                "category": "normal",
                "score": 1.0,
                "scores": scores,
                "note": "语义层未发现额外风险。",
            }

        primary = self._primary_detection(semantic)
        category = primary.get("category", "normal")
        score = float(primary.get("score", 0)) / 100
        scores["normal"] = max(0.0, 1.0 - score)
        scores[category] = score
        return {
            "category": category,
            "score": score,
            "scores": scores,
            "note": primary.get("reason", "语义分类器检测结果"),
        }

    @staticmethod
    def _primary_detection(
        detections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return max(detections, key=lambda item: item.get("score", 0), default={})

    @staticmethod
    def _detection_hits(
        detections: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        rows = []
        for detection in detections:
            for match in detection.get("matches", []):
                rows.append(
                    {
                        "type": detection.get("source", "unknown"),
                        "category": detection.get("category", "unknown"),
                        "value": str(match),
                    }
                )
        return rows

    def _action_from_score(self, score: int) -> str:
        risk = self.pipeline.config["risk"]
        if score >= int(risk.get("block_threshold", 80)):
            return "block"
        if score >= int(risk.get("sanitize_threshold", 40)):
            return "sanitize"
        return "pass"

    @staticmethod
    def _risk_from_score(score: int) -> str:
        if score >= 80:
            return "high"
        if score >= 40:
            return "medium"
        if score > 0:
            return "low"
        return "none"

    @staticmethod
    def _comparison_note(baseline_action: str, action: str) -> str:
        if baseline_action == "pass" and action != "pass":
            return "归一化与联合检测识别到原始规则层漏检的内容。"
        if baseline_action != "pass" and action == "pass":
            return "增强流程降低了原始规则层的误判风险。"
        if baseline_action != action:
            return "增强流程调整了风险等级或处理方式。"
        return "原始规则层与增强流程结论一致。"

    @staticmethod
    def _processing_strategy(
        action: str,
        rewrite_recheck: dict[str, Any] | None,
    ) -> str:
        if action == "block" and rewrite_recheck:
            return "改写后已重新归一化并复检；仍有风险，因此拦截。"
        if action == "block":
            return "高风险内容被拦截，未转发给大模型。"
        if action == "sanitize":
            return "脱敏后重新归一化并通过规则、语义复检，再转发给模型。"
        return "无需处理，原文正常放行。"

    @staticmethod
    def _model_status(chat_result: dict[str, Any], output_action: str) -> str:
        if chat_result["input_filter"]["action"] == "block":
            return "输入已拦截，未调用模型"
        if chat_result.get("service_error"):
            return "模型服务不可用，未生成输出"
        if output_action == "not_run":
            return "模型输出未执行"
        if output_action != "pass":
            return "风险原始输出已隐藏，仅展示安全处理结果"
        return "模型输出已通过安全复检（原文不在前端展示）"
