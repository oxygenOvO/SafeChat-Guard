from __future__ import annotations

from datetime import datetime
from typing import Any

from safechat_guard.pipeline import SafeChatPipeline


class FrontendPipelineAdapter:
    def __init__(self, pipeline: SafeChatPipeline):
        self.pipeline = pipeline

    def analyze(
        self,
        text: str,
        output_override: str | None = None,
    ) -> dict[str, Any]:
        trace = self.pipeline.normalizer.normalize_with_trace(text)
        baseline_detections = self.pipeline.rule_filter.detect(text.lower())
        baseline = self._summarize_detections(baseline_detections)
        input_result = self.pipeline.filter_input(text)
        input_summary = self._summarize_result(input_result)

        if input_result["action"] == "block":
            processed_text = "未转发给大模型"
            model_response = "输入内容风险较高，系统已拒绝转发给大模型。"
            output_result = None
            final_answer = model_response
        else:
            processed_text = input_result.get("sanitized_text") or text
            model_response = (
                output_override
                if output_override is not None
                else self.pipeline.llm.chat(processed_text)
            )
            output_result = self.pipeline.filter_output(model_response)
            final_answer = (
                output_result.get("final_text")
                or output_result.get("sanitized_text")
                or model_response
            )

        output_summary = self._summarize_output(output_result)
        semantic = self._semantic_summary(input_result["detections"])
        normalization_steps = [
            f"{step.normalizer}: {step.before} -> {step.after}"
            for step in trace.steps
        ] or ["文本无需归一化"]
        comparison_note = self._comparison_note(
            baseline["action"],
            input_result["action"],
        )
        strategy = self._processing_strategy(input_result["action"])

        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_text": text,
            "normalized_text": input_result["normalized_text"],
            "category": input_summary["category"],
            "risk": input_summary["risk"],
            "risk_score": input_result["risk_score"],
            "action": input_result["action"],
            "output_category": output_summary["category"],
            "output_action": output_summary["action"],
            "final_answer": final_answer,
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
            "comparison_note": comparison_note,
            "semantic_category": semantic["category"],
            "semantic_score": semantic["score"],
            "semantic_scores": semantic["scores"],
            "semantic_note": semantic["note"],
            "sentiment": "未评估",
            "masked_text": input_result.get("sanitized_text") or text,
            "rewrite_text": processed_text,
            "rewrite_strategy": strategy,
            "processed_text": processed_text,
            "model_response": model_response,
            "output_category": output_summary["category"],
            "output_risk": output_summary["risk"],
            "output_action": output_summary["action"],
            "output_hits": output_summary["hits"],
            "final_answer": final_answer,
            "record": record,
            "_input_filter": input_result,
            "_output_filter": output_result,
        }

    def record(self, result: dict[str, Any]) -> None:
        event = {
            "stage": "frontend",
            "input": result["original_text"],
            "safe_input": result["processed_text"],
            "raw_reply": result["model_response"],
            "final_reply": result["final_answer"],
            "input_filter": result["_input_filter"],
            "output_filter": result["_output_filter"],
        }
        self.pipeline.logger.write(event)

    def log_rows(self) -> list[dict[str, Any]]:
        rows = []
        for event in self.pipeline.logger.read_all():
            input_result = event.get("input_filter") or event.get("result") or {}
            output_result = event.get("output_filter") or {}
            input_summary = self._summarize_result(input_result)
            output_summary = self._summarize_output(output_result or None)
            rows.append(
                {
                    "time": event.get("time", ""),
                    "input_text": event.get("input", ""),
                    "category": input_summary["category"],
                    "risk": input_summary["risk"],
                    "action": input_result.get("action", "pass"),
                    "output_action": output_summary["action"],
                    "final_answer": event.get("final_reply", ""),
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
            "risk": self._risk_from_score(result.get("risk_score", 0)),
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
            note = (
                "规则层已有命中，未运行语义层。"
                if detections
                else "语义层未发现风险。"
            )
            scores["normal"] = 1.0
            return {
                "category": "normal",
                "score": 1.0,
                "scores": scores,
                "note": note,
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
            return "归一化增强版识别到原始规则层漏检的内容。"
        if baseline_action != "pass" and action == "pass":
            return "增强流程降低了原始规则层的误判风险。"
        if baseline_action != action:
            return "增强流程调整了风险等级或处理方式。"
        return "原始规则层与增强流程结论一致。"

    @staticmethod
    def _processing_strategy(action: str) -> str:
        if action == "block":
            return "高风险内容被拦截，未转发给大模型。"
        if action == "sanitize":
            return "依据真实命中规则完成脱敏后再转发。"
        return "无需处理，原文正常放行。"
