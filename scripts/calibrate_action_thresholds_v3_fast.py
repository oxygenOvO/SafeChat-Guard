from __future__ import annotations

from collections import Counter
import itertools
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.calibrate_action_thresholds_v3 import (
    CATEGORIES,
    ActionModelBundleV3,
    metrics,
    precompute,
    read_dev,
    sha256_file,
)


DEV_PATH = ROOT / "data/evaluation/performance_v3_dev.csv"
RISK_PATH = ROOT / "models/risk_model_v3.joblib"
BLOCK_PATH = ROOT / "models/block_model_v3.joblib"
CONFIG_PATH = ROOT / "config/action_thresholds_v3.json"
SEARCH_PATH = ROOT / "reports/performance_v3/dev_threshold_search.json"
METRICS_PATH = ROOT / "reports/performance_v3/dev_metrics.json"
LABELS = ("normal", "ad", "porn", "violence", "sensitive")


def quick_metrics(
    rows,
    risk_threshold: float,
    block_thresholds: dict[str, float],
    evidence_threshold: float,
):
    true_actions = Counter()
    hits = Counter()
    normal_fp = 0
    action_hits = 0
    label_confusion = Counter()
    for row in rows:
        actual_action = row["expected_action"]
        actual_label = row["label"]
        true_actions[actual_action] += 1
        if row["safe"]:
            predicted_action, predicted_label = "pass", "normal"
        elif row["severe"]:
            predicted_action, predicted_label = "block", row["category"]
        elif (
            (
                row["block_probability"] >= block_thresholds[row["category"]]
                and row["evidence_score"] >= 0.58
            )
            or row["evidence_score"] >= evidence_threshold
        ):
            predicted_action, predicted_label = "block", row["category"]
        elif (
            row["risk_probability"] >= risk_threshold
            and row["has_risk_entity"]
        ):
            predicted_action, predicted_label = "sanitize", row["category"]
        else:
            predicted_action, predicted_label = "pass", "normal"
        action_hits += predicted_action == actual_action
        hits[actual_action] += predicted_action == actual_action
        normal_fp += actual_label == "normal" and predicted_action != "pass"
        label_confusion[(actual_label, predicted_label)] += 1

    f1_values = []
    label_hits = 0
    for label in LABELS:
        tp = label_confusion[(label, label)]
        fp = sum(
            label_confusion[(actual, label)]
            for actual in LABELS
            if actual != label
        )
        fn = sum(
            label_confusion[(label, predicted)]
            for predicted in LABELS
            if predicted != label
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1_values.append(
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )
        label_hits += tp
    return {
        "accuracy": label_hits / len(rows),
        "macro_f1": sum(f1_values) / len(f1_values),
        "action_accuracy": action_hits / len(rows),
        "high_risk_block_recall": hits["block"] / true_actions["block"],
        "sanitize_routing_recall": hits["sanitize"] / true_actions["sanitize"],
        "normal_false_positive_rate": normal_fp / true_actions["pass"],
    }


def objective(item):
    metric = item["metrics"]
    feasible = (
        metric["high_risk_block_recall"] >= 0.95
        and metric["normal_false_positive_rate"] <= 0.03
    )
    return (
        int(feasible),
        metric["sanitize_routing_recall"] if feasible
        else metric["high_risk_block_recall"],
        metric["action_accuracy"] if feasible
        else -metric["normal_false_positive_rate"],
        metric["macro_f1"],
        -sum(item["category_block_thresholds"].values()),
        -item["risk_sanitize_threshold"],
    )


def main() -> int:
    rows = read_dev(DEV_PATH)
    risk_hash = sha256_file(RISK_PATH)
    block_hash = sha256_file(BLOCK_PATH)
    models = ActionModelBundleV3(
        RISK_PATH,
        BLOCK_PATH,
        expected_risk_sha256=risk_hash,
        expected_block_sha256=block_hash,
    )
    if not models.loaded:
        raise RuntimeError(models.error)
    prepared = precompute(rows, models)

    risk_values = (0.3, 0.4, 0.5, 0.6, 0.7)
    block_values = (0.3, 0.4, 0.5, 0.6, 0.7)
    evidence_values = (0.7, 0.8, 0.9, 0.95)
    candidates = []
    for risk in risk_values:
        for block_tuple in itertools.product(
            block_values, repeat=len(CATEGORIES)
        ):
            block_thresholds = dict(zip(CATEGORIES, block_tuple))
            for evidence in evidence_values:
                result = quick_metrics(
                    prepared, risk, block_thresholds, evidence
                )
                candidates.append(
                    {
                        "risk_sanitize_threshold": risk,
                        "category_block_thresholds": block_thresholds,
                        "evidence_block_threshold": evidence,
                        "metrics": result,
                    }
                )
    candidates.sort(key=objective, reverse=True)
    best = candidates[0]
    feasible_count = sum(
        item["metrics"]["high_risk_block_recall"] >= 0.95
        and item["metrics"]["normal_false_positive_rate"] <= 0.03
        for item in candidates
    )
    full_metrics = metrics(
        prepared,
        best["risk_sanitize_threshold"],
        best["category_block_thresholds"],
        best["evidence_block_threshold"],
    )
    best = {**best, "metrics": full_metrics}

    config = {
        "schema_version": 1,
        "risk_sanitize_threshold": best["risk_sanitize_threshold"],
        "category_block_thresholds": best["category_block_thresholds"],
        "evidence_block_threshold": best["evidence_block_threshold"],
        "risk_model_path": "models/risk_model_v3.joblib",
        "risk_model_sha256": risk_hash,
        "block_model_path": "models/block_model_v3.joblib",
        "block_model_sha256": block_hash,
        "calibration_split": "dev",
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    SEARCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "calibration_split": "dev",
                "sample_count": len(rows),
                "internal_holdout_used": False,
                "retired_diagnostic_data_used": False,
                "hard_constraints": {
                    "block_recall_minimum": 0.95,
                    "normal_fpr_maximum": 0.03,
                },
                "candidate_count": len(candidates),
                "feasible_candidate_count": feasible_count,
                "selected": best,
                "top_candidates": candidates[:20],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    dev_metrics = {
        "schema_version": 1,
        "evaluation_split": "dev",
        "sample_count": len(rows),
        "thresholds_frozen": True,
        "constraints_met": feasible_count > 0,
        **full_metrics,
    }
    METRICS_PATH.write_text(
        json.dumps(dev_metrics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        "V3 fast dev calibration complete: "
        f"candidates={len(candidates)}, feasible={feasible_count}, "
        f"block_recall={full_metrics['high_risk_block_recall']:.4f}, "
        f"normal_fpr={full_metrics['normal_false_positive_rate']:.4f}, "
        f"sanitize_recall={full_metrics['sanitize_routing_recall']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
