from __future__ import annotations

import csv
import json

import pytest

from scripts.evaluate_action_router_v1 import (
    CALIBRATION_ONLY_FILENAME,
    ERROR_FIELDS,
    evaluate_rows,
    load_calibration_rows,
    _validate_calibration_rows,
    resolve_frozen_model_path,
    sha256_file,
    write_outputs,
)


class IdentityNormalizer:
    @staticmethod
    def normalize(text):
        return text


class EmptyDetector:
    @staticmethod
    def detect(_text):
        return []


class MarkerRouter:
    @staticmethod
    def route(original_text, normalized_text, rule_detections, semantic_detections):
        assert original_text == normalized_text
        assert rule_detections == []
        assert semantic_detections == []
        action, category = {
            "ordinary": ("pass", "normal"),
            "mask": ("sanitize", "ad"),
            "deny": ("block", "violence"),
            "miss": ("pass", "normal"),
        }[original_text]
        return {
            "action": action,
            "category": category,
            "risk_level": "high" if action == "block" else "medium",
            "confidence": 0.9,
            "reason_codes": ["SYNTHETIC_TEST_ROUTE"],
            "hard_block": action == "block",
            "risk_score": 90 if action == "block" else 60,
            "matched_rule_ids": [],
            "sanitize_matches": [],
        }


def row(sample_id, text, label, expected_action):
    return {
        "sample_id": sample_id,
        "text": text,
        "label": label,
        "expected_action": expected_action,
    }


def test_evaluator_returns_required_metrics_and_prediction_fields():
    rows = [
        row("normal", "ordinary", "normal", "pass"),
        row("sanitize", "mask", "ad", "sanitize"),
        row("block", "deny", "violence", "block"),
        row("miss", "miss", "porn", "block"),
    ]

    metrics = evaluate_rows(
        rows,
        IdentityNormalizer(),
        EmptyDetector(),
        EmptyDetector(),
        MarkerRouter(),
    )

    assert metrics["sample_count"] == 4
    assert metrics["action_accuracy"] == 0.75
    assert metrics["block_total"] == 2
    assert metrics["block_correct"] == 1
    assert metrics["block_recall"] == 0.5
    assert metrics["sanitize_total"] == 1
    assert metrics["sanitize_correct"] == 1
    assert metrics["sanitize_recall"] == 1.0
    assert metrics["pass_total"] == 1
    assert metrics["normal_false_positive_count"] == 0
    assert metrics["normal_false_positive_rate"] == 0.0
    assert metrics["confusion_matrix"] == {
        "labels": ["pass", "sanitize", "block"],
        "values": [[1, 0, 0], [0, 1, 0], [1, 0, 1]],
    }
    assert set(metrics["predictions"][0]) == {
        "sample_id",
        "true_label",
        "expected_action",
        "predicted_label",
        "predicted_action",
        "risk_level",
        "risk_score",
        "confidence",
        "reason_codes",
        "matched_rule_ids",
        "hard_block",
    }
    assert all("text" not in prediction for prediction in metrics["predictions"])


def test_loader_refuses_test_split_before_reading_file(tmp_path):
    with pytest.raises(ValueError, match="restricted.*calibration"):
        load_calibration_rows(tmp_path / "missing.csv", "test")


def _valid_calibration_rows():
    actions = ["pass"] * 40 + ["sanitize"] * 16 + ["block"] * 24
    return [
        {
            "sample_id": f"cal-{index:03d}",
            "text": f"synthetic calibration row {index}",
            "label": "normal" if action == "pass" else "ad",
            "expected_action": action,
            "review_status": "verified",
            "evaluation_split": "calibration",
        }
        for index, action in enumerate(actions)
    ]


def _write_calibration_file(path, rows):
    fieldnames = [
        "sample_id", "text", "label", "risk_level", "expected_action",
        "scenario", "source_type", "source_reference", "review_status",
        "reviewer", "notes", "evaluation_split",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {**{field: "" for field in fieldnames}, **row_data}
            for row_data in rows
        )


def test_loader_accepts_isolated_verified_calibration_rows(tmp_path):
    path = tmp_path / CALIBRATION_ONLY_FILENAME
    _write_calibration_file(path, _valid_calibration_rows())

    selected = load_calibration_rows(path, "calibration")

    assert len(selected) == 80
    assert {item["sample_id"] for item in selected} == {
        f"cal-{index:03d}" for index in range(80)
    }


def test_loader_refuses_combined_gold_path_before_reading_file(tmp_path):
    combined = tmp_path / "semantic_gold_v1.csv"

    with pytest.raises(ValueError, match="isolated.*combined Gold is forbidden"):
        load_calibration_rows(combined, "calibration")


def test_loader_rejects_non_calibration_row(tmp_path):
    rows = _valid_calibration_rows()
    rows[-1]["evaluation_split"] = "test"
    path = tmp_path / CALIBRATION_ONLY_FILENAME
    _write_calibration_file(path, rows)

    with pytest.raises(ValueError, match="non-calibration rows.*test"):
        load_calibration_rows(path, "calibration")

@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows.pop(), "sample count mismatch.*actual=79.*expected=80"),
        (
            lambda rows: rows[-1].update(sample_id=rows[0]["sample_id"]),
            "sample_id values must be unique.*actual_unique=79",
        ),
        (
            lambda rows: rows[0].update(expected_action="allow"),
            "expected_action contains invalid values.*allow",
        ),
        (
            lambda rows: rows[40].update(expected_action="pass"),
            "action distribution mismatch.*sanitize.*15",
        ),
        (
            lambda rows: rows[0].update(review_status="pending"),
            "review_status mismatch.*actual_non_verified=1",
        ),
    ],
)
def test_calibration_invariants_are_enforced(mutate, message):
    rows = _valid_calibration_rows()
    mutate(rows)

    with pytest.raises(ValueError, match=message):
        _validate_calibration_rows(rows)

def test_model_resolver_prefers_local_worktree_model(tmp_path):
    model = tmp_path / "models/frozen.joblib"
    model.parent.mkdir()
    model.write_bytes(b"synthetic-model")

    resolved = resolve_frozen_model_path(tmp_path, "models/frozen.joblib")

    assert resolved == model.resolve()

def test_outputs_include_json_and_only_action_errors(tmp_path):
    metrics = evaluate_rows(
        [
            row("ok", "ordinary", "normal", "pass"),
            row("wrong", "miss", "porn", "block"),
        ],
        IdentityNormalizer(),
        EmptyDetector(),
        EmptyDetector(),
        MarkerRouter(),
        input_sha256="a" * 64,
    )
    output = tmp_path / "metrics.json"
    errors = tmp_path / "errors.csv"

    write_outputs(metrics, output, errors)

    stored = json.loads(output.read_text(encoding="utf-8"))
    error_rows = list(csv.DictReader(errors.open(encoding="utf-8")))
    assert stored["sample_count"] == 2
    assert stored["input_sha256"] == "a" * 64
    assert len(error_rows) == 1
    assert error_rows[0]["sample_id"] == "wrong"
    assert set(error_rows[0]) == set(ERROR_FIELDS)
    assert "text" not in error_rows[0]


def test_sha256_file_records_exact_input(tmp_path):
    path = tmp_path / CALIBRATION_ONLY_FILENAME
    path.write_bytes(b"isolated-calibration")

    assert sha256_file(path) == "81f7ad69c4328817dfed197524d7dd4873cbadd9d3ce6935c3961f17c9c7ed81"