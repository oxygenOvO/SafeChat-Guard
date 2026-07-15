from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.semantic_baseline_v2_common import RANDOM_SEED, evaluate_candidates
except ModuleNotFoundError:
    from semantic_baseline_v2_common import RANDOM_SEED, evaluate_candidates


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Evaluate semantic baseline V2 once on test.")
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=project_root / "reports/semantic_baseline_v2/split_manifest.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "reports/semantic_baseline_v2",
    )
    parser.add_argument("--model-dir", type=Path, default=project_root / "models")
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_candidates(
        args.project_root.resolve(),
        args.split_manifest.resolve(),
        args.output_dir.resolve(),
        args.model_dir.resolve(),
        args.random_seed,
    )
    print(
        "semantic baseline V2 evaluated: "
        f"selected={result['selected_model']}, scope={result['evaluation_scope']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
