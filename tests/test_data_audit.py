import csv
import json

from scripts.audit_training_data import audit_dataset
from scripts.data_baseline_common import find_leakage


def write_input(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(rows)


def test_audit_finds_empty_invalid_duplicate_and_conflict(tmp_path):
    input_path = tmp_path / "train.csv"
    report_dir = tmp_path / "reports"
    write_input(
        input_path,
        [
            {"text": "", "label": "normal"},
            {"text": "   ", "label": "normal"},
            {"text": "中文样本", "label": "normal"},
            {"text": "中文样本", "label": "ad"},
            {"text": "非法标签", "label": "other"},
        ],
    )

    summary = audit_dataset(input_path, report_dir, tmp_path)

    assert summary["missing_text"] == 1
    assert summary["blank_text"] == 1
    assert summary["invalid_labels"] == 1
    assert summary["exact_duplicate_groups"] == 1
    assert summary["conflicting_label_groups"] == 1
    assert (report_dir / "summary.json").exists()
    assert "中文样本" in (report_dir / "conflicting_labels.csv").read_text(encoding="utf-8")


def test_empty_issue_reports_keep_headers_and_are_deterministic(tmp_path):
    input_path = tmp_path / "clean.csv"
    write_input(input_path, [{"text": "天气很好", "label": "normal"}])
    first = tmp_path / "first"
    second = tmp_path / "second"

    audit_dataset(input_path, first, tmp_path)
    audit_dataset(input_path, second, tmp_path)

    for name in (
        "duplicate_rows.csv", "conflicting_labels.csv",
        "invalid_rows.csv", "leakage_candidates.csv",
    ):
        first_text = (first / name).read_text(encoding="utf-8")
        assert first_text.splitlines()[0]
        assert first_text == (second / name).read_text(encoding="utf-8")


def test_leakage_checks_nfkc_and_normalized_text(tmp_path):
    data_dir = tmp_path / "data/maps"
    data_dir.mkdir(parents=True)
    for name in ("homophone_map.json", "emoji_map.json", "variant_char_map.json", "pinyin_map.json", "abbreviation_map.json"):
        (data_dir / name).write_text("{}", encoding="utf-8")
    train = [{"sample_id": "train_1", "text": "ＶＸ", "label": "ad"}]
    evaluation = [{"sample_id": "eval_1", "text": "vx", "label": "ad"}]

    leakage = find_leakage(train, evaluation, tmp_path)

    assert leakage
    assert leakage[0]["match_type"] in {"nfkc", "normalized"}
