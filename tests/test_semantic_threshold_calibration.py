from __future__ import annotations

from pathlib import Path

import scripts.calibrate_semantic_thresholds_v1 as calibration
from scripts.calibrate_semantic_thresholds_v1 import (
    calibrate_probability_records,
    load_calibration_gold,
    probability_records,
)
from scripts.independent_eval_v1_common import GOLD_FIELDS, write_csv


class IdentityNormalizer:
    def normalize(self, text):
        return text


class CalibrationOnlyModel:
    classes_ = ("normal", "ad", "porn", "violence", "sensitive")

    def predict_proba(self, texts):
        assert texts == ["CALIBRATION_ONLY"]
        assert "TEST_MUST_NOT_BE_USED" not in texts
        return [[0.70, 0.10, 0.08, 0.07, 0.05]]


def _gold_row(sample_id: str, text: str, split: str) -> dict[str, str]:
    return {
        "sample_id": sample_id,
        "text": text,
        "label": "normal",
        "risk_level": "none",
        "expected_action": "pass",
        "scenario": "test",
        "source_type": "human_gold",
        "source_reference": "test",
        "review_status": "verified",
        "reviewer": "reviewer_1",
        "notes": "test",
        "evaluation_split": split,
    }


def test_calibration_loader_and_model_input_exclude_test_split(tmp_path):
    gold = tmp_path / "semantic_gold_v1.csv"
    write_csv(
        gold,
        GOLD_FIELDS,
        [
            _gold_row("calibration_1", "CALIBRATION_ONLY", "calibration"),
            _gold_row("test_1", "TEST_MUST_NOT_BE_USED", "test"),
        ],
    )

    rows = load_calibration_gold(gold)
    records = probability_records(rows, CalibrationOnlyModel(), IdentityNormalizer())

    assert [row["sample_id"] for row in rows] == ["calibration_1"]
    assert [record["sample_id"] for record in records] == ["calibration_1"]


def test_threshold_search_respects_normal_false_positive_constraint(monkeypatch):
    monkeypatch.setattr(calibration, "THRESHOLD_GRID", (0.20, 0.55))
    monkeypatch.setattr(calibration, "MARGIN_GRID", (0.0, 0.10))
    records = [
        {
            "sample_id": "normal_top",
            "true_label": "normal",
            "top_label": "normal",
            "top_probability": 0.40,
            "normal_probability": 0.40,
            "ranked_probabilities": [],
        },
        {
            "sample_id": "normal_close_ad",
            "true_label": "normal",
            "top_label": "ad",
            "top_probability": 0.30,
            "normal_probability": 0.29,
            "ranked_probabilities": [],
        },
        {
            "sample_id": "true_ad",
            "true_label": "ad",
            "top_label": "ad",
            "top_probability": 0.70,
            "normal_probability": 0.10,
            "ranked_probabilities": [],
        },
    ]

    result = calibrate_probability_records(records)
    selected = result["selected_configuration"]

    assert result["evaluated_configuration_count"] == 32
    assert selected["metrics"]["normal_false_positive_rate"] == 0.0
    assert selected["metrics"]["normal_false_positive_count"] == 0
    assert selected["metrics"]["macro_f1"] > 0
