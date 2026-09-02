from pathlib import Path

from safechat_guard.semantic_classifier import (
    DEFAULT_CATEGORY_THRESHOLDS,
    select_risk_prediction,
)
from safechat_guard.semantic_config import load_semantic_runtime_configuration


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_production_changes_only_violence_threshold_to_25_percent():
    configuration = load_semantic_runtime_configuration(PROJECT_ROOT)

    assert configuration.category_thresholds == {
        "ad": 0.25,
        "porn": 0.25,
        "violence": 0.25,
        "sensitive": 0.65,
    }
    assert DEFAULT_CATEGORY_THRESHOLDS["violence"] == 0.25


def test_violence_above_25_percent_is_selected_even_with_small_normal_margin():
    selected = select_risk_prediction(
        ("normal", "ad", "porn", "sensitive", "violence"),
        (0.24, 0.17, 0.16, 0.17, 0.26),
        {"ad": 0.25, "porn": 0.25, "violence": 0.25, "sensitive": 0.65},
        0.05,
    )

    assert selected == ("violence", 0.26, 0.24)


def test_violence_below_25_percent_is_not_selected():
    selected = select_risk_prediction(
        ("normal", "ad", "porn", "sensitive", "violence"),
        (0.24, 0.17, 0.17, 0.171, 0.249),
        {"ad": 0.25, "porn": 0.25, "violence": 0.25, "sensitive": 0.65},
        0.05,
    )

    assert selected is None


def test_other_categories_keep_existing_margin_gate():
    selected = select_risk_prediction(
        ("normal", "porn"),
        (0.46, 0.54),
        {"porn": 0.25},
        0.10,
    )

    assert selected is None
