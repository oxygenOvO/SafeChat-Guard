from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import joblib
import pandas
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.pipeline import Pipeline


RANDOM_SEED = 42
LABELS = ("normal", "ad", "porn", "violence", "sensitive")
RISK_LABELS = frozenset(LABELS) - {"normal"}
SOURCE_FILES = (
    ("normal", "data/normal_sentences.txt"),
    ("ad", "data/violation_sentences/ad.txt"),
    ("porn", "data/violation_sentences/porn.txt"),
    ("violence", "data/violation_sentences/violence.txt"),
    ("sensitive", "data/violation_sentences/sensitive.txt"),
)
SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}
SPLIT_FIELDS = (
    "group_id",
    "original_text",
    "normalized_text",
    "label",
    "source_type",
    "source_file",
    "source_line",
    "split",
)
MODEL_SPECS = {
    "word": {"analyzer": "word", "ngram_range": (1, 2)},
    "char": {"analyzer": "char", "ngram_range": (2, 5)},
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_split_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"split manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(SPLIT_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"split manifest missing columns: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"split manifest is empty: {path}")
    invalid_labels = sorted({row["label"] for row in rows} - set(LABELS))
    invalid_splits = sorted({row["split"] for row in rows} - set(SPLIT_RATIOS))
    if invalid_labels or invalid_splits:
        raise ValueError(
            f"invalid split manifest values: labels={invalid_labels}, splits={invalid_splits}"
        )
    return rows


