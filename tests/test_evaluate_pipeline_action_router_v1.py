from __future__ import annotations

import csv
import json

import pytest

from scripts.evaluate_pipeline_action_router_v1 import (
    ERROR_FIELDS,
    FixedSafeLLM,
    evaluate_rows,
    load_calibration_rows,
    main,
    write_outputs,
)


class FakePipeline:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def handle_chat(self, text, persist=True):
        self.calls.append((text, persist))
        return self.results.pop(0)


def pipeline_result(
    action,
    *,
    hard_block=False,
    rewrite_called=False,
    rewrite_changed=False,
    recheck_action=None,
    model_forwarded=False,
    fallback_used=False,
    reason_codes=None,
):
    filtered = {
        "action": action,
        "category": "normal" if action == "pass" else "ad",
        "risk_level": "high" if action == "block" else (
            "medium" if action == "sanitize" else "none"
        ),
        "risk_score": 90 if action == "block" else (
            60 if action == "sanitize" else 0
        ),
        "reason_codes": reason_codes or ["SYNTHETIC"],
        "hard_block": hard_block,
        "rewrite_called": rewrite_called,
        "rewrite_changed": rewrite_changed,
        "recheck_action": recheck_action,
        "fallback_used": fallback_used,
    }
    return {
        "input_filter": filtered,
        "model_forwarded": model_forwarded,
        "output_guard_action": "pass" if model_forwarded else None,
        "latency_ms": 3,
    }


def row(sample_id, text, expected_action):
    return {
        "sample_id": sample_id,
        "text": text,
        "label": "normal" if expected_action == "pass" else "ad",
        "expected_action": expected_action,
    }


def test_evaluator_metrics_and_predictions_are_complete_without_text():
    rows = [
        row("pass", "ordinary", "pass"),
        row("sanitize", "mask", "sanitize"),
        row("block", "deny", "block"),
        row("miss", "miss", "block"),
    ]
    pipeline = FakePipeline(
        [
            pipeline_result("pass", model_forwarded=True),
            pipeline_result(
                "sanitize", rewrite_called=True, rewrite_changed=True,
                recheck_action="pass", model_forwarded=True,
            ),
            pipeline_result("block", hard_block=True),
            pipeline_result("pass", model_forwarded=True),
        ]
    )

    metrics = evaluate_rows(rows, pipeline, input_sha256="a" * 64)

    assert metrics["sample_count"] == 4
    assert metrics["action_accuracy"] == 0.75
    assert metrics["block_recall"] == 0.5
    assert metrics["sanitize_recall"] == 1.0
    assert metrics["normal_false_positive_rate"] == 0.0
    assert metrics["hard_block_forwarded_count"] == 0
    assert metrics["unsafe_recheck_forwarded_count"] == 0
    assert metrics["confusion_matrix"]["values"] == [
        [1, 0, 0], [0, 1, 0], [1, 0, 1]
    ]
    assert set(metrics["predictions"][0]) == set(ERROR_FIELDS)
    assert all("text" not in item for item in metrics["predictions"])
    assert all(persist is False for _, persist in pipeline.calls)


def test_forwarding_invariant_counters_detect_violations():
    metrics = evaluate_rows(
        [row("hard", "one", "block"), row("recheck", "two", "sanitize")],
        FakePipeline(
            [
                pipeline_result("block", hard_block=True, model_forwarded=True),
                pipeline_result(
                    "block", rewrite_called=True, rewrite_changed=True,
                    recheck_action="sanitize", model_forwarded=True,
                ),
            ]
        ),
    )

    assert metrics["hard_block_forwarded_count"] == 1
    assert metrics["unsafe_recheck_forwarded_count"] == 1


@pytest.mark.parametrize(
    ("filtered", "expected"),
    [
        (
            pipeline_result(
                "block", rewrite_called=True,
                reason_codes=["SANITIZER_UNCHANGED"],
            ),
            "sanitizer_unchanged",
        ),
        (
            pipeline_result(
                "block", rewrite_called=True, rewrite_changed=True,
                recheck_action="sanitize",
            ),
            "recheck_still_sanitize",
        ),
        (
            pipeline_result("block", fallback_used=True),
            "action_router_error",
        ),
    ],
)
def test_sanitize_error_classification_is_stable(filtered, expected):
    metrics = evaluate_rows(
        [row("sample", "synthetic", "sanitize")], FakePipeline([filtered])
    )

    assert metrics["predictions"][0]["error"] == expected


def test_outputs_contain_only_action_errors_and_no_raw_text(tmp_path):
    metrics = evaluate_rows(
        [row("ok", "secret one", "pass"), row("bad", "secret two", "block")],
        FakePipeline(
            [
                pipeline_result("pass", model_forwarded=True),
                pipeline_result("pass", model_forwarded=True),
            ]
        ),
    )
    output = tmp_path / "metrics.json"
    errors = tmp_path / "errors.csv"

    write_outputs(metrics, output, errors)

    stored = json.loads(output.read_text(encoding="utf-8"))
    error_rows = list(csv.DictReader(errors.open(encoding="utf-8")))
    assert len(stored["predictions"]) == 2
    assert len(error_rows) == 1
    assert set(error_rows[0]) == set(ERROR_FIELDS)
    serialized = output.read_text(encoding="utf-8") + errors.read_text(encoding="utf-8")
    assert "secret one" not in serialized
    assert "secret two" not in serialized


def test_fixed_llm_is_offline_and_deterministic():
    llm = FixedSafeLLM()

    first = llm.chat("one")
    second = llm.chat("two")

    assert first == second
    assert llm.calls == ["one", "two"]
    assert llm.status()["mode"] == "offline_fake"
    assert llm.status()["key_configured"] is False


def test_loader_rejects_test_before_reading(tmp_path):
    with pytest.raises(ValueError, match="restricted.*calibration"):
        load_calibration_rows(tmp_path / "missing.csv", "test")


def test_loader_rejects_combined_gold_before_reading(tmp_path):
    with pytest.raises(ValueError, match="combined Gold is forbidden"):
        load_calibration_rows(tmp_path / "semantic_gold_v1.csv", "calibration")


def test_main_returns_nonzero_for_forbidden_gold(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate_pipeline_action_router_v1.py",
            "--project-root", str(tmp_path),
            "--gold", "semantic_gold_v1.csv",
            "--evaluation-split", "calibration",
        ],
    )

    assert main() == 2