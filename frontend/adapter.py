from __future__ import annotations

from datetime import datetime
from typing import Any
import hmac
import os
import warnings

from safechat_guard.pipeline import SafeChatPipeline
from safechat_guard.rule_manager import RuleManagerError, apply_rule_transaction


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
        final_action = chat_result.get("final_action")
        if final_action not in {"pass", "sanitize", "block"}:
            if (
                not chat_result.get("allowed", False)
                or output_summary["action"] == "block"
            ):
                final_action = "block"
            elif (
                input_result["action"] == "sanitize"
                or output_summary["action"] == "sanitize"
            ):
                final_action = "sanitize"
            else:
                final_action = "pass"
        final_allowed = chat_result.get("final_allowed")
        if not isinstance(final_allowed, bool):
            final_allowed = final_action != "block"

        # Baseline data is diagnostic only and never influences the safety action.
        trace = self.pipeline.normalizer.normalize_with_trace(text)
        baseline_detections = self.pipeline.rule_filter.detect(text.lower())
        baseline = self._summarize_detections(baseline_detections)
        semantic = self._semantic_summary(
            input_result.get("normalized_text", text)
        )
        normalization_steps = [
            f"{step.normalizer}: {step.before} -> {step.after}"
            for step in trace.steps
        ] or ["文本无需归一化"]

        rewrite_changed = bool(input_result.get("rewrite_changed", False))
        recheck_action = input_result.get("recheck_action")
        sanitized_text = input_result.get("sanitized_text")
        verified_sanitize = (
            input_result["action"] == "sanitize"
            and isinstance(sanitized_text, str)
            and bool(sanitized_text.strip())
            and rewrite_changed
            and recheck_action == "pass"
        )
        processed_text = chat_result.get("safe_input") or "未转发给模型"
        service_error = chat_result.get("service_error")
        model_status = self._model_status(chat_result, output_summary["action"])
        status = self.pipeline.stats(portable_paths=True)
        final_answer = chat_result["reply"]
        judge_view = self._judge_view(
            chat_result,
            status.get("llm_judge", {}),
            output_result,
        )
        strategy = self._processing_strategy(
            input_result["action"],
            input_result.get("rewrite_recheck"),
            input_result.get("reason_codes", []),
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
            "final_action": final_action,
            "final_allowed": final_allowed,
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
            "final_action": final_action,
            "final_allowed": final_allowed,
            "comparison_note": self._comparison_note(
                baseline["action"],
                input_result["action"],
            ),
            "semantic_category": semantic["category"],
            "semantic_score": semantic["score"],
            "semantic_scores": semantic["scores"],
            "semantic_note": semantic["note"],
            "semantic_final_category": semantic["final_category"],
            "semantic_available": semantic["available"],
            "semantic_gate_triggered": semantic["gate_triggered"],
            "semantic_error": semantic["error"],
            "sentiment": "未评估",
            "masked_text": sanitized_text if verified_sanitize else None,
            "rewrite_text": processed_text,
            "rewrite_strategy": strategy,
            "decision_note": self._decision_note(
                input_result.get("reason_codes", [])
            ),
            "rewrite_recheck": input_result.get("rewrite_recheck"),
            "rewrite_called": bool(input_result.get("rewrite_called", False)),
            "rewrite_changed": rewrite_changed,
            "recheck_action": recheck_action,
            "processed_text": processed_text,
            **judge_view,
            # Never place model raw text in a frontend view model.
            "model_response": model_status,
            "model_output_hidden": True,
            "output_category": output_summary["category"],
            "output_risk": output_summary["risk"],
            "output_action": output_summary["action"],
            "output_guard_action": (
                chat_result.get("output_guard_action") or output_summary["action"]
            ),
            "output_hits": output_summary["hits"],
            "output_recheck": (
                output_result.get("rewrite_recheck") if output_result else None
            ),
            "final_answer": final_answer,
            "allowed": chat_result["allowed"],
            "final_allowed": final_allowed,
            "model_forwarded": bool(chat_result.get("model_forwarded", False)),
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

    def daily_stats(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        return self.pipeline.logger.daily_stats(
            start_date=start_date,
            end_date=end_date,
            timezone_name=timezone_name,
        )

    def rule_catalog(
        self,
        *,
        include_pattern: bool = False,
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        if include_pattern and not self._pattern_access_authorized(admin_token):
            raise PermissionError("Rule management access denied")
        builtins = []
        for category, words in sorted(self.pipeline.rule_filter.words.items()):
            for index, word in enumerate(words):
                builtins.append(
                    self._public_rule(
                        {
                            "id": f"builtin:keyword:{category}:{index}",
                            "pattern": word,
                            "pattern_type": "keyword",
                            "category": category,
                            "action": "block" if category in {"porn", "violence"} else "sanitize",
                            "risk_level": "high" if category in {"porn", "violence"} else "medium",
                            "enabled": True,
                            "description": "Built-in keyword rule",
                            "source": "builtin",
                            "origin": "builtin",
                            "read_only": True,
                        },
                        include_pattern=include_pattern,
                    )
                )
        for index, rule in enumerate(self.pipeline.rule_filter.regex_rules):
            builtins.append(
                self._public_rule(
                    {
                        "id": f"builtin:regex:{index}",
                        "pattern": rule.get("pattern", ""),
                        "pattern_type": "regex",
                        "category": rule.get("category", "sensitive"),
                        "action": "block" if int(rule.get("score", 60)) >= 80 else "sanitize",
                        "risk_level": rule.get("level", "medium"),
                        "enabled": True,
                        "description": rule.get("reason", "Built-in regex rule"),
                        "source": "builtin",
                        "origin": "builtin",
                        "read_only": True,
                    },
                    include_pattern=include_pattern,
                )
            )
        users = [
            {
                **self._public_rule(rule, include_pattern=include_pattern),
                "origin": "user",
                "read_only": False,
            }
            for rule in self.pipeline.rule_manager.list_rules()
        ]
        return {
            "rules": [*builtins, *users],
            "built_in_count": len(builtins),
            "user_count": len(users),
            "pattern_access": include_pattern,
            **self.pipeline.rule_manager.metadata(),
        }

    def add_user_rule(self, rule: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        rule_id = rule.get("id") if isinstance(rule.get("id"), str) else None
        result = self._apply_rule_change(
            "rule_created",
            rule_id,
            lambda: self.pipeline.rule_manager.add_rule(
                rule, expected_revision=expected_revision
            ),
        )
        return self._public_management_result(result)

    def update_user_rule(
        self, rule_id: str, changes: dict[str, Any], expected_revision: int
    ) -> dict[str, Any]:
        result = self._apply_rule_change(
            "rule_updated",
            rule_id,
            lambda: self.pipeline.rule_manager.update_rule(
                rule_id, changes, expected_revision=expected_revision
            ),
        )
        return self._public_management_result(result)

    def set_user_rule_enabled(
        self, rule_id: str, enabled: bool, expected_revision: int
    ) -> dict[str, Any]:
        operation = (
            self.pipeline.rule_manager.enable_rule
            if enabled
            else self.pipeline.rule_manager.disable_rule
        )
        event = "rule_enabled" if enabled else "rule_disabled"
        result = self._apply_rule_change(
            event,
            rule_id,
            lambda: operation(rule_id, expected_revision=expected_revision),
        )
        return self._public_management_result(result)

    def delete_user_rule(self, rule_id: str, expected_revision: int) -> dict[str, Any]:
        return self._apply_rule_change(
            "rule_deleted",
            rule_id,
            lambda: self.pipeline.rule_manager.delete_rule(
                rule_id, expected_revision=expected_revision
            ),
        )

    def import_user_rules(
        self,
        content: bytes,
        *,
        format_name: str,
        dry_run: bool,
        mode: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        importer = (
            self.pipeline.rule_manager.import_csv
            if format_name == "csv"
            else self.pipeline.rule_manager.import_json
        )
        mutation = lambda: importer(
            content,
            dry_run=dry_run,
            mode=mode,
            expected_revision=expected_revision,
        )
        if dry_run:
            return mutation()
        return self._apply_rule_change("rule_imported", None, mutation)

    def _apply_rule_change(
        self, event: str, rule_id: str | None, mutation: Any
    ) -> dict[str, Any]:
        try:
            result = apply_rule_transaction(
                self.pipeline.rule_manager,
                self.pipeline.rule_filter,
                mutation,
            )
        except RuleManagerError:
            self._audit_rule_change(
                event,
                rule_id,
                self.pipeline.rule_manager.revision,
                "failed",
            )
            raise
        self._audit_rule_change(
            event, rule_id, result["revision"], "success"
        )
        return result

    def _audit_rule_change(
        self,
        event: str,
        rule_id: str | None,
        revision: int,
        result: str,
    ) -> None:
        try:
            self.pipeline.logger.write(
                {
                    "stage": "rule_management",
                    "operation": event,
                    "rule_id": rule_id,
                    "revision": revision,
                    "result": result,
                }
            )
        except Exception:
            warnings.warn(
                "rule management audit logging failed",
                RuntimeWarning,
                stacklevel=2,
            )

    @staticmethod
    def _public_rule(
        rule: dict[str, Any], *, include_pattern: bool
    ) -> dict[str, Any]:
        public = dict(rule)
        public["pattern_redacted"] = not include_pattern
        if not include_pattern:
            public["pattern"] = "[REDACTED]"
        return public

    @classmethod
    def _public_management_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        public = dict(result)
        if isinstance(public.get("rule"), dict):
            public["rule"] = cls._public_rule(
                public["rule"], include_pattern=False
            )
        return public

    @staticmethod
    def _pattern_access_authorized(admin_token: str | None) -> bool:
        configured = os.getenv("SAFECHAT_RULE_ADMIN_TOKEN")
        if not configured:
            return True
        supplied = admin_token if isinstance(admin_token, str) else ""
        return bool(supplied) and hmac.compare_digest(supplied, configured)
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
        text: str,
    ) -> dict[str, Any]:
        categories = ("normal", "ad", "porn", "sensitive", "violence")
        unavailable = {
            "category": None,
            "final_category": None,
            "score": None,
            "scores": {category: 0.0 for category in categories},
            "note": "语义模型不可用，已回退规则检测。",
            "available": False,
            "gate_triggered": False,
            "error": "semantic distribution unavailable",
        }
        predictor = getattr(
            self.pipeline.semantic_classifier, "predict_distribution", None
        )
        if not callable(predictor):
            return unavailable
        try:
            distribution = predictor(text)
        except Exception as exc:
            return {
                **unavailable,
                "error": f"semantic display failed: {type(exc).__name__}",
            }
        if not isinstance(distribution, dict) or not distribution.get("available"):
            return {
                **unavailable,
                "error": (
                    distribution.get("error", unavailable["error"])
                    if isinstance(distribution, dict)
                    else unavailable["error"]
                ),
            }

        raw_scores = distribution.get("probabilities", {})
        scores = {
            category: float(raw_scores.get(category, 0.0))
            for category in categories
        }
        category = str(distribution.get("top_category", "normal"))
        score = float(distribution.get("top_probability", 0.0))
        gate_triggered = bool(distribution.get("risk_detection_emitted", False))
        return {
            "category": category,
            "final_category": category if gate_triggered else "normal",
            "score": score,
            "scores": scores,
            "note": f"风险门控：{'已触发' if gate_triggered else '未触发'}。",
            "available": True,
            "gate_triggered": gate_triggered,
            "error": None,
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
        reason_codes: list[str],
    ) -> str:
        if action == "block" and rewrite_recheck:
            return "改写后已重新归一化并复检；仍有风险，因此拦截。"
        if action == "block":
            return "高风险内容被拦截，未转发给大模型。"
        if action == "sanitize":
            return "脱敏后重新归一化并通过规则、语义复检，再转发给模型。"
        if "V3_SAFE_CONTEXT" in reason_codes:
            return "安全语境放行"
        return "正常放行"

    @staticmethod
    def _decision_note(reason_codes: list[str]) -> str | None:
        if "V3_SAFE_CONTEXT" in reason_codes:
            return (
                "检测到局部风险语义，但上下文属于预防、教育或治理讨论，"
                "无需脱敏。"
            )
        return None

    @staticmethod
    def _judge_view(
        chat_result: dict[str, Any],
        judge_status: dict[str, Any],
        output_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        input_used = bool(chat_result.get("input_judge_used", False))
        output_used = bool(chat_result.get("output_judge_used", False))
        input_source = chat_result.get("input_decision_source", "local_only")
        output_source = chat_result.get("output_decision_source", "local_only")
        fallback = "local_fallback" in {input_source, output_source}
        configured_unavailable = bool(judge_status.get("enabled", False)) and not bool(
            judge_status.get("available", False)
        )
        if fallback or configured_unavailable:
            arbitration_status = "不可用，已回退本地安全策略"
        elif input_used or output_used:
            arbitration_status = "已启用"
        else:
            arbitration_status = "未触发"
        selected_action = (
            chat_result.get("output_judge_action")
            if output_used
            else chat_result.get("input_judge_action")
        )
        selected_reason = (
            chat_result.get("output_judge_reason")
            if output_used
            else chat_result.get("input_judge_reason")
        )
        selected_error_stage = (
            (output_result or {}).get("output_judge_error_stage")
            if output_used
            else chat_result.get("input_judge_error_stage")
        )
        selected_error_code = (
            (output_result or {}).get("output_judge_error_code")
            if output_used
            else chat_result.get("input_judge_error_code")
        )
        if configured_unavailable and selected_error_stage is None:
            selected_error_stage = "initialization"
            selected_error_code = judge_status.get("error") or "CLIENT_NOT_READY"
        selected_source = output_source if output_used else input_source
        source_labels = {
            "local_hard_block": "本地确定性安全规则",
            "local_only": "本地安全策略",
            "llm_judge": "LLM语义仲裁 + 本地安全约束",
            "local_fallback": "Judge不可用，采用本地安全策略",
        }
        return {
            "semantic_arbitration_enabled": bool(judge_status.get("enabled", False)),
            "semantic_arbitration_status": arbitration_status,
            "judge_action": selected_action,
            "judge_reason": selected_reason,
            "judge_decision_source": selected_source,
            "judge_error_stage": selected_error_stage,
            "judge_error_code": selected_error_code,
            "validation_error_code": (
                selected_error_code
                if selected_error_stage == "schema_validation" else None
            ),
            "judge_decision_source_label": source_labels.get(
                selected_source, "本地安全策略"
            ),
            "input_judge_used": input_used,
            "input_judge_action": chat_result.get("input_judge_action"),
            "input_judge_reason": chat_result.get("input_judge_reason"),
            "output_judge_used": output_used,
            "output_judge_action": chat_result.get("output_judge_action"),
            "output_judge_reason": chat_result.get("output_judge_reason"),
        }

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
