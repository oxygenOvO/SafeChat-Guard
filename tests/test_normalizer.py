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
