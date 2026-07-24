from __future__ import annotations

import csv
import json
import socket
from pathlib import Path

import pytest

from safechat_guard.models import Detection
from scripts.audit_independent_eval_v1 import audit_independent_eval
from scripts.build_independent_eval_v1_candidates import build_candidates
from scripts.build_semantic_gold_v1 import build_gold
from scripts.evaluate_system_v1 import MODES, evaluate_rows, load_gold
from scripts.independent_eval_v1_common import (
    CANDIDATE_FIELDS,
    GOLD_FIELDS,
    LABELS,
    make_normalizer,
    normalized_group_id,
    read_csv,
    stable_sample_id,
    write_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_candidate_distribution_fields_pending_and_stable_ids():
    rows = build_candidates()

    assert len(rows) == 200
    assert all(set(CANDIDATE_FIELDS) <= set(row) for row in rows)
    assert sum(row["label"] == "normal" for row in rows) == 100
    for label in ("ad", "porn", "violence", "sensitive"):
        label_rows = [row for row in rows if row["label"] == label]
        assert len(label_rows) == 25
        assert sum(row["expected_action"] == "sanitize" for row in label_rows) == 10
        assert sum(row["expected_action"] == "block" for row in label_rows) == 15
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(row["reviewer"] == "" for row in rows)
    assert len({row["sample_id"] for row in rows}) == 200
    assert all(
        row["sample_id"] == stable_sample_id(row["text"], row["label"])
        for row in rows
    )
    assert build_candidates() == rows


def test_review_template_initially_matches_candidates():
    candidates = read_csv(
        PROJECT_ROOT / "data/evaluation/semantic_independent_eval_v1_candidates.csv",
        CANDIDATE_FIELDS,
    )
    review = read_csv(
        PROJECT_ROOT / "reports/manual_review/semantic_independent_eval_v1_review_template.csv",
        CANDIDATE_FIELDS,
    )

    assert review == candidates


@pytest.fixture(scope="module")
def repository_audit(tmp_path_factory):
    report_dir = tmp_path_factory.mktemp("independent_eval_audit")
    coverage = audit_independent_eval(
        PROJECT_ROOT,
        PROJECT_ROOT / "data/evaluation/semantic_independent_eval_v1_candidates.csv",
        report_dir,
    )
    return coverage, report_dir


def test_no_exact_nfkc_or_normalizer_overlap_with_existing_data(repository_audit):
    coverage, report_dir = repository_audit

    assert coverage["exact_overlap_count"] == 0
    assert coverage["nfkc_overlap_count"] == 0
    assert coverage["text_normalizer_overlap_count"] == 0
    assert coverage["duplicate_sample_id_count"] == 0
    assert read_csv(report_dir / "exact_overlap.csv") == []
    assert read_csv(report_dir / "normalized_overlap.csv") == []


def _write_empty_maps(project: Path) -> None:
    maps = project / "data/maps"
    maps.mkdir(parents=True)
    for name in (
        "homophone_map.json",
        "emoji_map.json",
        "symbol_variant_map.json",
        "variant_char_map.json",
        "pinyin_map.json",
        "abbreviation_map.json",
    ):
        (maps / name).write_text("{}\n", encoding="utf-8")


def _write_audit_references(project: Path) -> None:
    references = {
        "data/normal_sentences.txt": "周末准备去河边骑车，记得带上水和遮阳伞。\n",
        "data/violation_sentences/ad.txt": "独立广告参考文本甲\n",
        "data/violation_sentences/porn.txt": "独立色情参考文本乙\n",
        "data/violation_sentences/violence.txt": "独立暴力参考文本丙\n",
        "data/violation_sentences/sensitive.txt": "独立敏感参考文本丁\n",
    }
    for relative, content in references.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for name in (
        "baseline_eval_v1.csv",
        "adversarial_eval_v1.csv",
        "adversarial_eval_v2.csv",
        "adversarial_eval_v3.csv",
    ):
        path = project / "data/evaluation" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"sample_id,text,label\nref_{name},完全不同的评估参考句子,normal\n",
            encoding="utf-8",
        )


