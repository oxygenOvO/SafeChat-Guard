import json
import threading
import time
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
    def __init__(
        self,
        path: str,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 5,
        retention_days: int = 7,
    ):
        self.path = Path(path)
        self.max_bytes = max(0, int(max_bytes))
        self.backup_count = max(0, int(backup_count))
        self.retention_days = max(0, int(retention_days))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        safe_event = self._redact_event(event)
        safe_event = {"time": datetime.now(timezone.utc).isoformat(), **safe_event}
        line = json.dumps(safe_event, ensure_ascii=False) + "\n"
        with self._lock:
            self._prune_expired()
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self.path.open("a", encoding="utf-8") as file:
                file.write(line)
                file.flush()

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

    def read_all(self, since: datetime | None = None) -> list[dict[str, Any]]:
        events = []
        with self._lock:
            self._prune_expired()
            for path in self._retained_log_paths():
                if not path.exists():
                    continue
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since is not None:
                        try:
                            event_time = datetime.fromisoformat(event["time"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if event_time.tzinfo is None:
                            event_time = event_time.replace(tzinfo=timezone.utc)
                        if event_time < since:
                            continue
                    events.append(event)
        return events

    def stats(self, since: datetime | None = None) -> dict[str, Any]:
        events = self.read_all(since=since)
        category_counter: Counter[str] = Counter()
        detection_category_counter: Counter[str] = Counter()
        level_counter: Counter[str] = Counter()
        action_counter: Counter[str] = Counter()
        stage_counter: Counter[str] = Counter()
        input_action_counter: Counter[str] = Counter()
        output_action_counter: Counter[str] = Counter()
        final_action_counter: Counter[str] = Counter()
        blocked = 0
        rewritten = 0
        rule_hit_count = 0
        semantic_hit_count = 0
        joint_rule_semantic_hit_count = 0
        input_detection_count = 0
        output_detection_count = 0

        for event in events:
            if event.get("stage") == "final":
                stage_counter["final"] += 1
                if event.get("action"):
                    final_action_counter[event["action"]] += 1
            results = [
                event.get("input_filter"),
                event.get("output_filter"),
                event.get("result"),
            ]
            for result in results:
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

                level = result.get(
                    "risk_level",
                    self._level_from_score(result.get("risk_score", 0)),
                )
                level_counter[level] += 1

                categories = result.get("risk_categories")
                if not categories:
                    categories = [
                        detection.get("category")
                        for detection in result.get("detections", [])
                        if detection.get("category")
                    ]
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
            "window_start": since.isoformat() if since is not None else None,
            "window_end": datetime.now(timezone.utc).isoformat(),
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
            "final_action_counts": dict(final_action_counter),
        }

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.max_bytes or not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return

        self._prune_expired()
        if self.backup_count == 0:
            self.path.unlink(missing_ok=True)
            return

        oldest = self._backup_path(self.backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self._backup_path(index)
            if source.exists():
                source.replace(self._backup_path(index + 1))
        self.path.replace(self._backup_path(1))

    def _prune_expired(self) -> None:
        if not self.retention_days:
            return
        cutoff = time.time() - self.retention_days * 86400
        for path in self._retained_log_paths(include_current=False):
            if path.exists() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    def _retained_log_paths(self, include_current: bool = True) -> list[Path]:
        backups = [
            self._backup_path(index)
            for index in range(self.backup_count, 0, -1)
        ]
        return [*backups, self.path] if include_current else backups

    @staticmethod
    def _level_from_score(score: int) -> str:
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
