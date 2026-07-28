from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from safechat_guard.logger import EventLogger, StatisticsValidationError


def summary(timestamp: str, **changes):
    event = {
        "stage": "request_summary",
        "timestamp": timestamp,
        "input_action": "pass",
        "output_action": "pass",
        "final_action": "pass",
        "final_allowed": True,
        "category": "normal",
        "fallback_used": False,
        "model_forwarded": True,
    }
    event.update(changes)
    return event


def write_events(path, events):
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def test_empty_log_returns_request_level_zero_state(tmp_path):
    stats = EventLogger(str(tmp_path / "events.jsonl")).daily_stats()
    assert stats["source"] == "request_summary"
    assert stats["request_count"] == stats["violation_count"] == 0
    assert stats["category_distribution"] == {}


def test_counts_pass_sanitize_block_and_request_semantics(tmp_path):
    path = tmp_path / "events.jsonl"
    write_events(
        path,
        [
            {"stage": "input", "action": "block"},
            summary("2026-07-20T01:00:00+00:00"),
            summary(
                "2026-07-20T02:00:00+00:00",
                input_action="sanitize",
                final_action="sanitize",
                category="ad",
            ),
            summary(
                "2026-07-20T03:00:00+00:00",
                input_action="block",
                output_action="not_run",
                final_action="block",
                final_allowed=False,
                category="violence",
                model_forwarded=False,
            ),
        ],
    )
    stats = EventLogger(str(path)).daily_stats(timezone_name="UTC")
    assert stats["request_count"] == 3
    assert stats["pass_count"] == stats["sanitize_count"] == stats["block_count"] == 1
    assert stats["violation_count"] == 2
    assert stats["input_block_count"] == 1
    assert stats["category_distribution"] == {"ad": 1, "violence": 1}


def test_output_block_fallback_and_model_forwarded_are_separate(tmp_path):
    path = tmp_path / "events.jsonl"
    write_events(
        path,
        [
            summary(
                "2026-07-20T03:00:00+00:00",
                output_action="block",
                final_action="block",
                final_allowed=False,
                category="porn",
                fallback_used=True,
            ),
            summary(
                "2026-07-20T04:00:00+00:00",
                model_forwarded=False,
                fallback_used=True,
            ),
        ],
    )
    stats = EventLogger(str(path)).daily_stats(timezone_name="UTC")
    assert stats["output_block_count"] == 1
    assert stats["fallback_count"] == 2
    assert stats["model_forwarded_count"] == 1


def test_timezone_changes_natural_day_boundary(tmp_path):
    path = tmp_path / "events.jsonl"
    write_events(
        path,
        [
            summary(
                "2026-07-20T16:30:00+00:00",
                final_action="block",
                category="sensitive",
            )
        ],
    )
    logger = EventLogger(str(path))
    utc = logger.daily_stats(timezone_name="UTC")
    shanghai = logger.daily_stats(timezone_name="Asia/Shanghai")
    assert utc["daily_violation_counts"] == {"2026-07-20": 1}
    assert shanghai["daily_violation_counts"] == {"2026-07-21": 1}


def test_date_range_includes_zero_days_and_filters(tmp_path):
    path = tmp_path / "events.jsonl"
    write_events(
        path,
        [
            summary(
                "2026-07-21T01:00:00+00:00",
                final_action="sanitize",
                category="ad",
            )
        ],
    )
    stats = EventLogger(str(path)).daily_stats(
        start_date="2026-07-20",
        end_date="2026-07-22",
        timezone_name="UTC",
    )
    assert stats["daily_violation_counts"] == {
        "2026-07-20": 0,
        "2026-07-21": 1,
        "2026-07-22": 0,
    }


@pytest.mark.parametrize(
    ("start", "end", "zone"),
    [
        ("bad", None, "UTC"),
        ("2026-07-22", "2026-07-20", "UTC"),
        ("2020-01-01", "2026-01-01", "UTC"),
        (None, None, "Mars/Olympus"),
    ],
)
def test_invalid_statistics_parameters_are_rejected(tmp_path, start, end, zone):
    logger = EventLogger(str(tmp_path / "events.jsonl"))
    with pytest.raises(StatisticsValidationError):
        logger.daily_stats(
            start_date=start, end_date=end, timezone_name=zone
        )


def test_legacy_logs_are_labeled_and_not_counted_as_requests(tmp_path):
    path = tmp_path / "events.jsonl"
    write_events(
        path,
        [
            {"stage": "input", "action": "block", "time": datetime.now(timezone.utc).isoformat()},
            {"stage": "final", "action": "block", "time": datetime.now(timezone.utc).isoformat()},
        ],
    )
    stats = EventLogger(str(path)).daily_stats()
    assert stats["source"] == "legacy_stage_events"
    assert stats["request_count"] == stats["block_count"] == 0
    assert stats["legacy_event_count"] == 2


def test_corrupted_line_is_skipped_with_safe_warning(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(summary("2026-07-20T00:00:00+00:00")) + "\n{broken",
        encoding="utf-8",
    )
    with pytest.warns(RuntimeWarning, match="malformed audit log line"):
        stats = EventLogger(str(path)).daily_stats()
    assert stats["request_count"] == 1
