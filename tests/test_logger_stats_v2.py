import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from safechat_guard.logger import EventLogger


def test_stats_counts_rule_semantic_joint_and_stages(tmp_path):
    logger = EventLogger(str(tmp_path / "events.jsonl"))
    logger.write(
        {
            "stage": "chat",
            "input_filter": {
                "stage": "input",
                "action": "sanitize",
                "risk_score": 70,
                "risk_categories": ["ad"],
                "detections": [
                    {
                        "category": "ad",
                        "level": "medium",
                        "score": 55,
                        "reason": "rule",
                        "source": "regex",
                        "matches": ["vx"],
                    },
                    {
                        "category": "ad",
                        "level": "medium",
                        "score": 70,
                        "reason": "semantic",
                        "source": "semantic_ml",
                        "matches": ["ad: 70%"],
                    },
                ],
            },
            "output_filter": {
                "stage": "output",
                "action": "pass",
                "risk_score": 0,
                "risk_categories": ["normal"],
                "detections": [],
            },
        }
    )

    stats = logger.stats()

    assert stats["rule_hit_count"] == 1
    assert stats["semantic_hit_count"] == 1
    assert stats["joint_rule_semantic_hit_count"] == 1
    assert stats["category_detection_counts"]["ad"] == 2
    assert stats["input_detection_count"] == 2
    assert stats["output_detection_count"] == 0
    assert stats["input_action_counts"]["sanitize"] == 1
    assert stats["output_action_counts"]["pass"] == 1


def test_concurrent_writes_remain_valid_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger(str(path), max_bytes=1024 * 1024)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: logger.write({"event_id": index}), range(200)))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    records = [json.loads(line) for line in lines]
    assert {record["event_id"] for record in records} == set(range(200))


def test_rotation_keeps_complete_json_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = EventLogger(str(path), max_bytes=250, backup_count=3, retention_days=7)

    for index in range(20):
        logger.write({"event_id": index, "action": "pass"})

    assert (tmp_path / "events.jsonl.1").exists()
    for log_path in tmp_path.glob("events.jsonl*"):
        for line in log_path.read_text(encoding="utf-8").splitlines():
            json.loads(line)


def test_malformed_partial_line_does_not_break_stats(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"event_id": 1}\n{"partial":', encoding="utf-8")
    logger = EventLogger(str(path))

    assert logger.read_all() == [{"event_id": 1}]
    assert logger.stats()["total_events"] == 1


def test_stats_supports_time_window(tmp_path):
    logger = EventLogger(str(tmp_path / "events.jsonl"))
    logger.write({"event_id": 1})

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    future = datetime.now(timezone.utc) + timedelta(minutes=1)

    assert logger.stats(since=past)["total_events"] == 1
    assert logger.stats(since=future)["total_events"] == 0
    assert logger.stats(since=past)["window_start"] == past.isoformat()


def test_retention_prunes_without_rotation_on_write(tmp_path):
    path = tmp_path / "events.jsonl"
    backup = tmp_path / "events.jsonl.1"
    backup.write_text('{"event_id": "old"}\n', encoding="utf-8")
    old = time.time() - 3 * 86400
    os.utime(backup, (old, old))
    logger = EventLogger(str(path), max_bytes=10**9, backup_count=2, retention_days=1)

    logger.write({"event_id": "new"})

    assert not backup.exists()
    assert path.exists()


def test_retention_prunes_without_rotation_on_read(tmp_path):
    path = tmp_path / "events.jsonl"
    backup = tmp_path / "events.jsonl.1"
    backup.write_text('{"event_id": "old"}\n', encoding="utf-8")
    old = time.time() - 3 * 86400
    os.utime(backup, (old, old))
    logger = EventLogger(str(path), max_bytes=10**9, backup_count=2, retention_days=1)

    assert logger.read_all() == []
    assert not backup.exists()
