from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.independent_eval_v1_common import GOLD_FIELDS, read_csv, write_json
except ModuleNotFoundError:
    from independent_eval_v1_common import GOLD_FIELDS, read_csv, write_json


ACTION_LABELS = ("pass", "sanitize", "block")
CALIBRATION_ONLY_FILENAME = "semantic_gold_v1_calibration.csv"
ERROR_FIELDS = (
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
)


def load_calibration_rows(
    gold_path: Path,
    evaluation_split: str,
) -> list[dict[str, str]]:
    """Load only the explicitly authorized calibration split."""
    if evaluation_split != "calibration":
        raise ValueError(
            "ActionRouter V1 evaluation is restricted to evaluation_split=calibration"
        )
    if gold_path.name != CALIBRATION_ONLY_FILENAME:
        raise ValueError(
            "ActionRouter calibration requires the isolated "
            f"{CALIBRATION_ONLY_FILENAME}; combined Gold is forbidden"
        )
    rows = read_csv(gold_path, GOLD_FIELDS)
    invalid_splits = sorted(
        {row["evaluation_split"] for row in rows} - {"calibration"}
    )
    if invalid_splits:
        raise ValueError(
            "calibration-only file contains non-calibration rows: "
            f"actual={invalid_splits}"
        )
    _validate_calibration_rows(rows)
    return rows


