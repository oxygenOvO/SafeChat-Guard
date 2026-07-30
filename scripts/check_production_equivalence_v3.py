from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api_server
from safechat_guard.pipeline import SafeChatPipeline


SAFE_REPLY = "?????????????????"


@dataclass(frozen=True)
class EquivalenceCase:
    suite: str
    case_id: str
    text: str


def _csv_cases(path: Path, suite: str, expected_count: int) -> list[EquivalenceCase]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_count:
        raise ValueError(
            f"{suite} requires {expected_count} public cases, got {len(rows)}"
        )
    return [EquivalenceCase(suite, row["id"], row["message"]) for row in rows]


def _generalization_cases() -> list[EquivalenceCase]:
    risk_entities = (
        "??????",
        "????",
        "????",
        "??????",
        "?????",
        "??????",
        "????",
        "????",
    )
    operation_templates = (
        "??????{entity}????????",
        "???????{entity}????????",
        "????????{entity}??????",
        "??????????????{entity}?",
        "{entity}?????????????????",
    )
    cases = [
        EquivalenceCase(
            "generalization_62",
            f"GEN-BLOCK-{entity_index:02d}-{template_index:02d}",
            template.format(entity=entity),
        )
        for entity_index, entity in enumerate(risk_entities, 1)
        for template_index, template in enumerate(operation_templates, 1)
    ]

    contextual_entities = (
        "??????",
        "?????????",
        "?????????",
        "????????",
    )
    contextual_templates = (
        "??????{entity}?",
        "????????{entity}?",
        "??????{entity}???",
        "???????{entity}?",
    )
    cases.extend(
        EquivalenceCase(
            "generalization_62",
            f"GEN-SAN-{entity_index:02d}-{template_index:02d}",
            template.format(entity=entity),
        )
        for entity_index, entity in enumerate(contextual_entities, 1)
        for template_index, template in enumerate(contextual_templates, 1)
    )

    explicit_operations = (
        "?????????????????????",
        "?????????????????????",
        "???????????????????",
        "????????????????????",
        "???????????????????",
        "??????????????????????????",
    )
    cases.extend(
        EquivalenceCase("generalization_62", f"GEN-PRE-{index:02d}", text)
        for index, text in enumerate(explicit_operations, 1)
    )
    if len(cases) != 62:
        raise AssertionError(f"generalization suite count is {len(cases)}, expected 62")
    return cases


def _safety_negative_cases() -> list[EquivalenceCase]:
    quoted_risks = (
        "??????",
        "????????",
        "????",
        "??????",
        "???????",
        "????????",
        "??????",
        "??????",
        "????",
        "??????",
        "??????",
        "??????",
    )
    safe_templates = (
        "???????{risk}????????????????",
        "???????{risk}??????????????",
        "??????{risk}??????????????",
    )
    cases = [
        EquivalenceCase(
            "safety_negative_36",
            f"SAFE-{risk_index:02d}-{template_index:02d}",
            template.format(risk=risk),
        )
        for risk_index, risk in enumerate(quoted_risks, 1)
        for template_index, template in enumerate(safe_templates, 1)
    ]
    if len(cases) != 36:
        raise AssertionError(f"safety suite count is {len(cases)}, expected 36")
    return cases


def load_public_cases(root: Path = ROOT) -> list[EquivalenceCase]:
    cases = [
        *_csv_cases(
            root / "reports/final_validation/manual_adversarial_matrix_v1.csv",
            "manual_adversarial_40",
            40,
        ),
        *_csv_cases(
            root / "reports/final_validation/context_boundary_matrix_v2.csv",
            "context_boundary_32",
            32,
        ),
        *_generalization_cases(),
        *_safety_negative_cases(),
    ]
    if len(cases) != 170:
        raise AssertionError(f"equivalence total is {len(cases)}, expected 170")
    identifiers = [(case.suite, case.case_id) for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise AssertionError("equivalence case identifiers must be unique")
    return cases


def run_equivalence(root: Path = ROOT) -> dict[str, Any]:
    cases = load_public_cases(root)
    pipeline = SafeChatPipeline.from_config(str(root / "config.yaml"))
    previous_pipeline = api_server.pipeline
    api_server.pipeline = pipeline
    results: list[dict[str, Any]] = []
    try:
        health = api_server.build_health_payload()
        for case in cases:
            direct = pipeline.detect_text(case.text)
            production = pipeline.handle_chat(
                case.text,
                raw_reply_override=SAFE_REPLY,
                persist=False,
            )
            results.append(
                {
                    "suite": case.suite,
                    "case_id": case.case_id,
                    "production_completed": True,
                    "action_match": (
                        direct["action"] == production.get("action")
                        and direct["action"] == production.get("final_action")
                    ),
                    "label_match": direct["category"] == production.get("category"),
                    "no_fallback": (
                        direct.get("fallback_used") is False
                        and production.get("fallback_used") is False
                    ),
                }
            )
    finally:
        api_server.pipeline = previous_pipeline

    suite_names = (
        "manual_adversarial_40",
        "context_boundary_32",
        "generalization_62",
        "safety_negative_36",
    )
    by_suite = {}
    for suite in suite_names:
        selected = [result for result in results if result["suite"] == suite]
        by_suite[suite] = {
            "sample_count": len(selected),
            "action_matches": sum(result["action_match"] for result in selected),
            "label_matches": sum(result["label_match"] for result in selected),
            "no_fallback": sum(result["no_fallback"] for result in selected),
            "production_completed": sum(
                result["production_completed"] for result in selected
            ),
        }
    return {
        "sample_count": len(results),
        "action_matches": sum(result["action_match"] for result in results),
        "label_matches": sum(result["label_match"] for result in results),
        "no_fallback": sum(result["no_fallback"] for result in results),
        "production_completed": sum(
            result["production_completed"] for result in results
        ),
        "health": {
            "active_filter_version": health.get("active_filter_version"),
            "v3_enabled": health.get("v3_enabled"),
            "v3_ready": health.get("v3_ready"),
            "risk_model_loaded": health.get("risk_model_loaded"),
            "block_model_loaded": health.get("block_model_loaded"),
            "fallback_active": health.get("fallback_active"),
            "fallback_reason": health.get("fallback_reason"),
            "risk_model_sha256": health.get("risk_model_sha256"),
            "block_model_sha256": health.get("block_model_sha256"),
            "threshold_config_sha256": health.get("threshold_config_sha256"),
        },
        "failed_case_ids": [
            f"{result['suite']}:{result['case_id']}"
            for result in results
            if not (
                result["production_completed"]
                and result["action_match"]
                and result["label_match"]
                and result["no_fallback"]
            )
        ],
    }


def main() -> int:
    summary = run_equivalence()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (
        summary["sample_count"] == 170
        and summary["action_matches"] == 170
        and summary["label_matches"] == 170
        and summary["no_fallback"] == 170
        and summary["production_completed"] == 170
        and summary["health"]["v3_ready"] is True
        and summary["health"]["fallback_active"] is False
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
