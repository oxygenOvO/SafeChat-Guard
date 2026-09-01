import json
from datetime import date
from pathlib import Path

import pytest

from safechat_guard.analytics_service import AnalyticsService
from safechat_guard.audit_service import AuditService
from safechat_guard.health_service import HealthService
from safechat_guard.logger import EventLogger
from safechat_guard.model_registry import ModelRegistry, ModelRegistryError
from safechat_guard.pipeline import SafeChatPipeline


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def product_config():
    return json.loads((ROOT / "config.yaml").read_text(encoding="utf-8"))


def request_event(**changes):
    event = {
        "stage": "request_summary",
        "timestamp": "2026-09-01T01:02:03+00:00",
        "request_id": "req-1",
        "provider": "mock",
        "model": "offline-mock",
        "category": "normal",
        "risk_level": "none",
        "risk_score": 0,
        "input_action": "pass",
        "output_action": "pass",
        "final_action": "pass",
        "model_forwarded": True,
        "latency_ms": 12,
    }
    event.update(changes)
    return event


def test_model_registry_uses_config_and_safe_runtime_overlay(tmp_path, product_config, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("NSCC_MAAS_API_KEY", raising=False)
    state_path = tmp_path / "runtime" / "models.json"
    registry = ModelRegistry(product_config, state_path=state_path)

    initial = registry.snapshot()
    assert initial["default_provider"] == "mock"
    assert {item["provider"] for item in initial["providers"]} == {
        "mock", "nscc_qwen", "qwen", "deepseek"
    }
    qwen = next(item for item in initial["providers"] if item["provider"] == "qwen")
    assert qwen["key_configured"] is False
    assert qwen["health"] == "not_configured"

    registry.set_default("deepseek")
    assert registry.snapshot()["default_provider"] == "deepseek"
    registry.set_enabled("deepseek", False)
    after_disable = registry.snapshot()
    assert after_disable["default_provider"] == "mock"
    with pytest.raises(ModelRegistryError, match="disabled"):
        registry.set_default("deepseek")
    serialized = state_path.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "dashscope" not in serialized

    registry.set_enabled("qwen", False)
    registry.set_enabled("nscc_qwen", False)
    with pytest.raises(ModelRegistryError, match="at least one"):
        registry.set_enabled("mock", False)
    assert registry.snapshot()["default_provider"] == "mock"


def test_connection_test_reports_timeout_without_exception_details(
    tmp_path, product_config, monkeypatch
):
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")

    class TimeoutAdapter:
        def status(self):
            return {"provider": "qwen", "ready": True, "key_configured": True}

        def chat(self, message, **kwargs):
            raise TimeoutError("secret upstream detail")

    monkeypatch.setattr(
        "safechat_guard.model_registry.LLMAdapterFactory.create",
        lambda config: TimeoutAdapter(),
    )
    result = registry.test_connection("qwen")

    assert result["status"] == "timeout"
    assert result["latency_ms"] is not None
    assert "secret" not in json.dumps(result)


def test_audit_read_filter_export_and_recursive_secret_redaction(tmp_path):
    logger = EventLogger(str(tmp_path / "events.jsonl"), retention_days=0)
    logger.write(
        request_event(
            api_key="super-secret",
            Authorization="Bearer private",
            input="13812345678",
        )
    )
    logger.write(
        request_event(
            request_id="req-2",
            provider="qwen",
            category="violence",
            risk_level="high",
            risk_score=95,
            input_action="block",
            output_action="not_run",
            final_action="block",
            model_forwarded=False,
        )
    )
    service = AuditService(logger)

    records = service.records(actions=["block"], providers=["qwen"])
    assert [item["request_id"] for item in records] == ["req-2"]
    assert service.records(start_date=date(2026, 9, 2)) == []
    exported = service.to_csv(records).decode("utf-8-sig")
    assert "req-2" in exported
    assert "super-secret" not in exported
    assert "Authorization" not in exported
    persisted = json.dumps(logger.read_all(), ensure_ascii=False)
    assert "super-secret" not in persisted
    assert "Bearer private" not in persisted
    assert "13812345678" not in persisted


def test_analytics_matches_the_same_audit_records_and_handles_bad_time():
    records = [
        AuditService._public_record(request_event()),
        AuditService._public_record(
            request_event(
                request_id="req-2",
                category="ad",
                risk_level="medium",
                input_action="sanitize",
                final_action="sanitize",
            )
        ),
        AuditService._public_record(
            request_event(
                request_id="req-3",
                timestamp="not-a-time",
                category="violence",
                risk_level="high",
                input_action="block",
                output_action="not_run",
                final_action="block",
            )
        ),
    ]

    stats = AnalyticsService.summarize(records)
    assert stats["total_requests"] == 3
    assert (stats["pass_count"], stats["sanitize_count"], stats["block_count"]) == (1, 1, 1)
    assert stats["action_distribution"] == {"block": 1, "pass": 1, "sanitize": 1}
    assert stats["category_distribution"] == {"ad": 1, "violence": 1}
    assert stats["invalid_time_count"] == 1


def test_analytics_empty_state_contains_no_invented_values():
    stats = AnalyticsService.summarize([])

    assert stats["total_requests"] == 0
    assert stats["action_distribution"] == {}
    assert stats["category_distribution"] == {}
    assert stats["daily_request_counts"] == {}


def test_health_reports_real_components_and_fail_closed(tmp_path, product_config):
    product_config["logging"]["path"] = str(tmp_path / "events.jsonl")
    pipeline = SafeChatPipeline(product_config, project_root=ROOT)
    registry = ModelRegistry(product_config, state_path=tmp_path / "models.json")
    service = HealthService(pipeline, registry)

    healthy = service.snapshot()
    assert healthy["model_calls_allowed"] is True
    assert next(item for item in healthy["providers"] if item["provider"] == "mock")["health"] == "available"

    pipeline.output_guard = None
    failed = service.snapshot()
    assert failed["status"] == "abnormal"
    assert failed["model_calls_allowed"] is False
    assert next(item for item in failed["components"] if item["name"] == "OutputGuard")["status"] == "abnormal"


def test_pipeline_persists_one_request_id_across_all_stages(tmp_path, product_config):
    product_config["logging"]["path"] = str(tmp_path / "events.jsonl")
    pipeline = SafeChatPipeline(product_config, project_root=ROOT)
    result = pipeline.handle_chat(
        "普通学习讨论",
        raw_reply_override="这是一个安全回答。",
        persist=True,
    )

    events = pipeline.logger.read_all()
    request_ids = {event["request_id"] for event in events}
    assert request_ids == {result["request_id"]}
    assert {event["provider"] for event in events} == {result["provider"]}
    assert [event["stage"] for event in events].count("request_summary") == 1
