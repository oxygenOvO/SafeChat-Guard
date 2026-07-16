import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_FIELDS = {
    "input",
    "input_text",
    "safe_input",
    "raw_reply",
    "final_reply",
    "reply",
    "original_text",
    "normalized_text",
    "sanitized_text",
    "final_text",
    "sanitized_raw_output",
    "masked_text",
    "rewrite_text",
    "normalization_steps",
    "matches",
    "match",
    "matched_rules",
}


class EventLogger:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        safe_event = self._redact_event(event)
        safe_event = {"time": datetime.now(timezone.utc).isoformat(), **safe_event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe_event, ensure_ascii=False) + "\n")

    @classmethod
    def _redact_event(cls, value: Any, field: str | None = None) -> Any:
        if field in SENSITIVE_FIELDS:
            if value is None:
                return None
            if isinstance(value, list):
                return ["[REDACTED]"] if value else []
            return "[REDACTED]"
        if isinstance(value, dict):
            return {key: cls._redact_event(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_event(item) for item in value]
        return value

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def stats(self) -> dict[str, Any]:
        events = self.read_all()
        category_counter: Counter[str] = Counter()
        detection_category_counter: Counter[str] = Counter()
        level_counter: Counter[str] = Counter()
        action_counter: Counter[str] = Counter()
        stage_counter: Counter[str] = Counter()
        input_action_counter: Counter[str] = Counter()
        output_action_counter: Counter[str] = Counter()
        blocked = 0
        rewritten = 0
        rule_hit_count = 0
        semantic_hit_count = 0
        joint_rule_semantic_hit_count = 0
        input_detection_count = 0
        output_detection_count = 0

        for event in events:
            for result in [event.get("input_filter"), event.get("output_filter"), event.get("result")]:
                if not result:
                    continue
                stage = result.get("stage") or event.get("stage") or "unknown"
                stage_counter[stage] += 1
                action = result.get("action", "unknown")
                action_counter[action] += 1
                if stage == "input":
                    input_action_counter[action] += 1
                elif stage == "output":
                    output_action_counter[action] += 1
                if action == "block" or result.get("blocked"):
                    blocked += 1
                if action in {"sanitize", "rewrite"} or result.get("rewritten"):
                    rewritten += 1

                level = result.get("risk_level", self._level_from_score(result.get("risk_score", 0)))
                level_counter[level] += 1

                categories = result.get("risk_categories")
                if not categories:
                    categories = [d.get("category") for d in result.get("detections", []) if d.get("category")]
                for category in categories or ["normal"]:
                    category_counter[category] += 1

                detections = result.get("detections", [])
                has_rule = False
                has_semantic = False
                for detection in detections:
                    source = str(detection.get("source", ""))
                    category = detection.get("category")
                    if category:
                        detection_category_counter[category] += 1
                    if stage == "input":
                        input_detection_count += 1
                    elif stage == "output":
                        output_detection_count += 1
                    if self._is_rule_source(source):
                        has_rule = True
                        rule_hit_count += 1
                    if self._is_semantic_source(source):
                        has_semantic = True
                        semantic_hit_count += 1
                if has_rule and has_semantic:
                    joint_rule_semantic_hit_count += 1

        return {
            "total_events": len(events),
            "blocked": blocked,
            "rewritten": rewritten,
            "category_counts": dict(category_counter),
            "risk_level_counts": dict(level_counter),
            "action_counts": dict(action_counter),
            "rule_hit_count": rule_hit_count,
            "semantic_hit_count": semantic_hit_count,
            "joint_rule_semantic_hit_count": joint_rule_semantic_hit_count,
            "category_detection_counts": dict(detection_category_counter),
            "stage_counts": dict(stage_counter),
            "input_detection_count": input_detection_count,
            "output_detection_count": output_detection_count,
            "input_action_counts": dict(input_action_counter),
            "output_action_counts": dict(output_action_counter),
        }

    def _level_from_score(self, score: int) -> str:
        if score >= 80:
            return "high"
        if score >= 40:
            return "medium"
        if score > 0:
            return "low"
        return "none"

    @staticmethod
    def _is_rule_source(source: str) -> bool:
        return source in {"keyword", "regex"} or source.startswith("rule")

    @staticmethod
    def _is_semantic_source(source: str) -> bool:
        return source.startswith("semantic")
