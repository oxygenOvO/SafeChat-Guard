from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

try:
    from data_baseline_common import VALID_LABELS, read_csv_rows, stable_id, write_csv, write_json
except ModuleNotFoundError:
    from scripts.data_baseline_common import VALID_LABELS, read_csv_rows, stable_id, write_csv, write_json


CLEAN_FIELDS = ["sample_id", "text", "label", "source", "data_version"]
REVIEW_FIELDS = ["row_number", "text", "labels", "reason", "source"]


def build_clean_dataset(
    input_path: Path,
    output_path: Path,
    review_output: Path,
    source: str = "legacy_raw_train_v3",
    data_version: str = "train_clean_v1",
) -> dict:
    fields, rows = read_csv_rows(input_path)
    missing_fields = sorted({"text", "label"} - set(fields))
    if missing_fields:
        raise ValueError(f"missing required CSV fields: {', '.join(missing_fields)}")

    candidates: dict[str, list[dict[str, str | int]]] = defaultdict(list)
    removed_empty = invalid_labels = 0
    for row_number, row in enumerate(rows, start=2):
        text = row.get("text", "")
        label = row.get("label", "")
        if not isinstance(text, str) or not isinstance(label, str):
            removed_empty += 1
            continue
        if not text.strip() or not label.strip():
            removed_empty += 1
            continue
        normalized_label = label.strip().lower()
        if normalized_label not in VALID_LABELS:
            invalid_labels += 1
            continue
        candidates[text].append(
            {"row_number": row_number, "text": text, "label": normalized_label}
        )

    clean_rows = []
    review_rows = []
    removed_duplicates = conflicts = 0
    for text in sorted(candidates):
        group = candidates[text]
        labels = sorted({str(item["label"]) for item in group})
        if len(labels) > 1:
            conflicts += 1
            for item in group:
                review_rows.append(
                    {
                        "row_number": item["row_number"],
                        "text": text,
                        "labels": "|".join(labels),
                        "reason": "conflicting_labels",
                        "source": source,
                    }
                )
            continue
        removed_duplicates += len(group) - 1
        label = labels[0]
        clean_rows.append(
            {
                "sample_id": stable_id(text, label, source),
                "text": text,
                "label": label,
                "source": source,
                "data_version": data_version,
            }
        )

    clean_rows.sort(key=lambda item: item["sample_id"])
    review_rows.sort(key=lambda item: (int(item["row_number"]), item["text"]))
    write_csv(output_path, CLEAN_FIELDS, clean_rows)
    write_csv(review_output, REVIEW_FIELDS, review_rows)
    summary = {
        "input_samples": len(rows),
        "output_samples": len(clean_rows),
        "removed_empty_or_missing": removed_empty,
        "removed_duplicates": removed_duplicates,
        "conflicting_text_groups": conflicts,
        "invalid_labels": invalid_labels,
        "manual_review_rows": len(review_rows),
        "source": source,
        "data_version": data_version,
    }
    write_json(review_output.parent / "cleaning_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic clean training data")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--review-output", required=True, type=Path)
    parser.add_argument("--source", default="legacy_raw_train_v3")
    parser.add_argument("--data-version", default="train_clean_v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_clean_dataset(
        args.input,
        args.output,
        args.review_output,
        source=args.source,
        data_version=args.data_version,
    )
    print(f"cleaning complete: {summary['output_samples']} samples -> {args.output}")


if __name__ == "__main__":
    main()
