# SafeChat-Guard API Contract

This document defines the backend API contract for the integrated B/C review
competition package.

## Limits

- Maximum request body size: 64 KiB.
- Maximum length of `message`, `text`, and `raw_reply_override`: 4096
  characters per field.
- Request body read timeout: 10 seconds.
- Request bodies for POST endpoints must be JSON objects.
- If `Content-Type` is present, it must be `application/json`.
- User text fields must be non-empty strings.
- When the semantic model is missing or cannot be loaded, rule-based filtering
  still runs and model state is reported as degraded.

## Error Format

All API errors use:

```json
{
  "error": "invalid_request",
  "message": "message must be a non-empty string"
}
```

Status code convention:

- `400`: invalid JSON, invalid JSON object, or invalid `Content-Length`.
- `413`: request body exceeds the configured limit.
- `408`: request body read timed out.
- `415`: request media type is not JSON.
- `422`: JSON is valid, but a required field is missing or has the wrong type.
- `404`: endpoint not found.
- `500`: internal error. The response never contains exception details or user
  text.

## GET /health

Lightweight process health check. It does not require the semantic model to be
loaded.

Response:

```json
{
  "status": "ok",
  "service": "SafeChat-Guard",
  "config_version": "bc-feedback-v1"
}
```

## GET /ready

Readiness check for model-backed serving.

Status code is `200` only when the semantic model is loaded, its SHA-256 matches
the configured value, its class set matches the configured contract, and the
configured LLM provider is ready. A missing, damaged, replaced, or incompatible
model, or a remote LLM with missing configuration, returns `503` and
`status=degraded`; the rule layer remains available for safe degradation.

Response fields:

- `ready`: boolean readiness flag.
- `model_loaded`: semantic model loaded flag.
- `model_error`: model loading error, or `null`.
- `model_version`: configured model version.
- `model_sha256`: configured model file SHA-256.
- `config_version`: configured API/config version.
- `semantic_classifier`: detailed classifier status.
- `llm`: provider, mode, model, readiness, endpoint validity, and whether the
  configured key environment variable exists. It never returns the key value.
- `stats`: current runtime statistics.

The classifier status includes `actual_sha256`, `expected_sha256`,
`integrity_verified`, `classes`, `expected_classes`, and `classes_valid`.

## GET /api/stats

Returns compatible runtime statistics. Existing fields are preserved, with the
following B/C integration fields:

- `model_loaded`
- `model_error`
- `model_version`
- `model_sha256`
- `config_version`
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
- `window_start`
- `window_end`

An optional UTC/ISO-8601 query parameter limits statistics to events at or
after the requested time:

```text
GET /api/stats?since=2026-07-21T00:00:00Z
```

## POST /api/detect

Request:

```json
{
  "text": "sample text"
}
```

Response fields:

- `status`
- `model_loaded`
- `detections`
- `model_error`
- `model_version`
- `model_sha256`
- `config_version`
- `normalized_text`
- `semantic_scores`

## POST /api/chat

Request:

```json
{
  "message": "sample text",
  "raw_reply_override": "optional model output for tests"
}
```

`raw_reply_override` may be omitted or set to a string. Any other type returns
`422`.

Response fields:

- `allowed`
- `reply`
- `safe_input`
- `raw_reply`
- `rewrite`
- `input_filter`
- `output_filter`
- `service_error` when the remote model is unavailable

When input filtering blocks a request, the model is not called and `raw_reply`
is `null`. When output filtering blocks or sanitizes model output, `raw_reply`
is also `null`, so unsafe model text is never returned through the API.
If the configured remote model is unavailable, the endpoint returns `503`, a
safe user-facing reply, `service_error=llm_unavailable`, and `raw_reply=null`.

## Risk Category Boundary

The semantic model predicts `normal`, `ad`, `porn`, `sensitive`, and
`violence`. The `abuse` category is intentionally rule-only until a reviewed
abuse training set is available. API and frontend statistics accept the union
of rule and semantic categories.
