from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

try:
    from data_baseline_common import (
        basic_text_variants, find_leakage, project_normalized,
        read_csv_rows, stable_id, write_csv, write_json,
    )
except ModuleNotFoundError:
    from scripts.data_baseline_common import (
        basic_text_variants, find_leakage, project_normalized,
        read_csv_rows, stable_id, write_csv, write_json,
    )


BASELINE_FIELDS = ["sample_id", "text", "label", "scenario", "source", "review_status", "notes"]
ADVERSARIAL_FIELDS = [
    "sample_id",
    "pair_id",
    "original_text",
    "adversarial_text",
    "label",
    "perturbation_type",
    "source",
    "review_status",
    "notes",
]
FAILURE_FIELDS = [
    "perturbation_type", "label", "target_count", "generated_count",
    "shortfall", "reason",
]
DIFF_FIELDS = [
    "change_type", "v2_sample_id", "v3_sample_id", "original_text",
    "v2_adversarial_text", "v3_adversarial_text", "label",
    "v2_perturbation_type", "v3_perturbation_type", "reason",
]
LEAKAGE_FIELDS = [
    "train_sample_id", "eval_sample_id", "train_text", "eval_text",
    "match_type", "train_label", "eval_label",
]
TARGETS = {"normal": 80, "ad": 30, "porn": 30, "violence": 30, "sensitive": 30}
PERTURBATIONS = (
    "homophone", "pinyin", "abbreviation", "variant_character",
    "traditional_simplified", "character_split", "space_insertion",
    "symbol_insertion", "emoji", "mixed_language", "url_obfuscation",
    "phone_obfuscation", "repeat_character",
)
V3_PERTURBATIONS = tuple(
    kind for kind in PERTURBATIONS if kind != "character_split"
)
DEPRECATED_PERTURBATIONS = {"character_split": "awaiting reviewed Chinese radical-split mappings"}
CONTEXT_CANDIDATES = (
    ("不要传播未经证实的暴力视频。", "negation"),
    ("老师引用‘加微信领取资料’作为广告引流反例。", "quotation"),
    ("课堂讲解如何识别色情网站和保护未成年人。", "education"),
    ("研究人员正在分析谐音绕过安全过滤的现象。", "research"),
    ("新闻报道介绍了警方打击网络诈骗的行动。", "news"),
    ("社区开展防范暴力威胁和网络谣言的宣传。", "prevention"),
    ("安全审核需要结合上下文判断风险词的真实含义。", "contextual"),
)
RISK_LABELS = ("ad", "porn", "violence", "sensitive")
V2_LABEL_TARGETS = {"ad": 3, "porn": 3, "violence": 2, "sensitive": 2}
CORE_RISK_KEYWORDS = {
    "ad": ("加微信", "刷单", "兼职", "优惠券", "招聘", "返利", "代理"),
    "porn": ("色情", "约炮", "裸聊", "性行为", "性服务", "黄网站", "成人视频"),
    "violence": ("枪支", "武器", "弩弓", "军刺", "杀死", "炸药", "砍人", "暴力"),
    "sensitive": ("成人用品", "迷药", "听话水", "催情药", "自杀", "自残", "割腕"),
}
VIOLENCE_TERMS = ("枪支", "买枪", "卖枪", "武器", "弩弓", "弩箭", "军刺", "炸药", "砍人", "杀死")
SENSITIVE_TERMS = (
    "成人用品", "情趣用品", "性玩具", "振动棒", "跳蛋", "飞机杯", "充气娃娃",
    "迷药", "听话水", "神仙水", "催情药", "自杀", "自残", "割腕", "跳楼",
)
SUPERSTITION_TERMS = ("风水", "算命", "占卜", "塔罗", "星座", "末日预言", "玛雅预言")
NEUTRAL_CONTEXT_TERMS = (
    "新闻报道", "警方通报", "课堂讲解", "教育", "研究人员", "研究分析",
    "预防", "防范", "治理", "不要", "不应", "禁止", "反对",
)
TRADITIONAL_TABLE = str.maketrans({"后": "後", "发": "發", "网": "網", "术": "術", "学": "學"})
CONFIDENCE_LEVELS = {"high", "medium", "low"}


def read_sentence_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def scenario_for(text: str, label: str) -> str:
    if label != "normal":
        return "direct"
    rules = (
        ("negation", ("不要", "不应", "不能", "拒绝")),
        ("quotation", ("引用", "原话", "所谓")),
        ("education", ("课程", "学习", "教育", "讲解")),
        ("research", ("研究", "实验", "分析")),
        ("news", ("新闻", "报道", "记者")),
        ("prevention", ("预防", "治理", "防范", "安全")),
    )
    return next((name for name, words in rules if any(word in text for word in words)), "contextual")


