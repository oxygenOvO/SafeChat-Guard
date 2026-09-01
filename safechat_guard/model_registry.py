"""Runtime model registry backed by tracked config plus a safe local overlay."""

from __future__ import annotations

import json
import os
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm_adapters import LLMAdapterFactory, PROVIDER_LABELS


class ModelRegistryError(RuntimeError):
    pass


class ModelRegistry:
    """Manage provider availability without persisting credentials."""

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
        self._require_provider(provider)
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
        self._require_provider(provider)
        if not self._provider_enabled(provider, self._read_state()):
            raise ModelRegistryError("disabled provider cannot be the default")
        state = self._read_state()
        state["default_provider"] = provider
        self._write_state(state)
        return self.snapshot()

    def test_connection(self, provider: str) -> dict[str, Any]:
        config = self.provider_config(provider)
        adapter = LLMAdapterFactory.create(config)
        status = adapter.status()
        if provider != "mock" and not status.get("key_configured"):
            result = self._connection_result(provider, "not_configured")
            self._store_check(result)
            return result
        if not status.get("ready"):
            result = self._connection_result(provider, "unavailable")
            self._store_check(result)
            return result

        started = time.perf_counter()
        try:
            adapter.chat("Reply with OK.")
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000)
            name = type(exc).__name__.lower()
            state = "timeout" if "timeout" in name or "timeout" in str(exc).lower() else "failed"
            result = self._connection_result(provider, state, latency_ms=elapsed)
        else:
            elapsed = round((time.perf_counter() - started) * 1000)
            result = self._connection_result(provider, "available", latency_ms=elapsed)
        self._store_check(result)
        return result

    def _provider_record(
        self,
        provider: str,
        config: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
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
            "display_name": PROVIDER_LABELS.get(provider, provider),
            "model": adapter_status.get("model") or config.get("model") or "unavailable",
            "mode": adapter_status.get("mode", "unknown"),
            "key_configured": bool(adapter_status.get("key_configured")),
            "enabled": self._provider_enabled(provider, state),
            "default": False,
            "health": health,
            "last_checked_at": last_check.get("checked_at") if isinstance(last_check, dict) else None,
            "latency_ms": last_check.get("latency_ms") if isinstance(last_check, dict) else None,
        }

    def _provider_enabled(self, provider: str, state: dict[str, Any]) -> bool:
        configured = state.get("providers", {}).get(provider, {})
        return configured.get("enabled", True) is not False

    def _store_check(self, result: dict[str, Any]) -> None:
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
