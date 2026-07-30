# SafeChat-Guard V3 cleanroom delivery report

Date: 2026-07-30

## Cleanroom

- Path: `D:\Projects\SafeChat-Guard-performance-v3-cleanroom-20260730`
- Location: outside the Git worktree.
- Files: 152.
- Total file bytes: 1,901,681.
- `.git`, cache directories, `.pyc/.pyo`, `.env*`, PEM/key files and `secrets.toml`: absent.
- `reports` directory: excluded.
- `data/evaluation` directory: excluded.
- `performance_v3_internal_holdout.csv`: absent.
- `internal_holdout_metrics.json`: absent.
- one-time internal holdout runner: excluded.

No holdout text or per-record prediction artifact was copied or inspected.

## Frozen models

| Model | Size | SHA256 |
|---|---:|---|
| `models/risk_model_v3.joblib` | 205,136 bytes | `136b9952869c6662eaa77e65d3a22e3cac3eddfe3f751ffa55bc99fd80845785` |
| `models/block_model_v3.joblib` | 205,136 bytes | `412f46781bcba63de8ada1d8781296acdbb25447f303130d0926cff6bd176b21` |

Both files exist in the cleanroom and match the pre-holdout freeze hashes.

## Runtime acceptance

The cleanroom API was started on a temporary local port with audit logging redirected to a system temporary directory.

- `GET /health`: HTTP 200.
- `active_filter_version=v3`.
- `v3_enabled=true`, `v3_ready=true`.
- Both V3 models loaded.
- `fallback_active=false`, `fallback_reason=null`.
- Health model and threshold hashes matched the frozen files.
- Public pass example: pass, no fallback.
- Public sanitize example: sanitize, no fallback.
- Public block example: block, no fallback.
- `GET /api/rules`: HTTP 200, 1,807 rules readable.
- `GET /api/stats`: HTTP 200, statistics returned normally.
- Streamlit headless startup: HTTP 200.

Runtime-created cache and empty log directories were removed after validation. The final cleanroom scan found zero forbidden files and zero cache/Git directories.

## Conclusion

The cleanroom contains the required V3 runtime, frozen models and dependencies while excluding repository metadata, caches, credentials and evaluation/holdout artifacts. API and Streamlit startup and core operational checks passed.
