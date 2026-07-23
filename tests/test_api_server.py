from datetime import timezone
from io import BytesIO
from types import SimpleNamespace

import api_server
from api_server import (
    MAX_TEXT_CHARS,
    SafeChatApiHandler,
    build_detect_payload,
    build_health_payload,
    build_ready_payload,
    error_payload,
    parse_since,
)
from safechat_guard.models import Detection


def test_detect_payload_uses_rule_and_semantic_union(monkeypatch):
    monkeypatch.setattr(
        api_server.pipeline.semantic_classifier,
        "detect",
        lambda text: [
            Detection("ad", "medium", 70, "semantic", "semantic_ml", ["evidence"])
        ],
    )

    payload = build_detect_payload("contact 13812345678")
    sources = {item["source"] for item in payload["detections"]}

    assert payload["status"] == "success"
    assert {"regex", "semantic_ml"} <= sources
    assert payload["action"] in {"sanitize", "block"}
    assert {"model_loaded", "model_error", "normalized_text", "risk_score"} <= payload.keys()


def test_health_payload_has_contract_fields():
    payload = build_health_payload()

    assert payload == {"status": "ok", "service": "SafeChat-Guard"}


def test_ready_payload_reports_runtime_state_without_stale_versions():
    payload, status = build_ready_payload()

    assert status in {200, 503}
    assert payload["status"] in {"ready", "degraded"}
    assert {"ready", "semantic_classifier", "llm", "stats"} <= payload.keys()
    assert "config_version" not in payload
    assert "model_version" not in payload


def test_error_payload_uses_stable_contract():
    assert error_payload("invalid_request", "bad") == {
        "error": "invalid_request",
        "message": "bad",
    }


def test_read_json_rejects_non_object_body():
    handler = SimpleNamespace(headers={"Content-Length": "2"}, rfile=BytesIO(b"[]"))
    payload, error = SafeChatApiHandler._read_json(handler)
    assert payload is None and error == "invalid_json_body"


def test_read_json_rejects_invalid_utf8():
    handler = SimpleNamespace(headers={"Content-Length": "1"}, rfile=BytesIO(b"\xff"))
    payload, error = SafeChatApiHandler._read_json(handler)
    assert payload is None and error == "invalid_encoding"


def test_read_json_rejects_oversized_body():
    handler = SimpleNamespace(
        headers={"Content-Length": str(64 * 1024 + 1)}, rfile=BytesIO(b"")
    )
    payload, error = SafeChatApiHandler._read_json(handler)
    assert payload is None and error == "request_too_large"


def test_read_json_rejects_non_json_content_type():
    handler = SimpleNamespace(
        headers={"Content-Length": "2", "Content-Type": "text/plain"},
        rfile=BytesIO(b"{}"),
    )
    payload, error = SafeChatApiHandler._read_json(handler)
    assert payload is None and error == "unsupported_media_type"


def test_text_field_length_limit_is_enforced():
    value, error = SafeChatApiHandler._validate_text_field(
        {"message": "x" * (MAX_TEXT_CHARS + 1)}, "message"
    )
    assert value is None
    assert error == (
        "text_too_long",
        f"message exceeds the maximum of {MAX_TEXT_CHARS} characters",
        413,
    )


def test_parse_since_normalizes_utc_timestamp():
    parsed = parse_since("2026-07-21T01:02:03Z")
    assert parsed.tzinfo == timezone.utc
    assert parsed.isoformat() == "2026-07-21T01:02:03+00:00"