def equivalence_keys(text: str, project_root: Path) -> dict[str, str]:
    keys = basic_text_variants(text)
    normalized = project_normalized(text, project_root)
    if normalized is not None:
        keys["normalized"] = normalized
    return keys


def select_unique_candidates(
    candidates: list[tuple[str, str, str]],
    label: str,
    target: int,
    project_root: Path,
    seen: dict[str, set[str]],
) -> list[dict[str, str]]:
    selected = []
    for text, scenario, source in candidates:
        keys = equivalence_keys(text, project_root)
        if any(value in seen.setdefault(kind, set()) for kind, value in keys.items()):
            continue
        row = {
            "sample_id": stable_id(text, label, source, "eval"),
            "text": text,
            "label": label,
            "scenario": scenario,
            "source": source,
            "review_status": "pending",
            "notes": "candidate only; requires independent human review",
        }
        selected.append(row)
        for kind, value in keys.items():
            seen.setdefault(kind, set()).add(value)
        if len(selected) == target:
            break
    return selected


def baseline_coverage(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    coverage = {}
    for label, target in TARGETS.items():
        label_rows = [row for row in rows if row["label"] == label]
        unique_ids = {row["sample_id"] for row in label_rows}
        coverage[label] = {
            "target_count": target,
            "actual_count": len(label_rows),
            "unique_count": len(unique_ids),
            "shortfall": max(0, target - len(label_rows)),
        }
    return coverage


def build_baseline(project_root: Path, output_path: Path) -> list[dict[str, str]]:
    sources = {"normal": project_root / "data/normal_sentences.txt"}
    sources.update({
        label: project_root / f"data/violation_sentences/{label}.txt"
        for label in ("ad", "porn", "violence", "sensitive")
    })
    rows = []
    seen: dict[str, set[str]] = {}
    for label, target in TARGETS.items():
        source = sources[label]
        candidates = []
        if label == "normal":
            candidates.extend(
                (text, scenario, "generated_context_candidates_v1")
                for text, scenario in CONTEXT_CANDIDATES
            )
        source_name = source.relative_to(project_root).as_posix()
        candidates.extend(
            (text, scenario_for(text, label), source_name)
            for text in read_sentence_file(source)
        )
        rows.extend(
            select_unique_candidates(
                candidates,
                label,
                target,
                project_root,
                seen,
            )
        )
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("baseline generation produced duplicate sample_id values")
    rows.sort(key=lambda item: (item["label"], item["sample_id"]))
    write_csv(output_path, BASELINE_FIELDS, rows)
    return rows


def load_maps(project_root: Path) -> dict[str, dict[str, str]]:
    result = {}
    for name in ("homophone", "pinyin", "abbreviation", "variant_char", "emoji"):
        path = project_root / f"data/maps/{name}_map.json"
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        result[name] = {
            key: value.get("target", "") if isinstance(value, dict) else str(value)
            for key, value in raw.items()
        }
    return result


def load_map_entries(project_root: Path) -> dict[str, list[dict[str, object]]]:
    result = {}
    for name in ("homophone", "pinyin", "abbreviation", "variant_char", "emoji"):
        path = project_root / f"data/maps/{name}_map.json"
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = []
        for variant, value in sorted(raw.items()):
            metadata = value if isinstance(value, dict) else {}
            raw_confidence = metadata.get("confidence", 0)
            if isinstance(raw_confidence, str):
                confidence_level = raw_confidence.lower()
                confidence_score = float(metadata.get("confidence_score", 0))
            else:
                confidence_score = float(raw_confidence)
                confidence_level = (
                    "high" if confidence_score >= 0.9
                    else "medium" if confidence_score >= 0.8
                    else "low"
                )
            entries.append({
                "variant": variant,
                "source": metadata.get("source", variant),
                "target": metadata.get("target", "") if isinstance(value, dict) else str(value),
                "confidence": confidence_score,
                "confidence_level": confidence_level,
                "rationale": metadata.get("rationale", ""),
                "type": metadata.get("type", ""),
            })
        result[name] = entries
    return result


def resolve_annotation_label(text: str, original_label: str) -> str:
    if any(term in text for term in NEUTRAL_CONTEXT_TERMS):
        return "normal"
    if any(term in text for term in VIOLENCE_TERMS):
        return "violence"
    if any(term in text for term in SENSITIVE_TERMS):
        return "sensitive"
    if any(term in text for term in SUPERSTITION_TERMS):
        return "normal"
    return original_label


def strict_mapping_replace(
    text: str,
    entries: list[dict[str, object]],
    minimum_confidence: float = 0.85,
) -> tuple[str, str] | None:
    for entry in sorted(entries, key=lambda item: (-len(str(item["target"])), str(item["variant"]))):
        target = str(entry["target"])
        variant = str(entry["variant"])
        confidence = float(entry["confidence"])
        if confidence >= minimum_confidence and target and target in text and variant != target:
            return text.replace(target, variant, 1), f"high-confidence map replacement ({confidence:.2f})"
    return None


def strict_homophone_replace(
    text: str,
    entries: list[dict[str, object]],
) -> tuple[str, str] | None:
    eligible = [
        entry for entry in entries
        if entry.get("confidence_level") in {"high", "medium"}
    ]
    for entry in sorted(eligible, key=lambda item: (-len(str(item["target"])), str(item["variant"]))):
        target = str(entry["target"])
        variant = str(entry["variant"])
        if target and target in text and variant != target:
            level = str(entry["confidence_level"])
            rationale = str(entry.get("rationale", "")).strip()
            notes = f"homophone confidence={level}"
            if rationale:
                notes += f"; {rationale}"
            if level == "medium":
                notes += "; high-priority manual review required"
            return text.replace(target, variant, 1), notes
    return None


def _is_cjk_character(value: str) -> bool:
    return len(value) == 1 and any(
        start <= ord(value) <= end
        for start, end in ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
    )


def valid_variant_character_entry(entry: dict[str, object]) -> bool:
    variant = str(entry.get("variant", ""))
    target = str(entry.get("target", ""))
    if not variant or len(variant) != len(target) or variant == target:
        return False
    if entry.get("type") not in {"visual_variant", "variant_character", "glyph_variant"}:
        return False
    if not str(entry.get("rationale", "")).strip():
        return False
    if not all(_is_cjk_character(char) for char in variant + target):
        return False
    if target.translate(TRADITIONAL_TABLE) == variant:
        return False
    return any(source != canonical for source, canonical in zip(variant, target))


def strict_variant_character_replace(
    text: str,
    entries: list[dict[str, object]],
) -> tuple[str, str] | None:
    eligible = [
        entry for entry in entries
        if valid_variant_character_entry(entry)
        and entry.get("confidence_level") in {"high", "medium"}
    ]
    for entry in sorted(eligible, key=lambda item: (-len(str(item["target"])), str(item["variant"]))):
        target = str(entry["target"])
        variant = str(entry["variant"])
        if target in text:
            return (
                text.replace(target, variant, 1),
                f"explicit variant-character replacement; {entry['rationale']}",
            )
    return None


def strict_perturb(
    text: str,
    kind: str,
    label: str,
    maps: dict[str, list[dict[str, object]]],
) -> tuple[str, str] | None:
    if kind == "homophone":
        return strict_homophone_replace(text, maps["homophone"])
    if kind == "variant_character":
        return strict_variant_character_replace(text, maps["variant_char"])
    mapping_names = {"pinyin": "pinyin", "abbreviation": "abbreviation"}
    if kind in mapping_names:
        return strict_mapping_replace(text, maps[mapping_names[kind]])
    if kind == "emoji":
        result = strict_mapping_replace(text, maps["emoji"], minimum_confidence=0.70)
        return (result[0], "replace core risk expression with mapped emoji") if result else None
    if kind == "phone_obfuscation":
        phone = re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text)
        if not phone:
            return None
        obscured = "-".join(phone.group(0))
        return text[:phone.start()] + obscured + text[phone.end():], "hyphenate existing phone number"
    if kind == "url_obfuscation":
        url = re.search(r"(?:https?://|www\.)[^\s，。；、]+", text, flags=re.I)
        if not url:
            return None
        obscured = re.sub(r"^https", "hxxps", url.group(0), flags=re.I)
        obscured = re.sub(r"^http", "hxxp", obscured, flags=re.I).replace(".", "[.]")
        return text[:url.start()] + obscured + text[url.end():], "obfuscate existing URL scheme and dots"
    if kind == "repeat_character":
        keyword = next((word for word in CORE_RISK_KEYWORDS[label] if word in text), None)
        if not keyword:
            return None
        repeated = keyword[0] * 2 + keyword[1:]
        return text.replace(keyword, repeated, 1), f"repeat character inside risk keyword: {keyword}"
    if kind == "traditional_simplified":
        table = str.maketrans({"后": "後", "发": "發", "网": "網", "术": "術", "学": "學"})
        changed = text.translate(table)
        return (changed, "fixed simplified-to-traditional character table") if changed != text else None
    if len(text) < 2:
        return None
    if kind == "character_split":
        keyword = next((word for word in CORE_RISK_KEYWORDS[label] if len(word) > 1 and word in text), None)
        return (text.replace(keyword, " ".join(keyword), 1), f"split risk keyword: {keyword}") if keyword else None
    if kind == "space_insertion":
        keyword = next((word for word in CORE_RISK_KEYWORDS[label] if len(word) > 1 and word in text), None)
        return (text.replace(keyword, " ".join(keyword), 1), f"insert spaces inside risk keyword: {keyword}") if keyword else None
    if kind == "symbol_insertion":
        keyword = next((word for word in CORE_RISK_KEYWORDS[label] if len(word) > 1 and word in text), None)
        return (text.replace(keyword, keyword[0] + "@" + keyword[1:], 1), f"insert symbol inside risk keyword: {keyword}") if keyword else None
    if kind == "mixed_language":
        replacements = (("微信", "wechat"), ("网站", "website"), ("暴力", "violence"), ("色情", "porn"))
        for source, target in replacements:
            if source in text:
                return text.replace(source, target, 1), f"replace {source} with {target}"
        return None
    return None


