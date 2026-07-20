from __future__ import annotations

import re
from typing import Any


class CaseNormalizer:
    name = "case"
    enabled = True
    PROTECTED_TOKENS = ("C++",)

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        normalized = list(text.lower())
        preserved = []
        for token in self.PROTECTED_TOKENS:
            for match in re.finditer(re.escape(token), text):
                normalized[match.start() : match.end()] = match.group()
                preserved.append({"token": match.group(), "start": match.start()})
        return "".join(normalized), {
            "strategy": "lower_except_protected_tokens",
            "preserved_tokens": preserved,
        }
