from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict
from pathlib import Path

try:
    from data_baseline_common import (
        VALID_LABELS, find_leakage, load_reference_samples,
        read_csv_rows, write_csv, write_json,
    )
except ModuleNotFoundError:
    from scripts.data_baseline_common import (
        VALID_LABELS, find_leakage, load_reference_samples,
        read_csv_rows, write_csv, write_json,
    )


ISSUE_FIELDS = ["row_number", "text", "label", "issue"]
LEAKAGE_FIELDS = [
    "train_sample_id",
    "eval_sample_id",
    "train_text",
    "eval_text",
    "match_type",
    "train_label",
    "eval_label",
]


def audit_dataset(input_path: Path, report_dir: Path, project_root: Path) -> dict:
    fields, rows = read_csv_rows(input_path)
    required = {"text", "label"}
    missing_fields = sorted(required - set(fields))
    if missing_fields:
        raise ValueError(f"missing required CSV fields: {', '.join(missing_fields)}")

    invalid_rows = []
    text_occurrences: dict[str, list[tuple[int, str]]] = defaultdict(list)
    trimmed_occurrences: dict[str, list[int]] = defaultdict(list)
    label_counts: Counter[str] = Counter()
    lengths = []
    missing_text = missing_label = blank_text = invalid_label = non_string = 0

    for row_number, row in enumerate(rows, start=2):
        text = row.get("text")
        label = row.get("label")
        if not isinstance(text, str) or not isinstance(label, str):
            non_string += 1
            invalid_rows.append(
                {"row_number": row_number, "text": text, "label": label, "issue": "non_string"}
            )
            continue
        if text == "":
            missing_text += 1
            invalid_rows.append({"row_number": row_number, "text": text, "label": label, "issue": "missing_text"})
        elif not text.strip():
            blank_text += 1
            invalid_rows.append({"row_number": row_number, "text": text, "label": label, "issue": "blank_text"})
        if label == "" or not label.strip():
            missing_label += 1
            invalid_rows.append({"row_number": row_number, "text": text, "label": label, "issue": "missing_label"})
        normalized_label = label.strip().lower()
        if label.strip() and normalized_label not in VALID_LABELS:
            invalid_label += 1
            invalid_rows.append({"row_number": row_number, "text": text, "label": label, "issue": "invalid_label"})
        if text.strip():
            label_counts[normalized_label] += 1
            lengths.append(len(text))
            text_occurrences[text].append((row_number, normalized_label))
            trimmed_occurrences[text.strip()].append(row_number)

    duplicate_rows = []
    conflicts = []
    for text, occurrences in sorted(text_occurrences.items()):
        if len(occurrences) > 1:
            labels = sorted({label for _, label in occurrences})
            duplicate_rows.append(
                {
                    "text": text,
                    "labels": "|".join(labels),
                    "row_numbers": "|".join(str(number) for number, _ in occurrences),
                    "count": len(occurrences),
                }
            )
            if len(labels) > 1:
                conflicts.append(duplicate_rows[-1])

    trimmed_duplicate_groups = sum(
        1 for occurrences in trimmed_occurrences.values() if len(occurrences) > 1
    )
    prepared_rows = [
        {
            "sample_id": f"row_{index}",
            "text": row.get("text", ""),
            "label": row.get("label", "").strip().lower(),
        }
        for index, row in enumerate(rows, start=1)
        if isinstance(row.get("text"), str)
    ]
    references = load_reference_samples(project_root)
    leakage = find_leakage(prepared_rows, references, project_root)
    leakage_counts = Counter(
        next(
            (item["set_type"] for item in references if item["sample_id"] == leak["eval_sample_id"]),
            "unknown",
        )
        for leak in leakage
    )

    total = len(rows)
    summary = {
        "input_file": str(input_path),
        "total_samples": total,
        "fields": fields,
        "valid_labels": list(VALID_LABELS),
        "missing_text": missing_text,
        "missing_label": missing_label,
        "blank_text": blank_text,
        "invalid_labels": invalid_label,
        "non_string_values": non_string,
        "label_distribution": {
            label: {
                "count": label_counts.get(label, 0),
                "ratio": round(label_counts.get(label, 0) / total, 6) if total else 0,
            }
            for label in VALID_LABELS
        },
        "exact_duplicate_groups": len(duplicate_rows),
        "same_text_same_label_groups": sum(
            1 for item in duplicate_rows if "|" not in item["labels"]
        ),
        "conflicting_label_groups": len(conflicts),
        "trimmed_duplicate_groups": trimmed_duplicate_groups,
        "text_length": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "mean": round(statistics.fmean(lengths), 3) if lengths else 0,
            "median": statistics.median(lengths) if lengths else 0,
        },
        "short_texts_lt_2": sum(length < 2 for length in lengths),
        "long_texts_gt_500": sum(length > 500 for length in lengths),
        "leakage_candidates": len(leakage),
        "leakage_by_reference_type": dict(sorted(leakage_counts.items())),
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "summary.json", summary)
    markdown = ["# Training Data Audit", ""]
    for key, value in summary.items():
        markdown.append(f"- **{key}**: `{value}`")
    (report_dir / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    duplicate_fields = ["text", "labels", "row_numbers", "count"]
    write_csv(report_dir / "duplicate_rows.csv", duplicate_fields, duplicate_rows)
    write_csv(report_dir / "conflicting_labels.csv", duplicate_fields, conflicts)
    write_csv(report_dir / "invalid_rows.csv", ISSUE_FIELDS, invalid_rows)
    write_csv(report_dir / "leakage_candidates.csv", LEAKAGE_FIELDS, leakage)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SafeChat training CSV data")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    summary = audit_dataset(args.input, args.report_dir, project_root)
    print(f"audit complete: {summary['total_samples']} samples -> {args.report_dir}")


if __name__ == "__main__":
    main()
