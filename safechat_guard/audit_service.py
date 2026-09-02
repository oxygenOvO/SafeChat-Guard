"""Privacy-preserving read model for SafeChat audit events."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .logger import EventLogger


AUDIT_EXPORT_FIELDS = (
    "time",
    "request_id",
    "provider",
    "model",
    "category",
    "risk_level",
    "risk_score",
    "input_action",
    "output_action",
    "final_action",
    "model_forwarded",
    "latency_ms",
)


class AuditService:
    def __init__(self, logger: EventLogger) -> None:
        self.logger = logger

    def records(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        actions: Iterable[str] | None = None,
        categories: Iterable[str] | None = None,
        providers: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        action_filter = set(actions or ())
        category_filter = set(categories or ())
        provider_filter = set(providers or ())
        rows = []
        for event in self.logger.read_all():
            if event.get("stage") != "request_summary":
                continue
            row = self._public_record(event)
            event_date = self._record_date(row["time"])
            if start_date is not None and (event_date is None or event_date < start_date):
                continue
            if end_date is not None and (event_date is None or event_date > end_date):
                continue
            if action_filter and row["final_action"] not in action_filter:
                continue
            if category_filter and row["category"] not in category_filter:
                continue
            if provider_filter and row["provider"] not in provider_filter:
                continue
            rows.append(row)
        return sorted(rows, key=lambda item: item["time"], reverse=True)

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        return self.records()[: max(0, int(limit))]

    @staticmethod
    def to_csv(records: list[dict[str, Any]]) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=AUDIT_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in AUDIT_EXPORT_FIELDS})
        return buffer.getvalue().encode("utf-8-sig")

    @staticmethod
    def _public_record(event: dict[str, Any]) -> dict[str, Any]:
        event_time = event.get("timestamp") or event.get("time") or "unavailable"
        return {
            "time": str(event_time),
            "request_id": str(event.get("request_id") or "unavailable"),
            "provider": str(event.get("provider") or "unknown"),
            "model": str(event.get("model") or "unknown"),
            "category": str(event.get("category") or "normal"),
            "risk_level": str(event.get("risk_level") or "none"),
            "risk_score": int(event.get("risk_score") or 0),
            "input_action": str(event.get("input_action") or "unknown"),
            "output_action": str(event.get("output_action") or "not_run"),
            "final_action": str(event.get("final_action") or "unknown"),
            "model_forwarded": event.get("model_forwarded") is True,
            "latency_ms": int(event.get("latency_ms") or 0),
        }

    @staticmethod
    def _record_date(value: str) -> date | None:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().date()
