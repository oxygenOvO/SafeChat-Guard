from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

FIELDS = (
    "sample_id", "text", "label", "risk_level", "expected_action", "scenario",
    "source_type", "source_reference", "review_status", "reviewer", "notes"
)

def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} missing fields: {sorted(missing)}")
        return [dict(row) for row in reader]

def main() -> int:
    parser = argparse.ArgumentParser(description="Compare reviewer_1 and reviewer_2 on the blind audit sample.")
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/manual_review/second_review_v1"))
    args = parser.parse_args()

    first = {row["sample_id"]: row for row in read_rows(args.first_review)}
    second = read_rows(args.second_review)
    if any(row["review_status"] == "pending" for row in second):
        pending = sum(row["review_status"] == "pending" for row in second)
        raise RuntimeError(f"second review incomplete: {pending} rows remain pending")
    if any(not row["reviewer"].strip() for row in second):
        raise ValueError("every second-review row must include reviewer")

    missing = [row["sample_id"] for row in second if row["sample_id"] not in first]
    if missing:
        raise ValueError(f"sample IDs absent from first review: {missing[:5]}")

    disagreements = []
    for row2 in second:
        row1 = first[row2["sample_id"]]
        if row1["review_status"] != row2["review_status"]:
            disagreements.append({
                "sample_id": row2["sample_id"],
                "text": row2["text"],
                "label": row2["label"],
                "expected_action": row2["expected_action"],
                "reviewer_1_status": row1["review_status"],
                "reviewer_1_notes": row1["notes"],
                "reviewer_2_status": row2["review_status"],
                "reviewer_2_notes": row2["notes"],
            })

    total = len(second)
    agreement = total - len(disagreements)
    summary = {
        "sample_count": total,
        "agreement_count": agreement,
        "disagreement_count": len(disagreements),
        "raw_agreement_rate": agreement / total if total else 0.0,
        "decision_note": (
            "Adjudicate every disagreement. Expand review within the same label/action stratum "
            "when disagreement reveals a systematic rule interpretation problem."
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "second_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "sample_id", "text", "label", "expected_action",
        "reviewer_1_status", "reviewer_1_notes",
        "reviewer_2_status", "reviewer_2_notes",
    ]
    with (args.output_dir / "second_review_disagreements.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(disagreements)

    print(
        f"second review compared: total={total}, agreement={agreement}, "
        f"disagreement={len(disagreements)}, rate={summary['raw_agreement_rate']:.2%}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
