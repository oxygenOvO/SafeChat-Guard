from dataclasses import dataclass, field
from typing import Any


@dataclass
class Detection:
    category: str
    level: str
    score: int
    reason: str
    source: str
    matches: list[str] = field(default_factory=list)


@dataclass
class FilterResult:
    original_text: str
    normalized_text: str
    action: str
    risk_score: int
    detections: list[Detection]
    sanitized_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