def _validate_calibration_rows(rows: list[dict[str, str]]) -> None:
    expected_count = 80
    actual_count = len(rows)
    if actual_count != expected_count:
        raise ValueError(
            f"calibration sample count mismatch: actual={actual_count}, "
            f"expected={expected_count}"
        )
    sample_ids = [row["sample_id"] for row in rows]
    unique_count = len(set(sample_ids))
    if unique_count != actual_count:
        raise ValueError(
            "calibration sample_id values must be unique: "
            f"actual_unique={unique_count}, expected_unique={actual_count}"
        )
    allowed_actions = set(ACTION_LABELS)
    invalid_actions = sorted(
        {row["expected_action"] for row in rows} - allowed_actions
    )
    if invalid_actions:
        raise ValueError(
            "calibration expected_action contains invalid values: "
            f"actual={invalid_actions}, expected={sorted(allowed_actions)}"
        )
    expected_distribution = {"pass": 40, "sanitize": 16, "block": 24}
    actual_distribution = {
        action: sum(row["expected_action"] == action for row in rows)
        for action in ACTION_LABELS
    }
    if actual_distribution != expected_distribution:
        raise ValueError(
            "calibration action distribution mismatch: "
            f"actual={actual_distribution}, expected={expected_distribution}"
        )
    non_verified = sum(row["review_status"] != "verified" for row in rows)
    if non_verified:
        raise ValueError(
            "calibration review_status mismatch: "
            f"actual_non_verified={non_verified}, expected_non_verified=0"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_components(project_root: Path):
    root = project_root.resolve()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    from safechat_guard.action_router import ActionRouter
    from safechat_guard.normalizer import TextNormalizer
    from safechat_guard.rule_filter import RuleFilter
    from safechat_guard.semantic_config import (
        DEFAULT_PRODUCTION_CONFIG_PATH,
        load_semantic_runtime_configuration,
    )
    from safechat_guard.semantic_classifier import SemanticClassifier

    normalizer = TextNormalizer(
        str(root / "data/maps/homophone_map.json"),
        str(root / "data/maps/emoji_map.json"),
    )
    rule_detector = RuleFilter(
        str(root / "data/lexicons"),
        str(root / "data/rules/regex_rules.json"),
    )
    semantic_configuration = load_semantic_runtime_configuration(
        root,
        root / DEFAULT_PRODUCTION_CONFIG_PATH,
    )
    classifier_options = semantic_configuration.classifier_options()
    classifier_options["model_path"] = str(
        resolve_frozen_model_path(root, semantic_configuration.model_path)
    )
    semantic_detector = SemanticClassifier(**classifier_options)
    semantic_status = semantic_detector.status()
    if not semantic_status["loaded"]:
        raise RuntimeError(
            "semantic model is unavailable: "
            f"{semantic_status['error']}"
        )
    router = ActionRouter(root / "config/action_rules_v1.json")
    return normalizer, rule_detector, semantic_detector, router


def resolve_frozen_model_path(
    project_root: Path,
    configured_model_path: str | Path,
) -> Path:
    """Resolve an untracked frozen model from this or the shared Git worktree."""
    project_root = project_root.resolve()
    configured = Path(configured_model_path)
    local_candidate = (
        configured.resolve()
        if configured.is_absolute()
        else (project_root / configured).resolve()
    )
    if local_candidate.is_file():
        return local_candidate

    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return local_candidate

    common_dir = Path(completed.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (project_root / common_dir).resolve()
    shared_candidate = (common_dir.resolve().parent / configured).resolve()
    return shared_candidate if shared_candidate.is_file() else local_candidate

def evaluate_rows(
    rows: list[dict[str, str]],
    normalizer,
    rule_detector,
    semantic_detector,
    router,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    predictions = []
    for row in rows:
        text = row["text"]
        normalized_text = normalizer.normalize(text)
        rule_detections = rule_detector.detect(normalized_text)
        semantic_detections = semantic_detector.detect(normalized_text)
        routed = router.route(
            text,
            normalized_text,
            rule_detections,
            semantic_detections,
        )
        predictions.append(
            {
                "sample_id": row["sample_id"],
                "true_label": row["label"],
                "expected_action": row["expected_action"],
                "predicted_label": routed["category"],
                "predicted_action": routed["action"],
                "risk_level": routed["risk_level"],
                "risk_score": routed["risk_score"],
                "confidence": routed["confidence"],
                "reason_codes": routed["reason_codes"],
                "matched_rule_ids": routed["matched_rule_ids"],
                "hard_block": routed["hard_block"],
            }
        )

    sample_count = len(rows)
    action_correct = sum(
        item["expected_action"] == item["predicted_action"]
        for item in predictions
    )
    block_total = sum(item["expected_action"] == "block" for item in predictions)
    block_correct = sum(
        item["expected_action"] == "block"
        and item["predicted_action"] == "block"
        for item in predictions
    )
    sanitize_total = sum(
        item["expected_action"] == "sanitize" for item in predictions
    )
    sanitize_correct = sum(
        item["expected_action"] == "sanitize"
        and item["predicted_action"] == "sanitize"
        for item in predictions
    )
    pass_total = sum(item["expected_action"] == "pass" for item in predictions)
    normal_false_positive_count = sum(
        item["expected_action"] == "pass"
        and item["predicted_action"] != "pass"
        for item in predictions
    )
    confusion_matrix = {
        "labels": list(ACTION_LABELS),
        "values": [
            [
                sum(
                    item["expected_action"] == expected
                    and item["predicted_action"] == predicted
                    for item in predictions
                )
                for predicted in ACTION_LABELS
            ]
            for expected in ACTION_LABELS
        ],
    }
    return {
        "schema_version": 1,
        "evaluation_scope": "action_router_v1_calibration_only",
        "evaluation_split": "calibration",
        "input_sha256": input_sha256,
        "sample_count": sample_count,
        "action_accuracy": action_correct / sample_count if sample_count else 0.0,
        "block_total": block_total,
        "block_correct": block_correct,
        "block_recall": block_correct / block_total if block_total else 0.0,
        "sanitize_total": sanitize_total,
        "sanitize_correct": sanitize_correct,
        "sanitize_recall": (
            sanitize_correct / sanitize_total if sanitize_total else 0.0
        ),
        "pass_total": pass_total,
        "normal_false_positive_count": normal_false_positive_count,
        "normal_false_positive_rate": (
            normal_false_positive_count / pass_total if pass_total else 0.0
        ),
        "confusion_matrix": confusion_matrix,
        "predictions": predictions,
    }


def write_outputs(
    metrics: dict[str, Any],
    output_path: Path,
    errors_output_path: Path,
) -> None:
    write_json(output_path, metrics)
    errors = [
        item
        for item in metrics["predictions"]
        if item["expected_action"] != item["predicted_action"]
    ]
    errors_output_path.parent.mkdir(parents=True, exist_ok=True)
    with errors_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ERROR_FIELDS)
        writer.writeheader()
        for item in errors:
            serialized = dict(item)
            serialized["reason_codes"] = "|".join(item["reason_codes"])
            serialized["matched_rule_ids"] = "|".join(item["matched_rule_ids"])
            writer.writerow(serialized)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Evaluate ActionRouter V1 on the authorized calibration split."
    )
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--gold",
        type=Path,
        default=project_root / "data/evaluation/semantic_gold_v1_calibration.csv",
    )
    parser.add_argument("--evaluation-split", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root
        / "reports/system_eval_v1/action_router_calibration_day1.json",
    )
    parser.add_argument(
        "--errors-output",
        type=Path,
        default=project_root
        / "reports/system_eval_v1/action_router_calibration_day1_errors.csv",
    )
    return parser.parse_args()


def _resolve_from_root(project_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    try:
        gold_path = _resolve_from_root(project_root, args.gold)
        rows = load_calibration_rows(gold_path, args.evaluation_split)
        components = build_components(project_root)
        metrics = evaluate_rows(
            rows,
            *components,
            input_sha256=sha256_file(gold_path),
        )
        output_path = _resolve_from_root(project_root, args.output)
        errors_output_path = _resolve_from_root(project_root, args.errors_output)
        write_outputs(metrics, output_path, errors_output_path)
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        "ActionRouter calibration complete: "
        f"samples={metrics['sample_count']}, "
        f"block={metrics['block_correct']}/{metrics['block_total']}, "
        f"normal_fp={metrics['normal_false_positive_count']}/"
        f"{metrics['pass_total']}, "
        f"output={output_path}, errors={errors_output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
