from __future__ import annotations

import unicodedata
from typing import Any


class UnicodeNormalizer:
    name = "unicode"
    enabled = True

    CONTROL_CATEGORIES = {"Cc", "Cf"}

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        stripped = text.strip()
        normalized = unicodedata.normalize("NFKC", stripped)
        cleaned = "".join(
            char
            for char in normalized
            if unicodedata.category(char) not in self.CONTROL_CATEGORIES
        )
        return cleaned, {"form": "NFKC", "removed_control_chars": normalized != cleaned}
