"""Operational analytics derived exclusively from public audit records."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any


class AnalyticsService:
    @staticmethod
    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        actions: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        trend: Counter[str] = Counter()
        invalid_time_count = 0
        input_high_risk = 0
        output_risk_events = 0
        for record in records:
            action = str(record.get("final_action") or "unknown")
            actions[action] += 1
            category = str(record.get("category") or "normal")
            if category != "normal":
                categories[category] += 1
            input_high_risk += int(
                record.get("input_action") == "block"
                or record.get("risk_level") == "high"
            )
            output_risk_events += int(
                record.get("output_action") in {"sanitize", "block"}
            )
            day = AnalyticsService._day(record.get("time"))
            if day is None:
                invalid_time_count += 1
            else:
                trend[day] += 1
        return {
            "total_requests": len(records),
            "pass_count": actions["pass"],
            "sanitize_count": actions["sanitize"],
            "block_count": actions["block"],
            "input_high_risk_count": input_high_risk,
            "output_risk_event_count": output_risk_events,
            "action_distribution": dict(sorted(actions.items())),
            "category_distribution": dict(sorted(categories.items())),
            "daily_request_counts": dict(sorted(trend.items())),
            "invalid_time_count": invalid_time_count,
        }

    @staticmethod
    def _day(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(normalized).date().isoformat()
        except ValueError:
            return None
