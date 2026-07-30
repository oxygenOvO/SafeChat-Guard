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

    assert payload == {
        "status": "ok",
        "service": "SafeChat-Guard",
        "active_filter_version": "v3",
        "v3_enabled": True,
        "v3_ready": True,
        "risk_model_loaded": True,
        "block_model_loaded": True,
        "fallback_active": False,
        "fallback_reason": None,
        "risk_model_sha256": "136b9952869c6662eaa77e65d3a22e3cac3eddfe3f751ffa55bc99fd80845785",
        "block_model_sha256": "412f46781bcba63de8ada1d8781296acdbb25447f303130d0926cff6bd176b21",
        "threshold_config_sha256": "5332006befae66475c9e7449d7c48dafd2ed6e5dba3ca6a5f7c0d2179783c3a2",
    }


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


def test_compatibility_app_reuses_canonical_api_server():
    import app

    assert app.pipeline is api_server.pipeline
    assert app.SafeChatHandler is api_server.SafeChatApiHandler
    assert app.create_server is api_server.create_server
    assert app.main is api_server.main


def test_server_factory_uses_canonical_handler():
    server = api_server.create_server("127.0.0.1", 0)
    try:
        assert server.RequestHandlerClass is api_server.SafeChatApiHandler
        assert server.daemon_threads is True
    finally:
        server.server_close()


def test_api_modules_resolve_config_outside_repository(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(project_root)!r}); "
        "import api_server, app; "
        "assert app.pipeline is api_server.pipeline; "
        "assert app.SafeChatHandler is api_server.SafeChatApiHandler; "
        "assert api_server.build_health_payload()['status'] == 'ok'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
