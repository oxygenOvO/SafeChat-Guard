from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from api_server import dispatch_management_get, dispatch_management_write

from safechat_guard.pipeline import SafeChatPipeline


def rule(rule_id="api-1", **changes):
    value = {
        "id": rule_id,
        "pattern": "紫色接口词",
        "pattern_type": "keyword",
        "category": "ad",
        "action": "sanitize",
        "risk_level": "medium",
        "enabled": True,
        "description": "api test",
    }
    value.update(changes)
    return value


class Handler:
    def __init__(self, *, address="127.0.0.1", headers=None):
        self.client_address = (address, 12345)
        self.headers = headers or {}
        self.response = None
        self.status = None

    def _send_json(self, payload, status=200):
        self.response = payload
        self.status = status


@pytest.fixture
def pipeline(tmp_path):
    config = json.loads(
        (Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8")
    )
    config["semantic"]["config_path"] = str(
        Path(__file__).parents[1] / "config" / "semantic_thresholds_v1.json"
    )
    config["logging"]["path"] = "data/logs/api-test.jsonl"
    with pytest.warns(RuntimeWarning):
        return SafeChatPipeline(config, project_root=tmp_path)


def write(handler, method, path, payload, pipeline):
    assert dispatch_management_write(
        handler, method, urlparse(path), payload, pipeline
    )
    return handler.response, handler.status


def test_list_get_create_update_delete_lifecycle(pipeline):
    handler = Handler()
    response, status = write(handler, "POST", "/api/rules", rule(), pipeline)
    assert status == 201
    revision = response["revision"]

    assert dispatch_management_get(handler, urlparse("/api/rules"), pipeline)
    assert handler.response["user_count"] == 1
    assert handler.response["built_in_count"] > 0

    assert dispatch_management_get(handler, urlparse("/api/rules/api-1"), pipeline)
    assert handler.response["rule"]["pattern"] == "[REDACTED]"
    assert handler.response["rule"]["pattern_redacted"] is True

    response, status = write(
        handler,
        "PATCH",
        "/api/rules/api-1",
        {"description": "changed", "expected_revision": revision},
        pipeline,
    )
    assert status == 200 and response["rule"]["description"] == "changed"
    response, status = write(
        handler,
        "DELETE",
        "/api/rules/api-1",
        {"expected_revision": response["revision"]},
        pipeline,
    )
    assert status == 200 and response["deleted"] == "api-1"


def test_enable_disable_and_immediate_filter_reload(pipeline):
    handler = Handler()
    created, _ = write(handler, "POST", "/api/rules", rule(), pipeline)
    assert pipeline.rule_filter.detect("出现紫色接口词")

    disabled, status = write(
        handler,
        "POST",
        "/api/rules/api-1/disable",
        {"expected_revision": created["revision"]},
        pipeline,
    )
    assert status == 200
    assert pipeline.rule_filter.detect("出现紫色接口词") == []

    enabled, status = write(
        handler,
        "POST",
        "/api/rules/api-1/enable",
        {"expected_revision": disabled["revision"]},
        pipeline,
    )
    assert status == 200 and enabled["rule"]["enabled"] is True
    assert pipeline.rule_filter.detect("出现紫色接口词")


def test_remote_write_without_token_is_forbidden(pipeline, monkeypatch):
    monkeypatch.delenv("SAFECHAT_RULE_ADMIN_TOKEN", raising=False)
    handler = Handler(address="192.0.2.10")
    response, status = write(handler, "POST", "/api/rules", rule(), pipeline)
    assert status == 403
    assert response["error"] == "forbidden"
    assert pipeline.rule_manager.list_rules() == []


def test_configured_token_is_required_and_never_echoed(pipeline, monkeypatch):
    token = "temporary-admin-secret"
    monkeypatch.setenv("SAFECHAT_RULE_ADMIN_TOKEN", token)
    denied = Handler()
    response, status = write(denied, "POST", "/api/rules", rule(), pipeline)
    assert status == 403 and token not in json.dumps(response)

    allowed = Handler(headers={"Authorization": f"Bearer {token}"})
    response, status = write(allowed, "POST", "/api/rules", rule(), pipeline)
    assert status == 201 and token not in json.dumps(response)
    assert token not in pipeline.logger.path.read_text(encoding="utf-8")


def test_stable_validation_not_found_conflict_and_builtin_statuses(pipeline):
    handler = Handler()
    _, status = write(
        handler, "POST", "/api/rules", rule(category="invalid"), pipeline
    )
    assert status == 400
    created, _ = write(handler, "POST", "/api/rules", rule(), pipeline)
    _, status = write(handler, "POST", "/api/rules", rule(), pipeline)
    assert status == 409
    _, status = write(
        handler,
        "PATCH",
        "/api/rules/missing",
        {"description": "x", "expected_revision": created["revision"]},
        pipeline,
    )
    assert status == 404
    _, status = write(
        handler,
        "DELETE",
        "/api/rules/builtin:regex:0",
        {},
        pipeline,
    )
    assert status == 409


def test_csv_json_import_dry_run_and_atomic_failure(pipeline):
    handler = Handler()
    csv_content = (
        "id,pattern,pattern_type,category,action,risk_level,enabled,description\n"
        "csv-1,紫色批量词,keyword,ad,sanitize,medium,true,batch\n"
    )
    report, status = write(
        handler,
        "POST",
        "/api/rules/validate-import",
        {"format": "csv", "content": csv_content},
        pipeline,
    )
    assert status == 200 and report["dry_run"] is True
    assert pipeline.rule_manager.list_rules() == []

    report, status = write(
        handler,
        "POST",
        "/api/rules/import",
        {"format": "csv", "content": csv_content, "dry_run": False},
        pipeline,
    )
    assert status == 200 and report["imported"] == 1
    assert pipeline.rule_filter.detect("紫色批量词")

    before = pipeline.rule_manager.storage_path.read_bytes()
    invalid = json.dumps(
        [
            rule("json-1", pattern="合法"),
            rule("json-2", pattern_type="regex", pattern="("),
        ],
        ensure_ascii=False,
    )
    response, status = write(
        handler,
        "POST",
        "/api/rules/import",
        {"format": "json", "content": invalid, "dry_run": False},
        pipeline,
    )
    assert status == 400 and response["details"]["invalid"] == 1
    assert pipeline.rule_manager.storage_path.read_bytes() == before


def test_oversized_import_maps_to_413(pipeline):
    handler = Handler()
    _, status = write(
        handler,
        "POST",
        "/api/rules/import",
        {"format": "json", "content": "x" * (1024 * 1024 + 1)},
        pipeline,
    )
    assert status == 413


def test_management_audit_contains_no_pattern_or_path(pipeline):
    handler = Handler()
    write(handler, "POST", "/api/rules", rule(pattern="不可记录的模式"), pipeline)
    events = pipeline.logger.read_all()
    audit = next(event for event in events if event.get("stage") == "rule_management")
    serialized = json.dumps(audit, ensure_ascii=False)
    assert "不可记录的模式" not in serialized
    assert str(pipeline.project_root) not in serialized
    assert audit["operation"] == "rule_created"


def test_stats_get_endpoints_validate_dates_and_hide_events(pipeline):
    pipeline.logger.write(
        {
            "stage": "request_summary",
            "timestamp": "2026-07-20T01:00:00+00:00",
            "input_action": "block",
            "output_action": "not_run",
            "final_action": "block",
            "category": "violence",
            "fallback_used": False,
            "model_forwarded": False,
        }
    )
    handler = Handler()
    assert dispatch_management_get(
        handler,
        urlparse(
            "/api/stats/summary?start_date=2026-07-20&end_date=2026-07-20&timezone=UTC"
        ),
        pipeline,
    )
    assert handler.status == 200 and handler.response["request_count"] == 1
    assert "events" not in handler.response and "path" not in handler.response

    assert dispatch_management_get(
        handler, urlparse("/api/stats/daily?start_date=bad"), pipeline
    )
    assert handler.status == 400


def test_user_rule_is_visible_to_chat_detection_chain(pipeline):
    handler = Handler()
    write(handler, "POST", "/api/rules", rule(), pipeline)
    result = pipeline.detect_text("消息含有紫色接口词")
    assert result["action"] != "pass"
    assert any(item["source"] == "rule:user_overlay" for item in result["detections"])
    assert all(item["matches"] == ["[REDACTED]"] for item in result["detections"])


def test_audit_write_failure_does_not_rollback_rule_or_leak_error(pipeline, monkeypatch):
    handler = Handler()

    def fail_audit(event):
        raise OSError("SECRET PATH D:/private")

    monkeypatch.setattr(pipeline.logger, "write", fail_audit)
    with pytest.warns(RuntimeWarning, match="audit logging failed") as warning:
        response, status = write(handler, "POST", "/api/rules", rule(), pipeline)
    assert status == 201
    assert pipeline.rule_manager.get_rule("api-1")["id"] == "api-1"
    assert "SECRET" not in str(warning[0].message)
    assert "D:/" not in str(warning[0].message)

@pytest.mark.parametrize("format_name", ["csv", "json"])
def test_imported_user_block_rule_immediately_blocks_pipeline(pipeline, format_name):
    handler = Handler()
    if format_name == "csv":
        content = (
            "id,pattern,pattern_type,category,action,risk_level,enabled,description\n"
            "import-block,import-block-token,phrase,ad,block,medium,true,import test\n"
        )
    else:
        content = json.dumps(
            [rule("import-block", pattern="import-block-token", action="block")]
        )
    report, status = write(
        handler,
        "POST",
        "/api/rules/import",
        {"format": format_name, "content": content, "dry_run": False},
        pipeline,
    )

    result = pipeline.handle_chat("contains import-block-token", persist=False)

    assert status == 200 and report["imported"] == 1
    assert result["action"] == result["final_action"] == "block"
    assert result["hard_block"] is True
    assert result["model_forwarded"] is False


def test_dry_run_and_failed_import_never_activate_block_rule(pipeline):
    handler = Handler()
    content = json.dumps(
        [rule("dry-block", pattern="dry-block-token", action="block")]
    )
    report, status = write(
        handler,
        "POST",
        "/api/rules/validate-import",
        {"format": "json", "content": content},
        pipeline,
    )
    assert status == 200 and report["dry_run"] is True
    assert pipeline.detect_text("dry-block-token")["action"] == "pass"

    invalid = json.dumps(
        [
            rule("valid-part", pattern="failed-block-token", action="block"),
            rule("invalid-part", pattern="(", pattern_type="regex", action="block"),
        ]
    )
    response, status = write(
        handler,
        "POST",
        "/api/rules/import",
        {"format": "json", "content": invalid, "dry_run": False},
        pipeline,
    )
    assert status == 400 and response["details"]["invalid"] == 1
    assert pipeline.detect_text("failed-block-token")["action"] == "pass"


def test_revision_conflict_does_not_change_active_block_behavior(pipeline):
    handler = Handler()
    created, status = write(
        handler,
        "POST",
        "/api/rules",
        rule(pattern="conflict-block-token", action="block"),
        pipeline,
    )
    assert status == 201
    response, status = write(
        handler,
        "PATCH",
        "/api/rules/api-1",
        {"action": "sanitize", "expected_revision": created["revision"] - 1},
        pipeline,
    )
    assert status == 409 and response["error"] == "conflict"
    assert pipeline.detect_text("conflict-block-token")["action"] == "block"


def test_block_chat_result_and_audit_do_not_leak_pattern(pipeline):
    handler = Handler()
    private_pattern = "private-block-pattern"
    created, status = write(
        handler,
        "POST",
        "/api/rules",
        rule(pattern=private_pattern, action="block"),
        pipeline,
    )
    result = pipeline.handle_chat(f"contains {private_pattern}", persist=True)
    response_text = json.dumps(result, ensure_ascii=False)
    log_text = pipeline.logger.path.read_text(encoding="utf-8")
    audits = [
        event
        for event in pipeline.logger.read_all()
        if event.get("stage") == "rule_management"
    ]

    assert status == 201 and created["rule"]["action"] == "block"
    assert result["action"] == result["final_action"] == "block"
    assert result["final_allowed"] is False
    assert result["model_forwarded"] is False
    assert private_pattern not in response_text
    assert private_pattern not in log_text
    assert audits
    assert set(audits[0]) <= {
        "time", "stage", "rule_id", "operation", "revision", "result"
    }

def test_default_rule_reads_are_redacted_even_on_loopback(pipeline):
    handler = Handler()
    private_pattern = "default-read-secret"
    write(handler, "POST", "/api/rules", rule(pattern=private_pattern), pipeline)

    assert dispatch_management_get(handler, urlparse("/api/rules"), pipeline)
    listed = next(item for item in handler.response["rules"] if item["id"] == "api-1")
    assert listed["pattern"] == "[REDACTED]"
    assert listed["pattern_redacted"] is True
    assert private_pattern not in json.dumps(handler.response)

    assert dispatch_management_get(handler, urlparse("/api/rules/api-1"), pipeline)
    assert handler.response["rule"]["pattern"] == "[REDACTED]"
    assert handler.response["rule"]["pattern_redacted"] is True


def test_privileged_pattern_read_reuses_management_authorization(pipeline, monkeypatch):
    private_pattern = "privileged-read-secret"
    write(Handler(), "POST", "/api/rules", rule(pattern=private_pattern), pipeline)

    monkeypatch.delenv("SAFECHAT_RULE_ADMIN_TOKEN", raising=False)
    remote = Handler(address="192.0.2.10")
    assert dispatch_management_get(
        remote, urlparse("/api/rules?include_pattern=true"), pipeline
    )
    assert remote.status == 403

    loopback = Handler()
    assert dispatch_management_get(
        loopback, urlparse("/api/rules/api-1?include_pattern=true"), pipeline
    )
    assert loopback.status == 200
    assert loopback.response["rule"]["pattern"] == private_pattern
    assert loopback.response["rule"]["pattern_redacted"] is False

    token = "pattern-admin-token"
    monkeypatch.setenv("SAFECHAT_RULE_ADMIN_TOKEN", token)
    wrong = Handler(address="192.0.2.10", headers={"X-Admin-Token": "wrong"})
    dispatch_management_get(
        wrong, urlparse("/api/rules?include_pattern=true"), pipeline
    )
    assert wrong.status == 403

    allowed = Handler(
        address="192.0.2.10", headers={"Authorization": f"Bearer {token}"}
    )
    dispatch_management_get(
        allowed, urlparse("/api/rules?include_pattern=true"), pipeline
    )
    listed = next(item for item in allowed.response["rules"] if item["id"] == "api-1")
    assert allowed.status == 200
    assert listed["pattern"] == private_pattern
    assert token not in json.dumps(allowed.response)
    assert token not in pipeline.logger.path.read_text(encoding="utf-8")


def test_reload_failure_rolls_back_file_memory_and_revision(pipeline, monkeypatch):
    created, _ = write(
        Handler(), "POST", "/api/rules", rule(pattern="old-active-pattern"), pipeline
    )
    before = pipeline.rule_manager.storage_path.read_bytes()
    revision = pipeline.rule_manager.revision
    original_reload = pipeline.rule_filter.reload_user_rules
    calls = 0

    def fail_activation(*, force=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original_reload(force=force)

    monkeypatch.setattr(pipeline.rule_filter, "reload_user_rules", fail_activation)
    response, status = write(
        Handler(),
        "PATCH",
        "/api/rules/api-1",
        {"pattern": "new-inactive-pattern", "expected_revision": created["revision"]},
        pipeline,
    )

    assert status == 500
    assert response == {
        "error": "storage_error",
        "message": "Rule storage operation failed",
    }
    assert pipeline.rule_manager.storage_path.read_bytes() == before
    assert pipeline.rule_manager.revision == revision
    assert pipeline.rule_manager.get_rule("api-1")["pattern"] == "old-active-pattern"
    assert pipeline.rule_filter.detect("old-active-pattern")
    assert pipeline.rule_filter.detect("new-inactive-pattern") == []
    failed = [
        event for event in pipeline.logger.read_all()
        if event.get("stage") == "rule_management" and event.get("result") == "failed"
    ]
    assert failed and "new-inactive-pattern" not in json.dumps(failed)


@pytest.mark.parametrize("format_name", ["csv", "json"])
def test_import_reload_failure_rolls_back_entire_batch(pipeline, monkeypatch, format_name):
    before = pipeline.rule_manager.storage_path.read_bytes()
    original_reload = pipeline.rule_filter.reload_user_rules
    calls = 0

    def fail_activation(*, force=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original_reload(force=force)

    monkeypatch.setattr(pipeline.rule_filter, "reload_user_rules", fail_activation)
    if format_name == "csv":
        content = (
            "id,pattern,pattern_type,category,action,risk_level,enabled,description\n"
            "rollback-import,rollback-import-token,phrase,ad,block,medium,true,review\n"
        )
    else:
        content = json.dumps([rule("rollback-import", pattern="rollback-import-token")])
    response, status = write(
        Handler(),
        "POST",
        "/api/rules/import",
        {"format": format_name, "content": content, "dry_run": False},
        pipeline,
    )

    assert status == 500 and response["error"] == "storage_error"
    assert pipeline.rule_manager.storage_path.read_bytes() == before
    assert pipeline.rule_manager.revision == 0
    assert pipeline.rule_manager.list_rules() == []
    assert pipeline.rule_filter.detect("rollback-import-token") == []


def test_rollback_failure_enters_degraded_mode_and_rejects_writes(pipeline, monkeypatch):
    original_reload = pipeline.rule_filter.reload_user_rules
    calls = 0

    def fail_activation(*, force=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original_reload(force=force)

    def fail_rollback(snapshot):
        raise OSError("private rollback path")

    monkeypatch.setattr(pipeline.rule_filter, "reload_user_rules", fail_activation)
    monkeypatch.setattr(pipeline.rule_manager, "restore_snapshot", fail_rollback)
    response, status = write(
        Handler(), "POST", "/api/rules", rule(pattern="degraded-new-rule"), pipeline
    )
    assert status == 500 and response["error"] == "storage_error"
    assert pipeline.rule_manager.degraded is True
    assert pipeline.rule_filter.reload_error_code == "USER_RULE_TRANSACTION_DEGRADED"
    assert pipeline.rule_filter.detect("degraded-new-rule") == []

    response, status = write(
        Handler(), "POST", "/api/rules", rule("second-rule"), pipeline
    )
    assert status == 500 and response["error"] == "storage_error"
    assert "private" not in json.dumps(response)
