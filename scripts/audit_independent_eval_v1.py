from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        REFERENCE_FILES,
        character_ngrams,
        equivalence_keys,
        make_normalizer,
        read_csv,
        sha256_text,
        validate_candidate_rows,
        write_csv,
        write_json,
    )
except ModuleNotFoundError:
    from independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        REFERENCE_FILES,
        character_ngrams,
        equivalence_keys,
        make_normalizer,
        read_csv,
        sha256_text,
        validate_candidate_rows,
        write_csv,
        write_json,
    )


OVERLAP_FIELDS = (
    "match_type",
    "candidate_sample_id",
    "candidate_text",
    "candidate_label",
    "reference_id",
    "reference_text",
    "reference_label",
    "reference_file",
)
SIMILARITY_FIELDS = (
    "candidate_sample_id",
    "candidate_text",
    "candidate_label",
    "reference_id",
    "reference_text",
    "reference_label",
    "reference_file",
    "char_3gram_jaccard",
)
CONFLICT_FIELDS = (
    "match_type",
    "canonical_sha256",
    "left_id",
    "left_label",
    "left_text",
    "right_id",
    "right_label",
    "right_text",
    "right_source",
)


def _txt_references(path: Path, relative_path: str) -> list[dict[str, str]]:
    label = "normal" if path.name == "normal_sentences.txt" else path.stem
    rows = []
    for line_number, text in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if text.strip() and not text.lstrip().startswith("#"):
            rows.append(
                {
                    "reference_id": f"{relative_path}:{line_number}",
                    "text": text,
                    "label": label,
                    "reference_file": relative_path,
                }
            )
    return rows


def _csv_references(path: Path, relative_path: str) -> list[dict[str, str]]:
    rows = read_csv(path)
    references: list[dict[str, str]] = []
    for row_number, row in enumerate(rows, start=1):
        sample_id = row.get("sample_id") or f"row_{row_number}"
        text_fields = (
            ("text", row.get("text", "")),
            ("original_text", row.get("original_text", "")),
            ("adversarial_text", row.get("adversarial_text", "")),
        )
        seen_texts = set()
        for field, text in text_fields:
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            references.append(
                {
                    "reference_id": f"{sample_id}:{field}",
                    "text": text,
                    "label": row.get("label", ""),
                    "reference_file": relative_path,
                }
            )
    return references


def load_references(project_root: Path) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for relative_path in REFERENCE_FILES:
        path = project_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"required audit reference not found: {path}")
        if path.suffix == ".txt":
            references.extend(_txt_references(path, relative_path))
        else:
            references.extend(_csv_references(path, relative_path))
    return references


def _overlap_row(
    match_type: str,
    candidate: dict[str, str],
    reference: dict[str, str],
) -> dict[str, str]:
    return {
        "match_type": match_type,
        "candidate_sample_id": candidate["sample_id"],
        "candidate_text": candidate["text"],
        "candidate_label": candidate["label"],
        "reference_id": reference["reference_id"],
        "reference_text": reference["text"],
        "reference_label": reference["label"],
        "reference_file": reference["reference_file"],
    }


