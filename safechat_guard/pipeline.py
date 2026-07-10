import json

from .llm_client import LLMClientFactory
from .logger import EventLogger
from .normalizer import TextNormalizer
from .output_guard import OutputGuard
from .rule_filter import RuleFilter
from .sanitizer import Sanitizer
from .semantic_classifier import SemanticClassifier


class SafeChatPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.normalizer = TextNormalizer("data/maps/homophone_map.json", "data/maps/emoji_map.json")
        self.rule_filter = RuleFilter("data/lexicons", "data/rules/regex_rules.json")
        self.semantic_classifier = SemanticClassifier()
        self.sanitizer = Sanitizer()
        self.llm = LLMClientFactory.create(config.get("llm", {}))
        self.logger = EventLogger(config.get("logging", {}).get("path", "data/logs/events.jsonl"))
        self.output_guard = OutputGuard(
            block_threshold=int(config["risk"].get("block_threshold", 80)),
            sanitize_threshold=int(config["risk"].get("sanitize_threshold", 40)),
        )

    @classmethod
    def from_config(cls, path: str):
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def handle_chat(self, message: str) -> dict:
        input_result = self._filter_text(message, stage="input")
        if input_result["action"] == "block":
            self.logger.write({"stage": "input", "input": message, "result": input_result})
            return {
                "allowed": False,
                "reply": "Your input was blocked because it contains high-risk unsafe content.",
                "input_filter": input_result,
                "output_filter": None,
            }

        safe_message = input_result.get("sanitized_text") or message
        raw_reply = self.llm.chat(safe_message)
        output_result = self._filter_output(raw_reply)
        final_reply = (
            output_result.get("final_text")
            or output_result.get("sanitized_text")
            or raw_reply
        )

        event = {
            "stage": "chat",
            "input": message,
            "safe_input": safe_message,
            "raw_reply": raw_reply,
            "final_reply": final_reply,
            "risk_categories": output_result.get("risk_categories", []),
            "risk_level": output_result.get("risk_level", "none"),
            "blocked": output_result.get("blocked", False),
            "rewritten": output_result.get("rewritten", False),
            "matched_rules": output_result.get("matched_rules", []),
            "input_filter": input_result,
            "output_filter": output_result,
        }
        self.logger.write(event)
        return {
            "allowed": output_result["action"] != "block",
            "reply": final_reply,
            "input_filter": input_result,
            "output_filter": output_result,
        }

    def _filter_output(self, text: str) -> dict:
        normalized = self.normalizer.normalize(text)
        detections = self.rule_filter.detect(normalized)
        if not detections:
            detections.extend(self.semantic_classifier.detect(normalized))
        return self.output_guard.process(text, normalized, detections)

    def filter_input(self, text: str) -> dict:
        return self._filter_text(text, stage="input")

    def filter_output(self, text: str) -> dict:
        return self._filter_output(text)

    def _filter_text(self, text: str, stage: str) -> dict:
        normalized = self.normalizer.normalize(text)
        detections = self.rule_filter.detect(normalized)
        if not detections:
            detections.extend(self.semantic_classifier.detect(normalized))

        score = max([d.score for d in detections], default=0)
        matches = []
        for detection in detections:
            matches.extend(detection.matches)

        block_threshold = int(self.config["risk"].get("block_threshold", 80))
        sanitize_threshold = int(self.config["risk"].get("sanitize_threshold", 40))
        action = "pass"
        sanitized = None
        if score >= block_threshold:
            action = "block"
        elif score >= sanitize_threshold:
            action = "sanitize"
            sanitized = self.sanitizer.sanitize(normalized, matches)

        return {
            "stage": stage,
            "original_text": text,
            "normalized_text": normalized,
            "action": action,
            "risk_score": score,
            "sanitized_text": sanitized,
            "detections": [d.__dict__ for d in detections],
        }

    def stats(self) -> dict:
        return self.logger.stats()
