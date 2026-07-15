from __future__ import annotations

import csv
import json
import socket
from pathlib import Path

import pytest

from safechat_guard.semantic_classifier import SemanticClassifier
from scripts.semantic_baseline_v2_common import (
    LABELS,
    SOURCE_FILES,
    build_semantic_data,
    evaluate_candidates,
    find_cross_split_leakage,
    read_split_manifest,
    split_xy,
    train_candidates,
)


def _write_project_data(root: Path, *, include_conflict: bool = False) -> None:
    map_dir = root / "data/maps"
    map_dir.mkdir(parents=True)
    for name in (
        "homophone_map.json",
        "emoji_map.json",
        "symbol_variant_map.json",
        "variant_char_map.json",
        "pinyin_map.json",
        "abbreviation_map.json",
    ):
        (map_dir / name).write_text("{}\n", encoding="utf-8")

    prefixes = {
        "normal": "日常天气散步",
        "ad": "广告联系购买",
        "porn": "色情低俗内容",
        "violence": "暴力威胁攻击",
        "sensitive": "敏感争议话题",
    }
    suffixes = "甲乙丙丁戊己庚辛壬癸子丑"
    for label, relative_path in SOURCE_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{prefixes[label]}{suffix}" for suffix in suffixes]
        if label == "normal":
            lines.append(lines[0])
            if include_conflict:
                lines.append("ＡＢＣ冲突")
        if label == "ad" and include_conflict:
            lines.append("abc冲突")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_same_seed_produces_identical_split_manifest(tmp_path):
    project = tmp_path / "project"
    _write_project_data(project)
    build_semantic_data(project, tmp_path / "run_a", seed=42)
    build_semantic_data(project, tmp_path / "run_b", seed=42)
    assert (tmp_path / "run_a/split_manifest.csv").read_bytes() == (
        tmp_path / "run_b/split_manifest.csv"
    ).read_bytes()


def test_group_and_text_equivalence_do_not_cross_splits(tmp_path):
    project = tmp_path / "project"
    output = tmp_path / "reports"
    _write_project_data(project)
    manifest = build_semantic_data(project, output)
    rows = read_split_manifest(output / "split_manifest.csv")
    assert len({row["group_id"] for row in rows}) == len(rows)
    assert find_cross_split_leakage(rows) == []
    assert manifest["cross_split_leakage_count"] == 0
    assert _read_csv(output / "leakage_report.csv") == []


def test_only_allowlisted_sources_are_read_and_paths_are_portable(tmp_path):
    project = tmp_path / "project"
    output = tmp_path / "reports"
    _write_project_data(project)
    evaluation = project / "data/evaluation"
    evaluation.mkdir(parents=True)
    (evaluation / "must_not_be_read.csv").write_text(
        "text,label\n评估陷阱,normal\n", encoding="utf-8"
    )
    manifest = build_semantic_data(project, output)
    expected = [path for _, path in SOURCE_FILES]
    assert manifest["build_parameters"]["source_allowlist"] == expected
    assert manifest["build_parameters"]["evaluation_data_used"] is False
    assert [item["path"] for item in manifest["source_files"]] == expected
    assert all(
        "\\" not in row["source_file"]
        for row in read_split_manifest(output / "split_manifest.csv")
    )


def test_multi_label_normalized_conflict_is_isolated(tmp_path):
    project = tmp_path / "project"
    output = tmp_path / "reports"
    _write_project_data(project, include_conflict=True)
    manifest = build_semantic_data(project, output)
    rows = read_split_manifest(output / "split_manifest.csv")
    conflicts = _read_csv(output / "label_conflict_report.csv")
    assert manifest["conflict_group_count"] == 1
    assert conflicts[0]["normalized_text"] == "abc冲突"
    assert conflicts[0]["labels"] == "ad|normal"
    assert all(row["normalized_text"] != "abc冲突" for row in rows)


@pytest.fixture(scope="module")
def miniature_experiment(tmp_path_factory):
    root = tmp_path_factory.mktemp("semantic_v2")
    project = root / "project"
    output = root / "reports"
    models = root / "models"
    _write_project_data(project)
    build_semantic_data(project, output)
    comparison = train_candidates(output / "split_manifest.csv", output, models)
    result = evaluate_candidates(
        project, output / "split_manifest.csv", output, models
    )
    return output, models, comparison, result


def test_word_and_char_share_manifest_and_use_plain_string_lists(
    miniature_experiment,
):
    output, _, comparison, _ = miniature_experiment
    rows = read_split_manifest(output / "split_manifest.csv")
    texts, labels = split_xy(rows, "train")
    run_config = json.loads((output / "run_config.json").read_text(encoding="utf-8"))
    word = json.loads((output / "word_metrics.json").read_text(encoding="utf-8"))
    char = json.loads((output / "char_metrics.json").read_text(encoding="utf-8"))
    assert isinstance(texts, list) and all(isinstance(item, str) for item in texts)
    assert isinstance(labels, list) and all(isinstance(item, str) for item in labels)
    assert run_config["split_manifest_sha256"]
    assert word["validation"]["sample_count"] == char["validation"]["sample_count"]
    assert comparison["test_metrics_used_for_selection"] is False


def test_real_joblib_model_loads_and_returns_labelled_probabilities(
    miniature_experiment,
):
    _, models, _, _ = miniature_experiment
    classifier = SemanticClassifier(model_path=str(models / "semantic_model_v2.joblib"))
    status = classifier.status()
    probabilities = classifier.model.predict_proba(["广告联系购买甲"])
    assert status["loaded"] is True
    assert set(status["classes"]) == set(LABELS)
    assert probabilities.shape == (1, len(LABELS))
    assert probabilities[0].sum() == pytest.approx(1.0)
    assert set(classifier.model.classes_) == set(LABELS)


def test_missing_model_safely_degrades_without_repository_artifact(tmp_path):
    classifier = SemanticClassifier(model_path=str(tmp_path / "not_present.joblib"))
    assert classifier.status()["loaded"] is False
    assert classifier.status()["error"] == "model file not found"
    assert classifier.detect("中文输入") == []


def test_training_smoke_does_not_call_external_api(tmp_path, monkeypatch):
    project = tmp_path / "project"
    output = tmp_path / "reports"
    models = tmp_path / "models"
    _write_project_data(project)
    build_semantic_data(project, output)

    def fail_network(*args, **kwargs):
        raise AssertionError("external network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = train_candidates(output / "split_manifest.csv", output, models)
    assert result["selected_model"] in {"word", "char"}
    assert all(
        (models / f"semantic_{kind}_v2.candidate.joblib").is_file()
        for kind in ("word", "char")
    )
