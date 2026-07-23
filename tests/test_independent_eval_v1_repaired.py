from __future__ import annotations

import hashlib
import json
import socket
from collections import Counter
from pathlib import Path

import pytest

import scripts.build_independent_eval_v1_repaired as repaired_builder
from scripts.build_independent_eval_v1_repaired import (
    EXPECTED_REPLACEMENTS,
    GENERATION_VERSION,
    MANIFEST_FIELDS,
    ORIGINAL_BASELINE_PATHS,
    PORN_BLOCK_GENERATION_VERSION,
    PORN_BLOCK_REJECTED_ID,
    REPAIR_V2_1_GENERATION_VERSION,
    REPAIR_V2_1_REPLACED_OLD_IDS,
    REPAIR_V2_2_REJECTED_SAMPLE_IDS,
    REPAIR_V2_2_REPLACED_OLD_IDS,
    REPAIR_V2_UNLINKED_SAMPLE_IDS,
    REPAIR_V1_SANITIZE_REFERENCES,
    _load_eliminated_rows,
    build_repair_v1_references,
    build_repaired_candidates,
    build_replacement_rows,
    build_semantic_linkage_audit,
    build_structure_metadata,
    run_repair,
)
from scripts.audit_independent_eval_v1_repaired import (
    LINKAGE_AUDIT_FIELDS,
    audit_semantic_linkage,
    audit_structure_metadata,
)
from scripts.independent_eval_v1_common import (
    CANDIDATE_FIELDS,
    read_csv,
    stable_sample_id,
    validate_candidate_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_PATH = (
    PROJECT_ROOT / "data/evaluation/semantic_independent_eval_v1_candidates.csv"
)
SANITIZE_AUDIT_PATH = (
    PROJECT_ROOT
    / "reports/manual_review/semantic_independent_eval_v1_sanitize_audit.csv"
)
TRIAL_PATH = (
    PROJECT_ROOT / "reports/manual_review/semantic_independent_eval_v1_trial30.csv"
)
LINKAGE_AUDIT_PATH = (
    PROJECT_ROOT
    / "reports/manual_review/semantic_independent_eval_v1_repair_v2_linkage_audit.csv"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_rows():
    original = read_csv(ORIGINAL_PATH, CANDIDATE_FIELDS)
    eliminated = _load_eliminated_rows(original, SANITIZE_AUDIT_PATH, TRIAL_PATH)
    return original, eliminated


def test_replacement_specs_have_required_distribution_and_stable_ids():
    rows = build_replacement_rows()

    assert len(rows) == 40
    assert Counter(
        (row["label"], row["expected_action"]) for row in rows
    ) == EXPECTED_REPLACEMENTS
    assert len({row["sample_id"] for row in rows}) == 40
    assert all(
        row["sample_id"] == stable_sample_id(row["text"], row["label"])
        for row in rows
    )
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(row["reviewer"] == "" for row in rows)
    assert all(row["notes"] for row in rows)
    forbidden_meta_phrases = ("请删除", "应遮盖", "需要脱敏", "可脱敏保存")
    assert all(
        not any(phrase in row["text"] for phrase in forbidden_meta_phrases)
        for row in rows
    )
    sanitize_rows = [row for row in rows if row["expected_action"] == "sanitize"]
    v1_ids = {row["sample_id"] for row in build_repair_v1_references()}
    assert len(sanitize_rows) == 39
    assert v1_ids.isdisjoint({row["sample_id"] for row in sanitize_rows})
    assert Counter(
        "repair_v2_2" if "repair_v2_2" in row["source_reference"] else "repair_v2_1"
        for row in sanitize_rows
    ) == {"repair_v2_1": 35, "repair_v2_2": 4}
    assert not any("私 xing" in row["text"] for row in sanitize_rows)
    preserved_block = [row for row in rows if row["expected_action"] == "block"]
    assert len(preserved_block) == 1
    assert (
        preserved_block[0]["source_reference"]
        == "curated_independent_v1_repaired:porn:block:01"
    )


def test_repaired_candidates_replace_exactly_40_and_preserve_160():
    original, eliminated = _source_rows()
    repaired, replacements, manifest = build_repaired_candidates(
        original, eliminated
    )
    validate_candidate_rows(repaired)

    eliminated_ids = {row["sample_id"] for row in eliminated}
    replacement_ids = {row["sample_id"] for row in replacements}
    repaired_by_id = {row["sample_id"]: row for row in repaired}
    retained = [row for row in original if row["sample_id"] not in eliminated_ids]

    assert len(original) == 200
    assert len(eliminated) == 40
    assert len(retained) == 160
    assert len(repaired) == 200
    assert len(replacements) == 40
    assert len(manifest) == 40
    assert eliminated_ids.isdisjoint(repaired_by_id)
    assert replacement_ids <= set(repaired_by_id)
    assert PORN_BLOCK_REJECTED_ID not in repaired_by_id
    assert all(repaired_by_id[row["sample_id"]] == row for row in retained)
    assert Counter(
        (row["label"], row["expected_action"]) for row in eliminated
    ) == EXPECTED_REPLACEMENTS
    assert Counter(
        (row["label"], row["expected_action"]) for row in replacements
    ) == EXPECTED_REPLACEMENTS
    assert {row["old_sample_id"] for row in manifest} == eliminated_ids
    assert {row["new_sample_id"] for row in manifest} == replacement_ids
    assert all(set(MANIFEST_FIELDS) <= set(row) for row in manifest)


def test_repository_repaired_outputs_match_builder_and_pass_audit():
    original, eliminated = _source_rows()
    expected_rows, _, expected_manifest = build_repaired_candidates(
        original, eliminated
    )
    repaired_path = (
        PROJECT_ROOT
        / "data/evaluation/semantic_independent_eval_v1_repaired_candidates.csv"
    )
    manifest_path = (
        PROJECT_ROOT
        / "data/evaluation/semantic_independent_eval_v1_replacement_manifest.csv"
    )
    review_path = (
        PROJECT_ROOT
        / "reports/manual_review/semantic_independent_eval_v1_repaired_review_template.csv"
    )
    report_dir = PROJECT_ROOT / "reports/data_audit_semantic_gold_v1_repaired"

    repaired_rows = read_csv(repaired_path, CANDIDATE_FIELDS)
    review_rows = read_csv(review_path, CANDIDATE_FIELDS)
    manifest_rows = read_csv(manifest_path, MANIFEST_FIELDS)
    new_coverage = json.loads(
        (report_dir / "new_candidates/coverage.json").read_text(encoding="utf-8")
    )
    repaired_coverage = json.loads(
        (report_dir / "repaired_candidates/coverage.json").read_text(
            encoding="utf-8"
        )
    )
    linkage_coverage = json.loads(
        (report_dir / "semantic_linkage_audit_v2_2.json").read_text(encoding="utf-8")
    )
    targeted_coverage = json.loads(
        (report_dir / "v2_2_targeted_candidates/coverage.json").read_text(
            encoding="utf-8"
        )
    )
    structure_coverage = json.loads(
        (report_dir / "structure_audit.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (report_dir / "summary.json").read_text(encoding="utf-8")
    )

    assert repaired_rows == expected_rows
    assert review_rows == expected_rows
    assert manifest_rows == expected_manifest
    for coverage in (targeted_coverage, new_coverage, repaired_coverage):
        assert coverage["hard_overlap_passed"] is True
        assert coverage["duplicate_sample_id_count"] == 0
        assert coverage["exact_overlap_count"] == 0
        assert coverage["nfkc_overlap_count"] == 0
        assert coverage["text_normalizer_overlap_count"] == 0
        assert coverage["training_source_overlap_count"] == 0
        assert coverage["old_evaluation_overlap_count"] == 0
        assert coverage["eliminated_text_overlap_count"] == 0
        assert coverage["label_conflict_count"] == 0
        assert coverage["repair_v1_text_overlap_count"] == 0
        assert coverage["repair_v1_overlap_by_match_type"] == {
            "exact": 0,
            "nfkc": 0,
            "text_normalizer": 0,
        }
    assert structure_coverage["structure_audit_passed"] is True
    assert summary["generation_version"] == GENERATION_VERSION
    assert summary["structure_audit_passed"] is True
    assert linkage_coverage["semantic_linkage_audit_passed"] is True
    assert linkage_coverage["unlinked_count"] == 0
    assert linkage_coverage["pending_count"] == 0
    assert summary["semantic_linkage_audit_passed"] is True
    assert summary["v2_2_targeted_candidates_audit_passed"] is True
    assert summary["verified_sanitize_candidate_count"] == 35
    assert summary["verified_sanitize_candidates_unchanged"] is True
    assert (
        summary["verified_sanitize_sample_text_sha256_before"]
        == summary["verified_sanitize_sample_text_sha256_after"]
    )


def test_repair_generation_is_byte_reproducible_and_offline(
    tmp_path, monkeypatch
):
    def fail_network(*args, **kwargs):
        raise AssertionError("external API access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    original_hashes = {
        relative: _sha256(PROJECT_ROOT / relative)
        for relative in ORIGINAL_BASELINE_PATHS
    }
    output = tmp_path / "repaired_candidates.csv"
    manifest = tmp_path / "replacement_manifest.csv"
    review = tmp_path / "review_template.csv"
    report_dir = tmp_path / "audit"

    def generate():
        return run_repair(
            PROJECT_ROOT,
            ORIGINAL_PATH,
            SANITIZE_AUDIT_PATH,
            TRIAL_PATH,
            output,
            manifest,
            review,
            report_dir,
        )

    generate()
    first = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }
    generate()
    second = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    assert first == second
    assert review.is_file()
    assert {
        relative: _sha256(PROJECT_ROOT / relative)
        for relative in ORIGINAL_BASELINE_PATHS
    } == original_hashes


def test_failed_audit_does_not_generate_review_template(
    tmp_path, monkeypatch
):
    def failed_audit(*args, **kwargs):
        return {"hard_overlap_passed": False}

    monkeypatch.setattr(repaired_builder, "audit_repaired_rows", failed_audit)
    review = tmp_path / "review_template.csv"

    with pytest.raises(RuntimeError, match="audit failed"):
        run_repair(
            PROJECT_ROOT,
            ORIGINAL_PATH,
            SANITIZE_AUDIT_PATH,
            TRIAL_PATH,
            tmp_path / "repaired_candidates.csv",
            tmp_path / "replacement_manifest.csv",
            review,
            tmp_path / "audit",
        )

    assert not review.exists()

def test_structure_metadata_meets_repair_v2_gates(tmp_path):
    metadata = build_structure_metadata()
    coverage = audit_structure_metadata(metadata, tmp_path)

    assert len(metadata) == 39
    assert coverage["structure_audit_passed"] is True
    assert coverage["meta_instruction_count"] == 0
    assert coverage["duplicate_template_signature_count"] == 0
    assert coverage["unnatural_obfuscation_count"] == 0
    assert coverage["mechanical_pairing_count"] == 0
    assert coverage["missing_risk_fragment_count"] == 0
    assert coverage["invalid_sanitized_text_count"] == 0
    assert coverage["obvious_two_part_ratio"] < 0.40
    for label, expected in {"ad": 9, "porn": 10, "violence": 10, "sensitive": 10}.items():
        label_result = coverage["by_label"][label]
        assert label_result["count"] == expected
        assert label_result["structure_type_count"] >= 4
        assert label_result["sanitize_operation_type_count"] >= 3
        assert label_result["max_structure_ratio"] <= 0.40
        assert label_result["risk_at_end_ratio"] <= 0.40
        assert all(label_result["gates"].values())
    assert (tmp_path / "structure_metadata.csv").is_file()
    assert (tmp_path / "structure_audit.json").is_file()


def test_manifest_versions_distinguish_v2_2_targets_from_frozen_rows():
    original, eliminated = _source_rows()
    _, replacements, manifest = build_repaired_candidates(original, eliminated)
    replacement_by_id = {row["sample_id"]: row for row in replacements}

    sanitize_manifest = [row for row in manifest if row["expected_action"] == "sanitize"]
    block_manifest = [row for row in manifest if row["expected_action"] == "block"]
    assert len(sanitize_manifest) == 39
    targeted = [
        row
        for row in sanitize_manifest
        if row["old_sample_id"] in REPAIR_V2_2_REPLACED_OLD_IDS
    ]
    frozen = [
        row
        for row in sanitize_manifest
        if row["old_sample_id"] not in REPAIR_V2_2_REPLACED_OLD_IDS
    ]
    assert len(targeted) == 4
    assert len(frozen) == 35
    assert all(row["generation_version"] == GENERATION_VERSION for row in targeted)
    assert all("Repair V2.2" in row["replacement_reason"] for row in targeted)
    assert all(
        row["generation_version"] == REPAIR_V2_1_GENERATION_VERSION
        for row in frozen
    )
    assert all("Repair V2.1" in row["replacement_reason"] for row in frozen)
    assert len(block_manifest) == 1
    assert block_manifest[0]["generation_version"] == PORN_BLOCK_GENERATION_VERSION
    assert replacement_by_id[block_manifest[0]["new_sample_id"]]["expected_action"] == "block"


def test_repair_v1_hard_overlap_baseline_is_complete_and_unique():
    references = build_repair_v1_references()

    assert len(REPAIR_V1_SANITIZE_REFERENCES) == 39
    assert len(references) == 39
    assert len({row["sample_id"] for row in references}) == 39
    assert Counter(row["label"] for row in references) == {
        "ad": 9,
        "porn": 10,
        "violence": 10,
        "sensitive": 10,
    }


def test_repair_v2_historical_linkage_audit_is_frozen():
    rows = read_csv(LINKAGE_AUDIT_PATH, LINKAGE_AUDIT_FIELDS)

    assert len(rows) == 39
    assert len({row["sample_id"] for row in rows}) == 39
    assert Counter(row["linkage_status"] for row in rows) == {
        "linked": 36,
        "unlinked": 3,
    }
    assert {
        row["sample_id"] for row in rows if row["linkage_status"] == "unlinked"
    } == REPAIR_V2_UNLINKED_SAMPLE_IDS
    assert Counter(
        (row["label"], row["linkage_status"]) for row in rows
    ) == {
        ("ad", "linked"): 9,
        ("porn", "linked"): 8,
        ("porn", "unlinked"): 2,
        ("violence", "linked"): 10,
        ("sensitive", "linked"): 9,
        ("sensitive", "unlinked"): 1,
    }
    assert all(row["legal_context"] for row in rows)
    assert all(row["risk_fragment"] in row["text"] for row in rows)
    assert all(row["linkage_reason"] for row in rows)


def test_repair_v2_2_replaces_only_four_human_rejected_candidates():
    sanitize_review_path = (
        PROJECT_ROOT
        / "reports/manual_review/"
        "semantic_independent_eval_v1_repair_v2_1_sanitize_review.csv"
    )
    repaired_path = (
        PROJECT_ROOT
        / "data/evaluation/semantic_independent_eval_v1_repaired_candidates.csv"
    )
    review_rows = read_csv(sanitize_review_path, CANDIDATE_FIELDS)
    repaired_rows = read_csv(repaired_path, CANDIDATE_FIELDS)
    verified = {
        row["sample_id"]: row["text"]
        for row in review_rows
        if row["review_status"] == "verified"
    }
    current = {row["sample_id"]: row["text"] for row in repaired_rows}

    assert len(verified) == 35
    assert set(verified) <= set(current)
    assert all(current[sample_id] == text for sample_id, text in verified.items())
    assert REPAIR_V2_2_REJECTED_SAMPLE_IDS.isdisjoint(current)

    original, eliminated = _source_rows()
    _, replacements, manifest = build_repaired_candidates(original, eliminated)
    targeted_manifest = [
        row
        for row in manifest
        if row["old_sample_id"] in REPAIR_V2_2_REPLACED_OLD_IDS
    ]
    targeted_ids = {row["new_sample_id"] for row in targeted_manifest}
    targeted_rows = [
        row for row in replacements if row["sample_id"] in targeted_ids
    ]

    assert len(targeted_manifest) == 4
    assert len(targeted_rows) == 4
    assert Counter(row["label"] for row in targeted_rows) == {
        "violence": 1,
        "sensitive": 3,
    }
    assert all(
        "repair_v2_2" in row["source_reference"] for row in targeted_rows
    )


def test_repair_v2_1_replaces_only_unlinked_v2_sample_ids():
    historical = read_csv(LINKAGE_AUDIT_PATH, LINKAGE_AUDIT_FIELDS)
    historical_ids = {row["sample_id"] for row in historical}
    replacements = build_replacement_rows()
    sanitize_rows = [
        row for row in replacements if row["expected_action"] == "sanitize"
    ]
    current_ids = {row["sample_id"] for row in sanitize_rows}

    assert len(current_ids) == 39
    assert len(current_ids & historical_ids) == 32
    assert current_ids.isdisjoint(
        REPAIR_V2_UNLINKED_SAMPLE_IDS | REPAIR_V2_2_REJECTED_SAMPLE_IDS
    )

    original, eliminated = _source_rows()
    _, _, manifest = build_repaired_candidates(original, eliminated)
    targeted = [
        row for row in manifest if row["old_sample_id"] in REPAIR_V2_1_REPLACED_OLD_IDS
    ]
    assert len(targeted) == 3
    assert all(
        row["generation_version"] == REPAIR_V2_1_GENERATION_VERSION
        for row in targeted
    )
    assert all("语义关联专项修复" in row["replacement_reason"] for row in targeted)


def test_semantic_linkage_metadata_meets_v2_2_gate(tmp_path):
    rows = build_semantic_linkage_audit()
    coverage = audit_semantic_linkage(
        rows,
        {row["sample_id"] for row in build_structure_metadata()},
        tmp_path,
        generation_version=GENERATION_VERSION,
        forbidden_sample_ids=(
            REPAIR_V2_UNLINKED_SAMPLE_IDS | REPAIR_V2_2_REJECTED_SAMPLE_IDS
        ),
    )

    assert len(rows) == 39
    assert coverage["linked_count"] == 39
    assert coverage["unlinked_count"] == 0
    assert coverage["pending_count"] == 0
    assert coverage["strict_structure_missing_reason_count"] == 0
    assert coverage["forbidden_sample_ids_present"] == []
    assert coverage["semantic_linkage_audit_passed"] is True
    assert all(coverage["gates"].values())
    assert (tmp_path / "semantic_linkage_audit_v2_2.csv").is_file()
    assert (tmp_path / "semantic_linkage_audit_v2_2.json").is_file()


def test_semantic_linkage_gate_rejects_unlinked_status(tmp_path):
    rows = build_semantic_linkage_audit()
    rows[0] = {**rows[0], "linkage_status": "unlinked"}
    coverage = audit_semantic_linkage(
        rows,
        {row["sample_id"] for row in build_structure_metadata()},
        tmp_path,
        generation_version=GENERATION_VERSION,
        forbidden_sample_ids=(
            REPAIR_V2_UNLINKED_SAMPLE_IDS | REPAIR_V2_2_REJECTED_SAMPLE_IDS
        ),
    )

    assert coverage["unlinked_count"] == 1
    assert coverage["semantic_linkage_audit_passed"] is False
    assert coverage["gates"]["unlinked_count_zero"] is False

def test_failed_structure_gate_removes_stale_review_template(tmp_path, monkeypatch):
    monkeypatch.setattr(
        repaired_builder,
        "audit_repaired_rows",
        lambda *args, **kwargs: {"hard_overlap_passed": True},
    )
    monkeypatch.setattr(
        repaired_builder,
        "audit_structure_metadata",
        lambda *args, **kwargs: {"structure_audit_passed": False},
    )
    review = tmp_path / "review_template.csv"
    review.write_text("stale", encoding="utf-8")

    with pytest.raises(RuntimeError, match="audit failed"):
        run_repair(
            PROJECT_ROOT,
            ORIGINAL_PATH,
            SANITIZE_AUDIT_PATH,
            TRIAL_PATH,
            tmp_path / "repaired_candidates.csv",
            tmp_path / "replacement_manifest.csv",
            review,
            tmp_path / "audit",
        )

    assert not review.exists()
