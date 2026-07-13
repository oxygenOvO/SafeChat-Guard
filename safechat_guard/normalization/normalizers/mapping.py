from __future__ import annotations

import re
from typing import Any

from ..providers import JsonMapProvider


class MappingNormalizer:
    def __init__(self, name: str, provider: JsonMapProvider, category: str):
        self.name = name
        self.provider = provider
        self.category = category
        self.enabled = True
        self.mapping = provider.load()

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        current = text
        matches = []
        for source, info in self._ordered_mapping():
            target = info["target"]
            if source not in current:
                continue
            count = current.count(source)
            current = current.replace(source, target)
            matches.append(self._match_metadata(source, target, info, count))
        return current, {"category": self.category, "matches": matches}

    def _ordered_mapping(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self.mapping.items(), key=lambda item: len(item[0]), reverse=True)

    def _match_metadata(
        self, source: str, target: str, info: dict[str, Any], count: int
    ) -> dict[str, Any]:
        metadata = {
            "source": source,
            "target": target,
            "count": count,
            "category": self.category,
        }
        for key in ["type", "category_hint", "confidence"]:
            if key in info:
                metadata[key] = info[key]
        return metadata


class TokenMappingNormalizer(MappingNormalizer):
    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        current = text
        matches = []
        for source, info in self._ordered_mapping():
            target = info["target"]
            pattern = self._pattern_for(source)
            current, count = pattern.subn(target, current)
            if count:
                matches.append(self._match_metadata(source, target, info, count))
        return current, {"category": self.category, "matches": matches}

    @staticmethod
    def _pattern_for(source: str) -> re.Pattern[str]:
        escaped = re.escape(source)
        if source.isascii() and any(char.isalnum() for char in source):
            return re.compile(rf"(?<![a-zA-Z0-9]){escaped}(?![a-zA-Z0-9])")
        return re.compile(escaped)
