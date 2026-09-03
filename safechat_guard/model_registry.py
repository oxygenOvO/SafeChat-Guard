"""运行时模型注册表：管理 Provider 的启用状态、默认模型与连接测试结果。

设计要点：
- 受版本控制的 ``config.yaml`` 是 Provider 配置基线；启用/默认/最近连接
  测试结果作为"本地 overlay"写入 ``data/runtime/model_registry.json``
  （该目录被 Git 忽略，且不保存任何 API Key）。
- ``snapshot()`` 是管理页 Provider 卡片的数据源，融合基线配置与 overlay
  状态，并即时探测密钥是否已配置（只探测环境变量是否存在，不读明文）。
- ``test_connection`` 对真实 Provider 发起一次最小化聊天调用（提示词固定、
  回复长度受限），失败时经 provider_diagnostics 归一化为分类诊断，
  日志只记录脱敏摘要（provider/model/错误类别/主机名），不记录密钥。
- 并发安全：所有"读-改-写"状态文件的操作持有类级 RLock，
  写入使用临时文件 + os.replace 原子替换。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .llm_adapters import LLMAdapterFactory, PROVIDER_LABELS
from .provider_diagnostics import (
    ProviderErrorDiagnostic,
    classify_provider_error,
    sanitize_provider_error,
)


LOGGER = logging.getLogger("safechat.provider")



class ModelRegistryError(RuntimeError):
    pass


class ModelRegistry:
    """Manage provider availability without persisting credentials."""

    _state_lock = threading.RLock()

    def __init__(
        self,
        config: dict[str, Any],
        *,
        state_path: str | Path,
    ) -> None:
        self.config = deepcopy(config)
        self.state_path = Path(state_path)
        llm = self.config.get("llm", {})
        self._providers = deepcopy(llm.get("providers", {}))
        self._base_default = str(llm.get("provider", "mock"))

    def snapshot(self) -> dict[str, Any]:
        """返回全部 Provider 的融合视图（管理页卡片数据源）。

        融合规则：基线配置 + overlay 启用状态 + 密钥探测 + 最近连接测试；
        默认 Provider 失效（被停用）时自动回退到第一个启用的 Provider。
        """
        state = self._read_state()
        records = [
            self._provider_record(provider, values, state)
            for provider, values in self._providers.items()
        ]
        enabled_ids = [item["provider"] for item in records if item["enabled"]]
        requested_default = str(state.get("default_provider", self._base_default))
        default_provider = (
            requested_default
            if requested_default in enabled_ids
            else (enabled_ids[0] if enabled_ids else None)
        )
        for record in records:
            record["default"] = record["provider"] == default_provider
        return {"default_provider": default_provider, "providers": records}

    def provider_config(self, provider: str) -> dict[str, Any]:
        """取指定 Provider 的运行配置；未配置或已停用抛 ModelRegistryError。"""
        snapshot = self.snapshot()
        record = next(
            (item for item in snapshot["providers"] if item["provider"] == provider),
            None,
        )
        if record is None:
            raise ModelRegistryError("provider is not configured")
        if not record["enabled"]:
            raise ModelRegistryError("provider is disabled")
        return {**deepcopy(self._providers[provider]), "provider": provider}

    def set_enabled(self, provider: str, enabled: bool) -> dict[str, Any]:
        """设置 Provider 启用状态（持锁读改写）；至少保留一个启用中的 Provider。"""
        self._require_provider(provider)
        with self._state_lock:
            state = self._read_state()
            current = self.snapshot()
            enabled_ids = [
                item["provider"] for item in current["providers"] if item["enabled"]
            ]
            if not enabled and provider in enabled_ids and len(enabled_ids) == 1:
                raise ModelRegistryError("at least one provider must remain enabled")
            provider_state = state.setdefault("providers", {}).setdefault(provider, {})
            provider_state["enabled"] = bool(enabled)
            if not enabled and current.get("default_provider") == provider:
                state["default_provider"] = next(
                    item for item in enabled_ids if item != provider
                )
            self._write_state(state)
        return self.snapshot()

    def set_default(self, provider: str) -> dict[str, Any]:
        """设置默认 Provider；已停用的 Provider 不允许设为默认。"""
        self._require_provider(provider)
        with self._state_lock:
            if not self._provider_enabled(provider, self._read_state()):
                raise ModelRegistryError("disabled provider cannot be the default")
            state = self._read_state()
            state["default_provider"] = provider
            self._write_state(state)
        return self.snapshot()

    def test_connection(self, provider: str) -> dict[str, Any]:
        """真实连接测试：发起一次最小化聊天调用并持久化结果。

        返回 {provider, status, checked_at, latency_ms}；status 取值：
        available / not_configured（密钥未配置，不发真实请求）/
        connection_failed / timeout / auth_failed 等分类诊断结果。
        全程日志只记录脱敏摘要，不打印密钥、请求正文或模型回复。
        """
        config = self.provider_config(provider)
        started = time.perf_counter()
        try:
            adapter = LLMAdapterFactory.create(config)
            status = adapter.status()
        except Exception as exc:
            return self._connection_failure(
                provider, config, classify_provider_error(exc), started
            )

        if provider != "mock" and not status.get("key_configured"):
            elapsed = round((time.perf_counter() - started) * 1000)
            result = self._connection_result(
                provider, "not_configured", latency_ms=elapsed
            )
            self._store_check(result)
            LOGGER.warning(
                "provider connection test skipped provider=%s model=%s "
                "category=not_configured duration_ms=%s",
                sanitize_provider_error(provider, max_length=80),
                sanitize_provider_error(config.get("model"), max_length=80),
                elapsed,
            )
            return result
        if not status.get("ready"):
            return self._connection_failure(
                provider,
                config,
                ProviderErrorDiagnostic(
                    category="connection_failed",
                    http_status=None,
                    error_type="ProviderNotReady",
                    safe_summary="provider adapter is not ready",
                ),
                started,
            )

        try:
            adapter.chat(
                [
                    {
                        "role": "system",
                        "content": "You are a connection test assistant. Reply briefly.",
                    },
                    {"role": "user", "content": "Reply with OK only. /no_think"},
                ],
            )
        except Exception as exc:
            return self._connection_failure(
                provider, config, classify_provider_error(exc), started
            )

        elapsed = round((time.perf_counter() - started) * 1000)
        result = self._connection_result(provider, "available", latency_ms=elapsed)
        LOGGER.info(
            "provider connection test succeeded provider=%s model=%s "
            "category=available duration_ms=%s endpoint_host=%s",
            sanitize_provider_error(provider, max_length=80),
            sanitize_provider_error(config.get("model"), max_length=80),
            elapsed,
            self._endpoint_host(config),
        )
        self._store_check(result)
        return result

    def _connection_failure(
        self,
        provider: str,
        config: dict[str, Any],
        diagnostic: ProviderErrorDiagnostic,
        started: float,
    ) -> dict[str, Any]:
        elapsed = round((time.perf_counter() - started) * 1000)
        level = logging.ERROR if diagnostic.category == "unknown_error" else logging.WARNING
        LOGGER.log(
            level,
            "provider connection test failed provider=%s model=%s category=%s "
            "http_status=%s error_type=%s duration_ms=%s endpoint_host=%s summary=%s",
            sanitize_provider_error(provider, max_length=80),
            sanitize_provider_error(config.get("model"), max_length=80),
            diagnostic.category,
            diagnostic.http_status if diagnostic.http_status is not None else "none",
            diagnostic.error_type,
            elapsed,
            self._endpoint_host(config),
            diagnostic.safe_summary,
        )
        result = self._connection_result(
            provider, diagnostic.category, latency_ms=elapsed
        )
        self._store_check(result)
        return result

    @staticmethod
    def _endpoint_host(config: dict[str, Any]) -> str:
        try:
            host = urlparse(str(config.get("base_url") or "")).hostname
        except ValueError:
            host = None
        return sanitize_provider_error(host or "unavailable", max_length=120)

    def _provider_record(
        self,
        provider: str,
        config: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """构建单个 Provider 的展示记录（健康状态推断：可用/未配置/未知等）。"""
        adapter = LLMAdapterFactory.create({**config, "provider": provider})
        adapter_status = adapter.status()
        last_check = state.get("last_checks", {}).get(provider)
        if provider == "mock":
            health = "available"
        elif not adapter_status.get("key_configured"):
            health = "not_configured"
        elif isinstance(last_check, dict):
            health = str(last_check.get("status", "unknown"))
        else:
            health = "unknown"
        return {
            "provider": provider,
            "display_name": config.get("display_name")
            or PROVIDER_LABELS.get(provider, provider),
            "platform": config.get("platform")
            or ("Local" if provider == "mock" else provider),
            "protocol": config.get("protocol") or ("offline" if provider == "mock" else "openai_compatible"),
            "model": adapter_status.get("model") or config.get("model") or "unavailable",
            "mode": config.get("mode") or adapter_status.get("mode", "unknown"),
            "key_configured": bool(adapter_status.get("key_configured")),
            "enabled": self._provider_enabled(provider, state),
            "default": False,
            "health": health,
            "last_checked_at": last_check.get("checked_at") if isinstance(last_check, dict) else None,
            "latency_ms": last_check.get("latency_ms") if isinstance(last_check, dict) else None,
        }

    def _provider_enabled(self, provider: str, state: dict[str, Any]) -> bool:
        configured = state.get("providers", {}).get(provider, {})
        default_enabled = self._providers.get(provider, {}).get("enabled", True)
        return configured.get("enabled", default_enabled) is not False

    def _store_check(self, result: dict[str, Any]) -> None:
        """把一次连接测试结果写入 overlay（持锁读改写）。"""
        with self._state_lock:
            state = self._read_state()
            state.setdefault("last_checks", {})[result["provider"]] = {
                "status": result["status"],
                "checked_at": result["checked_at"],
                "latency_ms": result.get("latency_ms"),
            }
            self._write_state(state)

    @staticmethod
    def _connection_result(
        provider: str,
        status: str,
        *,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": provider,
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms,
        }

    def _require_provider(self, provider: str) -> None:
        if provider not in self._providers:
            raise ModelRegistryError("provider is not configured")

    def _read_state(self) -> dict[str, Any]:
        """读取 overlay 状态文件；缺失/损坏/版本不符抛 ModelRegistryError 或返回默认。"""
        if not self.state_path.exists():
            return {"version": 1, "providers": {}, "last_checks": {}}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelRegistryError("model registry state is unavailable") from exc
        if not isinstance(state, dict) or state.get("version", 1) != 1:
            raise ModelRegistryError("model registry state is invalid")
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        """原子写入 overlay 状态（临时文件 + fsync + os.replace），失败可回退。"""
        state = {"version": 1, **state}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=".model-registry-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ModelRegistryError("model registry state could not be saved") from exc
