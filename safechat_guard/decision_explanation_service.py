"""决策解释服务：把一次真实的 Pipeline 结果还原成人类可读的决策链。

原则是"解释即证据"：优先消费输入结果中已保存的归一化文本、语义分数
（semantic_explanation）、规则命中与动作路由结论，只做组装不做二次推理，
确保解释与真实决策完全一致；仅在证据缺失时（如旧结果或手工构造的
输入）才补跑归一化/语义评分。

同时提供 ``explain_audit_record``：对历史审计摘要的解释——审计日志只存
脱敏字段，因此历史解释显式标注 [NOT STORED]，绝不尝试还原原文。
"""

from __future__ import annotations

from typing import Any


class DecisionExplanationService:
    """Build truthful explanations from one live SafeChatPipeline result."""

    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline

    def explain(
        self,
        text: str,
        result: dict[str, Any] | None = None,
        *,
        request_id: str = "unavailable",
        provider: str = "not_called",
        model: str = "not_called",
    ) -> dict[str, Any]:
        """把一次 Pipeline 结果解释为决策链视图。

        result 传 None 时自动跑一次 detect_text；传 handle_chat 完整结果时
        自动提取 input_filter/output_filter 并关联 request_id/provider/model。
        归一化轨迹会重跑一次以获得逐步 steps（生产证据优先用于
        normalized_text 与语义分数），保证解释与真实决策一致。
        """
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        input_result = result or self.pipeline.detect_text(text)
        if "input_filter" in input_result:
            chat_result = input_result
            input_result = chat_result["input_filter"]
            request_id = str(chat_result.get("request_id") or request_id)
            provider = str(chat_result.get("provider") or provider)
            model = str(chat_result.get("model") or model)
            output_result = chat_result.get("output_filter")
            final_action = str(chat_result.get("final_action") or input_result["action"])
        else:
            chat_result = None
            output_result = None
            final_action = str(input_result["action"])

        trace = self.pipeline.normalizer.normalize_with_trace(text)
        normalized_text = str(
            input_result.get("normalized_text") or trace.normalized_text
        )
        semantic = input_result.get("semantic_explanation")
        if not isinstance(semantic, dict):
            semantic = self.pipeline.semantic_classifier.score_text(normalized_text)
        detections = list(input_result.get("detections") or [])
        rule_evidence = [
            {
                "source": item.get("source", "unknown"),
                "category": item.get("category", "unknown"),
                "score": item.get("score", 0),
                "level": item.get("level", "unknown"),
                "reason": item.get("reason", ""),
                "matches": list(item.get("matches") or []),
            }
            for item in detections
            if not str(item.get("source", "")).startswith("semantic")
        ]
        output_action = "not_run"
        output_details: dict[str, Any] = {
            "action": "not_run", "risk_level": "none", "detections": []
        }
        if isinstance(output_result, dict):
            output_action = str(output_result.get("action") or "pass")
            output_details = {
                "action": output_action,
                "risk_level": output_result.get("risk_level", "none"),
                "risk_score": output_result.get("risk_score", 0),
                "risk_categories": list(output_result.get("risk_categories") or []),
                "detections": list(output_result.get("detections") or []),
                "rewrite_recheck": output_result.get("rewrite_recheck"),
            }

        sanitized_text = input_result.get("sanitized_text")
        safe_input = chat_result.get("safe_input") if chat_result else sanitized_text
        normalization_steps = [
            {
                "normalizer": step.normalizer,
                "before": step.before,
                "after": step.after,
            }
            for step in trace.steps
        ]
        return {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "historical": False,
            "input": {"original_text": text},
            "normalization": {
                "normalized_text": normalized_text,
                "adversarial_text": trace.adversarial_text,
                "changed": normalized_text != text,
                "steps": normalization_steps,
            },
            "rule_filter": {
                "hits": rule_evidence,
                "matched_rule_ids": list(input_result.get("matched_rule_ids") or []),
            },
            "semantic_classifier": semantic,
            "action_router": {
                "action": input_result.get("action", "block"),
                "category": input_result.get("category", "normal"),
                "risk_level": input_result.get("risk_level", "high"),
                "risk_score": input_result.get("risk_score", 0),
                "confidence": input_result.get("confidence", 0.0),
                "reason_codes": list(input_result.get("reason_codes") or []),
                "hard_block": bool(input_result.get("hard_block")),
                "fallback_used": bool(input_result.get("fallback_used")),
            },
            "sanitizer": {
                "called": bool(input_result.get("rewrite_called")),
                "changed": bool(input_result.get("rewrite_changed")),
                "sanitized_text": sanitized_text,
                "actual_model_input": safe_input,
                "recheck": input_result.get("rewrite_recheck"),
            },
            "output_guard": output_details,
            "final": {
                "action": final_action,
                "allowed": bool(
                    chat_result.get("final_allowed", final_action != "block")
                    if chat_result else final_action != "block"
                ),
                "output_action": output_action,
            },
        }

    @staticmethod
    def explain_audit_record(record: dict[str, Any]) -> dict[str, Any]:
        """解释历史审计摘要：只使用持久化的脱敏字段，原文一律 [NOT STORED]。"""
        return {
            "request_id": record.get("request_id", "unavailable"),
            "provider": record.get("provider", "unknown"),
            "model": record.get("model", "unknown"),
            "historical": True,
            "input": {"original_text": "[NOT STORED]"},
            "normalization": {"normalized_text": "[NOT STORED]", "steps": []},
            "rule_filter": {"hits": [], "matched_rule_ids": []},
            "semantic_classifier": {
                "scores": {}, "normal_score": None,
                "note": "历史审计仅保存脱敏摘要，无法还原逐类分数。",
            },
            "action_router": {
                "action": record.get("input_action", "unknown"),
                "category": record.get("category", "unknown"),
                "risk_level": record.get("risk_level", "unknown"),
                "risk_score": record.get("risk_score", 0),
            },
            "sanitizer": {"actual_model_input": "[NOT STORED]"},
            "output_guard": {"action": record.get("output_action", "not_run")},
            "final": {"action": record.get("final_action", "unknown")},
        }
