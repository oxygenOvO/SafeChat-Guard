from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import sys
from typing import Any

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safechat_guard.action_models_v3 import ActionModelBundleV3
from safechat_guard.action_router_v3 import (
    CATEGORIES,
    ActionRouterV3,
    RiskEvidenceExtractorV3,
)


LABELS = ("normal", "ad", "porn", "violence", "sensitive")
ACTIONS = ("pass", "sanitize", "block")
REQUIRED_FIELDS = {
    "sample_id", "text", "label", "expected_action", "intent", "context",
    "template_family", "source_type", "split",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_dev(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED_FIELDS <= set(reader.fieldnames or ()):
            raise ValueError("V3 dev dataset is missing required fields")
        rows = [dict(row) for row in reader]
    if not rows or any(row["split"] != "dev" for row in rows):
        raise ValueError("threshold calibration accepts dev split only")
    return rows


def precompute(
    rows: list[dict[str, str]],
    models: ActionModelBundleV3,
) -> list[dict[str, Any]]:
    extractor = RiskEvidenceExtractorV3()
    values = []
    for row in rows:
        text = row["text"]
        evidence = extractor.extract(text)
        scores = models.predict(text)
        category = extractor.infer_category(text, "ad")
        unsafe = ActionRouterV3._unsafe_intent(text, evidence)
        safe = bool(evidence["safe_context"]) and not unsafe
        evidence_score = ActionRouterV3._evidence_score(text, evidence)
        values.append(
            {
                "label": row["label"],
                "expected_action": row["expected_action"],
                "category": category,
                "safe": safe,
                "severe": bool(evidence["severe_direct_evidence"]),
                "risk_probability": scores.risk_probability,
                "block_probability": scores.block_probability,
                "evidence_score": evidence_score,
                "has_risk_entity": bool(evidence["risk_entity"]),
            }
        )
    return values


def predict(
    row: dict[str, Any],
    risk_threshold: float,
    block_thresholds: dict[str, float],
    evidence_threshold: float,
) -> tuple[str, str]:
    if row["safe"]:
        return "pass", "normal"
    if row["severe"]:
        return "block", row["category"]
    if (
        (
            row["block_probability"] >= block_thresholds[row["category"]]
            and row["evidence_score"] >= 0.58
        )
        or row["evidence_score"] >= evidence_threshold
    ):
        return "block", row["category"]
    if row["risk_probability"] >= risk_threshold and row["has_risk_entity"]:
        return "sanitize", row["category"]
    return "pass", "normal"


def metrics(
    rows: list[dict[str, Any]],
    risk_threshold: float,
    block_thresholds: dict[str, float],
    evidence_threshold: float,
) -> dict[str, Any]:
    outputs = [
        predict(row, risk_threshold, block_thresholds, evidence_threshold)
        for row in rows
    ]
    predicted_actions = [value[0] for value in outputs]
    predicted_labels = [value[1] for value in outputs]
    true_actions = [row["expected_action"] for row in rows]
    true_labels = [row["label"] for row in rows]
    block_total = sum(value == "block" for value in true_actions)
    sanitize_total = sum(value == "sanitize" for value in true_actions)
    normal_total = sum(value == "normal" for value in true_labels)
    block_recall = sum(
        actual == "block" and predicted == "block"
        for actual, predicted in zip(true_actions, predicted_actions)
    ) / block_total
    sanitize_recall = sum(
        actual == "sanitize" and predicted == "sanitize"
        for actual, predicted in zip(true_actions, predicted_actions)
    ) / sanitize_total
    normal_fpr = sum(
        actual == "normal" and predicted != "pass"
        for actual, predicted in zip(true_labels, predicted_actions)
    ) / normal_total
    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        true_labels,
        predicted_labels,
        labels=list(LABELS),
        average="macro",
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(true_labels, predicted_labels)),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "macro_f1": float(macro_f1),
        "action_accuracy": float(
            accuracy_score(true_actions, predicted_actions)
        ),
        "high_risk_block_recall": block_recall,
        "sanitize_routing_recall": sanitize_recall,
        "normal_false_positive_rate": normal_fpr,
        "confusion_matrix": {
            "labels": list(LABELS),
            "values": confusion_matrix(
                true_labels, predicted_labels, labels=list(LABELS)
            ).tolist(),
        },
        "action_confusion_matrix": {
            "labels": list(ACTIONS),
            "values": confusion_matrix(
                true_actions, predicted_actions, labels=list(ACTIONS)
            ).tolist(),
        },
    }


def objective(item: dict[str, Any]) -> tuple:
    metric = item["metrics"]
    feasible = (
        metric["high_risk_block_recall"] >= 0.95
        and metric["normal_false_positive_rate"] <= 0.03
    )
    return (
        int(feasible),
        metric["sanitize_routing_recall"] if feasible else metric["high_risk_block_recall"],
        metric["action_accuracy"] if feasible else -metric["normal_false_positive_rate"],
        metric["macro_f1"],
        -sum(item["category_block_thresholds"].values()),
        -item["risk_sanitize_threshold"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate V3 action thresholds.")
    parser.add_argument(
        "--dev",
        type=Path,
        default=ROOT / "data/evaluation/performance_v3_dev.csv",
    )
    parser.add_argument(
        "--risk-model",
        type=Path,
        default=ROOT / "models/risk_model_v3.joblib",
    )
    parser.add_argument(
        "--block-model",
        type=Path,
        default=ROOT / "models/block_model_v3.joblib",
    )
    parser.add_argument(
        "--config-output",
        type=Path,
        default=ROOT / "config/action_thresholds_v3.json",
    )
    parser.add_argument(
        "--search-output",
        type=Path,
        default=ROOT / "reports/performance_v3/dev_threshold_search.json",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=ROOT / "reports/performance_v3/dev_metrics.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_dev(args.dev)
    risk_hash = sha256_file(args.risk_model)
    block_hash = sha256_file(args.block_model)
    models = ActionModelBundleV3(
        args.risk_model,
        args.block_model,
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
    for risk, block_tuple, evidence in itertools.product(
        risk_values,
        itertools.product(block_values, repeat=len(CATEGORIES)),
        evidence_values,
    ):
        block_thresholds = dict(zip(CATEGORIES, block_tuple))
        result = metrics(prepared, risk, block_thresholds, evidence)
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
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    search_report = {
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
    }
    args.search_output.parent.mkdir(parents=True, exist_ok=True)
    args.search_output.write_text(
        json.dumps(search_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dev_metrics = {
        "schema_version": 1,
        "evaluation_split": "dev",
        "sample_count": len(rows),
        "thresholds_frozen": True,
        "constraints_met": feasible_count > 0,
        **best["metrics"],
    }
    args.metrics_output.write_text(
        json.dumps(dev_metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "V3 dev calibration complete: "
        f"candidates={len(candidates)}, feasible={feasible_count}, "
        f"block_recall={dev_metrics['high_risk_block_recall']:.4f}, "
        f"normal_fpr={dev_metrics['normal_false_positive_rate']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
