import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dev_constraints_are_met_before_holdout():
    metrics = json.loads(
        (ROOT / "reports/performance_v3/dev_metrics.json").read_text(
            encoding="utf-8"
        )
    )

    assert metrics["evaluation_split"] == "dev"
    assert metrics["sample_count"] == 270
    assert metrics["thresholds_frozen"] is True
    assert metrics["high_risk_block_recall"] >= 0.95
    assert metrics["normal_false_positive_rate"] <= 0.03
    assert metrics["sanitize_routing_recall"] >= 0.85


def test_training_and_calibration_provenance_excludes_holdout_and_retired_data():
    training = json.loads(
        (ROOT / "reports/performance_v3/training_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    search = json.loads(
        (ROOT / "reports/performance_v3/dev_threshold_search.json").read_text(
            encoding="utf-8"
        )
    )

    assert training["training_split"] == "train"
    assert training["internal_holdout_used"] is False
    assert training["retired_diagnostic_data_used"] is False
    assert search["calibration_split"] == "dev"
    assert search["internal_holdout_used"] is False
    assert search["retired_diagnostic_data_used"] is False


def test_completed_holdout_is_frozen_and_cannot_be_tuned_or_rerun():
    metrics = json.loads(
        (ROOT / "reports/performance_v3/internal_holdout_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    execution_manifest = (
        ROOT / "reports/performance_v3/holdout_execution_manifest.txt"
    ).read_text(encoding="utf-8")
    amendment = (
        ROOT / "reports/performance_v3/holdout_execution_manifest_amendment.txt"
    ).read_text(encoding="utf-8")

    assert metrics["formal_evaluation"] is True
    assert metrics["holdout_run_count"] == 1
    assert metrics["post_holdout_tuning_allowed"] is False
    assert "holdout_run_count=1" in execution_manifest
    assert "post_holdout_tuning_allowed=false" in execution_manifest
    assert "execution_count=1" in amendment
    assert "holdout_run_count=1" in amendment
    assert "post_holdout_tuning=false" in amendment
    assert "rerun=false" in amendment
