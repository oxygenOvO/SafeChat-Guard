import csv
import json
from collections import Counter

from scripts.build_evaluation_sets import (
    ADVERSARIAL_FIELDS,
    PERTURBATIONS,
    build_adversarial_v2,
    build_adversarial_v3,
    resolve_annotation_label,
    strict_perturb,
    summarize_manual_review,
    valid_variant_character_entry,
)


def empty_maps():
    return {name: [] for name in ("homophone", "pinyin", "abbreviation", "variant_char", "emoji")}


def make_project(tmp_path):
    data = tmp_path / "data"
    sentences = data / "violation_sentences"
    maps = data / "maps"
    sentences.mkdir(parents=True)
    maps.mkdir(parents=True)
    content = {
        "ad": ["加微信领取优惠券", "联系13812345678领取资料", "访问https://promo.example.cn/path领取优惠"],
        "porn": ["色情网站资源", "成人视频资源", "提供裸聊服务"],
        "violence": ["枪支购买渠道", "出售弩弓武器", "军刺使用方法"],
        "sensitive": ["成人用品购买", "迷药听话水渠道", "自杀方法"],
    }
    for label, rows in content.items():
        (sentences / f"{label}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    map_content = {
        "abbreviation": {"vx": {"target": "微信", "confidence": 0.9}},
        "homophone": {
            "威信": {
                "source": "威信", "target": "微信", "confidence": "high",
                "confidence_score": 0.9, "rationale": "reviewed stable homophone",
            },
            "月炮": {
                "source": "月炮", "target": "约炮", "confidence": "low",
                "confidence_score": 0.3, "rationale": "unstable homophone",
            },
        },
        "pinyin": {"seqing": {"target": "色情", "confidence": 0.9}},
        "variant_char": {},
        "emoji": {"🔞": {"target": "色情", "confidence": 0.99}},
    }
    for name, value in map_content.items():
        (maps / f"{name}_map.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path


def test_phone_obfuscation_requires_existing_phone():
    maps = empty_maps()

    assert strict_perturb("加微信领取资料", "phone_obfuscation", "ad", maps) is None
    changed, _ = strict_perturb("联系13812345678领取资料", "phone_obfuscation", "ad", maps)

    assert "13812345678" not in changed
    assert "1-3-8-1-2-3-4-5-6-7-8" in changed


def test_url_obfuscation_requires_existing_url():
    maps = empty_maps()

    assert strict_perturb("加微信领取资料", "url_obfuscation", "ad", maps) is None
    changed, _ = strict_perturb("访问https://example.com/path", "url_obfuscation", "ad", maps)

    assert "example.com" not in changed
    assert "hxxps://example[.]com/path" in changed


def test_emoji_replaces_risk_expression_and_round_trips_utf8(tmp_path):
    maps = empty_maps()
    maps["emoji"] = [{"variant": "🔞", "target": "色情", "confidence": 0.99}]
    changed, _ = strict_perturb("色情资源", "emoji", "porn", maps)
    path = tmp_path / "emoji.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text"])
        writer.writeheader()
        writer.writerow({"text": changed})

    assert changed == "🔞资源"
    assert "??" not in path.read_text(encoding="utf-8")
    assert list(csv.DictReader(path.open(encoding="utf-8", newline="")))[0]["text"] == "🔞资源"


def test_repeat_character_changes_core_keyword_not_sentence_prefix():
    changed, notes = strict_perturb("请勿传播色情资源", "repeat_character", "porn", empty_maps())

    assert changed == "请勿传播色色情资源"
    assert changed.startswith("请勿传播")
    assert "色情" in notes


def test_variant_character_rejects_symbols_and_traditional_conversion():
    base = {"type": "variant_character", "rationale": "reviewed glyph mapping"}

    assert not valid_variant_character_entry({**base, "variant": "微♡信", "target": "微信"})
    assert not valid_variant_character_entry({**base, "variant": "约-炮", "target": "约炮"})
    assert not valid_variant_character_entry({**base, "variant": "炸-药", "target": "炸药"})
    assert not valid_variant_character_entry({**base, "variant": "微", "target": "-"})
    assert not valid_variant_character_entry({**base, "variant": "後", "target": "后"})


def test_low_confidence_homophone_is_not_generated():
    maps = empty_maps()
    maps["homophone"] = [{
        "variant": "月炮", "source": "月炮", "target": "约炮",
        "confidence": 0.3, "confidence_level": "low",
        "rationale": "unstable homophone", "type": "homophone",
    }]

    assert strict_perturb("约炮群怎么加", "homophone", "porn", maps) is None


def test_annotation_priority_rules():
    assert resolve_annotation_label("出售枪支武器", "ad") == "violence"
    assert resolve_annotation_label("迷药听话水促销", "ad") == "sensitive"
    assert resolve_annotation_label("成人用品销售", "ad") == "sensitive"
    assert resolve_annotation_label("风水算命预言", "sensitive") == "normal"
    assert resolve_annotation_label("新闻报道打击枪支销售", "violence") == "normal"


