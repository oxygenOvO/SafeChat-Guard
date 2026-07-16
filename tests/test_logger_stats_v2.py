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
