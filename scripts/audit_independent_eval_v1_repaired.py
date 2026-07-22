from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.audit_independent_eval_v1 import load_references
    from scripts.independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        REFERENCE_FILES,
        character_ngrams,
        equivalence_keys,
        make_normalizer,
        sha256_text,
        write_csv,
        write_json,
    )
except ModuleNotFoundError:
    from audit_independent_eval_v1 import load_references
    from independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        REFERENCE_FILES,
        character_ngrams,
        equivalence_keys,
        make_normalizer,
        sha256_text,
        write_csv,
        write_json,
    )


ELIMINATED_REFERENCE = "original_eliminated_candidates"
REPAIR_V1_REFERENCE = "repair_v1_sanitize_candidates"
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


LINKAGE_AUDIT_FIELDS = (
    "sample_id",
    "label",
    "text",
    "structure_type",
    "risk_position",
    "sanitize_operation",
    "legal_context",
    "risk_fragment",
    "linkage_reason",
    "linkage_status",
    "notes",
)
STRICT_LINKAGE_STRUCTURES = {
    "title_pollution",
    "signature_pollution",
    "field_pollution",
    "list_pollution",
}

def _validate_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("audit candidate rows must not be empty")
    if any(not set(CANDIDATE_FIELDS) <= set(row) for row in rows):
        raise ValueError("audit candidate rows are missing required fields")


def _reference_source_kind(reference_file: str) -> str:
    if reference_file == "candidate_set_internal":
        return "internal"
    if reference_file == ELIMINATED_REFERENCE:
        return "eliminated"
    if reference_file == REPAIR_V1_REFERENCE:
        return "repair_v1"
    if reference_file.startswith("data/normal_sentences.txt") or reference_file.startswith(
        "data/violation_sentences/"
    ):
        return "training"
    if reference_file.startswith("data/evaluation/"):
        return "old_evaluation"
    return "other"


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


def _conflict_row(
    match_type: str,
    canonical: str,
    left: dict[str, str],
    reference: dict[str, str],
) -> dict[str, str]:
    return {
        "match_type": match_type,
        "canonical_sha256": sha256_text(canonical),
        "left_id": left["sample_id"],
        "left_label": left["label"],
        "left_text": left["text"],
        "right_id": reference["reference_id"],
        "right_label": reference["label"],
        "right_text": reference["text"],
        "right_source": reference["reference_file"],
    }


def _eliminated_references(
    rows: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {
            "reference_id": f"eliminated:{row['sample_id']}",
            "text": row["text"],
            "label": row["label"],
            "reference_file": ELIMINATED_REFERENCE,
        }
        for row in rows
    ]

STRUCTURE_METADATA_FIELDS = (
    "sample_id",
    "text",
    "label",
    "structure_type",
    "risk_position",
    "sanitize_operation",
    "risk_fragment",
    "sanitized_text",
    "template_signature",
    "semantic_relation",
    "obvious_two_part",
    "safe_context_reference",
    "severe_core_intent",
    "uses_real_identifier",
)


def _metadata_bool(row: dict[str, str], field: str) -> bool:
    value = row[field].strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"invalid boolean metadata {field}={row[field]!r}")
    return value == "true"


