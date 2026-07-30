from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/performance_v3/freeze_manifest.txt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    audit = json.loads(
        (ROOT / "reports/performance_v3/dataset_audit.json").read_text(
            encoding="utf-8"
        )
    )
    dev_metrics = json.loads(
        (ROOT / "reports/performance_v3/dev_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    required = [
        ROOT / "models/risk_model_v3.joblib",
        ROOT / "models/block_model_v3.joblib",
        ROOT / "config/action_thresholds_v3.json",
        ROOT / "config/action_rules_v1.json",
        ROOT / "data/rules/regex_rules.json",
        ROOT / "safechat_guard/action_models_v3.py",
        ROOT / "safechat_guard/action_router_v3.py",
        ROOT / "safechat_guard/pipeline.py",
        ROOT / "scripts/build_performance_dataset_v3.py",
        ROOT / "scripts/train_action_models_v3.py",
        ROOT / "scripts/calibrate_action_thresholds_v3.py",
        ROOT / "scripts/calibrate_action_thresholds_v3_fast.py",
        ROOT / "data/evaluation/performance_v3_train.csv",
        ROOT / "data/evaluation/performance_v3_dev.csv",
        ROOT / "data/evaluation/performance_v3_internal_holdout.csv",
    ]
    required.extend(sorted((ROOT / "data/lexicons").glob("*")))
    missing = [relative(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"freeze inputs missing: {missing}")
    holdout_path = ROOT / audit["files"]["internal_holdout"]["path"]
    holdout_hash = sha256_file(holdout_path)
    if holdout_hash != audit["files"]["internal_holdout"]["sha256"]:
        raise RuntimeError("internal_holdout hash changed after dataset audit")
    if not dev_metrics["thresholds_frozen"]:
        raise RuntimeError("Dev thresholds are not frozen")

    lines = [
        "SafeChat-Guard performance V3 pre-holdout freeze manifest",
        "schema_version=1",
        "state=PRE_HOLDOUT_FROZEN",
        "internal_holdout_evaluated=false",
        "internal_holdout_text_inspected=false",
        "internal_holdout_metrics_computed=false",
        "internal_holdout_run_count=0",
        "threshold_calibration_split=dev",
        f"dev_thresholds_frozen={str(dev_metrics['thresholds_frozen']).lower()}",
        f"dev_block_recall={dev_metrics['high_risk_block_recall']:.6f}",
        f"dev_normal_fpr={dev_metrics['normal_false_positive_rate']:.6f}",
        f"dev_sanitize_recall={dev_metrics['sanitize_routing_recall']:.6f}",
        f"holdout_row_count={audit['counts']['internal_holdout']['total']}",
        "holdout_structure_valid=true",
        "holdout_template_family_cross_split_count="
        f"{audit['template_family_cross_split_count']}",
        "holdout_exact_duplicate_count="
        f"{audit['exact_text_duplicate_count']}",
        "holdout_normalized_duplicate_count="
        f"{audit['normalized_text_duplicate_count']}",
        "",
        "[sha256]",
    ]
    lines.extend(
        f"{sha256_file(path)}  {relative(path)}" for path in required
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"pre-holdout manifest written: files={len(required)}, "
        f"holdout_rows={audit['counts']['internal_holdout']['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
