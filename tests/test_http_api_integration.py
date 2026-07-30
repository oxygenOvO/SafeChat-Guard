import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import api_server
from safechat_guard.pipeline import SafeChatPipeline


def request_json(
    base_url: str,
    path: str,
    payload=None,
    content_type="application/json",
    method: str | None = None,
):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url}{path}", data=data, method=method)
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
    assert {
        "active_filter_version",
        "v3_enabled",
        "v3_ready",
        "risk_model_loaded",
        "block_model_loaded",
        "fallback_active",
        "fallback_reason",
        "risk_model_sha256",
        "block_model_sha256",
        "threshold_config_sha256",
    } <= health.keys()
    assert health["active_filter_version"] == "v2"
    assert health["v3_enabled"] is True
    assert health["v3_ready"] is False
    assert health["risk_model_loaded"] is False
    assert health["block_model_loaded"] is False
    assert health["fallback_active"] is True
    assert health["fallback_reason"]

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
    assert all(payload["final_allowed"] is True for _, payload in results)
    assert all(payload["final_action"] == "pass" for _, payload in results)
    assert pipeline.logger.stats()["total_events"] == 48
    status, stats = request_json(base_url, "/api/stats")
    assert status == 200
    assert stats["total_events"] == 48
    assert stats["stage_counts"]["request_summary"] == 12


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


def test_api_output_block_uses_final_contract_without_raw_leak(api_runtime):
    base_url, _ = api_runtime
    unsafe = "\u6211\u4f1a\u6740\u4e86\u4f60"

    status, payload = request_json(
        base_url,
        "/api/chat",
        {
            "message": "ordinary question",
            "raw_reply_override": unsafe,
        },
    )
    serialized = json.dumps(payload, ensure_ascii=False)

    assert status == 200
    assert payload["action"] == "pass"
    assert payload["output_guard_action"] == "block"
    assert payload["final_action"] == "block"
    assert payload["final_allowed"] is False
    assert payload["raw_reply"] is None
    assert payload["model_response"] is None
    assert unsafe not in serialized


def test_rule_management_real_http_routes_and_reload(api_runtime):
    base_url, pipeline = api_runtime
    new_rule = {
        "id": "http-rule-1",
        "pattern": "青色接口命中",
        "pattern_type": "phrase",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "HTTP integration",
    }
    status, created = request_json(
        base_url, "/api/rules", new_rule, method="POST"
    )
    assert status == 201
    assert pipeline.rule_filter.detect("包含青色接口命中")

    status, listed = request_json(base_url, "/api/rules")
    assert status == 200 and listed["user_count"] == 1
    status, disabled = request_json(
        base_url,
        "/api/rules/http-rule-1",
        {"enabled": False, "expected_revision": created["revision"]},
        method="PATCH",
    )
    assert status == 200 and disabled["rule"]["enabled"] is False
    assert pipeline.rule_filter.detect("包含青色接口命中") == []

    status, deleted = request_json(
        base_url,
        "/api/rules/http-rule-1",
        {"expected_revision": disabled["revision"]},
        method="DELETE",
    )
    assert status == 200 and deleted["deleted"] == "http-rule-1"


def test_request_summary_statistics_real_http_route(api_runtime):
    base_url, _ = api_runtime
    request_json(base_url, "/api/chat", {"message": "ordinary request"})
    status, stats = request_json(base_url, "/api/stats/summary?timezone=UTC")
    assert status == 200
    assert stats["source"] == "request_summary"
    assert stats["request_count"] == 1
    assert stats["pass_count"] == 1
    assert "events" not in stats and "path" not in stats

def test_http_chat_user_overlay_block_contract_and_no_leak(api_runtime, monkeypatch):
    base_url, pipeline = api_runtime
    private_pattern = "http-private-block-token"

    def forbidden(_message):
        raise AssertionError("user overlay block must not call LLM")

    monkeypatch.setattr(pipeline.llm, "chat", forbidden)
    status, created = request_json(
        base_url,
        "/api/rules",
        {
            "id": "http-block-rule",
            "pattern": private_pattern,
            "pattern_type": "phrase",
            "category": "ad",
            "action": "block",
            "risk_level": "medium",
            "enabled": True,
            "description": "HTTP block contract",
        },
        method="POST",
    )
    assert status == 201 and created["rule"]["action"] == "block"

    status, result = request_json(
        base_url,
        "/api/chat",
        {"message": f"contains {private_pattern}"},
        method="POST",
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert status == 200
    assert result["action"] == result["final_action"] == "block"
    assert result["final_allowed"] is False
    assert result["hard_block"] is True
    assert result["model_forwarded"] is False
    assert "USER_RULE_BLOCK" in result["reason_codes"]
    assert private_pattern not in serialized
    assert private_pattern not in pipeline.logger.path.read_text(encoding="utf-8")