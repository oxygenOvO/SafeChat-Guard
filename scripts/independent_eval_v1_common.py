from __future__ import annotations

import csv
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


RANDOM_SEED = 42
LABELS = ("normal", "ad", "porn", "violence", "sensitive")
RISK_LABELS = frozenset(LABELS) - {"normal"}
REVIEW_STATUSES = frozenset({"verified", "pending", "rejected"})
CANDIDATE_FIELDS = (
    "sample_id",
    "text",
    "label",
    "risk_level",
    "expected_action",
    "scenario",
    "source_type",
    "source_reference",
    "review_status",
    "reviewer",
    "notes",
)
GOLD_FIELDS = (*CANDIDATE_FIELDS, "evaluation_split")
REFERENCE_FILES = (
    "data/normal_sentences.txt",
    "data/violation_sentences/ad.txt",
    "data/violation_sentences/porn.txt",
    "data/violation_sentences/violence.txt",
    "data/violation_sentences/sensitive.txt",
    "data/evaluation/baseline_eval_v1.csv",
    "data/evaluation/adversarial_eval_v1.csv",
    "data/evaluation/adversarial_eval_v2.csv",
    "data/evaluation/adversarial_eval_v3.csv",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_sample_id(text: str, label: str) -> str:
    payload = "\x1f".join((label, text))
    return f"siev1_{sha256_text(payload)[:16]}"


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path, required_fields: Iterable[str] = ()) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required_fields) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"CSV missing required fields {sorted(missing)}: {path}")
        return [dict(row) for row in reader]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def make_normalizer(project_root: Path):
    root_text = str(project_root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from safechat_guard.normalizer import TextNormalizer

    return TextNormalizer(
        str(project_root / "data/maps/homophone_map.json"),
        str(project_root / "data/maps/emoji_map.json"),
    )


def equivalence_keys(text: str, normalizer) -> dict[str, str]:
    return {
        "exact": text,
        "nfkc": unicodedata.normalize("NFKC", text),
        "text_normalizer": normalizer.normalize(text),
    }


def normalized_group_id(text: str, normalizer) -> str:
    return sha256_text(normalizer.normalize(text))


def character_ngrams(text: str, size: int = 3) -> set[str]:
    canonical = "".join(unicodedata.normalize("NFKC", text).casefold().split())
    if len(canonical) < size:
        return {canonical} if canonical else set()
    return {canonical[index:index + size] for index in range(len(canonical) - size + 1)}


def ngram_jaccard(left: str, right: str, size: int = 3) -> float:
    left_set = character_ngrams(left, size)
    right_set = character_ngrams(right, size)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def validate_candidate_rows(rows: list[dict[str, str]]) -> None:
    if len(rows) != 200:
        raise ValueError(f"candidate set must contain 200 rows, found {len(rows)}")
    ids = [row["sample_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate set contains duplicate sample_id values")
    expected_labels = {"normal": 100, "ad": 25, "porn": 25, "violence": 25, "sensitive": 25}
    expected_actions = {
        ("normal", "pass"): 100,
        ("ad", "sanitize"): 10,
        ("ad", "block"): 15,
        ("porn", "sanitize"): 10,
        ("porn", "block"): 15,
        ("violence", "sanitize"): 10,
        ("violence", "block"): 15,
        ("sensitive", "sanitize"): 10,
        ("sensitive", "block"): 15,
    }
    actual_labels = defaultdict(int)
    actual_actions = defaultdict(int)
    for row in rows:
        actual_labels[row["label"]] += 1
        actual_actions[(row["label"], row["expected_action"])] += 1
        if row["review_status"] != "pending" or row["reviewer"]:
            raise ValueError("automatically generated candidates must be pending with no reviewer")
        if row["sample_id"] != stable_sample_id(row["text"], row["label"]):
            raise ValueError(f"unstable sample_id: {row['sample_id']}")
    if dict(actual_labels) != expected_labels:
        raise ValueError(f"invalid label distribution: {dict(actual_labels)}")
    for key, expected in expected_actions.items():
        if actual_actions[key] != expected:
            raise ValueError(f"invalid action distribution for {key}: {actual_actions[key]}")


def group_split_counts(size: int, calibration_ratio: float = 0.40) -> tuple[int, int]:
    calibration = int(size * calibration_ratio + 0.5)
    return calibration, size - calibration
