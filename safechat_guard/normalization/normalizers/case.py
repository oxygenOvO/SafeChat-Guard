from __future__ import annotations

from typing import Any


class CaseNormalizer:
    name = "case"
    enabled = True

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        return text.lower(), {"strategy": "lower"}
