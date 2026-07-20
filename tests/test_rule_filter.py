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


def make_context_filter(tmp_path):
    lexicons = tmp_path / "context_lexicons"
    lexicons.mkdir()
    (lexicons / "ad.txt").write_text("网络\n推广\n微信\n", encoding="utf-8")
    (lexicons / "sensitive.txt").write_text("谣言\n", encoding="utf-8")
    rules = tmp_path / "context_rules.json"
    rules.write_text("[]", encoding="utf-8")
    return RuleFilter(str(lexicons), str(rules))


def test_single_weak_keyword_is_ignored_in_clear_safe_context(tmp_path):
    rule_filter = make_context_filter(tmp_path)

    assert rule_filter.detect("这门课的网络攻击检测实验很有意思") == []
    assert rule_filter.detect("请解释一下如何识别谣言信息") == []


def test_safe_context_does_not_hide_additional_risk_matches(tmp_path):
    rule_filter = make_context_filter(tmp_path)

    detections = rule_filter.detect("网络安全课程也不能推广加微信")

    assert len(detections) == 1
    assert detections[0].category == "ad"
    assert set(detections[0].matches) == {"网络", "推广", "微信"}


def test_weak_keyword_without_safe_context_is_still_detected(tmp_path):
    rule_filter = make_context_filter(tmp_path)

    detections = rule_filter.detect("不要传播未经证实的谣言")

    assert len(detections) == 1
    assert detections[0].category == "sensitive"
    assert detections[0].matches == ["谣言"]
