import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import api_server
from safechat_guard.pipeline import SafeChatPipeline


def request_json(base_url: str, path: str, payload=None, content_type="application/json"):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url}{path}", data=data)
    if data is not None:
        request.add_header("Content-Type", content_type)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture
def api_runtime(production_config_without_model, monkeypatch):
    test_pipeline = SafeChatPipeline.from_config(
        str(production_config_without_model)
    )
    monkeypatch.setattr(api_server, "pipeline", test_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.SafeChatApiHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, test_pipeline
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_ready_and_error_contracts(api_runtime):
    base_url, _ = api_runtime

    status, health = request_json(base_url, "/health")
    assert status == 200
    assert health["status"] == "ok"

    status, ready = request_json(base_url, "/ready")
    assert status == 200
    assert ready["ready"] is True
    semantic = ready["semantic_classifier"]
    assert semantic["required"] is False
    assert semantic["loaded"] is False
    assert semantic["error"] == "model file not found"
    assert semantic["model_sha256_verified"] is False
    assert "min_margin" in semantic

    status, error = request_json(base_url, "/api/chat", {"message": 123})
    assert status == 422
    assert error == {
        "error": "invalid_request",
        "message": "message must be a non-empty string",
    }

    status, error = request_json(
        base_url,
        "/api/chat",
        {"message": "hello"},
        content_type="text/plain",
    )
    assert status == 415
    assert error["error"] == "unsupported_media_type"


def test_concurrent_chat_and_stats_requests(api_runtime):
    base_url, pipeline = api_runtime

    def send(index: int):
        return request_json(base_url, "/api/chat", {"message": f"学习建议 {index}"})

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(send, range(12)))

    assert all(status == 200 for status, _ in results)
    assert all(payload["allowed"] is True for _, payload in results)
    assert pipeline.logger.stats()["total_events"] == 36
    status, stats = request_json(base_url, "/api/stats")
    assert status == 200
    assert stats["total_events"] == 36


def test_internal_error_does_not_expose_exception(api_runtime, monkeypatch):
    base_url, pipeline = api_runtime

    def fail(*args, **kwargs):
        raise RuntimeError("SECRET-INTERNAL-DETAIL")

    monkeypatch.setattr(pipeline, "handle_chat", fail)
    status, error = request_json(base_url, "/api/chat", {"message": "hello"})

    assert status == 500
    assert error == {"error": "internal_error", "message": "Internal server error"}
    assert "SECRET-INTERNAL-DETAIL" not in json.dumps(error)


def test_stats_time_window_and_invalid_timestamp(api_runtime):
    base_url, _ = api_runtime
    request_json(base_url, "/api/chat", {"message": "hello"})

    status, stats = request_json(
        base_url,
        "/api/stats?since=2999-01-01T00%3A00%3A00Z",
    )
    assert status == 200
    assert stats["total_events"] == 0
    assert stats["window_start"] == "2999-01-01T00:00:00+00:00"

    status, error = request_json(base_url, "/api/stats?since=not-a-time")
    assert status == 422
    assert error["error"] == "invalid_request"


def test_get_internal_error_uses_unified_safe_response(api_runtime, monkeypatch):
    base_url, pipeline = api_runtime

    def fail(*args, **kwargs):
        raise RuntimeError("SECRET-GET-DETAIL")

    monkeypatch.setattr(pipeline, "stats", fail)
    status, error = request_json(base_url, "/api/stats")

    assert status == 500
    assert error == {"error": "internal_error", "message": "Internal server error"}
    assert "SECRET-GET-DETAIL" not in json.dumps(error)
