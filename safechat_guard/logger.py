import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        event = {"time": datetime.now(timezone.utc).isoformat(), **event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

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
        level_counter: Counter[str] = Counter()
        action_counter: Counter[str] = Counter()
        blocked = 0
        rewritten = 0

        for event in events:
            for result in [event.get("input_filter"), event.get("output_filter"), event.get("result")]:
                if not result:
                    continue
                action = result.get("action", "unknown")
                action_counter[action] += 1
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

        return {
            "total_events": len(events),
            "blocked": blocked,
            "rewritten": rewritten,
            "category_counts": dict(category_counter),
            "risk_level_counts": dict(level_counter),
            "action_counts": dict(action_counter),
        }

    def _level_from_score(self, score: int) -> str:
        if score >= 80:
            return "high"
        if score >= 40:
            return "medium"
        if score > 0:
            return "low"
        return "none"
