"""运维统计分析：只消费公开审计记录，绝不接触敏感原文。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any


class AnalyticsService:
    """从 request_summary 审计记录聚合运维统计（管理页"系统总览"数据源）。"""

    @staticmethod
    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        """聚合总量、动作分布、风险类别分布、每日请求趋势与异常时间计数。"""
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