def make_normalizer(project_root: Path):
    root_text = str(project_root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from safechat_guard.normalizer import TextNormalizer

    return TextNormalizer(
        str(project_root / "data/maps/homophone_map.json"),
        str(project_root / "data/maps/emoji_map.json"),
    )


def _split_counts(size: int) -> dict[str, int]:
    exact = {name: size * ratio for name, ratio in SPLIT_RATIOS.items()}
    counts = {name: int(value) for name, value in exact.items()}
    remainder = size - sum(counts.values())
    order = sorted(
        SPLIT_RATIOS,
        key=lambda name: (-(exact[name] - counts[name]), tuple(SPLIT_RATIOS).index(name)),
    )
    for name in order[:remainder]:
        counts[name] += 1
    return counts


def _stable_group_order(group_id: str, label: str, seed: int) -> str:
    return sha256_text(f"{seed}\x1f{label}\x1f{group_id}")


def find_cross_split_leakage(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    key_functions = {
        "exact": lambda row: row["original_text"],
        "nfkc": lambda row: unicodedata.normalize("NFKC", row["original_text"]),
        "text_normalizer": lambda row: row["normalized_text"],
    }
    findings: list[dict[str, str]] = []
    for match_type, key_function in key_functions.items():
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[key_function(row)].append(row)
        for match_value, matches in grouped.items():
            splits = sorted({row["split"] for row in matches})
            if len(splits) > 1:
                findings.append(
                    {
                        "match_type": match_type,
                        "match_sha256": sha256_text(match_value),
                        "splits": "|".join(splits),
                        "group_ids": "|".join(sorted({row["group_id"] for row in matches})),
                        "labels": "|".join(sorted({row["label"] for row in matches})),
                    }
                )
    return sorted(
        findings,
        key=lambda row: (row["match_type"], row["match_sha256"]),
    )


def build_semantic_data(
    project_root: Path,
    output_dir: Path,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    normalizer = make_normalizer(project_root)
    source_manifest: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    for source_order, (label, relative_path) in enumerate(SOURCE_FILES):
        source_path = project_root / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(f"training source not found: {source_path}")
        raw_lines = source_path.read_text(encoding="utf-8-sig").splitlines()
        cleaned_count = 0
        for line_number, original_text in enumerate(raw_lines, start=1):
            if not original_text.strip():
                continue
            cleaned_count += 1
            normalized_text = normalizer.normalize(original_text)
            if not normalized_text.strip():
                continue
            records.append(
                {
                    "original_text": original_text,
                    "normalized_text": normalized_text,
                    "label": label,
                    "source_type": "weak_label",
                    "source_file": relative_path,
                    "source_line": line_number,
                    "source_order": source_order,
                }
            )
        source_manifest.append(
            {
                "path": relative_path,
                "sha256": sha256_file(source_path),
                "raw_line_count": len(raw_lines),
                "nonblank_line_count": cleaned_count,
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["normalized_text"]].append(record)

    conflicts: list[dict[str, str]] = []
    duplicate_rows: list[dict[str, Any]] = []
    unique_rows: list[dict[str, Any]] = []
    exact_duplicate_count = 0
    normalized_duplicate_count = 0

    for normalized_text in sorted(grouped, key=lambda value: (sha256_text(value), value)):
        matches = sorted(
            grouped[normalized_text],
            key=lambda row: (row["source_order"], row["source_line"], row["original_text"]),
        )
        labels = sorted({row["label"] for row in matches})
        group_id = sha256_text(normalized_text)
        if len(labels) > 1:
            conflicts.append(
                {
                    "group_id": group_id,
                    "normalized_text": normalized_text,
                    "labels": "|".join(labels),
                    "occurrence_count": str(len(matches)),
                    "sources": json.dumps(
                        [
                            {
                                "label": row["label"],
                                "source_file": row["source_file"],
                                "source_line": row["source_line"],
                                "original_text": row["original_text"],
                            }
                            for row in matches
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
            continue

        kept = matches[0]
        unique_rows.append(
            {
                "group_id": group_id,
                "original_text": kept["original_text"],
                "normalized_text": normalized_text,
                "label": kept["label"],
                "source_type": "weak_label",
                "source_file": kept["source_file"],
                "source_line": str(kept["source_line"]),
            }
        )
        for duplicate in matches[1:]:
            duplicate_type = (
                "exact" if duplicate["original_text"] == kept["original_text"]
                else "normalized_equivalent"
            )
            if duplicate_type == "exact":
                exact_duplicate_count += 1
            else:
                normalized_duplicate_count += 1
            duplicate_rows.append(
                {
                    "group_id": group_id,
                    "duplicate_type": duplicate_type,
                    "label": kept["label"],
                    "kept_source_file": kept["source_file"],
                    "kept_source_line": kept["source_line"],
                    "kept_original_text": kept["original_text"],
                    "duplicate_source_file": duplicate["source_file"],
                    "duplicate_source_line": duplicate["source_line"],
                    "duplicate_original_text": duplicate["original_text"],
                    "normalized_text": normalized_text,
                }
            )

    rows_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique_rows:
        rows_by_label[row["label"]].append(row)

    split_rows: list[dict[str, str]] = []
    for label in LABELS:
        label_rows = sorted(
            rows_by_label[label],
            key=lambda row: (_stable_group_order(row["group_id"], label, seed), row["group_id"]),
        )
        counts = _split_counts(len(label_rows))
        boundaries = (
            ("train", counts["train"]),
            ("validation", counts["train"] + counts["validation"]),
            ("test", len(label_rows)),
        )
        start = 0
        for split, stop in boundaries:
            for row in label_rows[start:stop]:
                split_rows.append({**row, "split": split})
            start = stop

    split_rows.sort(
        key=lambda row: (
            tuple(SPLIT_RATIOS).index(row["split"]),
            LABELS.index(row["label"]),
            row["group_id"],
        )
    )
    leakage_rows = find_cross_split_leakage(split_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    split_path = output_dir / "split_manifest.csv"
    write_csv(split_path, SPLIT_FIELDS, split_rows)
    write_csv(
        output_dir / "duplicate_report.csv",
        (
            "group_id",
            "duplicate_type",
            "label",
            "kept_source_file",
            "kept_source_line",
            "kept_original_text",
            "duplicate_source_file",
            "duplicate_source_line",
            "duplicate_original_text",
            "normalized_text",
        ),
        sorted(
            duplicate_rows,
            key=lambda row: (
                row["group_id"],
                row["duplicate_source_file"],
                row["duplicate_source_line"],
            ),
        ),
    )
    write_csv(
        output_dir / "label_conflict_report.csv",
        ("group_id", "normalized_text", "labels", "occurrence_count", "sources"),
        conflicts,
    )
    write_csv(
        output_dir / "leakage_report.csv",
        ("match_type", "match_sha256", "splits", "group_ids", "labels"),
        leakage_rows,
    )

    per_label = Counter(row["label"] for row in split_rows)
    per_split = Counter(row["split"] for row in split_rows)
    per_split_label = {
        split: dict(sorted(Counter(
            row["label"] for row in split_rows if row["split"] == split
        ).items()))
        for split in SPLIT_RATIOS
    }
    manifest = {
        "schema_version": 2,
        "evaluation_scope": "weak_label_grouped_holdout",
        "official_competition_metric": False,
        "random_seed": seed,
        "source_type": "weak_label",
        "source_files": source_manifest,
        "raw_line_count": sum(item["raw_line_count"] for item in source_manifest),
        "nonblank_line_count": len(records),
        "unique_after_exact_deduplication": len(records) - exact_duplicate_count,
        "unique_after_normalized_deduplication": len(split_rows),
        "unique_after_deduplication": len(split_rows),
        "exact_duplicate_count": exact_duplicate_count,
        "normalized_equivalent_duplicate_count": normalized_duplicate_count,
        "conflict_group_count": len(conflicts),
        "conflict_occurrence_count": sum(int(item["occurrence_count"]) for item in conflicts),
        "per_label_count": dict(sorted(per_label.items())),
        "per_split_count": dict(per_split),
        "per_split_label_count": per_split_label,
        "cross_split_leakage_count": len(leakage_rows),
        "cross_split_leakage_by_type": dict(
            sorted(Counter(row["match_type"] for row in leakage_rows).items())
        ),
        "build_parameters": {
            "split_ratios": SPLIT_RATIOS,
            "group_id": "SHA-256(normalized_text)",
            "deduplication": "exact_then_text_normalizer_equivalence",
            "conflict_policy": "exclude_all_multi_label_normalized_text_groups",
            "oversampling_before_split": False,
            "source_allowlist": [path for _, path in SOURCE_FILES],
            "evaluation_data_used": False,
        },
        "split_manifest_sha256": sha256_file(split_path),
    }
    write_json(output_dir / "data_manifest.json", manifest)
    return manifest


def model_pipeline(kind: str, seed: int = RANDOM_SEED) -> Pipeline:
    if kind not in MODEL_SPECS:
        raise ValueError(f"unknown model kind: {kind}")
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(**MODEL_SPECS[kind])),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    random_state=seed,
                    max_iter=2000,
                ),
            ),
        ]
    )


def split_xy(rows: list[dict[str, str]], split: str) -> tuple[list[str], list[str]]:
    selected = [row for row in rows if row["split"] == split]
    texts = [str(row["normalized_text"]) for row in selected]
    labels = [str(row["label"]) for row in selected]
    if not texts:
        raise ValueError(f"split contains no rows: {split}")
    return texts, labels


def metric_payload(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=list(LABELS),
        zero_division=0,
    )
    _, _, macro_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    macro_precision, macro_recall, _, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    _, _, weighted_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="weighted", zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=list(LABELS))
    normal_total = sum(1 for label in y_true if label == "normal")
    normal_false_positives = sum(
        1 for actual, predicted in zip(y_true, y_pred)
        if actual == "normal" and predicted != "normal"
    )
    risk_total = sum(1 for label in y_true if label in RISK_LABELS)
    risk_detected = sum(
        1 for actual, predicted in zip(y_true, y_pred)
        if actual in RISK_LABELS and predicted in RISK_LABELS
    )
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": {
            label: {
                "precision": precision[index],
                "recall": recall[index],
                "f1": f1[index],
                "support": int(support[index]),
            }
            for index, label in enumerate(LABELS)
        },
        "confusion_matrix": {
            "labels": list(LABELS),
            "values": matrix.tolist(),
        },
        "normal_false_positive_rate": (
            normal_false_positives / normal_total if normal_total else 0.0
        ),
        "risk_recall": risk_detected / risk_total if risk_total else 0.0,
        "sample_count": len(y_true),
    }


def metrics_document(kind: str, validation: dict[str, Any], test: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "model": kind,
        "evaluation_scope": "weak_label_grouped_holdout",
        "official_competition_metric": False,
        "validation": validation,
        "test": test,
    }


def train_candidates(
    split_manifest: Path,
    output_dir: Path,
    model_dir: Path,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    rows = read_split_manifest(split_manifest)
    train_texts, train_labels = split_xy(rows, "train")
    validation_texts, validation_labels = split_xy(rows, "validation")
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    validation_metrics: dict[str, dict[str, Any]] = {}
    training_seconds: dict[str, float] = {}
    candidate_paths: dict[str, Path] = {}
    for kind in MODEL_SPECS:
        model = model_pipeline(kind, seed)
        started = time.perf_counter()
        model.fit(list(train_texts), list(train_labels))
        training_seconds[kind] = time.perf_counter() - started
        validation_metrics[kind] = metric_payload(
            validation_labels,
            [str(item) for item in model.predict(list(validation_texts))],
        )
        candidate_path = model_dir / f"semantic_{kind}_v2.candidate.joblib"
        joblib.dump(model, candidate_path)
        candidate_paths[kind] = candidate_path
        write_json(
            output_dir / f"{kind}_metrics.json",
            metrics_document(kind, validation_metrics[kind], None),
        )

    ranking = sorted(
        MODEL_SPECS,
        key=lambda kind: (
            -validation_metrics[kind]["macro_f1"],
            -validation_metrics[kind]["accuracy"],
            kind,
        ),
    )
    selected = ranking[0]
    comparison = {
        "schema_version": 2,
        "evaluation_scope": "weak_label_grouped_holdout",
        "official_competition_metric": False,
        "selection_split": "validation",
        "selection_metric": "macro_f1_then_accuracy",
        "selected_model": selected,
        "test_metrics_used_for_selection": False,
        "validation": {
            kind: {
                "macro_f1": validation_metrics[kind]["macro_f1"],
                "accuracy": validation_metrics[kind]["accuracy"],
            }
            for kind in MODEL_SPECS
        },
        "training_duration_seconds": training_seconds,
    }
    write_json(output_dir / "model_comparison.json", comparison)
    run_config = {
        "schema_version": 2,
        "random_seed": seed,
        "evaluation_scope": "weak_label_grouped_holdout",
        "official_competition_metric": False,
        "split_manifest": split_manifest.as_posix(),
        "split_manifest_sha256": sha256_file(split_manifest),
        "models": {
            kind: {
                "tfidf": {
                    "analyzer": MODEL_SPECS[kind]["analyzer"],
                    "ngram_range": list(MODEL_SPECS[kind]["ngram_range"]),
                },
                "classifier": {
                    "type": "LogisticRegression",
                    "class_weight": "balanced",
                    "random_state": seed,
                    "max_iter": 2000,
                },
            }
            for kind in MODEL_SPECS
        },
        "training_text_field": "normalized_text",
        "test_evaluations_per_model": 1,
        "external_api_calls": False,
    }
    write_json(output_dir / "run_config.json", run_config)
    return comparison


def _write_confusion_csv(path: Path, split_metrics: dict[str, dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        matrix = split_metrics[split]["confusion_matrix"]["values"]
        for index, actual_label in enumerate(LABELS):
            rows.append(
                {
                    "split": split,
                    "actual_label": actual_label,
                    **{f"predicted_{label}": matrix[index][column] for column, label in enumerate(LABELS)},
                }
            )
    write_csv(
        path,
        ("split", "actual_label", *(f"predicted_{label}" for label in LABELS)),
        rows,
    )


def evaluate_candidates(
    project_root: Path,
    split_manifest: Path,
    output_dir: Path,
    model_dir: Path,
    seed: int = RANDOM_SEED,
    remove_candidates: bool = True,
) -> dict[str, Any]:
    rows = read_split_manifest(split_manifest)
    test_texts, test_labels = split_xy(rows, "test")
    comparison_path = output_dir / "model_comparison.json"
    if not comparison_path.is_file():
        raise FileNotFoundError(f"model comparison not found; run training first: {comparison_path}")
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    selected = comparison["selected_model"]
    evaluated_models: dict[str, Any] = {}

    for kind in MODEL_SPECS:
        metrics_path = output_dir / f"{kind}_metrics.json"
        candidate_path = model_dir / f"semantic_{kind}_v2.candidate.joblib"
        if not candidate_path.is_file():
            raise FileNotFoundError(f"candidate model not found; run training first: {candidate_path}")
        model = joblib.load(candidate_path)
        test_metrics = metric_payload(
            test_labels,
            [str(item) for item in model.predict(list(test_texts))],
        )
        document = json.loads(metrics_path.read_text(encoding="utf-8"))
        document["test"] = test_metrics
        write_json(metrics_path, document)
        _write_confusion_csv(
            output_dir / f"confusion_matrix_{kind}.csv",
            {"validation": document["validation"], "test": test_metrics},
        )
        evaluated_models[kind] = model

    selected_model = evaluated_models[selected]
    final_model_path = model_dir / "semantic_model_v2.joblib"
    joblib.dump(selected_model, final_model_path)
    data_manifest_path = output_dir / "data_manifest.json"
    metadata = {
        "schema_version": 2,
        "evaluation_scope": "weak_label_grouped_holdout",
        "official_competition_metric": False,
        "selected_model": selected,
        "model_parameters": {
            "tfidf": {
                "analyzer": MODEL_SPECS[selected]["analyzer"],
                "ngram_range": list(MODEL_SPECS[selected]["ngram_range"]),
            },
            "classifier": {
                "type": "LogisticRegression",
                "class_weight": "balanced",
                "random_state": seed,
                "max_iter": 2000,
            },
        },
        "labels": [str(item) for item in selected_model.classes_],
        "data_manifest_sha256": sha256_file(data_manifest_path),
        "split_manifest_sha256": sha256_file(split_manifest),
        "model_file": final_model_path.relative_to(project_root).as_posix()
        if final_model_path.is_relative_to(project_root)
        else final_model_path.as_posix(),
        "model_file_sha256": sha256_file(final_model_path),
        "random_seed": seed,
        "training_duration_seconds": comparison["training_duration_seconds"][selected],
        "versions": {
            "python": platform.python_version(),
            "pandas": pandas.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    write_json(output_dir / "model_metadata.json", metadata)
    comparison["test"] = {
        kind: {
            key: json.loads((output_dir / f"{kind}_metrics.json").read_text(encoding="utf-8"))["test"][key]
            for key in ("macro_f1", "accuracy", "normal_false_positive_rate", "risk_recall")
        }
        for kind in MODEL_SPECS
    }
    comparison["final_model_path"] = metadata["model_file"]
    write_json(comparison_path, comparison)

    if remove_candidates:
        for kind in MODEL_SPECS:
            candidate_path = model_dir / f"semantic_{kind}_v2.candidate.joblib"
            if candidate_path.exists():
                candidate_path.unlink()
    return comparison
