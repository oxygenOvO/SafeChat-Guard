from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

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


MODES = ("rule_only", "semantic_only", "combined")


def load_gold(path: Path, evaluation_split: str = "test") -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(
            "人工审核尚未完成：semantic_gold_v1.csv 不存在；"
            "评估脚本不会回退使用训练数据或旧评估集"
        )
    rows = read_csv(path, GOLD_FIELDS)
    selected = [row for row in rows if row["evaluation_split"] == evaluation_split]
    if not selected:
        raise ValueError(f"gold contains no rows for evaluation_split={evaluation_split}")
    if any(row["review_status"] != "verified" for row in selected):
        raise ValueError("gold contains non-verified rows")
    return selected


def _default_detectors(
    project_root: Path,
    mode: str,
    model_path: Path | None,
):
    rule_detector = None
    semantic_detector = None
    if mode in {"rule_only", "combined"}:
        from safechat_guard.rule_filter import RuleFilter

        rule_detector = RuleFilter(
            str(project_root / "data/lexicons"),
            str(project_root / "data/rules/regex_rules.json"),
        )
    if mode in {"semantic_only", "combined"}:
        from safechat_guard.semantic_classifier import SemanticClassifier

        semantic_detector = SemanticClassifier(
            model_path=str(model_path or project_root / "models/semantic_model_v2.joblib")
        )
        if not semantic_detector.status()["loaded"]:
            raise RuntimeError(
                "semantic model is unavailable: "
                f"{semantic_detector.status()['error']}"
            )
    return rule_detector, semantic_detector


def _prediction(
    text: str,
    mode: str,
    normalizer,
    rule_detector,
    semantic_detector,
    sanitize_threshold: int,
    block_threshold: int,
) -> dict[str, Any]:
    normalized = normalizer.normalize(text)
    detections = []
    if mode in {"rule_only", "combined"}:
        detections.extend(rule_detector.detect(normalized))
    if mode in {"semantic_only", "combined"}:
        detections.extend(semantic_detector.detect(normalized))
    detections.sort(key=lambda item: (-item.score, item.category, item.source))
    score = max((item.score for item in detections), default=0)
    predicted_label = detections[0].category if detections else "normal"
    predicted_action = (
        "block" if score >= block_threshold
        else "sanitize" if score >= sanitize_threshold
        else "pass"
    )
    return {
        "normalized_text": normalized,
        "predicted_label": predicted_label,
        "predicted_action": predicted_action,
        "risk_score": score,
        "detections": [item.__dict__ for item in detections],
    }


def evaluate_rows(
    rows: list[dict[str, str]],
    mode: str,
    project_root: Path,
    model_path: Path | None = None,
    rule_detector=None,
    semantic_detector=None,
    sanitize_threshold: int = 40,
    block_threshold: int = 80,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    project_root = project_root.resolve()
    normalizer = make_normalizer(project_root)
    if rule_detector is None and semantic_detector is None:
        rule_detector, semantic_detector = _default_detectors(project_root, mode, model_path)
    if mode in {"rule_only", "combined"} and rule_detector is None:
        raise ValueError(f"{mode} requires a rule detector")
    if mode in {"semantic_only", "combined"} and semantic_detector is None:
        raise ValueError(f"{mode} requires a semantic detector")

    predictions = [
        _prediction(
            row["text"],
            mode,
            normalizer,
            rule_detector,
            semantic_detector,
            sanitize_threshold,
            block_threshold,
        )
        for row in rows
    ]
    true_labels = [row["label"] for row in rows]
    predicted_labels = [item["predicted_label"] for item in predictions]
    true_actions = [row["expected_action"] for row in rows]
    predicted_actions = [item["predicted_action"] for item in predictions]
    precision, recall, f1, support = precision_recall_fscore_support(
        true_labels,
        predicted_labels,
        labels=list(LABELS),
        zero_division=0,
    )
    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        true_labels,
        predicted_labels,
        average="macro",
        labels=list(LABELS),
        zero_division=0,
    )
    matrix = confusion_matrix(true_labels, predicted_labels, labels=list(LABELS))
    normal_total = sum(label == "normal" for label in true_labels)
    normal_false_positives = sum(
        actual == "normal" and predicted != "normal"
        for actual, predicted in zip(true_labels, predicted_labels)
    )
    block_total = sum(action == "block" for action in true_actions)
    block_hits = sum(
        actual == "block" and predicted == "block"
        for actual, predicted in zip(true_actions, predicted_actions)
    )
    sanitize_total = sum(action == "sanitize" for action in true_actions)
    sanitize_hits = sum(
        actual == "sanitize" and predicted == "sanitize"
        for actual, predicted in zip(true_actions, predicted_actions)
    )
    return {
        "schema_version": 1,
        "evaluation_scope": "independent_human_reviewed_gold_v1",
        "mode": mode,
        "sample_count": len(rows),
        "accuracy": float(accuracy_score(true_labels, predicted_labels)),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "macro_f1": float(macro_f1),
        "normal_false_positive_rate": (
            normal_false_positives / normal_total if normal_total else 0.0
        ),
        "high_risk_block_recall": block_hits / block_total if block_total else 0.0,
        "sanitize_routing_recall": (
            sanitize_hits / sanitize_total if sanitize_total else 0.0
        ),
        "action_accuracy": float(accuracy_score(true_actions, predicted_actions)),
        "per_class": {
            label: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(support[index]),
            }
            for index, label in enumerate(LABELS)
        },
        "confusion_matrix": {
            "labels": list(LABELS),
            "values": matrix.tolist(),
        },
        "thresholds": {
            "sanitize": sanitize_threshold,
            "block": block_threshold,
        },
        "predictions": [
            {
                "sample_id": row["sample_id"],
                "true_label": row["label"],
                "expected_action": row["expected_action"],
                **prediction,
            }
            for row, prediction in zip(rows, predictions)
        ],
    }


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Evaluate SafeChat-Guard on independent gold V1.")
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument(
        "--gold",
        type=Path,
        default=project_root / "data/evaluation/semantic_gold_v1.csv",
    )
    parser.add_argument("--evaluation-split", choices=("calibration", "test"), default="test")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows = load_gold(args.gold, args.evaluation_split)
        metrics = evaluate_rows(rows, args.mode, args.project_root, args.model_path)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output = args.output or (
        args.project_root / f"reports/system_eval_v1/{args.mode}_{args.evaluation_split}_metrics.json"
    )
    write_json(output, metrics)
    print(f"system evaluation complete: mode={args.mode}, samples={len(rows)}, output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
