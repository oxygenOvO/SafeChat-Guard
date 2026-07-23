# SafeChat-Guard Competition Operations

## Supported Runtime

- Python 3.14
- Dependencies pinned in `requirements.txt` and `requirements-dev.txt`
- Windows 11 and GitHub Actions Windows/Linux jobs
- Offline-safe default: `llm.provider=mock`

Install and verify:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\verify_runtime.py
.\.venv\Scripts\python.exe -m pytest -q
```

## Startup

API:

```powershell
.\.venv\Scripts\python.exe api_server.py
```

Frontend:

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend\streamlit_app.py
```

The default Mock mode is fully offline and is recommended for a guaranteed
demo. To use Qwen's OpenAI-compatible endpoint, set `llm.provider` to `qwen`,
set an HTTPS chat-completions URL and model in `config.yaml`, then provide the
key only through the configured environment variable:

```powershell
$env:QWEN_API_KEY = "<competition-secret>"
.\.venv\Scripts\python.exe api_server.py
```

The key is never stored in the project or returned by status endpoints. An
unknown provider no longer silently falls back to Mock. Remote request failures
return a safe `503` response and do not expose upstream error bodies.

Preflight checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Do not start the public demonstration if `/ready` returns `503`. The rule layer
still degrades safely, but either the semantic model or configured remote LLM
is not in the accepted state.

## Model Artifact

The only active model path is `models/semantic_model_v2.joblib`. Its version,
SHA-256, class contract, build runtime, and data manifest are recorded in
`models/MODEL_MANIFEST.json`. Startup verifies SHA-256 before `joblib.load()`
and rejects a replaced model before deserialization.

The packaged model is a reproducible char n-gram weak-label baseline. Its
metrics are engineering evidence, not an official competition score. Replace
it only through the B-to-C handoff contract and update all of the following in
one reviewed change:

1. Model artifact.
2. `models/MODEL_MANIFEST.json`.
3. `config.yaml` model path, version, SHA-256, and classes.
4. Independent evaluation report.
5. Runtime verification output.

## Logging

JSONL event logs are recursively redacted before disk write. The default
policy is 5 MiB per file, five backups, and seven-day retention. Writes and
reads share a process lock so concurrent requests cannot produce partial JSON
records. Malformed residual lines are ignored by statistics instead of taking
down `/api/stats`.

Logs remain local under `data/logs/` and are excluded from version control.
Before submission, run:

```powershell
.\.venv\Scripts\python.exe scripts\security_scan.py
```

## Incident Checklist

If `/ready` fails, inspect only the non-sensitive model fields returned by the
endpoint. Restore the trusted artifact whose SHA matches the manifest; do not
edit the configured hash to match an unexplained file.

If an API credential has ever appeared in Git history, revoke it in the
provider console and review usage. Code changes cannot revoke an external
credential or erase already-cloned history.