def reverse_replace(text: str, mapping: dict[str, str]) -> str | None:
    for variant, canonical in sorted(mapping.items(), key=lambda item: (-len(item[1]), item[0])):
        if canonical and canonical in text and variant != canonical:
            return text.replace(canonical, variant, 1)
    return None


def perturb(text: str, kind: str, maps: dict[str, dict[str, str]]) -> tuple[str, str] | None:
    mapping_names = {
        "homophone": "homophone", "pinyin": "pinyin",
        "abbreviation": "abbreviation", "variant_character": "variant_char",
        "emoji": "emoji",
    }
    if kind in mapping_names:
        changed = reverse_replace(text, maps[mapping_names[kind]])
        if changed:
            return changed, f"reverse replacement from {mapping_names[kind]}_map"
        return None
    if kind == "traditional_simplified":
        table = str.maketrans({"后": "後", "发": "發", "网": "網", "术": "術", "学": "學"})
        changed = text.translate(table)
        return (changed, "fixed simplified-to-traditional character table") if changed != text else None
    if len(text) < 2:
        return None
    if kind == "character_split":
        return text[0] + " " + text[1:], "split first two characters"
    if kind == "space_insertion":
        return " ".join(text), "insert spaces between all characters"
    if kind == "symbol_insertion":
        return text[0] + "@" + text[1:], "insert @ after first character"
    if kind == "mixed_language":
        replacements = (("微信", "wechat"), ("网站", "website"), ("暴力", "violence"), ("色情", "porn"))
        for source, target in replacements:
            if source in text:
                return text.replace(source, target, 1), f"replace {source} with {target}"
        return text + " online", "append mixed-language context token"
    if kind == "url_obfuscation":
        url = re.search(r"https?://|www\.", text, flags=re.I)
        if url:
            return text[:url.start()] + text[url.start():].replace(".", "[.]"), "replace URL dots with [.]"
        return None
    if kind == "phone_obfuscation":
        phone = re.search(r"1[3-9]\d{9}", text)
        if phone:
            value = "-".join(phone.group(0))
            return text[:phone.start()] + value + text[phone.end():], "hyphenate phone digits"
        return None
    if kind == "repeat_character":
        keyword = next(
            (word for words in CORE_RISK_KEYWORDS.values() for word in words if word in text),
            None,
        )
        if keyword:
            return text.replace(keyword, keyword[0] * 2 + keyword[1:], 1), f"repeat inside risk keyword: {keyword}"
        return None
    return None


