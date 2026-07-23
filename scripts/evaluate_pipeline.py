from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from safechat_guard.pipeline import SafeChatPipeline  # noqa: E402


DEFAULT_INPUT = PROJECT_ROOT / "data/test_cases/frontend_cases.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/pipeline_eval_results.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "reports/pipeline_eval_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the full SafeChat-Guard pipeline.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--text-column", default="input_text")
    parser.add_argument("--label-column", default="expected_category")
    parser.add_argument("--action-column", default="expected_action")
    parser.add_argument("--raw-output-column", default="mock_model_output")
    return parser.parse_args()


def read_cases(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def split_detections(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rule = []
    semantic = []
    for detection in result.get("detections", []):
        source = str(detection.get("source", ""))
        if source.startswith("semantic"):
            semantic.append(detection)
        elif source in {"keyword", "regex"} or source.startswith("rule"):
            rule.append(detection)
    return rule, semantic


def primary_category(result: dict[str, Any] | None) -> str:
    if not result:
        return "normal"
    categories = [item for item in result.get("risk_categories", []) if item != "normal"]
    if categories:
        return categories[0]
    return result.get("risk_category") or "normal"


def effective_action(
    input_filter: dict[str, Any],
    output_filter: dict[str, Any],
) -> str:
    rank = {"pass": 0, "sanitize": 1, "rewrite": 1, "block": 2}
    actions = [input_filter.get("action", "pass")]
    if output_filter:
        actions.append(output_filter.get("action", "pass"))
    return max(actions, key=lambda action: rank.get(action, -1))


def is_correct(
    predicted_category: str,
    final_action: str,
    expected_category: str,
    expected_action: str,
) -> bool | None:
    if expected_category:
        if expected_category == "normal":
            category_ok = predicted_category == "normal"
        else:
            category_ok = predicted_category == expected_category
        if expected_action:
            return category_ok and final_action == expected_action
        return category_ok
    if expected_action:
        return final_action == expected_action
    return None


def evaluate(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pipeline = SafeChatPipeline.from_config(args.config)
    input_path = Path(args.input)
    rows = read_cases(input_path)
    output_rows: list[dict[str, Any]] = []
    action_counter: Counter[str] = Counter()
    input_action_counter: Counter[str] = Counter()
    output_action_counter: Counter[str] = Counter()
    label_counter: Counter[str] = Counter()
    prediction_counter: Counter[str] = Counter()
    correct_count = 0
    scored_count = 0

    for index, row in enumerate(rows, start=1):
        text = row.get(args.text_column, "")
        expected_category = row.get(args.label_column, "")
        expected_action = row.get(args.action_column, "")
        raw_override = row.get(args.raw_output_column) or None

        result = pipeline.handle_chat(text, raw_reply_override=raw_override, persist=False)
        input_filter = result.get("input_filter") or {}
        output_filter = result.get("output_filter") or {}
        input_rule, input_semantic = split_detections(input_filter)
        output_rule, output_semantic = split_detections(output_filter)
        predicted_category = primary_category(input_filter)
        input_action = input_filter.get("action", "pass")
        output_action = output_filter.get("action", "not_run")
        final_action = effective_action(input_filter, output_filter)
        correct = is_correct(
            predicted_category,
            input_action,
            expected_category,
            expected_action,
        )

        action_counter[final_action] += 1
        input_action_counter[input_action] += 1
        output_action_counter[output_action] += 1
        if expected_category:
            label_counter[expected_category] += 1
        prediction_counter[predicted_category] += 1
        if correct is not None:
            scored_count += 1
            correct_count += int(correct)

        output_rows.append(
            {
                "index": index,
                "text": text,
                "expected_category": expected_category,
                "predicted_category": predicted_category,
                "expected_action": expected_action,
                "input_action": input_action,
                "output_action": output_action,
                "final_action": final_action,
                "risk_score": input_filter.get("risk_score", 0),
                "risk_level": input_filter.get("risk_level", "none"),
                "rule_result": dump_json({"input": input_rule, "output": output_rule}),
                "semantic_result": dump_json(
                    {
                        "input": input_semantic,
                        "output": output_semantic,
                        "scores": input_filter.get("semantic_scores", {}),
                    }
                ),
                "sanitized_result": (
                    input_filter.get("sanitized_text")
                    or output_filter.get("sanitized_text")
                    or ""
                ),
                "final_reply": result.get("reply", ""),
                "correct": "" if correct is None else str(bool(correct)).lower(),
            }
        )

    accuracy = correct_count / scored_count if scored_count else None
    summary = {
        "input": str(input_path),
        "total": len(rows),
        "scored": scored_count,
        "correct": correct_count,
        "accuracy": accuracy,
        "action_counts": dict(action_counter),
        "input_action_counts": dict(input_action_counter),
        "output_action_counts": dict(output_action_counter),
        "label_counts": dict(label_counter),
        "prediction_counts": dict(prediction_counter),
        "model_version": pipeline.semantic_model_version,
        "model_sha256": pipeline.semantic_model_sha256,
        "config_version": pipeline.config.get("app", {}).get("config_version", "unknown"),
        "semantic_classifier": pipeline.semantic_classifier.status(),
    }
    return output_rows, summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    summary_path = Path(args.summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "index",
        "text",
        "expected_category",
        "predicted_category",
        "expected_action",
        "input_action",
        "output_action",
        "final_action",
        "risk_score",
        "risk_level",
        "rule_result",
        "semantic_result",
        "sanitized_result",
        "final_reply",
        "correct",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    rows, summary = evaluate(args)
    write_outputs(rows, summary, args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
