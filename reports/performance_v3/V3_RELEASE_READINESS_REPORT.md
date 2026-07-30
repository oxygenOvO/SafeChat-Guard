# SafeChat-Guard V3 release readiness report

Date: 2026-07-30
Branch: `feat/performance-v3`
Baseline HEAD: `09445fe97b4c8cc46b225748de962bf140e22b99`

## Decision

**V3 is recommended to replace V2**, provided the eventual explicit delivery includes both currently untracked V3 model files. This task did not stage, commit or push files.

## Delivery blockers

| Blocker | Result |
|---|---|
| V3 models ignored by Git | Closed with two filename-specific `.gitignore` exceptions |
| Frozen model identity | Closed; both SHA256 values unchanged |
| V3 runtime visibility | Closed; `/health` exposes active version, enable/readiness, individual model load state, fallback state/reason and three SHA256 values |
| Direct/production consistency | Closed; action and label 170/170, V3 used throughout, fallback 0 |
| Stale pre-holdout pytest assertion | Closed by replacing it with stronger post-holdout count/freeze/no-tuning/no-rerun assertions |
| Execution-count field | Closed by additive amendment; original execution manifest remains unchanged |
| Clean source delivery | Closed by external cleanroom validation |

## Frozen artifact identity

```text
risk_model_v3.joblib       205136 bytes  136b9952869c6662eaa77e65d3a22e3cac3eddfe3f751ffa55bc99fd80845785
block_model_v3.joblib      205136 bytes  412f46781bcba63de8ada1d8781296acdbb25447f303130d0926cff6bd176b21
action_thresholds_v3.json                5332006befae66475c9e7449d7c48dafd2ed6e5dba3ca6a5f7c0d2179783c3a2
```

## Acceptance summary

- Production equivalence: 170/170 action, 170/170 label, fallback 0.
- Cleanroom: model hashes correct; API, Streamlit, pass/sanitize/block, rule read and statistics passed.
- Full pytest: 571 passed.
- Limited compileall command: passed.
- `git diff --check`: passed.

## Holdout integrity statement

The formal internal holdout was not rerun. Its text and the two false-positive records were not read or analyzed. No post-holdout tuning occurred. Models, thresholds, rules, datasets and action-core filtering logic were not changed. The original holdout execution manifest was not modified; only the required amendment was added.

## Remaining delivery note

The two V3 model files are now visible to Git but remain untracked because staging and committing were prohibited. A later authorized release operation must name and include them explicitly; it must not use `git add .` or `git add -A`.