def audit_structure_metadata(
    metadata: list[dict[str, str]],
    report_dir: Path,
    *,
    generation_version: str = "independent_eval_v1_repair_v2_1",
) -> dict[str, Any]:
    expected_counts = {"ad": 9, "porn": 10, "violence": 10, "sensitive": 10}
    if len(metadata) != 39:
        raise ValueError(f"structure metadata must contain 39 rows, found {len(metadata)}")
    if any(not set(STRUCTURE_METADATA_FIELDS) <= set(row) for row in metadata):
        raise ValueError("structure metadata is missing required fields")
    by_label_count = Counter(row["label"] for row in metadata)
    if dict(by_label_count) != expected_counts:
        raise ValueError(f"invalid structure metadata distribution: {dict(by_label_count)}")

    meta_phrases = ("请删除", "应删除", "请遮盖", "应遮盖", "需要脱敏", "请脱敏", "内容包含")
    unnatural_phrases = ("私 xing", "加-微", "约pao", "微★信")
    mechanical_pairs = (
        ("设备采购", "精神科"),
        ("设备采购", "治疗"),
        ("文学标题", "色情"),
        ("小说标题", "裸聊"),
    )
    meta_instruction_count = sum(
        any(phrase in row["text"] for phrase in meta_phrases) for row in metadata
    )
    unnatural_obfuscation_count = sum(
        any(phrase in row["text"] for phrase in unnatural_phrases)
        for row in metadata
    )
    mechanical_pairing_count = sum(
        any(left in row["text"] and right in row["text"] for left, right in mechanical_pairs)
        for row in metadata
    )
    missing_risk_fragment_count = sum(
        not row["risk_fragment"] or row["risk_fragment"] not in row["text"]
        for row in metadata
    )
    invalid_sanitized_text_count = sum(
        not row["sanitized_text"].strip()
        or row["sanitized_text"] == row["text"]
        or row["risk_fragment"] in row["sanitized_text"]
        for row in metadata
    )
    safe_context_reference_count = sum(
        _metadata_bool(row, "safe_context_reference") for row in metadata
    )
    severe_core_intent_count = sum(
        _metadata_bool(row, "severe_core_intent") for row in metadata
    )
    real_identifier_count = sum(
        _metadata_bool(row, "uses_real_identifier") for row in metadata
    )
    semantic_unlinked_count = sum(
        not row["semantic_relation"].strip() for row in metadata
    )
    signature_counts = Counter(row["template_signature"] for row in metadata)
    duplicate_template_signature_count = sum(
        count - 1 for count in signature_counts.values() if count > 1
    )
    obvious_two_part_count = sum(
        _metadata_bool(row, "obvious_two_part") for row in metadata
    )
    obvious_two_part_ratio = obvious_two_part_count / len(metadata)

    by_label: dict[str, Any] = {}
    label_gates_passed = True
    for label, expected_count in expected_counts.items():
        rows = [row for row in metadata if row["label"] == label]
        structures = Counter(row["structure_type"] for row in rows)
        positions = Counter(row["risk_position"] for row in rows)
        operations = Counter(row["sanitize_operation"] for row in rows)
        max_structure_ratio = max(structures.values()) / expected_count
        risk_at_end_ratio = positions["end"] / expected_count
        gates = {
            "at_least_four_structures": len(structures) >= 4,
            "at_least_three_operations": len(operations) >= 3,
            "max_structure_ratio_at_most_0_40": max_structure_ratio <= 0.40,
            "risk_at_end_ratio_at_most_0_40": risk_at_end_ratio <= 0.40,
        }
        label_gates_passed = label_gates_passed and all(gates.values())
        by_label[label] = {
            "count": expected_count,
            "structure_type_distribution": dict(sorted(structures.items())),
            "risk_position_distribution": dict(sorted(positions.items())),
            "sanitize_operation_distribution": dict(sorted(operations.items())),
            "structure_type_count": len(structures),
            "sanitize_operation_type_count": len(operations),
            "max_structure_ratio": round(max_structure_ratio, 6),
            "risk_at_end_ratio": round(risk_at_end_ratio, 6),
            "gates": gates,
        }

    gates = {
        "label_structure_gates_passed": label_gates_passed,
        "meta_instruction_count_zero": meta_instruction_count == 0,
        "duplicate_template_signature_count_zero": duplicate_template_signature_count == 0,
        "unnatural_obfuscation_count_zero": unnatural_obfuscation_count == 0,
        "mechanical_pairing_count_zero": mechanical_pairing_count == 0,
        "risk_fragment_present_for_all": missing_risk_fragment_count == 0,
        "sanitized_text_valid_for_all": invalid_sanitized_text_count == 0,
        "safe_context_reference_count_zero": safe_context_reference_count == 0,
        "severe_core_intent_count_zero": severe_core_intent_count == 0,
        "real_identifier_count_zero": real_identifier_count == 0,
        "semantic_unlinked_count_zero": semantic_unlinked_count == 0,
        "obvious_two_part_ratio_below_0_40": obvious_two_part_ratio < 0.40,
    }
    structure_audit_passed = all(gates.values())
    coverage = {
        "schema_version": 1,
        "generation_version": generation_version,
        "candidate_count": len(metadata),
        "by_label": by_label,
        "meta_instruction_count": meta_instruction_count,
        "obvious_two_part_count": obvious_two_part_count,
        "obvious_two_part_ratio": round(obvious_two_part_ratio, 6),
        "duplicate_template_signature_count": duplicate_template_signature_count,
        "unnatural_obfuscation_count": unnatural_obfuscation_count,
        "mechanical_pairing_count": mechanical_pairing_count,
        "missing_risk_fragment_count": missing_risk_fragment_count,
        "invalid_sanitized_text_count": invalid_sanitized_text_count,
        "safe_context_reference_count": safe_context_reference_count,
        "severe_core_intent_count": severe_core_intent_count,
        "real_identifier_count": real_identifier_count,
        "semantic_unlinked_count": semantic_unlinked_count,
        "gates": gates,
        "structure_audit_passed": structure_audit_passed,
    }
    write_csv(report_dir / "structure_metadata.csv", STRUCTURE_METADATA_FIELDS, metadata)
    write_json(report_dir / "structure_audit.json", coverage)
    return coverage

