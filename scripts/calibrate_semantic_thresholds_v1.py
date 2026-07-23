from __future__ import annotations

import argparse
import hashlib
import itertools
import sys
from pathlib import Path
from typing import Any

try:
    import joblib
except ImportError:
    joblib = None

try:
    from scripts.independent_eval_v1_common import (
        GOLD_FIELDS,
        LABELS,
        make_normalizer,
        read_csv,
        write_json,
    )
except ModuleNotFoundError:
    from independent_eval_v1_common import (
        GOLD_FIELDS,
        LABELS,
        make_normalizer,
        read_csv,
        write_json,
    )

try:
    from safechat_guard.semantic_classifier import (
        DEFAULT_CATEGORY_THRESHOLDS,
        DEFAULT_MIN_MARGIN,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from safechat_guard.semantic_classifier import (
        DEFAULT_CATEGORY_THRESHOLDS,
        DEFAULT_MIN_MARGIN,
    )


RISK_LABELS = ("ad", "porn", "violence", "sensitive")
THRESHOLD_GRID = tuple(round(0.20 + 0.05 * index, 2) for index in range(11))
MARGIN_GRID = tuple(round(0.05 * index, 2) for index in range(6))
MAX_NORMAL_FALSE_POSITIVE_RATE = 0.10


def load_calibration_gold(path: Path) -> list[dict[str, str]]:
    """Return only the frozen calibration partition; test is never selectable."""
    rows = read_csv(path, GOLD_FIELDS)
    calibration_rows = [
        row for row in rows if row["evaluation_split"] == "calibration"
    ]
    if not calibration_rows:
        raise ValueError("gold contains no calibration rows")
    if any(row["review_status"] != "verified" for row in calibration_rows):
        raise ValueError("calibration gold contains non-verified rows")
    if any(row["label"] not in LABELS for row in calibration_rows):
        raise ValueError("calibration gold contains unsupported labels")
    return calibration_rows


def probability_records(
    rows: list[dict[str, str]],
    model,
    normalizer,
) -> list[dict[str, Any]]:
    normalized_texts = [normalizer.normalize(row["text"]) for row in rows]
    probabilities = model.predict_proba(normalized_texts)
    classes = [str(item) for item in model.classes_]
    if set(classes) != set(LABELS):
        raise ValueError(f"semantic model classes do not match gold labels: {classes}")

    records = []
    for row, values in zip(rows, probabilities, strict=True):
        by_label = {
            label: float(probability)
            for label, probability in zip(classes, values, strict=True)
        }
        ranked = sorted(by_label.items(), key=lambda item: item[1], reverse=True)
        top_label, top_probability = ranked[0]
        records.append(
            {
                "sample_id": row["sample_id"],
                "true_label": row["label"],
                "top_label": top_label,
                "top_probability": top_probability,
                "normal_probability": by_label["normal"],
                "ranked_probabilities": ranked,
            }
        )
    return records


def predictions_for_configuration(
    records: list[dict[str, Any]],
    category_thresholds: dict[str, float],
    min_margin: float,
) -> list[str]:
    predictions = []
    for record in records:
        label = record["top_label"]
        probability = record["top_probability"]
        margin = probability - record["normal_probability"]
        if (
            label == "normal"
            or probability < category_thresholds[label]
            or margin < min_margin
        ):
            predictions.append("normal")
        else:
            predictions.append(label)
    return predictions


def legacy_predictions(records: list[dict[str, Any]]) -> list[str]:
    """Reproduce the removed normal-to-second-risk fallback for comparison."""
    predictions = []
    for record in records:
        ranked = record["ranked_probabilities"]
        top_label, top_probability = ranked[0]
        if top_probability < 0.15:
            predictions.append("normal")
            continue
        if top_label != "normal":
            predictions.append(top_label)
            continue
        second_label, second_probability = (
            ranked[1] if len(ranked) > 1 else (None, 0.0)
        )
        if (
            top_probability < 0.6
            and second_label is not None
            and second_label != "normal"
            and second_probability > 0.15
        ):
            predictions.append(second_label)
        else:
            predictions.append("normal")
    return predictions


def classification_metrics(
    true_labels: list[str],
    predicted_labels: list[str],
) -> dict[str, Any]:
    sample_count = len(true_labels)
    correct = sum(
        actual == predicted
        for actual, predicted in zip(true_labels, predicted_labels, strict=True)
    )
    per_class = {}
    f1_values = []
    for label in LABELS:
        true_positive = sum(
            actual == label and predicted == label
            for actual, predicted in zip(
                true_labels, predicted_labels, strict=True
            )
        )
        false_positive = sum(
            actual != label and predicted == label
            for actual, predicted in zip(
                true_labels, predicted_labels, strict=True
            )
        )
        false_negative = sum(
            actual == label and predicted != label
            for actual, predicted in zip(
                true_labels, predicted_labels, strict=True
            )
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        support = sum(actual == label for actual in true_labels)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        f1_values.append(f1)

    normal_total = sum(label == "normal" for label in true_labels)
    normal_false_positive_count = sum(
        actual == "normal" and predicted != "normal"
        for actual, predicted in zip(true_labels, predicted_labels, strict=True)
    )
    risk_total = sum(label != "normal" for label in true_labels)
    risk_hits = sum(
        actual != "normal" and predicted == actual
        for actual, predicted in zip(true_labels, predicted_labels, strict=True)
    )
    return {
        "sample_count": sample_count,
        "accuracy": correct / sample_count if sample_count else 0.0,
        "macro_f1": sum(f1_values) / len(LABELS),
        "normal_false_positive_count": normal_false_positive_count,
        "normal_false_positive_rate": (
            normal_false_positive_count / normal_total if normal_total else 0.0
        ),
        "risk_recall": risk_hits / risk_total if risk_total else 0.0,
        "predicted_label_counts": {
            label: predicted_labels.count(label) for label in LABELS
        },
        "per_class": per_class,
    }


def calibrate_probability_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    true_labels = [record["true_label"] for record in records]
    best = None
    evaluated = 0
    feasible = 0

    for threshold_values in itertools.product(
        THRESHOLD_GRID, repeat=len(RISK_LABELS)
    ):
        thresholds = dict(zip(RISK_LABELS, threshold_values, strict=True))
        distance_from_defaults = sum(
            abs(thresholds[label] - DEFAULT_CATEGORY_THRESHOLDS[label])
            for label in RISK_LABELS
        )
        for margin in MARGIN_GRID:
            predictions = predictions_for_configuration(
                records, thresholds, margin
            )
            metrics = classification_metrics(true_labels, predictions)
            evaluated += 1
            if (
                metrics["normal_false_positive_rate"]
                > MAX_NORMAL_FALSE_POSITIVE_RATE
            ):
                continue
            feasible += 1
            selection_key = (
                metrics["macro_f1"],
                metrics["accuracy"],
                -metrics["normal_false_positive_rate"],
                metrics["risk_recall"],
                -distance_from_defaults,
                -margin,
                tuple(-thresholds[label] for label in RISK_LABELS),
            )
            if best is None or selection_key > best["selection_key"]:
                best = {
                    "selection_key": selection_key,
                    "category_thresholds": thresholds,
                    "min_margin": margin,
                    "metrics": metrics,
                }

    if best is None:
        raise RuntimeError(
            "no threshold configuration satisfies normal_false_positive_rate <= 0.10"
        )
    best.pop("selection_key")
    return {
        "evaluated_configuration_count": evaluated,
        "feasible_configuration_count": feasible,
        "selected_configuration": best,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_calibration(
    project_root: Path,
    gold_path: Path,
    model_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if joblib is None:
        raise RuntimeError("model dependency missing: joblib")
    project_root = project_root.resolve()
    rows = load_calibration_gold(gold_path)
    model = joblib.load(model_path)
    records = probability_records(rows, model, make_normalizer(project_root))

    result = calibrate_probability_records(records)
    true_labels = [record["true_label"] for record in records]
    legacy_metrics = classification_metrics(
        true_labels, legacy_predictions(records)
    )
    default_metrics = classification_metrics(
        true_labels,
        predictions_for_configuration(
            records,
            dict(DEFAULT_CATEGORY_THRESHOLDS),
            DEFAULT_MIN_MARGIN,
        ),
    )
    sample_id_payload = "\n".join(
        sorted(row["sample_id"] for row in rows)
    )
    report = {
        "schema_version": 1,
        "evaluation_scope": "single_review_independent_gold_v1_calibration",
        "review_provenance": {
            "human_review_status": "single_review",
            "ai_assisted_organization": True,
            "second_independent_review": "pending",
        },
        "evaluation_split": "calibration",
        "test_split_used": False,
        "sample_count": len(rows),
        "calibration_sample_id_sha256": hashlib.sha256(
            sample_id_payload.encode("utf-8")
        ).hexdigest(),
        "gold_path": str(gold_path.resolve()),
        "model_path": str(model_path.resolve()),
        "model_sha256": _sha256_file(model_path),
        "constraint": {
            "metric": "normal_false_positive_rate",
            "operator": "<=",
            "value": MAX_NORMAL_FALSE_POSITIVE_RATE,
        },
        "optimization_metric": "macro_f1",
        "tie_breakers": [
            "accuracy",
            "lower_normal_false_positive_rate",
            "risk_recall",
            "distance_to_default_thresholds",
            "lower_margin",
            "deterministic_threshold_order",
        ],
        "search_space": {
            "category_thresholds": {
                label: list(THRESHOLD_GRID) for label in RISK_LABELS
            },
            "min_margin": list(MARGIN_GRID),
        },
        "default_configuration": {
            "category_thresholds": dict(DEFAULT_CATEGORY_THRESHOLDS),
            "min_margin": DEFAULT_MIN_MARGIN,
            "metrics": default_metrics,
        },
        "removed_legacy_behavior": {
            "description": (
                "normal最高时回退到第二风险类别，且风险类别仅要求概率不低于0.15"
            ),
            "metrics": legacy_metrics,
        },
        **result,
        "action_interpretation": {
            "semantic_model_capability": (
                "五分类模型只预测类别，不能区分同一类别中的sanitize与block"
            ),
            "block_routing_dependency": (
                "block仍依赖规则命中、高危意图证据或后续严重度模型"
            ),
            "action_score_thresholds_tuned": False,
        },
    }
    write_json(output_path, report)
    return report


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Calibrate semantic risk thresholds on Gold V1 calibration only."
    )
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--gold",
        type=Path,
        default=project_root / "data/evaluation/semantic_gold_v1.csv",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=project_root / "models/semantic_model_v2.joblib",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            project_root
            / "reports/system_eval_v1/semantic_threshold_calibration.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_calibration(
            args.project_root,
            args.gold.resolve(),
            args.model_path.resolve(),
            args.output.resolve(),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    selected = report["selected_configuration"]
    print(
        "semantic threshold calibration complete: "
        f"samples={report['sample_count']}, "
        f"macro_f1={selected['metrics']['macro_f1']:.4f}, "
        f"normal_fpr={selected['metrics']['normal_false_positive_rate']:.4f}, "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
