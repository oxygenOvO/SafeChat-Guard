from __future__ import annotations

import csv
import hashlib
import json
import sys
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any


VALID_LABELS = ("normal", "ad", "porn", "violence", "sensitive")
CSV_ENCODING = "utf-8-sig"


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    try:
        with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"CSV has no header: {path}")
            return list(reader.fieldnames), [dict(row) for row in reader]
    except UnicodeError as exc:
        raise ValueError(f"unable to decode {path} as UTF-8: {exc}") from exc
    except csv.Error as exc:
        raise ValueError(f"invalid CSV {path}: {exc}") from exc


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stable_id(text: str, label: str, source: str, prefix: str = "sample") -> str:
    payload = "\x1f".join((text, label, source)).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:16]}"


def basic_text_variants(text: str) -> dict[str, str]:
    stripped = text.strip()
    return {
        "exact": text,
        "trimmed": stripped,
        "casefolded": stripped.casefold(),
        "nfkc": unicodedata.normalize("NFKC", stripped).casefold(),
    }


@lru_cache(maxsize=8)
def _project_normalizer(project_root: Path):
    root_text = str(project_root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from safechat_guard.normalizer import TextNormalizer

        return TextNormalizer(
            str(project_root / "data/maps/homophone_map.json"),
            str(project_root / "data/maps/emoji_map.json"),
        )
    except (ImportError, OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            f"unable to initialize project Normalizer from {project_root}: {exc}"
        ) from exc


def project_normalized(text: str, project_root: Path) -> str | None:
    normalizer = _project_normalizer(project_root.resolve())
    return normalizer.normalize(text) if normalizer is not None else None


def load_reference_samples(project_root: Path) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    test_dir = project_root / "data/test_cases"
    jsonl_path = test_dir / "sample_cases.jsonl"
    if jsonl_path.exists():
        for line_number, line in enumerate(
            jsonl_path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if not line.strip():
                continue
            item = json.loads(line)
            text = str(item.get("text", ""))
            if text:
                samples.append(
                    {
                        "sample_id": str(item.get("id", line_number)),
                        "text": text,
                        "label": str(item.get("category", "")),
                        "source": jsonl_path.as_posix(),
                        "set_type": "test",
                    }
                )
    frontend_path = test_dir / "frontend_cases.csv"
    if frontend_path.exists():
        _, rows = read_csv_rows(frontend_path)
        for index, item in enumerate(rows, start=1):
            text = item.get("input_text", "")
            if text:
                samples.append(
                    {
                        "sample_id": item.get("id", str(index)),
                        "text": text,
                        "label": item.get("expected_category", ""),
                        "source": frontend_path.as_posix(),
                        "set_type": "test",
                    }
                )
    evaluation_dir = project_root / "data/evaluation"
    if evaluation_dir.exists():
        for path in sorted(evaluation_dir.glob("*.csv")):
            _, rows = read_csv_rows(path)
            for index, item in enumerate(rows, start=1):
                text = item.get("text") or item.get("adversarial_text") or ""
                if text:
                    samples.append(
                        {
                            "sample_id": item.get("sample_id", str(index)),
                            "text": text,
                            "label": item.get("label", ""),
                            "source": path.as_posix(),
                            "set_type": "evaluation",
                        }
                    )
    return samples


def find_leakage(
    train_rows: list[dict[str, str]],
    eval_rows: list[dict[str, str]],
    project_root: Path,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    match_order = ("exact", "trimmed", "casefolded", "nfkc", "normalized")
    train_variants = []
    for index, row in enumerate(train_rows, start=1):
        variants = basic_text_variants(row.get("text", ""))
        normalized = project_normalized(row.get("text", ""), project_root)
        if normalized is not None:
            variants["normalized"] = normalized
        train_variants.append((index, row, variants))

    for eval_index, eval_row in enumerate(eval_rows, start=1):
        eval_variants = basic_text_variants(eval_row.get("text", ""))
        normalized = project_normalized(eval_row.get("text", ""), project_root)
        if normalized is not None:
            eval_variants["normalized"] = normalized
        for train_index, train_row, variants in train_variants:
            match_type = next(
                (
                    name
                    for name in match_order
                    if name in variants
                    and name in eval_variants
                    and variants[name] == eval_variants[name]
                ),
                None,
            )
            if match_type:
                results.append(
                    {
                        "train_sample_id": train_row.get("sample_id")
                        or f"row_{train_index}",
                        "eval_sample_id": eval_row.get("sample_id")
                        or f"row_{eval_index}",
                        "train_text": train_row.get("text", ""),
                        "eval_text": eval_row.get("text", ""),
                        "match_type": match_type,
                        "train_label": train_row.get("label", ""),
                        "eval_label": eval_row.get("label", ""),
                    }
                )
    return sorted(
        results,
        key=lambda item: (
            item["train_sample_id"],
            item["eval_sample_id"],
            item["match_type"],
        ),
    )