def audit_semantic_linkage(
    rows: list[dict[str, str]],
    expected_candidate_ids: set[str],
    report_dir: Path,
    *,
    generation_version: str,
    forbidden_sample_ids: set[str] | None = None,
) -> dict[str, Any]:
    expected_counts = {"ad": 9, "porn": 10, "violence": 10, "sensitive": 10}
    forbidden_sample_ids = forbidden_sample_ids or set()
    if len(rows) != 39:
        raise ValueError(f"semantic linkage audit must contain 39 rows, found {len(rows)}")
    if any(not set(LINKAGE_AUDIT_FIELDS) <= set(row) for row in rows):
        raise ValueError("semantic linkage audit is missing required fields")

    ids = [row["sample_id"] for row in rows]
    duplicate_ids = len(ids) - len(set(ids))
    candidate_id_mismatch = set(ids) != expected_candidate_ids
    invalid_statuses = sorted(
        {row["linkage_status"] for row in rows} - {"linked", "unlinked", "pending"}
    )
    status_counts = Counter(row["linkage_status"] for row in rows)
    by_label_count = Counter(row["label"] for row in rows)
    if dict(by_label_count) != expected_counts:
        raise ValueError(f"invalid semantic linkage distribution: {dict(by_label_count)}")

    missing_context_count = sum(not row["legal_context"].strip() for row in rows)
    missing_risk_fragment_count = sum(
        not row["risk_fragment"].strip() or row["risk_fragment"] not in row["text"]
        for row in rows
    )
    missing_linkage_reason_count = sum(
        not row["linkage_reason"].strip() for row in rows
    )
    strict_rows = [
        row for row in rows if row["structure_type"] in STRICT_LINKAGE_STRUCTURES
    ]
    strict_missing_reason_count = sum(
        not row["linkage_reason"].strip() for row in strict_rows
    )
    forbidden_ids_present = sorted(set(ids) & forbidden_sample_ids)
    gates = {
        "candidate_ids_match": not candidate_id_mismatch,
        "duplicate_sample_id_count_zero": duplicate_ids == 0,
        "invalid_status_count_zero": not invalid_statuses,
        "unlinked_count_zero": status_counts["unlinked"] == 0,
        "pending_count_zero": status_counts["pending"] == 0,
        "all_legal_contexts_present": missing_context_count == 0,
        "all_risk_fragments_present": missing_risk_fragment_count == 0,
        "all_linkage_reasons_present": missing_linkage_reason_count == 0,
        "strict_structure_reasons_present": strict_missing_reason_count == 0,
        "forbidden_sample_ids_absent": not forbidden_ids_present,
    }
    passed = all(gates.values())
    coverage = {
        "schema_version": 1,
        "generation_version": generation_version,
        "candidate_count": len(rows),
        "linked_count": status_counts["linked"],
        "unlinked_count": status_counts["unlinked"],
        "pending_count": status_counts["pending"],
        "by_label": {
            label: dict(
                sorted(
                    Counter(
                        row["linkage_status"] for row in rows if row["label"] == label
                    ).items()
                )
            )
            for label in expected_counts
        },
        "duplicate_sample_id_count": duplicate_ids,
        "invalid_statuses": invalid_statuses,
        "candidate_id_mismatch": candidate_id_mismatch,
        "missing_legal_context_count": missing_context_count,
        "missing_risk_fragment_count": missing_risk_fragment_count,
        "missing_linkage_reason_count": missing_linkage_reason_count,
        "strict_structure_count": len(strict_rows),
        "strict_structure_missing_reason_count": strict_missing_reason_count,
        "forbidden_sample_ids_present": forbidden_ids_present,
        "gates": gates,
        "semantic_linkage_audit_passed": passed,
    }
    version_suffix = generation_version.rsplit("_repair_", 1)[-1]
    write_csv(
        report_dir / f"semantic_linkage_audit_{version_suffix}.csv",
        LINKAGE_AUDIT_FIELDS,
        rows,
    )
    write_json(report_dir / f"semantic_linkage_audit_{version_suffix}.json", coverage)
    return coverage

