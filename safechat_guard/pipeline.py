from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import time
import warnings

from .action_router import ActionRouter
from .llm_client import LLMClientError, LLMClientFactory
from .logger import EventLogger
from .normalizer import TextNormalizer
from .output_guard import OutputGuard
from .rule_filter import RuleFilter
from .sanitizer import Sanitizer
from .semantic_config import (
    DEFAULT_PRODUCTION_CONFIG_PATH,
    build_semantic_classifier,
    load_semantic_runtime_configuration,
)


class SafeChatPipeline:
    def __init__(self, config: dict, *, project_root: str | Path | None = None):
        self.config = config
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.package_root = Path(__file__).resolve().parent.parent
        self.normalizer = TextNormalizer(
            str(self.package_root / "data/maps/homophone_map.json"),
            str(self.package_root / "data/maps/emoji_map.json"),
        )
        self.rule_filter = RuleFilter(
            str(self.package_root / "data/lexicons"),
            str(self.package_root / "data/rules/regex_rules.json"),
        )
        semantic_options = config.get("semantic", {})
        semantic_config_path = semantic_options.get(
            "config_path", str(DEFAULT_PRODUCTION_CONFIG_PATH)
        )
        self.semantic_required = bool(semantic_options.get("required", False))
        runtime_configuration = load_semantic_runtime_configuration(
            self.project_root,
            semantic_config_path,
        )
        self.semantic_classifier = build_semantic_classifier(runtime_configuration)
        self.semantic_config_path = str(runtime_configuration.config_path)
        self.semantic_model_path = runtime_configuration.model_path
        semantic_status = self.semantic_classifier.status()
        if not semantic_status["loaded"]:
            message = (
                "semantic classifier unavailable: "
                f"{semantic_status['error']} "
                f"(model={runtime_configuration.model_path})"
            )
            if self.semantic_required:
                raise RuntimeError(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)

        self.sanitizer = Sanitizer()
        self.llm = LLMClientFactory.create(config.get("llm", {}))
        logging_config = config.get("logging", {})
        log_path = Path(logging_config.get("path", "data/logs/events.jsonl"))
        if not log_path.is_absolute():
            log_path = self.project_root / log_path
        self.logger = EventLogger(
            str(log_path),
            max_bytes=int(logging_config.get("max_bytes", 5 * 1024 * 1024)),
            backup_count=int(logging_config.get("backup_count", 5)),
            retention_days=int(logging_config.get("retention_days", 7)),
        )
        self.output_guard = OutputGuard(
            block_threshold=int(config["risk"].get("block_threshold", 80)),
            sanitize_threshold=int(config["risk"].get("sanitize_threshold", 40)),
        )
        self.action_router = None
        self.action_router_error_code = None
        try:
            self.action_router = ActionRouter(self._resolve_action_rules_path())
        except Exception:
            self.action_router_error_code = "ROUTER_UNAVAILABLE"

    @classmethod
    def from_config(cls, path: str):
        config_path = Path(path).resolve()
        with config_path.open("r", encoding="utf-8-sig") as file:
            return cls(json.load(file), project_root=config_path.parent)

    def handle_chat(
        self,
        message: str,
        raw_reply_override: str | None = None,
        persist: bool = True,
    ) -> dict:
        started = time.perf_counter()
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if raw_reply_override is not None and not isinstance(raw_reply_override, str):
            raise TypeError("raw_reply_override must be a string or None")

        input_result = self._filter_text(message, stage="input")
        self._write_event(
            {"stage": "input", "input": message, "result": input_result}, persist
        )
        if input_result["action"] == "block":
            result = {
                "allowed": False,
                "reply": "\u62b1\u6b49\uff0c\u60a8\u7684\u8f93\u5165\u5305\u542b\u9ad8\u98ce\u9669\u5185\u5bb9\uff0c\u5df2\u62e6\u622a\u4e14\u672a\u8f6c\u53d1\u7ed9\u6a21\u578b\u3002",
                "safe_input": None,
                "raw_reply": None,
                "rewrite": {
                    "changed": bool(input_result.get("rewrite_called")),
                    "rewrite_text": input_result.get("sanitized_text"),
                },
                "input_filter": input_result,
                "output_filter": None,
            }
            result.update(
                self._pipeline_result_fields(
                    input_result,
                    model_forwarded=False,
                    model_response=None,
                    output_guard_action=None,
                    started=started,
                )
            )
            self._write_event(
                {"stage": "final", "action": "block", "reason": "input_block"},
                persist,
            )
            return result

        safe_message = input_result.get("sanitized_text") or message
        rewrite = {
            "changed": safe_message != message,
            "rewrite_text": safe_message if safe_message != message else None,
        }
        model_forwarded = raw_reply_override is None
        input_result["model_forwarded"] = model_forwarded
        try:
            raw_reply = (
                raw_reply_override
                if raw_reply_override is not None
                else self.llm.chat(safe_message)
            )
        except LLMClientError:
            result = {
                "allowed": False,
                "reply": "\u6a21\u578b\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
                "safe_input": safe_message,
                "raw_reply": None,
                "rewrite": rewrite,
                "input_filter": input_result,
                "output_filter": None,
                "service_error": "llm_unavailable",
            }
            result.update(
                self._pipeline_result_fields(
                    input_result,
                    model_forwarded=model_forwarded,
                    model_response=None,
                    output_guard_action=None,
                    started=started,
                )
            )
            self._write_event(
                {
                    "stage": "final",
                    "action": "service_error",
                    "reason": "llm_unavailable",
                },
                persist,
            )
            return result

        output_result = self._filter_output(raw_reply)
        self._write_event(
            {"stage": "output", "raw_reply": raw_reply, "result": output_result},
            persist,
        )
        final_reply = output_result["final_text"]
        output_risky = output_result["action"] != "pass"
        public_output_result = self._public_output_result(output_result)
        result = {
            "allowed": output_result["action"] != "block",
            "reply": final_reply,
            "safe_input": safe_message,
            "raw_reply": None if output_risky else raw_reply,
            "rewrite": rewrite,
            "input_filter": input_result,
            "output_filter": public_output_result,
        }
        result.update(
            self._pipeline_result_fields(
                input_result,
                model_forwarded=model_forwarded,
                model_response=None if output_risky else raw_reply,
                output_guard_action=output_result["action"],
                started=started,
            )
        )
        self._write_event(
            {
                "stage": "final",
                "action": output_result["action"],
                "allowed": result["allowed"],
                "final_reply": final_reply,
            },
            persist,
        )
        return result
    def detect_text(self, text: str) -> dict:
        return self._filter_text(text, stage="detect")

    def _scan_text(self, text: str) -> tuple[str, list]:
        normalized, rule_detections, semantic_detections = (
            self._scan_text_layers(text)
        )
        return normalized, self._deduplicate_detections(
            [*rule_detections, *semantic_detections]
        )

    def _scan_text_layers(self, text: str) -> tuple[str, list, list]:
        normalized = self.normalizer.normalize(text)
        rule_detections = self.rule_filter.detect(normalized)
        semantic_detections = self.semantic_classifier.detect(normalized)
        return normalized, rule_detections, semantic_detections

    def _filter_output(self, text: str) -> dict:
        if not isinstance(text, str):
            raise TypeError("output text must be a string")
        normalized, detections = self._scan_text(text)
        result = self.output_guard.process(text, normalized, detections)
        if result["action"] != "sanitize":
            result["rewrite_recheck"] = None
            return result

        rewritten = result["final_text"]
        re_normalized, re_detections = self._scan_text(rewritten)
        rechecked = self.output_guard.process(rewritten, re_normalized, re_detections)
        result["rewrite_recheck"] = {
            "normalized_text": re_normalized,
            "action": rechecked["action"],
            "detections": rechecked["detections"],
        }
        if rechecked["action"] != "pass":
            categories = sorted(
                set(result.get("risk_categories", []))
                | set(rechecked.get("risk_categories", []))
            )
            refusal = self.output_guard._refusal(categories)
            result.update(
                {
                    "action": "block",
                    "blocked": True,
                    "rewritten": True,
                    "risk_level": "high",
                    "risk_categories": categories,
                    "final_text": refusal,
                    "sanitized_text": refusal,
                }
            )
        return result

    def _filter_text(self, text: str, stage: str) -> dict:
        started = time.perf_counter()
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized, rule_detections, semantic_detections = (
            self._scan_text_layers(text)
        )
        detections = self._deduplicate_detections(
            [*rule_detections, *semantic_detections]
        )
        routed, fallback_used = self._route_input(
            text,
            normalized,
            rule_detections,
            semantic_detections,
        )
        action = routed["action"]
        category = routed["category"]
        risk_level = routed["risk_level"]
        risk_score = routed["risk_score"]
        reason_codes = list(routed["reason_codes"])
        hard_block = bool(routed["hard_block"])
        if self._is_explicit_legacy_hard_block(routed, rule_detections):
            action = "block"
            hard_block = True
            risk_level = "high"
            risk_score = max(
                risk_score,
                max(detection.score for detection in rule_detections),
            )
            reason_codes.append("LEGACY_EXPLICIT_HARD_BLOCK")
        sanitized = None
        rewrite_called = False
        rewrite_changed = False
        rewrite_recheck = None
        recheck_action = None

        if action == "sanitize":
            rewrite_called = True
            matches = list(routed.get("sanitize_matches", []))
            matches.extend(
                match
                for detection in rule_detections
                for match in detection.matches
                if match and match in normalized
            )
            try:
                rewritten = self.sanitizer.sanitize(normalized, matches)
            except Exception:
                action = "block"
                risk_level = "high"
                risk_score = max(risk_score, 60)
                reason_codes.append("SANITIZER_ERROR")
            else:
                if not isinstance(rewritten, str) or not rewritten.strip():
                    action = "block"
                    risk_level = "high"
                    risk_score = max(risk_score, 60)
                    reason_codes.append("SANITIZER_EMPTY")
                elif rewritten == normalized:
                    action = "block"
                    risk_level = "high"
                    risk_score = max(risk_score, 60)
                    reason_codes.append("SANITIZER_UNCHANGED")
                    rewrite_recheck = {
                        "normalized_text": normalized,
                        "action": "block",
                        "category": category,
                        "risk_level": "high",
                        "risk_score": risk_score,
                        "reason_codes": ["SANITIZER_UNCHANGED"],
                        "hard_block": False,
                        "fallback_used": False,
                        "detections": [d.__dict__ for d in detections],
                    }
                else:
                    rewrite_changed = True
                    if "，" in text and "," not in text:
                        rewritten = rewritten.replace(",", "，")
                    try:
                        (
                            re_normalized,
                            re_rule_detections,
                            re_semantic_detections,
                        ) = self._scan_text_layers(rewritten)
                        re_detections = self._deduplicate_detections(
                            [*re_rule_detections, *re_semantic_detections]
                        )
                        re_routed, re_fallback = self._route_input(
                            rewritten,
                            re_normalized,
                            re_rule_detections,
                            re_semantic_detections,
                        )
                        fallback_used = fallback_used or re_fallback
                        recheck_action = re_routed["action"]
                        rewrite_recheck = {
                            "normalized_text": re_normalized,
                            "action": recheck_action,
                            "category": re_routed["category"],
                            "risk_level": re_routed["risk_level"],
                            "risk_score": re_routed["risk_score"],
                            "reason_codes": re_routed["reason_codes"],
                            "hard_block": re_routed["hard_block"],
                            "fallback_used": re_fallback,
                            "detections": [d.__dict__ for d in re_detections],
                        }
                    except Exception:
                        re_fallback = True
                        fallback_used = True
                        recheck_action = "block"
                        rewrite_recheck = {
                            "normalized_text": None,
                            "action": "block",
                            "category": category,
                            "risk_level": "high",
                            "risk_score": max(risk_score, 60),
                            "reason_codes": ["RECHECK_ERROR"],
                            "hard_block": False,
                            "fallback_used": True,
                            "detections": [],
                        }

                    if re_fallback:
                        action = "block"
                        risk_level = "high"
                        risk_score = max(risk_score, 60)
                        reason_codes.append("RECHECK_ROUTER_ERROR")
                    elif recheck_action == "pass":
                        sanitized = rewritten
                    else:
                        action = "block"
                        hard_block = bool(re_routed["hard_block"])
                        risk_level = "high"
                        risk_score = max(risk_score, re_routed["risk_score"])
                        reason_codes.extend(
                            [
                                f"REWRITE_RECHECK_{recheck_action.upper()}",
                                *re_routed["reason_codes"],
                            ]
                        )

        categories = sorted(
            {d.category for d in detections}
            | ({category} if category != "normal" else set())
        )
        return {
            "stage": stage,
            "original_text": text,
            "normalized_text": normalized,
            "action": action,
            "category": category,
            "risk_score": int(risk_score),
            "risk_level": risk_level,
            "risk_categories": categories,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "hard_block": hard_block,
            "confidence": routed.get("confidence", 0.0),
            "matched_rule_ids": list(routed.get("matched_rule_ids", [])),
            "sanitized_text": sanitized,
            "rewrite_called": rewrite_called,
            "rewrite_changed": rewrite_changed,
            "recheck_action": recheck_action,
            "rewrite_recheck": rewrite_recheck,
            "detections": [d.__dict__ for d in detections],
            "semantic_model_status": self._semantic_model_status(),
            "fallback_used": fallback_used,
            "model_forwarded": False,
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        }

    def _is_explicit_legacy_hard_block(
        self,
        routed: dict,
        rule_detections: list,
    ) -> bool:
        return (
            routed["action"] == "sanitize"
            and "RULE_RISK_EVIDENCE" in routed.get("reason_codes", [])
            and "SEMANTIC_RISK_EVIDENCE" not in routed.get("reason_codes", [])
            and any(
                detection.source in {"keyword", "regex"}
                and detection.level == "high"
                and detection.score
                >= int(self.config["risk"].get("block_threshold", 80))
                for detection in rule_detections
            )
        )
    def _route_input(
        self,
        original_text: str,
        normalized_text: str,
        rule_detections: list,
        semantic_detections: list,
    ) -> tuple[dict, bool]:
        if self.action_router is None:
            return (
                self._router_failure_result(
                    rule_detections,
                    semantic_detections,
                    self.action_router_error_code or "ROUTER_UNAVAILABLE",
                ),
                True,
            )
        try:
            return (
                self.action_router.route(
                    original_text,
                    normalized_text,
                    rule_detections,
                    semantic_detections,
                ),
                False,
            )
        except Exception:
            return (
                self._router_failure_result(
                    rule_detections,
                    semantic_detections,
                    "ROUTER_ERROR",
                ),
                True,
            )

    def _router_failure_result(
        self,
        rule_detections: list,
        semantic_detections: list,
        reason_code: str,
    ) -> dict:
        detections = [*rule_detections, *semantic_detections]
        if not detections:
            semantic_available = self._semantic_model_status() == "loaded"
            if not semantic_available:
                return {
                    "action": "block",
                    "category": "normal",
                    "risk_level": "high",
                    "confidence": 0.0,
                    "reason_codes": [
                        reason_code,
                        "ROUTER_AND_SEMANTIC_UNAVAILABLE",
                    ],
                    "hard_block": False,
                    "risk_score": 60,
                    "matched_rule_ids": [],
                    "sanitize_matches": [],
                }
            return {
                "action": "pass",
                "category": "normal",
                "risk_level": "none",
                "confidence": 0.0,
                "reason_codes": [reason_code, "NO_DETECTION_EVIDENCE"],
                "hard_block": False,
                "risk_score": 0,
                "matched_rule_ids": [],
                "sanitize_matches": [],
            }
        selected = max(detections, key=lambda detection: detection.score)
        explicit_rule_block = any(
            detection.source in {"keyword", "regex"}
            and detection.level == "high"
            and detection.score
            >= int(self.config["risk"].get("block_threshold", 80))
            for detection in rule_detections
        )
        return {
            "action": "block",
            "category": selected.category,
            "risk_level": "high",
            "confidence": 0.0,
            "reason_codes": [reason_code, "DETECTION_EVIDENCE_FAIL_CLOSED"],
            "hard_block": explicit_rule_block,
            "risk_score": max(int(selected.score), 60),
            "matched_rule_ids": [],
            "sanitize_matches": [],
        }

    def _resolve_action_rules_path(self) -> Path:
        configured = self.config.get("action_router", {}).get("rules_path")
        if configured:
            path = Path(configured)
            return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()
        return (self.package_root / "config/action_rules_v1.json").resolve()

    def _semantic_model_status(self) -> str:
        status = self.semantic_classifier.status()
        return "loaded" if status.get("loaded") else "unavailable"

    @staticmethod
    def _pipeline_result_fields(
        input_result: dict,
        *,
        model_forwarded: bool,
        model_response: str | None,
        output_guard_action: str | None,
        started: float,
    ) -> dict:
        return {
            "action": input_result["action"],
            "category": input_result["category"],
            "risk_level": input_result["risk_level"],
            "risk_score": input_result["risk_score"],
            "reason_codes": input_result["reason_codes"],
            "hard_block": input_result["hard_block"],
            "normalized_text": input_result["normalized_text"],
            "sanitized_text": input_result.get("sanitized_text"),
            "model_forwarded": model_forwarded,
            "model_response": model_response,
            "output_guard_action": output_guard_action,
            "semantic_model_status": input_result["semantic_model_status"],
            "fallback_used": input_result["fallback_used"],
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        }
    def stats(
        self,
        since: datetime | None = None,
        *,
        portable_paths: bool = False,
    ) -> dict:
        stats = self.logger.stats(since=since)
        semantic_status = dict(self.semantic_classifier.status())
        semantic_status["required"] = self.semantic_required
        semantic_status["config_path"] = self.semantic_config_path
        if portable_paths:
            semantic_status["config_path"] = self._portable_path(self.semantic_config_path)
            semantic_status["model_path"] = self.semantic_model_path
        stats["semantic_classifier"] = semantic_status
        stats["model_loaded"] = semantic_status.get("loaded", False)
        stats["model_error"] = semantic_status.get("error")
        stats["llm"] = self.llm.status()
        return stats

    @staticmethod
    def _public_output_result(result: dict) -> dict:
        if result.get("action") == "pass":
            return result
        public = dict(result)
        for field in ("original_text", "normalized_text", "sanitized_raw_output"):
            public[field] = None
        public["matched_rules"] = [
            {**rule, "match": "[REDACTED]"}
            for rule in result.get("matched_rules", [])
        ]
        public["detections"] = [
            {**detection, "matches": ["[REDACTED]"] if detection.get("matches") else []}
            for detection in result.get("detections", [])
        ]
        return public

    def _portable_path(self, value: str) -> str:
        path = Path(value)
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return path.name

    def _write_event(self, event: dict, persist: bool) -> None:
        if persist:
            self.logger.write(event)

    def _risk_level(self, score: int) -> str:
        if score >= int(self.config["risk"].get("block_threshold", 80)):
            return "high"
        if score >= int(self.config["risk"].get("sanitize_threshold", 40)):
            return "medium"
        if score > 0:
            return "low"
        return "none"

    @staticmethod
    def _deduplicate_detections(detections: list) -> list:
        unique = []
        seen = set()
        for detection in detections:
            key = (detection.category, detection.source, tuple(detection.matches))
            if key not in seen:
                seen.add(key)
                unique.append(detection)
        return unique
