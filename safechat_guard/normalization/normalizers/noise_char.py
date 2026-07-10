from __future__ import annotations

import re
from typing import Any


class NoiseCharNormalizer:
    name = "noise_char"
    enabled = True

    DEFAULT_NOISE_CHARS = set("@#_$%^&*+=|\\/~`·•・")
    EMAIL_CHARS = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@"
    )
    EMAIL_PATTERN = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    def __init__(self, noise_chars: set[str] | None = None):
        self.noise_chars = noise_chars or self.DEFAULT_NOISE_CHARS

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        chars = list(text)
        output = []
        removed = []
        for index, char in enumerate(chars):
            if self._should_remove(chars, index):
                removed.append({"char": char, "index": index})
                continue
            output.append(char)
        return "".join(output), {"removed": removed}

    def _should_remove(self, chars: list[str], index: int) -> bool:
        char = chars[index]
        if (
            char in self.noise_chars
            and self._has_text_neighbor(chars, index)
            and not self._inside_email(chars, index)
        ):
            return True
        if char.isspace() and self._between_cjk(chars, index):
            return True
        return False

    @classmethod
    def _inside_email(cls, chars: list[str], index: int) -> bool:
        if chars[index] not in cls.EMAIL_CHARS:
            return False

        start = index
        while start > 0 and chars[start - 1] in cls.EMAIL_CHARS:
            start -= 1

        end = index + 1
        while end < len(chars) and chars[end] in cls.EMAIL_CHARS:
            end += 1

        return cls.EMAIL_PATTERN.fullmatch("".join(chars[start:end])) is not None

    @staticmethod
    def _has_text_neighbor(chars: list[str], index: int) -> bool:
        prev_char = chars[index - 1] if index > 0 else ""
        next_char = chars[index + 1] if index + 1 < len(chars) else ""
        return _is_text_char(prev_char) and _is_text_char(next_char)

    @staticmethod
    def _between_cjk(chars: list[str], index: int) -> bool:
        prev_char = chars[index - 1] if index > 0 else ""
        next_char = chars[index + 1] if index + 1 < len(chars) else ""
        return _is_cjk(prev_char) and _is_cjk(next_char)


def _is_text_char(char: str) -> bool:
    return char.isalnum() or _is_cjk(char)


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"
