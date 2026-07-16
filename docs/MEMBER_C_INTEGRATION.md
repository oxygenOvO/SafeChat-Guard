# Member C Integration Notes

This document describes the Group C backend integration work.

## Scope

- Configurable semantic thresholds.
- Extended `/api/stats` statistics.
- Batch full-pipeline evaluation script.
- GitHub Actions test workflow.
- Safe degradation when the semantic model cannot be loaded.

## Semantic Thresholds

Thresholds are configured in `config.yaml`:

```json
"semantic_thresholds": {
  "ad": 0.65,
  "porn": 0.55,
  "violence": 0.55,
  "sensitive": 0.65
}
```

If the field is missing, the same defaults are used. Invalid categories,
non-numeric values, or values outside `[0, 1]` raise clear `ValueError`
messages during pipeline initialization.

## Batch Evaluation

Default command:

```bash
python scripts/evaluate_pipeline.py
```

Default input:

```text
data/test_cases/frontend_cases.csv
```

Default outputs:

```text
reports/pipeline_eval_results.csv
reports/pipeline_eval_summary.json
```

Custom input example:

```bash
python scripts/evaluate_pipeline.py --input data/test_cases/frontend_cases.csv --text-column input_text --label-column expected_category
```

The output CSV includes rule result, semantic result, final action, risk score,
sanitized result, and whether the prediction is correct.

## Extended Stats

`/api/stats` keeps the original fields and adds:

- `model_loaded`
- `model_error`
- `semantic_classifier`
- `rule_hit_count`
- `semantic_hit_count`
- `joint_rule_semantic_hit_count`
- `category_detection_counts`
- `stage_counts`
- `input_detection_count`
- `output_detection_count`
- `input_action_counts`
- `output_action_counts`

## Safe Degradation

When `models/semantic_model.pkl` is missing, `joblib` is unavailable, or model
loading fails, the semantic classifier reports the error through `status()`.
The pipeline still runs the normalizer, rule filter, risk decision, and output
guard.

## CI

`.github/workflows/tests.yml` runs on pull requests and pushes to `main`:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall .
```
