import json
from pathlib import Path

from .config_utils import load_semantic_thresholds
from .llm_client import LLMClientFactory
from .logger import EventLogger
from .normalizer import TextNormalizer
from .output_guard import OutputGuard
from .rewriter import EmotionPreservingRewriter
from .rule_filter import RuleFilter
from .sanitizer import Sanitizer
from .semantic_classifier import SemanticClassifier


class SafeChatPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.project_root = Path(__file__).resolve().parent.parent
        self.normalizer = TextNormalizer(
            str(self.project_root / "data/maps/homophone_map.json"),
            str(self.project_root / "data/maps/emoji_map.json"),
        )
        self.rule_filter = RuleFilter(
            str(self.project_root / "data/lexicons"),
            str(self.project_root / "data/rules/regex_rules.json"),
        )
        self.semantic_thresholds = load_semantic_thresholds(config)
        self.semantic_classifier = SemanticClassifier(thresholds=self.semantic_thresholds)
        self.sanitizer = Sanitizer()
        self.rewriter = EmotionPreservingRewriter()
        self.llm = LLMClientFactory.create(config.get("llm", {}))

        log_path = Path(config.get("logging", {}).get("path", "data/logs/events.jsonl"))
        if not log_path.is_absolute():
            log_path = self.project_root / log_path
        self.logger = EventLogger(str(log_path))
        self.output_guard = OutputGuard(
            block_threshold=int(config["risk"].get("block_threshold", 80)),
            sanitize_threshold=int(config["risk"].get("sanitize_threshold", 40)),
        )

    @classmethod
    def from_config(cls, path: str):
        config_path = Path(path)
        if not config_path.is_absolute() and not config_path.exists():
            config_path = Path(__file__).resolve().parent.parent / config_path
        with config_path.open("r", encoding="utf-8") as file:
            return cls(json.load(file))

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
        rewrite_result = self.rewriter.unchanged(message)

        if input_result["action"] == "block":
            reply = "抱歉，您的输入包含高风险不合规内容，系统已拦截且未转发给大模型。"
            event = {"stage": "input", "input": message, "result": input_result}
            if persist:
                self.logger.write(event)
            return {
                "allowed": False,
                "reply": reply,
                "safe_input": "未转发给大模型",
                "raw_reply": "",
                "rewrite": rewrite_result,
                "input_filter": input_result,
                "output_filter": None,
            }

        safe_message = message
        if input_result["action"] == "sanitize":
            rewrite_result = self.rewriter.rewrite(
                message,
                input_result["risk_category"],
                input_result["matches"],
            )
            safe_message = rewrite_result["rewrite_text"]

        raw_reply = raw_reply_override if raw_reply_override is not None else self.llm.chat(safe_message)
        output_result = self._filter_output(raw_reply)
        final_reply = output_result.get("final_text") or raw_reply

        event = {
            "stage": "chat",
            "input": message,
            "safe_input": safe_message,
            "raw_reply": raw_reply if output_result["action"] == "pass" else None,
            "final_reply": final_reply,
            "risk_categories": output_result.get("risk_categories", []),
            "risk_level": output_result.get("risk_level", "none"),
            "blocked": output_result.get("blocked", False),
            "rewritten": output_result.get("rewritten", False),
            "matched_rules": output_result.get("matched_rules", []),
            "input_filter": input_result,
            "output_filter": output_result,
        }
        if persist:
            self.logger.write(event)
        return {
            "allowed": output_result["action"] != "block",
            "reply": final_reply,
            "safe_input": safe_message,
            "raw_reply": raw_reply if output_result["action"] == "pass" else None,
            "rewrite": rewrite_result,
            "input_filter": input_result,
            "output_filter": output_result,
        }

    def _filter_output(self, text: str) -> dict:
        if not isinstance(text, str):
            raise TypeError("output text must be a string")
        normalized = self.normalizer.normalize(text)
        detections = self.rule_filter.detect(normalized)
        detections.extend(self.semantic_classifier.detect(normalized))
        detections = self._deduplicate_detections(detections)
        return self.output_guard.process(text, normalized, detections)

    def _filter_text(self, text: str, stage: str) -> dict:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        trace = self.normalizer.normalize_with_trace(text)
        normalized = trace.normalized_text
        normalization_steps = [
            f"{step.normalizer}: {step.before} -> {step.after}"
            for step in trace.steps
        ] or ["未触发中文对抗归一化"]
        rule_detections = self.rule_filter.detect(normalized)
        semantic_scores = self.semantic_classifier.predict_scores(normalized)
        semantic_detections = self.semantic_classifier.detect(normalized)
        detections = self._deduplicate_detections([*rule_detections, *semantic_detections])

        score = max((d.score for d in detections), default=0)
        primary = max(detections, key=lambda item: item.score, default=None)
        matches = [match for detection in detections for match in detection.matches]

        block_threshold = int(self.config["risk"].get("block_threshold", 80))
        sanitize_threshold = int(self.config["risk"].get("sanitize_threshold", 40))
        action = "pass"
        sanitized = None
        if score >= block_threshold:
            action = "block"
        elif score >= sanitize_threshold:
            action = "sanitize"
            sanitized = self.sanitizer.sanitize(normalized, matches)
            if not sanitized or sanitized == normalized:
                rewrite = self.rewriter.rewrite(
                    text,
                    primary.category if primary else "unknown",
                    matches,
                )
                sanitized = rewrite["rewrite_text"]
            if not sanitized or sanitized in {text, normalized}:
                action = "block"
                sanitized = None

        return {
            "stage": stage,
            "original_text": text,
            "normalized_text": normalized,
            "normalization_steps": normalization_steps,
            "action": action,
            "risk_score": score,
            "risk_level": self._risk_level(score),
            "risk_category": primary.category if primary else "normal",
            "risk_categories": sorted({d.category for d in detections}) or ["normal"],
            "matches": matches,
            "sanitized_text": sanitized,
            "semantic_scores": semantic_scores,
            "semantic_category": max(semantic_scores, key=semantic_scores.get),
            "semantic_score": max(semantic_scores.values()),
            "semantic_applied": True,
            "detections": [d.__dict__ for d in detections],
        }

    def _risk_level(self, score: int) -> str:
        if score >= int(self.config["risk"].get("block_threshold", 80)):
            return "high"
        if score >= int(self.config["risk"].get("sanitize_threshold", 40)):
            return "medium"
        if score > 0:
            return "low"
        return "none"

    def stats(self) -> dict:
        stats = self.logger.stats()
        semantic_status = self.semantic_classifier.status()
        stats["semantic_classifier"] = semantic_status
        stats["model_loaded"] = semantic_status.get("loaded", False)
        stats["model_error"] = semantic_status.get("error")
        return stats

    @staticmethod
    def _deduplicate_detections(detections: list) -> list:
        unique = []
        seen = set()
        for detection in detections:
            key = (
                detection.category,
                detection.source,
                tuple(detection.matches),
            )
            if key not in seen:
                seen.add(key)
                unique.append(detection)
        return unique
