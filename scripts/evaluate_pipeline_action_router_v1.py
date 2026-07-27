from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.evaluate_action_router_v1 import (
        ACTION_LABELS,
        CALIBRATION_ONLY_FILENAME,
        build_components,
        load_calibration_rows,
        sha256_file,
    )
    from scripts.independent_eval_v1_common import write_json
except ModuleNotFoundError:
    from evaluate_action_router_v1 import (
        ACTION_LABELS,
        CALIBRATION_ONLY_FILENAME,
        build_components,
        load_calibration_rows,
        sha256_file,
    )
    from independent_eval_v1_common import write_json


ERROR_FIELDS = (
    "sample_id",
    "expected_action",
    "predicted_action",
    "predicted_label",
    "risk_level",
    "risk_score",
    "reason_codes",
    "hard_block",
    "rewrite_called",
    "rewrite_changed",
    "recheck_action",
    "model_forwarded",
    "output_guard_action",
    "fallback_used",
    "latency_ms",
    "error",
)


class FixedSafeLLM:
    provider = "pipeline_evaluator_fake"

    def __init__(self):
        self.calls: list[str] = []

    def chat(self, message: str) -> str:
        self.calls.append(message)
        return "这是固定的安全评估回复。"

    @staticmethod
    def status() -> dict[str, Any]:
        return {
            "provider": "pipeline_evaluator_fake",
            "ready": True,
            "mode": "offline_fake",
            "model": "fixed-safe-response",
            "key_configured": False,
        }


def build_pipeline(project_root: Path):
    root = project_root.resolve()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    from safechat_guard.pipeline import SafeChatPipeline

    config = json.loads((root / "config.yaml").read_text(encoding="utf-8"))
    config["llm"] = {"provider": "mock"}
    config["logging"]["path"] = str(
        root / ".tmp/pipeline_action_router_evaluator.jsonl"
    )
    pipeline = SafeChatPipeline(config, project_root=root)
    normalizer, rule_detector, semantic_detector, router = build_components(root)
    pipeline.normalizer = normalizer
    pipeline.rule_filter = rule_detector
    pipeline.semantic_classifier = semantic_detector
    pipeline.action_router = router
    pipeline.action_router_error_code = None
    pipeline.llm = FixedSafeLLM()
    return pipeline


def _sanitize_error_classification(
    expected_action: str,
    predicted_action: str,
    filtered: dict,
) -> str:
    if expected_action == predicted_action:
        return ""
    if expected_action != "sanitize":
        return "action_mismatch"
    reasons = set(filtered.get("reason_codes", []))
    if filtered.get("fallback_used"):
        return "action_router_error"
    if "SANITIZER_ERROR" in reasons:
        return "sanitizer_error"
    if "SANITIZER_EMPTY" in reasons:
        return "sanitizer_empty"
    if "SANITIZER_UNCHANGED" in reasons:
        return "sanitizer_unchanged"
    if filtered.get("recheck_action") == "sanitize":
        return "recheck_still_sanitize"
    if filtered.get("recheck_action") == "block":
        return "recheck_block"
    if not filtered.get("rewrite_called"):
        return "router_did_not_sanitize"
    return "pipeline_field_mapping_error"


def evaluate_rows(
    rows: list[dict[str, str]],
    pipeline,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    predictions = []
    for row in rows:
        result = pipeline.handle_chat(row["text"], persist=False)
        filtered = result["input_filter"]
        predicted_action = filtered["action"]
        prediction = {
            "sample_id": row["sample_id"],
            "expected_action": row["expected_action"],
            "predicted_action": predicted_action,
            "predicted_label": filtered["category"],
            "risk_level": filtered["risk_level"],
            "risk_score": filtered["risk_score"],
            "reason_codes": filtered["reason_codes"],
            "hard_block": filtered["hard_block"],
            "rewrite_called": filtered["rewrite_called"],
            "rewrite_changed": filtered["rewrite_changed"],
            "recheck_action": filtered["recheck_action"],
            "model_forwarded": result["model_forwarded"],
            "output_guard_action": result["output_guard_action"],
            "fallback_used": filtered["fallback_used"],
            "latency_ms": result["latency_ms"],
            "error": _sanitize_error_classification(
                row["expected_action"], predicted_action, filtered
            ),
        }
        predictions.append(prediction)

    sample_count = len(predictions)
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
    hard_block_forwarded_count = sum(
        item["hard_block"] and item["model_forwarded"] for item in predictions
    )
    unsafe_recheck_forwarded_count = sum(
        item["rewrite_called"]
        and item["recheck_action"] != "pass"
        and item["model_forwarded"]
        for item in predictions
    )
    return {
        "schema_version": 1,
        "evaluation_scope": "pipeline_action_router_v1_calibration_only",
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
        "hard_block_forwarded_count": hard_block_forwarded_count,
        "unsafe_recheck_forwarded_count": unsafe_recheck_forwarded_count,
        "router_fallback_count": sum(
            item["fallback_used"] for item in predictions
        ),
        "confusion_matrix": {
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
        },
        "predictions": predictions,
    }


def write_outputs(metrics: dict[str, Any], output: Path, errors_output: Path) -> None:
    write_json(output, metrics)
    errors = [
        item for item in metrics["predictions"]
        if item["expected_action"] != item["predicted_action"]
    ]
    errors_output.parent.mkdir(parents=True, exist_ok=True)
    with errors_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ERROR_FIELDS)
        writer.writeheader()
        for item in errors:
            serialized = dict(item)
            serialized["reason_codes"] = "|".join(item["reason_codes"])
            writer.writerow(serialized)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Evaluate the Pipeline ActionRouter gate on calibration only."
    )
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--gold", type=Path,
        default=root / "data/evaluation" / CALIBRATION_ONLY_FILENAME,
    )
    parser.add_argument("--evaluation-split", required=True)
    parser.add_argument(
        "--output", type=Path,
        default=root / "reports/system_eval_v1/pipeline_action_router_calibration_v1.json",
    )
    parser.add_argument(
        "--errors-output", type=Path,
        default=root / "reports/system_eval_v1/pipeline_action_router_calibration_v1_errors.csv",
    )
    return parser.parse_args()


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    try:
        gold = _resolve(root, args.gold)
        rows = load_calibration_rows(gold, args.evaluation_split)
        pipeline = build_pipeline(root)
        metrics = evaluate_rows(rows, pipeline, sha256_file(gold))
        output = _resolve(root, args.output)
        errors = _resolve(root, args.errors_output)
        write_outputs(metrics, output, errors)
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        "Pipeline ActionRouter calibration complete: "
        f"samples={metrics['sample_count']}, "
        f"block={metrics['block_correct']}/{metrics['block_total']}, "
        f"sanitize={metrics['sanitize_correct']}/{metrics['sanitize_total']}, "
        f"normal_fp={metrics['normal_false_positive_count']}/{metrics['pass_total']}, "
        f"hard_forwarded={metrics['hard_block_forwarded_count']}, "
        f"unsafe_recheck_forwarded={metrics['unsafe_recheck_forwarded_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())