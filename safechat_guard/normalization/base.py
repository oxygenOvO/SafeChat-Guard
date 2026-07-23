from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizationStep:
    normalizer: str
    before: str
    after: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass(frozen=True)
class NormalizationResult:
    original_text: str
    normalized_text: str
    steps: list[NormalizationStep]


class BaseNormalizer(Protocol):
    name: str
    enabled: bool

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        ...