def build_adversarial(project_root: Path, output_path: Path) -> list[dict[str, str]]:
    maps = load_maps(project_root)
    seeds = []
    for label in ("ad", "porn", "violence", "sensitive"):
        path = project_root / f"data/violation_sentences/{label}.txt"
        source = path.relative_to(project_root).as_posix()
        seeds.extend((text, label, source) for text in read_sentence_file(path))
    rows = []
    for kind in PERTURBATIONS:
        generated = set()
        for text, label, source in seeds:
            result = perturb(text, kind, maps)
            if not result:
                continue
            adversarial, rule = result
            if adversarial in generated:
                continue
            generated.add(adversarial)
            pair_id = stable_id(text, label, source, "pair")
            rows.append({
                "sample_id": stable_id(adversarial, label, pair_id, "adv"),
                "pair_id": pair_id,
                "original_text": text,
                "adversarial_text": adversarial,
                "label": label,
                "perturbation_type": kind,
                "source": source,
                "review_status": "pending",
                "notes": rule,
            })
            if len(generated) == 10:
                break
    rows.sort(key=lambda item: (item["perturbation_type"], item["sample_id"]))
    write_csv(output_path, ADVERSARIAL_FIELDS, rows)
    return rows


def final_duplicate_candidates(
    rows: list[dict[str, str]],
    project_root: Path,
) -> list[dict[str, str]]:
    comparable = [{**row, "text": row["adversarial_text"]} for row in rows]
    matches = find_leakage(comparable, comparable, project_root)
    result = []
    seen_pairs = set()
    for item in matches:
        left = item["train_sample_id"]
        right = item["eval_sample_id"]
        if left == right:
            continue
        pair = tuple(sorted((left, right)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        result.append(item)
    return result


def build_adversarial_v2(
    project_root: Path,
    output_path: Path,
    report_dir: Path,
    label_targets: dict[str, int] | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    targets = label_targets or V2_LABEL_TARGETS
    maps = load_map_entries(project_root)
    seeds_by_label: dict[str, list[tuple[str, str]]] = {label: [] for label in RISK_LABELS}
    for original_label in RISK_LABELS:
        path = project_root / f"data/violation_sentences/{original_label}.txt"
        source = path.relative_to(project_root).as_posix()
        for text in read_sentence_file(path):
            label = resolve_annotation_label(text, original_label)
            if label in seeds_by_label:
                seeds_by_label[label].append((text, source))

    rows = []
    failures = []
    matrix = {label: {kind: 0 for kind in PERTURBATIONS} for label in RISK_LABELS}
    used_adversarial = set()
    for kind in PERTURBATIONS:
        for label in RISK_LABELS:
            target = targets.get(label, 0)
            generated = 0
            for text, source in seeds_by_label[label]:
                result = strict_perturb(text, kind, label, maps)
                if not result:
                    continue
                adversarial, rule = result
                if adversarial == text or adversarial in used_adversarial:
                    continue
                pair_id = stable_id(text, label, source, "pair")
                row = {
                    "sample_id": stable_id(adversarial, label, pair_id, "adv2"),
                    "pair_id": pair_id,
                    "original_text": text,
                    "adversarial_text": adversarial,
                    "label": label,
                    "perturbation_type": kind,
                    "source": source,
                    "review_status": "pending",
                    "notes": rule,
                }
                rows.append(row)
                used_adversarial.add(adversarial)
                generated += 1
                if generated == target:
                    break
            matrix[label][kind] = generated
            shortfall = max(0, target - generated)
            if shortfall:
                failures.append({
                    "perturbation_type": kind,
                    "label": label,
                    "target_count": target,
                    "generated_count": generated,
                    "shortfall": shortfall,
                    "reason": "insufficient eligible source samples",
                })

    rows.sort(key=lambda item: (item["perturbation_type"], item["label"], item["sample_id"]))
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("adversarial v2 produced duplicate sample_id values")
    if len({row["adversarial_text"] for row in rows}) != len(rows):
        raise ValueError("adversarial v2 produced duplicate adversarial_text values")
    write_csv(output_path, ADVERSARIAL_FIELDS, rows)
    report_dir.mkdir(parents=True, exist_ok=True)
    duplicates = final_duplicate_candidates(rows, project_root)
    write_csv(report_dir / "adversarial_duplicate_candidates.csv", LEAKAGE_FIELDS, duplicates)
    write_csv(report_dir / "adversarial_generation_failures.csv", FAILURE_FIELDS, failures)
    coverage = {
        "version": "adversarial_eval_v2",
        "review_status": "pending",
        "total": len(rows),
        "target_per_label_per_type": targets,
        "by_perturbation_type": dict(sorted(Counter(row["perturbation_type"] for row in rows).items())),
        "by_label": dict(sorted(Counter(row["label"] for row in rows).items())),
        "label_by_perturbation_type": matrix,
        "shortfall_by_perturbation_type": {
            kind: sum(
                max(0, targets.get(label, 0) - matrix[label][kind])
                for label in RISK_LABELS
            )
            for kind in PERTURBATIONS
        },
        "shortfall_total": sum(int(row["shortfall"]) for row in failures),
        "duplicate_candidate_pairs": len(duplicates),
    }
    write_json(report_dir / "adversarial_coverage.json", coverage)
    return rows, coverage


def _matching_homophone_notes(
    row: dict[str, str],
    entries: list[dict[str, object]],
) -> str | None:
    for entry in entries:
        if entry.get("confidence_level") not in {"high", "medium"}:
            continue
        target = str(entry["target"])
        variant = str(entry["variant"])
        if target and row["original_text"].replace(target, variant, 1) == row["adversarial_text"]:
            level = str(entry["confidence_level"])
            rationale = str(entry.get("rationale", "")).strip()
            notes = f"homophone confidence={level}"
            if rationale:
                notes += f"; {rationale}"
            if level == "medium":
                notes += "; high-priority manual review required"
            return notes
    return None


def _build_v2_v3_diff(
    v2_rows: list[dict[str, str]],
    v3_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    old_by_id = {row["sample_id"]: row for row in v2_rows}
    new_by_id = {row["sample_id"]: row for row in v3_rows}
    diff_rows = []
    unchanged = changed = 0
    for sample_id, old in sorted(old_by_id.items()):
        new = new_by_id.get(sample_id)
        if new is None:
            reason = "removed by v3 quality rules"
            if old["perturbation_type"] == "character_split":
                reason = "character_split deprecated"
            elif old["perturbation_type"] == "variant_character":
                reason = "invalid symbol-based variant_character"
            elif old["perturbation_type"] == "homophone":
                reason = "low-confidence homophone excluded"
            diff_rows.append({
                "change_type": "removed", "v2_sample_id": sample_id,
                "v3_sample_id": "", "original_text": old["original_text"],
                "v2_adversarial_text": old["adversarial_text"],
                "v3_adversarial_text": "", "label": old["label"],
                "v2_perturbation_type": old["perturbation_type"],
                "v3_perturbation_type": "", "reason": reason,
            })
        elif old == new:
            unchanged += 1
        else:
            changed += 1
            diff_rows.append({
                "change_type": "changed", "v2_sample_id": sample_id,
                "v3_sample_id": sample_id, "original_text": new["original_text"],
                "v2_adversarial_text": old["adversarial_text"],
                "v3_adversarial_text": new["adversarial_text"], "label": new["label"],
                "v2_perturbation_type": old["perturbation_type"],
                "v3_perturbation_type": new["perturbation_type"],
                "reason": "generation metadata updated for reviewed confidence policy",
            })
    added = 0
    for sample_id, new in sorted(new_by_id.items()):
        if sample_id in old_by_id:
            continue
        added += 1
        diff_rows.append({
            "change_type": "added", "v2_sample_id": "", "v3_sample_id": sample_id,
            "original_text": new["original_text"], "v2_adversarial_text": "",
            "v3_adversarial_text": new["adversarial_text"], "label": new["label"],
            "v2_perturbation_type": "", "v3_perturbation_type": new["perturbation_type"],
            "reason": "new candidate satisfies v3 generation rules",
        })
    counts = {
        "added": added,
        "removed": sum(row["change_type"] == "removed" for row in diff_rows),
        "changed": changed,
        "unchanged": unchanged,
        "retained_total": unchanged + changed,
    }
    return sorted(diff_rows, key=lambda row: (row["change_type"], row["v2_sample_id"], row["v3_sample_id"])), counts


def _targeted_review_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = []
    homophones = sorted(
        (row for row in rows if row["perturbation_type"] == "homophone"),
        key=lambda row: ("confidence=medium" not in row["notes"], row["sample_id"]),
    )[:3]
    selected.extend(homophones)
    selected.extend(
        [row for row in rows if row["perturbation_type"] == "variant_character"][:3]
    )
    selected.extend(
        [row for row in rows if row["perturbation_type"] == "space_insertion"][:3]
    )
    selected.extend(
        row for row in rows
        if row["perturbation_type"] == "abbreviation"
        and "yp" in row["adversarial_text"].casefold()
    )
    selected.extend(
        row for row in rows
        if row["perturbation_type"] == "emoji"
        and ("🎁姬" in row["adversarial_text"] or "福利姬" in row["original_text"])
    )
    unique = {row["sample_id"]: {**row, "review_status": "pending"} for row in selected}
    return sorted(unique.values(), key=lambda row: (row["perturbation_type"], row["sample_id"]))


def build_adversarial_v3(
    project_root: Path,
    v2_path: Path,
    output_path: Path,
    report_dir: Path,
    targeted_review_path: Path,
    label_targets: dict[str, int] | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    targets = label_targets or V2_LABEL_TARGETS
    _, v2_rows = read_csv_rows(v2_path)
    maps = load_map_entries(project_root)
    rows = []
    for old in v2_rows:
        kind = old["perturbation_type"]
        if kind in {"character_split", "variant_character"}:
            continue
        row = {**old, "review_status": "pending"}
        if kind == "homophone":
            notes = _matching_homophone_notes(row, maps["homophone"])
            if notes is None:
                continue
            row["notes"] = notes
        rows.append(row)

    used_text = {row["adversarial_text"] for row in rows}
    for label in RISK_LABELS:
        target = targets.get(label, 0)
        generated = sum(
            row["label"] == label and row["perturbation_type"] == "variant_character"
            for row in rows
        )
        path = project_root / f"data/violation_sentences/{label}.txt"
        source = path.relative_to(project_root).as_posix()
        for text in read_sentence_file(path):
            if generated >= target:
                break
            result = strict_variant_character_replace(text, maps["variant_char"])
            if not result:
                continue
            adversarial, notes = result
            if adversarial in used_text:
                continue
            pair_id = stable_id(text, label, source, "pair")
            rows.append({
                "sample_id": stable_id(adversarial, label, pair_id, "adv3"),
                "pair_id": pair_id, "original_text": text,
                "adversarial_text": adversarial, "label": label,
                "perturbation_type": "variant_character", "source": source,
                "review_status": "pending", "notes": notes,
            })
            used_text.add(adversarial)
            generated += 1

    rows.sort(key=lambda row: (row["perturbation_type"], row["label"], row["sample_id"]))
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("adversarial v3 produced duplicate sample_id values")
    if len({row["adversarial_text"] for row in rows}) != len(rows):
        raise ValueError("adversarial v3 produced duplicate adversarial_text values")
    if any(row["review_status"] != "pending" for row in rows):
        raise ValueError("adversarial v3 must not inherit reviewed statuses")

    matrix = {
        label: {
            kind: sum(
                row["label"] == label and row["perturbation_type"] == kind
                for row in rows
            )
            for kind in PERTURBATIONS
        }
        for label in RISK_LABELS
    }
    failures = []
    for kind in PERTURBATIONS:
        for label in RISK_LABELS:
            actual = matrix[label][kind]
            target = targets.get(label, 0)
            shortfall = max(0, target - actual)
            if not shortfall:
                continue
            reason = (
                f"deprecated: {DEPRECATED_PERTURBATIONS[kind]}"
                if kind in DEPRECATED_PERTURBATIONS
                else "insufficient candidates satisfying v3 quality rules"
            )
            failures.append({
                "perturbation_type": kind, "label": label,
                "target_count": target, "generated_count": actual,
                "shortfall": shortfall, "reason": reason,
            })

    duplicates = final_duplicate_candidates(rows, project_root)
    diff_rows, diff_counts = _build_v2_v3_diff(v2_rows, rows)
    write_csv(output_path, ADVERSARIAL_FIELDS, rows)
    report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(report_dir / "adversarial_duplicate_candidates.csv", LEAKAGE_FIELDS, duplicates)
    write_csv(report_dir / "adversarial_generation_failures.csv", FAILURE_FIELDS, failures)
    write_csv(report_dir / "adversarial_v2_v3_diff.csv", DIFF_FIELDS, diff_rows)
    targeted = _targeted_review_rows(rows)
    write_csv(targeted_review_path, ADVERSARIAL_FIELDS, targeted)
    coverage = {
        "version": "adversarial_eval_v3", "review_status": "pending",
        "total": len(rows), "target_per_label_per_type": targets,
        "deprecated_perturbation_types": DEPRECATED_PERTURBATIONS,
        "by_perturbation_type": dict(sorted(Counter(row["perturbation_type"] for row in rows).items())),
        "by_label": dict(sorted(Counter(row["label"] for row in rows).items())),
        "label_by_perturbation_type": matrix,
        "shortfall_by_perturbation_type": {
            kind: sum(max(0, targets.get(label, 0) - matrix[label][kind]) for label in RISK_LABELS)
            for kind in PERTURBATIONS
        },
        "shortfall_total": sum(int(row["shortfall"]) for row in failures),
        "duplicate_candidate_pairs": len(duplicates),
        "v2_v3_diff": diff_counts,
        "targeted_review_count": len(targeted),
    }
    write_json(report_dir / "adversarial_coverage.json", coverage)
    return rows, coverage


def summarize_manual_review(
    review_path: Path,
    output_path: Path,
    reviewer: str = "oxygen",
    data_version: str = "adversarial_eval_v2",
) -> dict[str, object]:
    if not review_path.is_file():
        raise FileNotFoundError(
            f"manual review input file does not exist: {review_path}"
        )
    _, rows = read_csv_rows(review_path)
    allowed = {"verified", "pending", "rejected"}
    statuses = Counter(row.get("review_status", "") for row in rows)
    invalid = sorted(set(statuses) - allowed)
    if invalid:
        raise ValueError(f"invalid manual review statuses: {', '.join(invalid)}")
    by_type = {}
    for kind in sorted({row.get("perturbation_type", "") for row in rows}):
        type_rows = [row for row in rows if row.get("perturbation_type") == kind]
        counts = Counter(row["review_status"] for row in type_rows)
        by_type[kind] = {
            "total": len(type_rows),
            **{status: counts.get(status, 0) for status in ("verified", "pending", "rejected")},
        }
    total = len(rows)
    summary = {
        "total": total, "verified": statuses.get("verified", 0),
        "pending": statuses.get("pending", 0), "rejected": statuses.get("rejected", 0),
        "verified_rate": round(statuses.get("verified", 0) / total, 4) if total else 0,
        "status_by_perturbation_type": by_type,
        "generation_rules_requiring_fix": [
            "variant_character must use maintained glyph mappings only",
            "homophone must enforce high/medium/low confidence policy",
            "character_split is deprecated until reviewed radical mappings exist",
            "yp abbreviations and mechanical emoji combinations require targeted review",
        ],
        "reviewer": reviewer, "data_version": data_version,
    }
    write_json(output_path, summary)
    return summary


def load_training_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    _, rows = read_csv_rows(path)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pending SafeChat evaluation candidates")
    parser.add_argument(
        "--mode",
        choices=("all-v1", "adversarial-v2", "adversarial-v3", "manual-review-summary"),
        default="all-v1",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation"))
    parser.add_argument("--train-input", type=Path)
    parser.add_argument("--report-dir", type=Path, default=Path("reports/data_audit_v1"))
    parser.add_argument("--v2-report-dir", type=Path, default=Path("reports/data_audit_v2"))
    parser.add_argument("--v3-report-dir", type=Path, default=Path("reports/data_audit_v3"))
    parser.add_argument(
        "--review-input",
        type=Path,
        default=Path("reports/manual_review/adversarial_sample_v2_reviewed.csv"),
    )
    parser.add_argument(
        "--review-summary",
        type=Path,
        default=Path("reports/manual_review/adversarial_sample_v2_review_summary.json"),
    )
    parser.add_argument(
        "--targeted-review",
        type=Path,
        default=Path("reports/manual_review/adversarial_v3_targeted_review.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    if args.mode == "adversarial-v2":
        rows, coverage = build_adversarial_v2(
            project_root,
            args.output_dir / "adversarial_eval_v2.csv",
            args.v2_report_dir,
        )
        print(
            f"adversarial v2 candidates: {len(rows)}, "
            f"shortfall={coverage['shortfall_total']}"
        )
        return
    if args.mode == "adversarial-v3":
        rows, coverage = build_adversarial_v3(
            project_root,
            args.output_dir / "adversarial_eval_v2.csv",
            args.output_dir / "adversarial_eval_v3.csv",
            args.v3_report_dir,
            args.targeted_review,
        )
        print(
            f"adversarial v3 candidates: {len(rows)}, "
            f"shortfall={coverage['shortfall_total']}"
        )
        return
    if args.mode == "manual-review-summary":
        summary = summarize_manual_review(args.review_input, args.review_summary)
        print(
            f"manual review summary: {summary['verified']}/{summary['total']} verified"
        )
        return
    baseline = build_baseline(project_root, args.output_dir / "baseline_eval_v1.csv")
    adversarial = build_adversarial(project_root, args.output_dir / "adversarial_eval_v1.csv")
    train_rows = load_training_rows(args.train_input)
    eval_rows = baseline + [
        {**row, "text": row["adversarial_text"]} for row in adversarial
    ]
    leakage = find_leakage(train_rows, eval_rows, project_root)
    write_csv(args.report_dir / "evaluation_leakage_candidates.csv", LEAKAGE_FIELDS, leakage)
    internal_matches = find_leakage(eval_rows, eval_rows, project_root)
    duplicate_candidates = []
    seen_pairs = set()
    for item in internal_matches:
        left = item["train_sample_id"]
        right = item["eval_sample_id"]
        if left == right:
            continue
        pair = tuple(sorted((left, right)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        duplicate_candidates.append(item)
    write_csv(
        args.report_dir / "evaluation_duplicate_candidates.csv",
        LEAKAGE_FIELDS,
        duplicate_candidates,
    )
    per_label_coverage = baseline_coverage(baseline)
    coverage = {
        "baseline_total": len(baseline),
        "baseline_by_label": dict(sorted(Counter(row["label"] for row in baseline).items())),
        "baseline_by_scenario": dict(sorted(Counter(row["scenario"] for row in baseline).items())),
        "adversarial_total": len(adversarial),
        "adversarial_by_type": dict(sorted(Counter(row["perturbation_type"] for row in adversarial).items())),
        "review_status": "pending",
        "baseline_coverage": per_label_coverage,
        "target_shortfall": {
            label: details["shortfall"]
            for label, details in per_label_coverage.items()
        },
        "leakage_candidates": len(leakage),
        "evaluation_duplicate_candidates": len(duplicate_candidates),
    }
    write_json(args.report_dir / "evaluation_coverage.json", coverage)
    print(f"evaluation candidates: baseline={len(baseline)}, adversarial={len(adversarial)}")


if __name__ == "__main__":
    main()
