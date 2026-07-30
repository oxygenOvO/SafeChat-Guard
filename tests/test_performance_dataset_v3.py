import json
from pathlib import Path

import pytest

from safechat_guard.normalizer import TextNormalizer


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports/performance_v3/dataset_audit.json"
EXPECTED_FIELDS = {
    "sample_id", "text", "label", "expected_action", "intent", "context",
    "template_family", "source_type", "split",
}


def test_dataset_audit_proves_split_isolation_without_opening_holdout_text():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert audit["fields"] == [
        "sample_id", "text", "label", "expected_action", "intent", "context",
        "template_family", "source_type", "split",
    ]
    assert audit["counts"]["train"]["total"] == 900
    assert audit["counts"]["dev"]["total"] == 270
    assert audit["counts"]["internal_holdout"]["total"] == 330
    assert audit["sample_id_unique"] is True
    assert audit["sample_id_duplicate_count"] == 0
    assert audit["exact_text_duplicate_count"] == 0
    assert audit["normalized_text_duplicate_count"] == 0
    assert audit["template_family_cross_split_count"] == 0
    assert audit["high_similarity_cross_split_pair_count"] == 0
    assert audit["retired_diagnostic_data_used"] is False
    assert audit["holdout_text_exposed_in_audit"] is False


def test_holdout_structure_is_frozen_by_header_count_and_hash_only():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    path = ROOT / audit["files"]["internal_holdout"]["path"]
    with path.open("rb") as handle:
        header = handle.readline().decode("utf-8-sig").strip().split(",")

    assert set(header) == EXPECTED_FIELDS
    assert audit["counts"]["internal_holdout"]["total"] == 330
    assert len(audit["files"]["internal_holdout"]["sha256"]) == 64


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("购 买 枪 支", "购买枪支"),
        ("私｜域｜团｜购", "私域团购"),
        ("裸 聊 入 口", "裸聊入口"),
        ("定 位 与 门 牌", "定位与门牌"),
    ],
)
def test_normalizer_compacts_symbol_and_space_variants(source, expected):
    normalizer = TextNormalizer(
        str(ROOT / "data/maps/homophone_map.json"),
        str(ROOT / "data/maps/emoji_map.json"),
    )

    assert expected in normalizer.normalize(source)
