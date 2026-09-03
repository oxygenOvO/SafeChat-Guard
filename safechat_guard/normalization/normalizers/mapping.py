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
        self._ordered_entries = self._build_ordered_entries()

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        current = text
        matches = []
        for source, info in self._ordered_entries:
            target = info["target"]
            if source not in current:
                continue
            count = current.count(source)
            current = current.replace(source, target)
            matches.append(self._match_metadata(source, target, info, count))
        return current, {"category": self.category, "matches": matches}

    def _build_ordered_entries(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self.mapping.items(), key=lambda item: len(item[0]), reverse=True)

    def _ordered_mapping(self) -> list[tuple[str, dict[str, Any]]]:
        return self._ordered_entries

    def _match_metadata(
        self, source: str, target: str, info: dict[str, Any], count: int
    ) -> dict[str, Any]:
        metadata = {
            "source": source,
            "target": target,
            "count": count,
            "category": self.category,
        }
        for key in [
            "type",
            "category_hint",
            "confidence",
            "confidence_score",
            "rationale",
        ]:
            if key in info:
                metadata[key] = info[key]
        return metadata


class TokenMappingNormalizer(MappingNormalizer):
    def __init__(self, name: str, provider: JsonMapProvider, category: str):
        super().__init__(name, provider, category)
        self._ordered_patterns = [
            (source, info, self._pattern_for(source))
            for source, info in self._ordered_entries
        ]

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        current = text
        matches = []
        for source, info, pattern in self._ordered_patterns:
            target = info["target"]
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
