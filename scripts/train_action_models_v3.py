from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
)
from sklearn.pipeline import FeatureUnion, Pipeline


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_FIELDS = {
    "sample_id", "text", "label", "expected_action", "intent", "context",
    "template_family", "source_type", "split",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_train(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED_FIELDS <= set(reader.fieldnames or ()):
            raise ValueError("V3 train dataset is missing required fields")
        rows = [dict(row) for row in reader]
    if not rows or any(row["split"] != "train" for row in rows):
        raise ValueError("action model training accepts train split only")
    return rows


def action_pipeline(class_weight: dict[int, float], seed: int) -> Pipeline:
    features = FeatureUnion(
        [
            (
                "char",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=2,
                    sublinear_tf=True,
                ),
            ),
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    return Pipeline(
        [
            ("features", features),
            (
                "classifier",
                LogisticRegression(
                    class_weight=class_weight,
                    random_state=seed,
                    max_iter=2000,
                    C=2.0,
                    solver="liblinear",
                ),
            ),
        ]
    )


def binary_metrics(y_true: list[int], y_pred: list[int]) -> dict:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "positive_precision": float(precision),
        "positive_recall": float(recall),
        "positive_f1": float(f1),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train V3 action models.")
    parser.add_argument(
        "--train",
        type=Path,
        default=ROOT / "data/evaluation/performance_v3_train.csv",
    )
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports/performance_v3/training_metrics.json",
    )
    parser.add_argument("--seed", type=int, default=43)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    rows = read_train(args.train)
    texts = [row["text"] for row in rows]
    risk_y = [int(row["expected_action"] != "pass") for row in rows]
    block_y = [int(row["expected_action"] == "block") for row in rows]

    risk_model = action_pipeline({0: 1.35, 1: 1.0}, args.seed)
    block_model = action_pipeline({0: 1.0, 1: 2.6}, args.seed)
    risk_model.fit(texts, risk_y)
    block_model.fit(texts, block_y)

    args.model_dir.mkdir(parents=True, exist_ok=True)
    risk_path = args.model_dir / "risk_model_v3.joblib"
    block_path = args.model_dir / "block_model_v3.joblib"
    joblib.dump(risk_model, risk_path)
    joblib.dump(block_model, block_path)

    report = {
        "schema_version": 1,
        "training_split": "train",
        "sample_count": len(rows),
        "retired_diagnostic_data_used": False,
        "internal_holdout_used": False,
        "features": {
            "char_tfidf": {"ngram_range": [2, 5], "min_df": 2},
            "word_tfidf": {"ngram_range": [1, 2], "min_df": 2},
            "feature_fusion": "FeatureUnion",
        },
        "models": {
            "risk": {
                "algorithm": "LogisticRegression",
                "class_weight": {"0": 1.35, "1": 1.0},
                "metrics_on_train": binary_metrics(
                    risk_y, [int(value) for value in risk_model.predict(texts)]
                ),
                "path": "models/risk_model_v3.joblib",
                "sha256": sha256_file(risk_path),
            },
            "block": {
                "algorithm": "LogisticRegression",
                "class_weight": {"0": 1.0, "1": 2.6},
                "metrics_on_train": binary_metrics(
                    block_y, [int(value) for value in block_model.predict(texts)]
                ),
                "path": "models/block_model_v3.joblib",
                "sha256": sha256_file(block_path),
            },
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "V3 action models trained: "
        f"samples={len(rows)}, risk_sha256={report['models']['risk']['sha256']}, "
        f"block_sha256={report['models']['block']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
