import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reports/performance_v3/public_release_evidence_v3.json"


def load_evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_dev_constraints_are_met_before_holdout():
    dev = load_evidence()["dev_validation"]

    assert dev["evaluation_split"] == "dev"
    assert dev["sample_count"] == 270
    assert dev["thresholds_frozen"] is True
    assert dev["block_recall"] >= 0.95
    assert dev["normal_fpr"] <= 0.03
    assert dev["sanitize_recall"] >= 0.85


def test_training_and_calibration_provenance_excludes_holdout_and_retired_data():
    provenance = load_evidence()["provenance"]

    assert provenance["training_split"] == "train"
    assert provenance["training_sample_count"] == 900
    assert provenance["training_used_holdout"] is False
    assert provenance["training_used_retired_test"] is False
    assert provenance["calibration_split"] == "dev"
    assert provenance["calibration_used_holdout"] is False
    assert provenance["calibration_used_retired_test"] is False


def test_completed_holdout_is_frozen_and_cannot_be_tuned_or_rerun():
    evidence = load_evidence()

    assert evidence["evaluation_scope"] == "single_frozen_internal_holdout_aggregate_only"
    assert evidence["sample_count"] == 330
    assert evidence["block_recall"] >= 0.90
    assert evidence["normal_fpr"] <= 0.05
    assert evidence["sanitize_recall"] >= 0.85
    assert evidence["execution_count"] == 1
    assert evidence["holdout_run_count"] == 1
    assert evidence["post_holdout_tuning"] is False
    assert evidence["holdout_rerun"] is False
    assert evidence["holdout_text_included"] is False
    assert evidence["per_record_predictions_included"] is False


def test_public_release_evidence_matches_delivered_artifact_hashes():
    evidence = load_evidence()

    assert evidence["risk_model_sha256"] == sha256_file(
        ROOT / "models/risk_model_v3.joblib"
    )
    assert evidence["block_model_sha256"] == sha256_file(
        ROOT / "models/block_model_v3.joblib"
    )
    assert evidence["threshold_config_sha256"] == sha256_file(
        ROOT / "config/action_thresholds_v3.json"
    )
    assert evidence["threshold_config_semantic_change"] is False
    assert evidence["line_ending_normalization"] == "CRLF_to_LF"
