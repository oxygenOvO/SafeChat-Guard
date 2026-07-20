from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

try:
    from scripts.independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        GOLD_FIELDS,
        LABELS,
        RANDOM_SEED,
        REVIEW_STATUSES,
        group_split_counts,
        make_normalizer,
        normalized_group_id,
        read_csv,
        sha256_text,
        write_csv,
    )
except ModuleNotFoundError:
    from independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        GOLD_FIELDS,
        LABELS,
        RANDOM_SEED,
        REVIEW_STATUSES,
        group_split_counts,
        make_normalizer,
        normalized_group_id,
        read_csv,
        sha256_text,
        write_csv,
    )


def build_gold(
    project_root: Path,
    review_path: Path,
    output_path: Path,
    seed: int = RANDOM_SEED,
) -> list[dict[str, str]]:
    rows = read_csv(review_path, CANDIDATE_FIELDS)
    invalid_statuses = sorted({row["review_status"] for row in rows} - REVIEW_STATUSES)
    if invalid_statuses:
        raise ValueError(f"invalid review statuses: {invalid_statuses}")
    pending_count = sum(row["review_status"] == "pending" for row in rows)
    if pending_count:
        raise RuntimeError(
            "人工审核尚未完成："
            f"{pending_count} 条样本仍为 pending；不会生成 semantic_gold_v1.csv"
        )
    reviewed_without_reviewer = [
        row["sample_id"]
        for row in rows
        if row["review_status"] in {"verified", "rejected"} and not row["reviewer"].strip()
    ]
    if reviewed_without_reviewer:
        raise ValueError(
            "reviewer is required for verified/rejected rows: "
            + ", ".join(reviewed_without_reviewer[:5])
        )

    verified = [dict(row) for row in rows if row["review_status"] == "verified"]
    if not verified:
        raise RuntimeError("人工审核已结束但没有 verified 样本；不会生成最终 gold")
    normalizer = make_normalizer(project_root.resolve())
    group_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in verified:
        if row["label"] not in LABELS:
            raise ValueError(f"invalid label in reviewed data: {row['label']}")
        group_rows[normalized_group_id(row["text"], normalizer)].append(row)
    duplicates = {group_id: items for group_id, items in group_rows.items() if len(items) > 1}
    if duplicates:
        raise ValueError(
            "verified review contains duplicate normalized groups: "
            + ", ".join(sorted(duplicates)[:5])
        )

    strata: dict[tuple[str, str], list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for group_id, items in group_rows.items():
        row = items[0]
        strata[(row["label"], row["expected_action"])].append((group_id, row))

    output_rows: list[dict[str, str]] = []
    for stratum in sorted(strata):
        label, action = stratum
        ordered = sorted(
            strata[stratum],
            key=lambda item: (
                sha256_text(f"{seed}\x1f{label}\x1f{action}\x1f{item[0]}"),
                item[0],
            ),
        )
        calibration_count, _ = group_split_counts(len(ordered), 0.40)
        for index, (_, row) in enumerate(ordered):
            output_rows.append(
                {
                    **row,
                    "evaluation_split": "calibration" if index < calibration_count else "test",
                }
            )
    output_rows.sort(
        key=lambda row: (
            0 if row["evaluation_split"] == "calibration" else 1,
            LABELS.index(row["label"]),
            row["expected_action"],
            row["sample_id"],
        )
    )
    write_csv(output_path, GOLD_FIELDS, output_rows)
    return output_rows


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build verified-only independent semantic gold V1.")
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--review-input",
        type=Path,
        default=project_root / "reports/manual_review/semantic_independent_eval_v1_review_template.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "data/evaluation/semantic_gold_v1.csv",
    )
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows = build_gold(args.project_root, args.review_input, args.output, args.random_seed)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    calibration = sum(row["evaluation_split"] == "calibration" for row in rows)
    print(f"semantic gold V1 written: total={len(rows)}, calibration={calibration}, test={len(rows) - calibration}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