def test_high_similarity_candidate_is_reported_without_auto_deletion(tmp_path):
    project = tmp_path / "project"
    report_dir = tmp_path / "reports"
    candidate_path = tmp_path / "candidates.csv"
    _write_empty_maps(project)
    _write_audit_references(project)
    write_csv(candidate_path, CANDIDATE_FIELDS, build_candidates())

    coverage = audit_independent_eval(
        project, candidate_path, report_dir, similarity_threshold=0.55
    )
    similarities = read_csv(report_dir / "high_similarity_candidates.csv")

    assert coverage["high_similarity_candidate_count"] >= 1
    assert any("河边骑车" in row["candidate_text"] for row in similarities)
    assert len(read_csv(candidate_path, CANDIDATE_FIELDS)) == 200


def _review_rows(status: str = "verified") -> list[dict[str, str]]:
    rows = build_candidates()
    for row in rows:
        row["review_status"] = status
        row["reviewer"] = "human_reviewer"
        row["notes"] = "人工审核完成"
    return rows


def test_incomplete_review_cannot_create_gold(tmp_path):
    review = tmp_path / "review.csv"
    output = tmp_path / "semantic_gold_v1.csv"
    write_csv(review, CANDIDATE_FIELDS, build_candidates())

    with pytest.raises(RuntimeError, match="人工审核尚未完成"):
        build_gold(PROJECT_ROOT, review, output)

    assert not output.exists()


def test_only_verified_rows_enter_gold(tmp_path):
    rows = _review_rows("rejected")
    rows[0]["review_status"] = "verified"
    review = tmp_path / "review.csv"
    output = tmp_path / "semantic_gold_v1.csv"
    write_csv(review, CANDIDATE_FIELDS, rows)

    gold = build_gold(PROJECT_ROOT, review, output)

    assert len(gold) == 1
    assert gold[0]["sample_id"] == rows[0]["sample_id"]
    assert gold[0]["review_status"] == "verified"


def test_gold_split_is_deterministic_and_has_no_group_leakage(tmp_path):
    review = tmp_path / "review.csv"
    first = tmp_path / "gold_first.csv"
    second = tmp_path / "gold_second.csv"
    write_csv(review, CANDIDATE_FIELDS, _review_rows())

    first_rows = build_gold(PROJECT_ROOT, review, first, seed=42)
    second_rows = build_gold(PROJECT_ROOT, review, second, seed=42)
    normalizer = make_normalizer(PROJECT_ROOT)
    groups: dict[str, set[str]] = {}
    for row in first_rows:
        group_id = normalized_group_id(row["text"], normalizer)
        groups.setdefault(group_id, set()).add(row["evaluation_split"])

    assert first.read_bytes() == second.read_bytes()
    assert len(first_rows) == 200
    assert sum(row["evaluation_split"] == "calibration" for row in first_rows) == 80
    assert sum(row["evaluation_split"] == "test" for row in first_rows) == 120
    assert all(len(splits) == 1 for splits in groups.values())
    assert all(set(GOLD_FIELDS) <= set(row) for row in second_rows)


class FakeDetector:
    def detect(self, text):
        for label in ("ad", "porn", "violence", "sensitive"):
            if label in text:
                score = 85 if "block" in text else 60
                return [
                    Detection(
                        category=label,
                        level="high" if score >= 80 else "medium",
                        score=score,
                        reason="test detector",
                        source="test",
                        matches=[label],
                    )
                ]
        return []


def _evaluation_rows():
    rows = []
    for index, label in enumerate(LABELS):
        action = "pass" if label == "normal" else "block"
        rows.append(
            {
                "sample_id": f"sample_{index}",
                "text": "ordinary pass" if label == "normal" else f"{label} block",
                "label": label,
                "expected_action": action,
            }
        )
    return rows


@pytest.mark.parametrize("mode", MODES)
def test_evaluation_modes_return_required_structure(mode, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("external API access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    detector = FakeDetector()
    metrics = evaluate_rows(
        _evaluation_rows(),
        mode,
        PROJECT_ROOT,
        rule_detector=detector if mode in {"rule_only", "combined"} else None,
        semantic_detector=detector if mode in {"semantic_only", "combined"} else None,
    )

    assert metrics["mode"] == mode
    assert {
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "normal_false_positive_rate",
        "high_risk_block_recall",
        "sanitize_routing_recall",
        "action_accuracy",
        "per_class",
        "confusion_matrix",
    } <= metrics.keys()
    assert set(metrics["per_class"]) == set(LABELS)
    assert metrics["action_interpretation"]["action_score_thresholds_tuned"] is False
    assert "不能区分" in metrics["action_interpretation"]["semantic_model_capability"]


def test_evaluator_never_falls_back_when_gold_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="不会回退使用训练数据"):
        load_gold(tmp_path / "semantic_gold_v1.csv")
