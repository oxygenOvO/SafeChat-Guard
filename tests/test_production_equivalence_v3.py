import hashlib
from pathlib import Path

from scripts.check_production_equivalence_v3 import (
    load_public_cases,
    run_equivalence,
)


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_equivalence_case_inventory_is_exact():
    cases = load_public_cases()

    assert len(cases) == 170
    assert {
        suite: sum(case.suite == suite for case in cases)
        for suite in {
            "manual_adversarial_40",
            "context_boundary_32",
            "generalization_62",
            "safety_negative_36",
        }
    } == {
        "manual_adversarial_40": 40,
        "context_boundary_32": 32,
        "generalization_62": 62,
        "safety_negative_36": 36,
    }


def test_v3_core_and_production_api_are_equivalent_without_fallback():
    summary = run_equivalence()

    assert summary["sample_count"] == 170
    assert summary["action_matches"] == 170
    assert summary["label_matches"] == 170
    assert summary["no_fallback"] == 170
    assert summary["production_completed"] == 170
    assert summary["failed_case_ids"] == []
    assert summary["health"] == {
        "active_filter_version": "v3",
        "v3_enabled": True,
        "v3_ready": True,
        "risk_model_loaded": True,
        "block_model_loaded": True,
        "fallback_active": False,
        "fallback_reason": None,
        "risk_model_sha256": "136b9952869c6662eaa77e65d3a22e3cac3eddfe3f751ffa55bc99fd80845785",
        "block_model_sha256": "412f46781bcba63de8ada1d8781296acdbb25447f303130d0926cff6bd176b21",
        "threshold_config_sha256": sha256_file(
            ROOT / "config/action_thresholds_v3.json"
        ),
    }
