from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.semantic_baseline_v2_common import RANDOM_SEED, build_semantic_data
except ModuleNotFoundError:
    from semantic_baseline_v2_common import RANDOM_SEED, build_semantic_data


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build deterministic weak-label semantic data V2.")
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "reports/semantic_baseline_v2",
    )
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_semantic_data(args.project_root, args.output_dir, args.random_seed)
    print(
        "semantic data V2 built: "
        f"unique={manifest['unique_after_deduplication']}, "
        f"conflicts={manifest['conflict_group_count']}, "
        f"leakage={manifest['cross_split_leakage_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
