import json

from safechat_guard.rule_filter import RuleFilter
from safechat_guard.sanitizer import Sanitizer


def make_filter(tmp_path):
    lexicons = tmp_path / "lexicons"
    lexicons.mkdir()
    rules = tmp_path / "regex_rules.json"
    rules.write_text(
        json.dumps(
            [
                {"category": "ad", "pattern": r"1[3-9]\d{9}", "score": 55},
                {
                    "category": "ad",
                    "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    "score": 60,
                },
                {"category": "ad", "pattern": r"https?://[^\s]+", "score": 80},
                {"category": "ad", "pattern": "[invalid", "score": 80},
            ]
        ),
        encoding="utf-8",
    )
    return RuleFilter(str(lexicons), str(rules))


def test_regex_detections_store_real_matches(tmp_path):
    rule_filter = make_filter(tmp_path)
    text = (
        "电话13812345678或13987654321，邮箱user@example.com，"
        "网址https://example.com/path"
    )

    detections = rule_filter.detect(text)
    matches = [match for detection in detections for match in detection.matches]

    assert "13812345678" in matches
    assert "13987654321" in matches
    assert "user@example.com" in matches
    assert "https://example.com/path" in matches
    assert len(rule_filter.regex_rules) == 3


def test_repeated_regex_values_are_stably_deduplicated(tmp_path):
    detections = make_filter(tmp_path).detect(
        "13812345678 13812345678 13987654321"
    )

    assert detections[0].matches == ["13812345678", "13987654321"]


def test_sanitizer_replaces_regex_match_values(tmp_path):
    text = "联系13812345678或user@example.com"
    detections = make_filter(tmp_path).detect(text)
    matches = [match for detection in detections for match in detection.matches]

    sanitized = Sanitizer().sanitize(text, matches)

    assert "13812345678" not in sanitized
    assert "user@example.com" not in sanitized
    assert sanitized.count("***") == 2


def test_sanitizer_uses_contact_placeholder_and_generic_fallback():
    sanitized = Sanitizer().sanitize(
        "加微信领取优惠券，普通敏感片段",
        ["普通敏感片段", "加微信", ""],
    )

    assert sanitized == "[联系方式已隐藏]领取优惠券，***"