def audit_repaired_rows(
    project_root: Path,
    candidates: list[dict[str, str]],
    eliminated_rows: list[dict[str, str]],
    report_dir: Path,
    *,
    candidate_file_label: str,
    additional_reference_rows: list[dict[str, str]] | None = None,
    similarity_threshold: float = 0.55,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    _validate_rows(candidates)
    references = load_references(project_root)
    references.extend(_eliminated_references(eliminated_rows))
    if additional_reference_rows:
        references.extend(
            {
                "reference_id": row.get("reference_id", f"repair_v1:{row['sample_id']}"),
                "text": row["text"],
                "label": row["label"],
                "reference_file": row.get("reference_file", REPAIR_V1_REFERENCE),
            }
            for row in additional_reference_rows
        )
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
        keys = reference_keys[reference["reference_id"]]
        for match_type, canonical in keys.items():
            reference_indexes[match_type][canonical].append(reference)

    exact_overlaps: list[dict[str, str]] = []
    normalized_overlaps: list[dict[str, str]] = []
    label_conflicts: list[dict[str, str]] = []
    for candidate in candidates:
        keys = candidate_keys[candidate["sample_id"]]
        for match_type in ("exact", "nfkc", "text_normalizer"):
            for reference in reference_indexes[match_type].get(keys[match_type], []):
                overlap = _overlap_row(match_type, candidate, reference)
                if match_type == "text_normalizer":
                    normalized_overlaps.append(overlap)
                else:
                    exact_overlaps.append(overlap)
                if candidate["label"] != reference["label"]:
                    label_conflicts.append(
                        _conflict_row(match_type, keys[match_type], candidate, reference)
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
                    overlap = _overlap_row(match_type, left, reference)
                    if match_type == "text_normalizer":
                        normalized_overlaps.append(overlap)
                    else:
                        exact_overlaps.append(overlap)
                    if left["label"] != right["label"]:
                        label_conflicts.append(
                            _conflict_row(match_type, canonical, left, reference)
                        )

    reference_grams = [
        (reference, character_ngrams(reference["text"], 3))
        for reference in references
    ]
    high_similarity: list[dict[str, str]] = []
    for candidate in candidates:
        grams = character_ngrams(candidate["text"], 3)
        for reference, other_grams in reference_grams:
            union = grams | other_grams
            score = len(grams & other_grams) / len(union) if union else 0.0
            if score >= similarity_threshold:
                high_similarity.append(
                    {
                        "candidate_sample_id": candidate["sample_id"],
                        "candidate_text": candidate["text"],
                        "candidate_label": candidate["label"],
                        "reference_id": reference["reference_id"],
                        "reference_text": reference["text"],
                        "reference_label": reference["label"],
                        "reference_file": reference["reference_file"],
                        "char_3gram_jaccard": f"{score:.6f}",
                    }
                )

    candidate_grams = [
        (candidate, character_ngrams(candidate["text"], 3))
        for candidate in candidates
    ]
    for left_index, (left, left_grams) in enumerate(candidate_grams):
        for right, right_grams in candidate_grams[left_index + 1:]:
            union = left_grams | right_grams
            score = len(left_grams & right_grams) / len(union) if union else 0.0
            if score >= similarity_threshold:
                high_similarity.append(
                    {
                        "candidate_sample_id": left["sample_id"],
                        "candidate_text": left["text"],
                        "candidate_label": left["label"],
                        "reference_id": right["sample_id"],
                        "reference_text": right["text"],
                        "reference_label": right["label"],
                        "reference_file": "candidate_set_internal",
                        "char_3gram_jaccard": f"{score:.6f}",
                    }
                )

    exact_overlaps.sort(
        key=lambda row: (row["match_type"], row["candidate_sample_id"], row["reference_id"])
    )
    normalized_overlaps.sort(
        key=lambda row: (row["candidate_sample_id"], row["reference_id"])
    )
    high_similarity.sort(
        key=lambda row: (
            -float(row["char_3gram_jaccard"]),
            row["candidate_sample_id"],
            row["reference_id"],
        )
    )
    label_conflicts.sort(
        key=lambda row: (row["match_type"], row["left_id"], row["right_id"])
    )
    write_csv(report_dir / "exact_overlap.csv", OVERLAP_FIELDS, exact_overlaps)
    write_csv(report_dir / "normalized_overlap.csv", OVERLAP_FIELDS, normalized_overlaps)
    write_csv(
        report_dir / "high_similarity_candidates.csv",
        SIMILARITY_FIELDS,
        high_similarity,
    )
    write_csv(report_dir / "label_conflicts.csv", CONFLICT_FIELDS, label_conflicts)

    all_overlaps = exact_overlaps + normalized_overlaps
    overlap_counts = Counter(row["match_type"] for row in all_overlaps)
    overlap_source_counts = Counter(
        _reference_source_kind(row["reference_file"]) for row in all_overlaps
    )
    duplicate_ids = len(candidates) - len({row["sample_id"] for row in candidates})
    hard_overlap_passed = (
        duplicate_ids == 0
        and not label_conflicts
        and all(
            overlap_counts[match_type] == 0
            for match_type in ("exact", "nfkc", "text_normalizer")
        )
    )
    coverage = {
        "schema_version": 1,
        "candidate_file": candidate_file_label,
        "candidate_count": len(candidates),
        "reference_text_count": len(references),
        "reference_files": [
            *REFERENCE_FILES,
            ELIMINATED_REFERENCE,
            REPAIR_V1_REFERENCE,
            "candidate_set_internal",
        ],
        "eliminated_reference_count": len(eliminated_rows),
        "by_label": dict(sorted(Counter(row["label"] for row in candidates).items())),
        "by_expected_action": dict(
            sorted(Counter(row["expected_action"] for row in candidates).items())
        ),
        "by_label_and_action": {
            label: dict(
                sorted(
                    Counter(
                        row["expected_action"]
                        for row in candidates
                        if row["label"] == label
                    ).items()
                )
            )
            for label in ("normal", "ad", "porn", "violence", "sensitive")
        },
        "review_status": dict(
            sorted(Counter(row["review_status"] for row in candidates).items())
        ),
        "duplicate_sample_id_count": duplicate_ids,
        "exact_overlap_count": overlap_counts["exact"],
        "nfkc_overlap_count": overlap_counts["nfkc"],
        "text_normalizer_overlap_count": overlap_counts["text_normalizer"],
        "training_source_overlap_count": overlap_source_counts["training"],
        "old_evaluation_overlap_count": overlap_source_counts["old_evaluation"],
        "eliminated_text_overlap_count": overlap_source_counts["eliminated"],
        "repair_v1_text_overlap_count": overlap_source_counts["repair_v1"],
        "repair_v1_overlap_by_match_type": {
            match_type: sum(
                row["match_type"] == match_type
                and row["reference_file"] == REPAIR_V1_REFERENCE
                for row in all_overlaps
            )
            for match_type in ("exact", "nfkc", "text_normalizer")
        },
        "internal_overlap_count": overlap_source_counts["internal"],
        "high_similarity_threshold": similarity_threshold,
        "high_similarity_candidate_count": len(high_similarity),
        "internal_high_similarity_count": sum(
            row["reference_file"] == "candidate_set_internal"
            for row in high_similarity
        ),
        "label_conflict_count": len(label_conflicts),
        "hard_overlap_passed": hard_overlap_passed,
    }
    write_json(report_dir / "coverage.json", coverage)
    return coverage
