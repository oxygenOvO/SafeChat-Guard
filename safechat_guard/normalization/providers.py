from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonMapProvider:
    """Loads normalization mappings from JSON.

    Supports both legacy format:
        {"src": "target"}

    and enriched format:
        {"src": {"target": "target", "type": "...", "confidence": 0.9}}
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def source_name(self) -> str:
        return str(self.path)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for source, value in raw.items():
            if not isinstance(source, str) or not source:
                continue
            normalized = self._normalize_value(value)
            if normalized:
                result[source] = normalized
        return result

    @staticmethod
    def _normalize_value(value: Any) -> dict[str, Any] | None:
        if isinstance(value, str):
            return {"target": value}
        if isinstance(value, dict) and isinstance(value.get("target"), str):
            return dict(value)
        return None


class CompositeMapProvider:
    def __init__(self, providers: list[JsonMapProvider]):
        self.providers = providers

    def load(self) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for provider in self.providers:
            merged.update(provider.load())
        return merged
