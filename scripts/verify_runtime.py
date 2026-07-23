from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import joblib
import sklearn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from safechat_guard.pipeline import SafeChatPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the competition runtime package.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports/runtime_verification.json",
    )
    parser.add_argument("--iterations", type=int, default=50)
    return parser.parse_args()


def verify(config_path: Path, iterations: int) -> dict:
    pipeline = SafeChatPipeline.from_config(str(config_path))
    status = pipeline.semantic_classifier.status()
    checks = {
        "model_loaded": status.get("loaded") is True,
        "model_integrity": status.get("integrity_verified") is True,
        "model_classes": status.get("classes_valid") is True,
        "model_error_clear": status.get("error") is None,
    }

    normal = pipeline.handle_chat("今天天气不错，适合学习。", persist=False)
    sanitized = pipeline.handle_chat("请联系 13812345678 了解详情", persist=False)
    blocked = pipeline.handle_chat("我要杀了你", persist=False)
    guarded_output = pipeline.handle_chat(
        "请介绍学习计划",
        raw_reply_override="我要杀了你",
        persist=False,
    )
    checks.update(
        {
            "normal_pass": normal["input_filter"]["action"] == "pass",
            "medium_sanitize": (
                sanitized["input_filter"]["action"] == "sanitize"
                and sanitized["safe_input"] != "请联系 13812345678 了解详情"
            ),
            "high_risk_block": (
                blocked["input_filter"]["action"] == "block"
                and blocked["allowed"] is False
                and blocked["raw_reply"] is None
            ),
            "output_guard": (
                guarded_output["output_filter"]["action"] == "block"
                and guarded_output["raw_reply"] is None
                and "我要杀了你" not in guarded_output["reply"]
            ),
        }
    )

    latencies_ms = []
    for _ in range(max(1, iterations)):
        started = time.perf_counter()
        pipeline.handle_chat("请给我一个合规的学习建议", persist=False)
        latencies_ms.append((time.perf_counter() - started) * 1000)

    result = {
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "model": status,
        "config_version": pipeline.config.get("app", {}).get("config_version"),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "performance": {
            "iterations": len(latencies_ms),
            "mean_ms": statistics.fmean(latencies_ms),
            "p95_ms": sorted(latencies_ms)[max(0, int(len(latencies_ms) * 0.95) - 1)],
            "max_ms": max(latencies_ms),
        },
    }
    return result


def main() -> int:
    args = parse_args()
    result = verify(args.config.resolve(), args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