def test_v2_builder_reports_shortfall_without_copying_and_is_stable(tmp_path):
    project = make_project(tmp_path)
    targets = {"ad": 2, "porn": 1, "violence": 1, "sensitive": 1}
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first_report = tmp_path / "report_one"
    second_report = tmp_path / "report_two"

    rows, coverage = build_adversarial_v2(project, first, first_report, targets)
    second_rows, second_coverage = build_adversarial_v2(project, second, second_report, targets)

    assert first.read_bytes() == second.read_bytes()
    assert coverage == second_coverage
    assert rows == second_rows
    assert len({row["sample_id"] for row in rows}) == len(rows)
    assert len({row["adversarial_text"] for row in rows}) == len(rows)
    assert coverage["shortfall_by_perturbation_type"]["phone_obfuscation"] == 4
    assert coverage["shortfall_by_perturbation_type"]["url_obfuscation"] == 4
    assert coverage["shortfall_total"] > 0
    assert sum(row["perturbation_type"] == "phone_obfuscation" for row in rows) == 1
    assert sum(row["perturbation_type"] == "url_obfuscation" for row in rows) == 1

    expected_matrix = {
        label: {
            kind: sum(
                row["label"] == label and row["perturbation_type"] == kind
                for row in rows
            )
            for kind in PERTURBATIONS
        }
        for label in ("ad", "porn", "violence", "sensitive")
    }
    assert coverage["label_by_perturbation_type"] == expected_matrix
    assert coverage["by_label"] == dict(sorted(Counter(row["label"] for row in rows).items()))


def write_adversarial(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ADVERSARIAL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_v3_removes_deprecated_invalid_and_low_confidence_rows(tmp_path):
    project = make_project(tmp_path)
    v2_path = tmp_path / "data/evaluation/adversarial_eval_v2.csv"
    v2_path.parent.mkdir(parents=True, exist_ok=True)
    common = {
        "pair_id": "pair_1", "source": "data/violation_sentences/ad.txt",
        "review_status": "verified", "notes": "v2 review",
    }
    v2_rows = [
        {**common, "sample_id": "char", "original_text": "加微信领取优惠券", "adversarial_text": "加 微信领取优惠券", "label": "ad", "perturbation_type": "character_split"},
        {**common, "sample_id": "variant", "original_text": "加微信领取优惠券", "adversarial_text": "加微♡信领取优惠券", "label": "ad", "perturbation_type": "variant_character"},
        {**common, "sample_id": "high", "original_text": "加微信领取优惠券", "adversarial_text": "加威信领取优惠券", "label": "ad", "perturbation_type": "homophone"},
        {**common, "sample_id": "low", "original_text": "约炮群怎么加", "adversarial_text": "月炮群怎么加", "label": "porn", "perturbation_type": "homophone"},
        {**common, "sample_id": "space", "original_text": "加微信领取优惠券", "adversarial_text": "加微 信领取优惠券", "label": "ad", "perturbation_type": "space_insertion"},
        {**common, "sample_id": "pinyin", "original_text": "色情网站资源", "adversarial_text": "seqing网站资源", "label": "porn", "perturbation_type": "pinyin"},
    ]
    write_adversarial(v2_path, v2_rows)
    output = tmp_path / "data/evaluation/adversarial_eval_v3.csv"
    report = tmp_path / "reports/data_audit_v3"
    targeted = tmp_path / "reports/manual_review/adversarial_v3_targeted_review.csv"

    rows, coverage = build_adversarial_v3(
        project, v2_path, output, report, targeted,
        {"ad": 1, "porn": 1, "violence": 0, "sensitive": 0},
    )

    assert {row["sample_id"] for row in rows} == {"high", "space", "pinyin"}
    assert all(row["review_status"] == "pending" for row in rows)
    assert all(row["perturbation_type"] != "character_split" for row in rows)
    assert "加 微信领取优惠券" not in {row["adversarial_text"] for row in rows}
    assert coverage["deprecated_perturbation_types"]["character_split"]
    assert coverage["v2_v3_diff"] == {
        "added": 0, "removed": 3, "changed": 3,
        "unchanged": 0, "retained_total": 3,
    }
    assert (report / "adversarial_v2_v3_diff.csv").exists()
    assert targeted.exists()


def test_manual_review_summary_is_machine_readable_without_mutating_input(tmp_path):
    review = tmp_path / "reviewed.csv"
    rows = [
        {"perturbation_type": "emoji", "review_status": "verified", "notes": "人工通过"},
        {"perturbation_type": "emoji", "review_status": "pending", "notes": "人工待定"},
        {"perturbation_type": "homophone", "review_status": "rejected", "notes": "人工拒绝"},
    ]
    with review.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["perturbation_type", "review_status", "notes"])
        writer.writeheader()
        writer.writerows(rows)
    original = review.read_bytes()

    summary = summarize_manual_review(review, tmp_path / "summary.json")

    assert review.read_bytes() == original
    assert summary["total"] == 3
    assert summary["verified_rate"] == 0.3333
    assert summary["status_by_perturbation_type"]["emoji"] == {
        "total": 2, "verified": 1, "pending": 1, "rejected": 0,
    }
