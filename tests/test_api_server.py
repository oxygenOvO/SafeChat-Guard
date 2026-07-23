from io import BytesIO
from datetime import timezone
from types import SimpleNamespace

from api_server import (
    MAX_TEXT_CHARS,
    SafeChatApiHandler,
    build_detect_payload,
    build_health_payload,
    build_ready_payload,
    error_payload,
    parse_since,
)


def test_detect_payload_has_frontend_contract_fields():
    payload = build_detect_payload("加 V-X 领取优 惠 券，名额有限")

    assert payload["status"] == "success"
    assert "model_loaded" in payload
    assert "detections" in payload
    assert "model_error" in payload
    assert "model_version" in payload
    assert "model_sha256" in payload
    assert "config_version" in payload
    assert "normalized_text" in payload
    assert "semantic_scores" in payload


def test_health_payload_has_contract_fields():
    payload = build_health_payload()

    assert payload["status"] == "ok"
    assert payload["service"] == "SafeChat-Guard"
    assert "config_version" in payload


def test_ready_payload_reports_model_state():
    payload, status = build_ready_payload()

    assert status in {200, 503}
    assert payload["status"] in {"ready", "degraded"}
    assert "ready" in payload
    assert "model_loaded" in payload
    assert "model_error" in payload
    assert "model_version" in payload
    assert "model_sha256" in payload
    assert "config_version" in payload
    assert "semantic_classifier" in payload
    assert "llm" in payload
    assert "stats" in payload


def test_error_payload_uses_stable_contract():
    payload = error_payload("invalid_request", "message must be a non-empty string")

    assert payload == {
        "error": "invalid_request",
        "message": "message must be a non-empty string",
    }


def test_read_json_rejects_non_object_body():
    handler = SimpleNamespace(
        headers={"Content-Length": "2"},
        rfile=BytesIO(b"[]"),
    )

    payload, error = SafeChatApiHandler._read_json(handler)

    assert payload is None
    assert error == "invalid_json_body"


def test_read_json_rejects_oversized_body():
    handler = SimpleNamespace(
        headers={"Content-Length": str(64 * 1024 + 1)},
        rfile=BytesIO(b""),
    )

    payload, error = SafeChatApiHandler._read_json(handler)

    assert payload is None
    assert error == "request_too_large"


def test_read_json_rejects_non_json_content_type():
    handler = SimpleNamespace(
        headers={"Content-Length": "2", "Content-Type": "text/plain"},
        rfile=BytesIO(b"{}"),
    )

    payload, error = SafeChatApiHandler._read_json(handler)

    assert payload is None
    assert error == "unsupported_media_type"


def test_text_field_length_limit_is_enforced():
    value, error = SafeChatApiHandler._validate_text_field(
        {"message": "x" * (MAX_TEXT_CHARS + 1)},
        "message",
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
