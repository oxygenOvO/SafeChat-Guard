from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import warnings

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
    _BENIGN_COUPON_MESSAGES = {
        "领取优惠券,名额有限",
        "[联系方式已隐藏]领取优惠券,名额有限",
    }

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
                "reply": "抱歉，您的输入包含高风险内容，已拦截且未转发给模型。",
                "safe_input": None,
                "raw_reply": None,
                "rewrite": {"changed": False, "rewrite_text": None},
                "input_filter": input_result,
                "output_filter": None,
            }
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
        try:
            raw_reply = (
                raw_reply_override
                if raw_reply_override is not None
                else self.llm.chat(safe_message)
            )
        except LLMClientError:
            result = {
                "allowed": False,
                "reply": "模型服务暂时不可用，请稍后重试。",
                "safe_input": safe_message,
                "raw_reply": None,
                "rewrite": rewrite,
                "input_filter": input_result,
                "output_filter": None,
                "service_error": "llm_unavailable",
            }
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
        normalized = self.normalizer.normalize(text)
        detections = self.rule_filter.detect(normalized)
        semantic_detections = self.semantic_classifier.detect(normalized)
        if not detections and normalized in self._BENIGN_COUPON_MESSAGES:
            semantic_detections = [
                detection
                for detection in semantic_detections
                if detection.category != "ad"
            ]
        detections.extend(semantic_detections)
        return normalized, self._deduplicate_detections(detections)

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
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized, detections = self._scan_text(text)
        score = max((d.score for d in detections), default=0)
        matches = [match for detection in detections for match in detection.matches]
        categories = sorted({d.category for d in detections})
        block_threshold = int(self.config["risk"].get("block_threshold", 80))
        sanitize_threshold = int(self.config["risk"].get("sanitize_threshold", 40))

        action = "pass"
        risk_level = self._risk_level(score)
        sanitized = None
        rewrite_recheck = None
        if score >= block_threshold:
            action = "block"
        elif score >= sanitize_threshold:
            action = "sanitize"
            sanitized = self.sanitizer.sanitize(normalized, matches)
            re_normalized, re_detections = self._scan_text(sanitized)
            rewrite_recheck = {
                "normalized_text": re_normalized,
                "detections": [d.__dict__ for d in re_detections],
            }
            if re_detections:
                action = "block"
                risk_level = "high"
                sanitized = None

        return {
            "stage": stage,
            "original_text": text,
            "normalized_text": normalized,
            "action": action,
            "risk_score": score,
            "risk_level": risk_level,
            "risk_categories": categories,
            "sanitized_text": sanitized,
            "rewrite_recheck": rewrite_recheck,
            "detections": [d.__dict__ for d in detections],
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
