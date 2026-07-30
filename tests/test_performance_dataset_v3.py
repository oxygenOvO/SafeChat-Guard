import json
from pathlib import Path
import subprocess

import pytest

from safechat_guard.normalizer import TextNormalizer


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reports/performance_v3/public_release_evidence_v3.json"
PRIVATE_RELEASE_PATHS = (
    "data/evaluation/performance_v3_internal_holdout.csv",
    "reports/performance_v3/internal_holdout_metrics.json",
)


def load_evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_dataset_audit_proves_split_isolation_without_opening_holdout_text():
    evidence = load_evidence()
    isolation = evidence["split_isolation"]

    assert evidence["split_counts"] == {"train": 900, "dev": 270, "holdout": 330}
    assert set(isolation["template_family_intersection_counts"].values()) == {0}
    assert set(isolation["raw_text_hash_intersection_counts"].values()) == {0}
    assert set(isolation["normalized_text_hash_intersection_counts"].values()) == {0}
    assert isolation["high_similarity_cross_split_pair_count"] == 0
    assert evidence["holdout_text_included"] is False


def test_holdout_structure_is_frozen_by_header_count_and_hash_only():
    evidence = load_evidence()

    assert evidence["sample_count"] == 330
    assert evidence["split_counts"]["holdout"] == 330
    assert len(evidence["holdout_dataset_sha256"]) == 64
    assert set(evidence["holdout_dataset_sha256"]) <= set("0123456789abcdef")
    assert evidence["execution_count"] == 1
    assert evidence["holdout_rerun"] is False


def test_public_git_tree_excludes_private_holdout_and_prediction_artifacts():
    result = subprocess.run(
        ["git", "ls-files", "--", *PRIVATE_RELEASE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    ignored = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())

    assert tracked == set()
    assert set(PRIVATE_RELEASE_PATHS) <= ignored


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
