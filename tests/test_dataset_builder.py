import csv

from scripts.build_clean_dataset import build_clean_dataset
from scripts.data_baseline_common import stable_id
import scripts.build_evaluation_sets as evaluation_builder


def write_input(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_clean_builder_is_stable_preserves_utf8_and_input(tmp_path):
    input_path = tmp_path / "raw.csv"
    rows = [
        {"text": "加薇领取资料📱", "label": " AD "},
        {"text": "加薇领取资料📱", "label": "ad"},
        {"text": "天气很好", "label": "NORMAL"},
    ]
    write_input(input_path, rows)
    original = input_path.read_bytes()

    outputs = []
    for suffix in ("one", "two"):
        output = tmp_path / f"{suffix}.csv"
        review = tmp_path / suffix / "review.csv"
        build_clean_dataset(input_path, output, review)
        outputs.append(output.read_bytes())

    assert input_path.read_bytes() == original
    assert outputs[0] == outputs[1]
    clean = read_rows(tmp_path / "one.csv")
    assert len(clean) == 2
    assert clean[0]["sample_id"]
    assert any(row["text"] == "加薇领取资料📱" for row in clean)
    assert {row["label"] for row in clean} == {"ad", "normal"}


def test_conflicts_go_to_review_and_invalid_rows_are_counted(tmp_path):
    input_path = tmp_path / "raw.csv"
    write_input(
        input_path,
        [
            {"text": "同一文本", "label": "normal"},
            {"text": "同一文本", "label": "ad"},
            {"text": "", "label": "normal"},
            {"text": "非法", "label": "other"},
        ],
    )
    output = tmp_path / "clean.csv"
    review = tmp_path / "reports/review.csv"

    summary = build_clean_dataset(input_path, output, review)

    assert summary["conflicting_text_groups"] == 1
    assert summary["manual_review_rows"] == 2
    assert summary["removed_empty_or_missing"] == 1
    assert summary["invalid_labels"] == 1
    assert read_rows(output) == []
    assert {row["reason"] for row in read_rows(review)} == {"conflicting_labels"}


def test_sample_id_is_stable():
    first = stable_id("中文文本", "normal", "source")

    assert first == stable_id("中文文本", "normal", "source")
    assert first != stable_id("中文文本", "ad", "source")


def make_evaluation_root(tmp_path, normal_lines):
    data = tmp_path / "data"
    maps = data / "maps"
    maps.mkdir(parents=True)
    (data / "normal_sentences.txt").write_text(
        "\n".join(normal_lines) + "\n",
        encoding="utf-8",
    )
    for name in (
        "homophone_map.json", "emoji_map.json", "variant_char_map.json",
        "pinyin_map.json", "abbreviation_map.json",
    ):
        (maps / name).write_text("{}\n", encoding="utf-8")
    return tmp_path


def test_final_selection_deduplicates_candidates_from_two_sources(tmp_path):
    root = make_evaluation_root(tmp_path, [])
    seen = {}
    candidates = [
        ("同一候选", "contextual", "source_a"),
        ("同一候选", "research", "source_b"),
        ("未使用候选", "contextual", "source_b"),
    ]

    selected = evaluation_builder.select_unique_candidates(
        candidates, "normal", 2, root, seen
    )

    assert [row["text"] for row in selected] == ["同一候选", "未使用候选"]


def test_final_selection_deduplicates_exact_strip_casefold_nfkc_and_normalized(tmp_path):
    root = make_evaluation_root(tmp_path, [])
    candidates = [
        ("Test", "contextual", "a"),
        (" Test ", "contextual", "b"),
        ("test", "contextual", "c"),
        ("Ｔｅｓｔ", "contextual", "d"),
        ("唯一文本", "contextual", "e"),
    ]

    selected = evaluation_builder.select_unique_candidates(
        candidates, "normal", 10, root, {}
    )

    assert [row["text"] for row in selected] == ["Test", "唯一文本"]
    assert len({row["sample_id"] for row in selected}) == len(selected)
    assert len({row["text"] for row in selected}) == len(selected)


def test_normal_quota_uses_only_unselected_candidates(tmp_path, monkeypatch):
    root = make_evaluation_root(
        tmp_path,
        ["重复文本", "重复文本", "候选二", "候选三", "候选四", "候选五"],
    )
    monkeypatch.setattr(evaluation_builder, "TARGETS", {"normal": 5})
    monkeypatch.setattr(
        evaluation_builder,
        "CONTEXT_CANDIDATES",
        (("重复文本", "contextual"),),
    )
    output = tmp_path / "baseline.csv"

    rows = evaluation_builder.build_baseline(root, output)

    assert len(rows) == 5
    assert len({row["sample_id"] for row in rows}) == 5
    assert len({row["text"] for row in rows}) == 5
    assert {row["text"] for row in rows} == {
        "重复文本", "候选二", "候选三", "候选四", "候选五"
    }


def test_candidate_shortfall_is_reported_without_copying(tmp_path, monkeypatch):
    root = make_evaluation_root(tmp_path, ["唯一一", "唯一一", "唯一二"])
    monkeypatch.setattr(evaluation_builder, "TARGETS", {"normal": 5})
    monkeypatch.setattr(evaluation_builder, "CONTEXT_CANDIDATES", ())

    rows = evaluation_builder.build_baseline(root, tmp_path / "baseline.csv")
    coverage = evaluation_builder.baseline_coverage(rows)

    assert len(rows) == 2
    assert coverage["normal"] == {
        "target_count": 5,
        "actual_count": 2,
        "unique_count": 2,
        "shortfall": 3,
    }


def test_baseline_generation_is_byte_deterministic(tmp_path, monkeypatch):
    root = make_evaluation_root(tmp_path, ["文本一", "文本二", "文本三"])
    monkeypatch.setattr(evaluation_builder, "TARGETS", {"normal": 3})
    monkeypatch.setattr(evaluation_builder, "CONTEXT_CANDIDATES", ())
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"

    evaluation_builder.build_baseline(root, first)
    evaluation_builder.build_baseline(root, second)

    assert first.read_bytes() == second.read_bytes()
