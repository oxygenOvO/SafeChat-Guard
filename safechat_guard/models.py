from dataclasses import dataclass, field


@dataclass
class Detection:
    category: str
    level: str
    score: int
    reason: str
    source: str
    matches: list[str] = field(default_factory=list)
