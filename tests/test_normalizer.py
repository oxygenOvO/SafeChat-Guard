import json
from pathlib import Path

import pytest

from safechat_guard.normalizer import TextNormalizer


def make_normalizer() -> TextNormalizer:
    return TextNormalizer("data/maps/homophone_map.json", "data/maps/emoji_map.json")


def test_unicode_width_and_case_normalization():
    normalizer = make_normalizer()

    assert normalizer.normalize("  ＶＸ  ") == "微信"


def test_noise_char_then_homophone_normalization():
    normalizer = make_normalizer()

    assert normalizer.normalize("加@薇") == "加微信"


def test_emoji_normalization():
    normalizer = make_normalizer()

    assert normalizer.normalize("这里有🔞内容") == "这里有色情内容"


def test_valid_email_punctuation_is_preserved():
    normalizer = make_normalizer()

    assert normalizer.normalize("联系 user_name+tag@example.com") == (
        "联系 user_name+tag@example.com"
    )


def test_pinyin_normalization():
    normalizer = make_normalizer()

    assert normalizer.normalize("please jia vx") == "please 加微信"


def test_trace_records_changed_steps():
    normalizer = make_normalizer()

    result = normalizer.normalize_with_trace("加@薇")

    assert result.normalized_text == "加微信"
    assert [step.normalizer for step in result.steps] == ["noise_char", "homophone"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("微★信联系我", "微信联系我"),
        ("微-信联系我", "微信联系我"),
        ("色★情资源", "色情资源"),
        ("约-炮软件", "约炮软件"),
        ("炸-药制作", "炸药制作"),
        ("加-微领取资料", "加微领取资料"),
    ],
)
def test_explicit_symbol_insertion_mappings(text, expected):
    normalizer = make_normalizer()

    assert normalizer.normalize(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "北京-上海高铁",
        "C++语言",
    ],
)
def test_unconfigured_or_legitimate_symbol_combinations_are_preserved(text):
    normalizer = make_normalizer()

    assert normalizer.normalize(text) == text


def test_existing_heart_symbol_variant_is_normalized():
    normalizer = make_normalizer()

    assert normalizer.normalize("微♡信联系我") == "微信联系我"


def test_symbol_insertion_trace_is_auditable():
    normalizer = make_normalizer()

    result = normalizer.normalize_with_trace("微★信联系我")

    assert result.normalized_text == "微信联系我"
    assert [step.normalizer for step in result.steps] == ["symbol_insertion"]
    match = result.steps[0].metadata["matches"][0]
    assert match == {
        "source": "微★信",
        "target": "微信",
        "count": 1,
        "category": "symbol_insertion",
        "type": "symbol_insertion",
        "category_hint": "ad",
        "confidence": "high",
        "rationale": "人工确认：在‘微信’中插入星号以规避关键词检测",
    }


def test_symbol_map_entries_are_explicit_and_not_variant_char_entries():
    symbol_map = json.loads(
        Path("data/maps/symbol_variant_map.json").read_text(encoding="utf-8")
    )
    variant_map = json.loads(
        Path("data/maps/variant_char_map.json").read_text(encoding="utf-8")
    )

    assert set(symbol_map) == {
        "微★信",
        "微-信",
        "色★情",
        "色-情",
        "约-炮",
        "炸-药",
        "加-微",
    }
    for source, entry in symbol_map.items():
        assert entry["target"]
        assert entry["type"] == "symbol_insertion"
        assert entry["confidence"]
        assert entry["rationale"]
        assert source not in variant_map