def audit_independent_eval(
    project_root: Path,
    candidate_path: Path,
    report_dir: Path,
    similarity_threshold: float = 0.55,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    candidates = read_csv(candidate_path, CANDIDATE_FIELDS)
    validate_candidate_rows(candidates)
    references = load_references(project_root)
    normalizer = make_normalizer(project_root)

    candidate_keys = {
        row["sample_id"]: equivalence_keys(row["text"], normalizer)
        for row in candidates
    }
    reference_keys = {
        row["reference_id"]: equivalence_keys(row["text"], normalizer)
        for row in references
    }
    reference_indexes: dict[str, dict[str, list[dict[str, str]]]] = {
        match_type: defaultdict(list)
        for match_type in ("exact", "nfkc", "text_normalizer")
    }
    for reference in references:
        for match_type, value in reference_keys[reference["reference_id"]].items():
            reference_indexes[match_type][value].append(reference)

    exact_overlaps: list[dict[str, str]] = []
    normalized_overlaps: list[dict[str, str]] = []
    label_conflicts: list[dict[str, str]] = []
    for candidate in candidates:
        keys = candidate_keys[candidate["sample_id"]]
        for match_type in ("exact", "nfkc", "text_normalizer"):
            for reference in reference_indexes[match_type].get(keys[match_type], []):
                item = _overlap_row(match_type, candidate, reference)
                if match_type == "text_normalizer":
                    normalized_overlaps.append(item)
                else:
                    exact_overlaps.append(item)
                if candidate["label"] != reference["label"]:
                    label_conflicts.append(
                        {
                            "match_type": match_type,
                            "canonical_sha256": sha256_text(keys[match_type]),
                            "left_id": candidate["sample_id"],
                            "left_label": candidate["label"],
                            "left_text": candidate["text"],
                            "right_id": reference["reference_id"],
                            "right_label": reference["label"],
                            "right_text": reference["text"],
                            "right_source": reference["reference_file"],
                        }
                    )

    for match_type in ("exact", "nfkc", "text_normalizer"):
        internal_index: dict[str, list[dict[str, str]]] = defaultdict(list)
        for candidate in candidates:
            internal_index[candidate_keys[candidate["sample_id"]][match_type]].append(candidate)
        for canonical, matches in internal_index.items():
            if len(matches) < 2:
                continue
            for left_index, left in enumerate(matches):
                for right in matches[left_index + 1:]:
                    reference = {
                        "reference_id": right["sample_id"],
                        "text": right["text"],
                        "label": right["label"],
                        "reference_file": "candidate_set_internal",
                    }
                    item = _overlap_row(match_type, left, reference)
                    if match_type == "text_normalizer":
                        normalized_overlaps.append(item)
                    else:
                        exact_overlaps.append(item)
                    if left["label"] != right["label"]:
                        label_conflicts.append(
                            {
                                "match_type": match_type,
                                "canonical_sha256": sha256_text(canonical),
                                "left_id": left["sample_id"],
                                "left_label": left["label"],
                                "left_text": left["text"],
                                "right_id": right["sample_id"],
                                "right_label": right["label"],
                                "right_text": right["text"],
                                "right_source": "candidate_set_internal",
                            }
                        )

    reference_grams = [
        (reference, character_ngrams(reference["text"], 3))
        for reference in references
    ]
    high_similarity: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_grams = character_ngrams(candidate["text"], 3)
        best_reference = None
        best_score = 0.0
        for reference, grams in reference_grams:
            union = candidate_grams | grams
            score = len(candidate_grams & grams) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_reference = reference
        if best_reference is not None and best_score >= similarity_threshold:
            high_similarity.append(
                {
                    "candidate_sample_id": candidate["sample_id"],
                    "candidate_text": candidate["text"],
                    "candidate_label": candidate["label"],
                    "reference_id": best_reference["reference_id"],
                    "reference_text": best_reference["text"],
                    "reference_label": best_reference["label"],
                    "reference_file": best_reference["reference_file"],
                    "char_3gram_jaccard": f"{best_score:.6f}",
                }
            )

    exact_overlaps.sort(key=lambda row: (row["match_type"], row["candidate_sample_id"], row["reference_id"]))
    normalized_overlaps.sort(key=lambda row: (row["candidate_sample_id"], row["reference_id"]))
    high_similarity.sort(key=lambda row: (-float(row["char_3gram_jaccard"]), row["candidate_sample_id"]))
    label_conflicts.sort(key=lambda row: (row["match_type"], row["left_id"], row["right_id"]))
    write_csv(report_dir / "exact_overlap.csv", OVERLAP_FIELDS, exact_overlaps)
    write_csv(report_dir / "normalized_overlap.csv", OVERLAP_FIELDS, normalized_overlaps)
    write_csv(report_dir / "high_similarity_candidates.csv", SIMILARITY_FIELDS, high_similarity)
    write_csv(report_dir / "label_conflicts.csv", CONFLICT_FIELDS, label_conflicts)

    duplicate_ids = len(candidates) - len({row["sample_id"] for row in candidates})
    overlap_counts = Counter(row["match_type"] for row in exact_overlaps + normalized_overlaps)
    coverage = {
        "schema_version": 1,
        "candidate_file": candidate_path.relative_to(project_root).as_posix()
        if candidate_path.is_relative_to(project_root)
        else candidate_path.as_posix(),
        "candidate_count": len(candidates),
        "reference_text_count": len(references),
        "reference_files": list(REFERENCE_FILES),
        "by_label": dict(sorted(Counter(row["label"] for row in candidates).items())),
        "by_expected_action": dict(sorted(Counter(row["expected_action"] for row in candidates).items())),
        "by_label_and_action": {
            label: dict(sorted(Counter(
                row["expected_action"] for row in candidates if row["label"] == label
            ).items()))
            for label in ("normal", "ad", "porn", "violence", "sensitive")
        },
        "by_scenario": dict(sorted(Counter(row["scenario"] for row in candidates).items())),
        "review_status": dict(sorted(Counter(row["review_status"] for row in candidates).items())),
        "duplicate_sample_id_count": duplicate_ids,
        "exact_overlap_count": overlap_counts["exact"],
        "nfkc_overlap_count": overlap_counts["nfkc"],
        "text_normalizer_overlap_count": overlap_counts["text_normalizer"],
        "high_similarity_threshold": similarity_threshold,
        "high_similarity_candidate_count": len(high_similarity),
        "label_conflict_count": len(label_conflicts),
        "hard_overlap_passed": all(overlap_counts[kind] == 0 for kind in (
            "exact", "nfkc", "text_normalizer"
        )),
    }
    write_json(report_dir / "coverage.json", coverage)
    return coverage


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit independent semantic evaluation V1 candidates.")
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=project_root / "data/evaluation/semantic_independent_eval_v1_candidates.csv",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=project_root / "reports/data_audit_semantic_gold_v1",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.55)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    coverage = audit_independent_eval(
        args.project_root,
        args.candidates,
        args.report_dir,
        args.similarity_threshold,
    )
    print(
        "independent evaluation audit: "
        f"exact={coverage['exact_overlap_count']}, "
        f"nfkc={coverage['nfkc_overlap_count']}, "
        f"normalizer={coverage['text_normalizer_overlap_count']}, "
        f"high_similarity={coverage['high_similarity_candidate_count']}"
    )
    return 0 if coverage["hard_overlap_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
