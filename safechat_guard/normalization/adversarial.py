from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class AdversarialView:
    text: str
    source_offsets: tuple[int, ...]


class AdversarialSeparatorNormalizer:
    """Join separators only inside confirmed high-risk Chinese fragments."""

    FRAGMENTS = frozenset(
        {
            "炸药",
            "爆炸物",
            "枪械",
            "枪械配件",
            "违禁武器",
            "微信",
            "加微",
            "色情",
            "约炮",
        }
    )
    MAX_SEPARATOR_LENGTH = 8
    EXPLICIT_SEPARATORS = frozenset(
        "\u200b\u200c\u200d\ufeff"
        "★☆*._·•"
        "-‐‑‒–—﹘﹣－"
        "💥"
    )
    MAPPED_SEPARATOR_TOKENS = ("爆款",)

    def normalize(self, text: str) -> AdversarialView:
        output: list[str] = []
        offsets: list[int] = []
        index = 0
        while index < len(text):
            matched = self._match_fragment(text, index)
            if matched is None:
                output.append(text[index])
                offsets.append(index)
                index += 1
                continue
            fragment, source_positions, end = matched
            output.extend(fragment)
            offsets.extend(source_positions)
            index = end
        offsets.append(len(text))
        return AdversarialView("".join(output), tuple(offsets))

    def _match_fragment(
        self, text: str, start: int
    ) -> tuple[str, tuple[int, ...], int] | None:
        left = text[start]
        candidates = sorted(
            (term for term in self.FRAGMENTS if term[0] == left),
            key=len,
            reverse=True,
        )
        if not candidates:
            return None
        for fragment in candidates:
            cursor = start
            positions: list[int] = []
            saw_separator = False
            for expected in fragment:
                if positions:
                    advanced = self._separator_end(text, cursor)
                    saw_separator = saw_separator or advanced > cursor
                    cursor = advanced
                if cursor >= len(text) or text[cursor] != expected:
                    break
                positions.append(cursor)
                cursor += 1
            else:
                if saw_separator:
                    return fragment, tuple(positions), cursor
        return None

    def _separator_end(self, text: str, start: int) -> int:
        index = start
        consumed = 0
        while index < len(text) and consumed < self.MAX_SEPARATOR_LENGTH:
            token = next(
                (
                    value
                    for value in self.MAPPED_SEPARATOR_TOKENS
                    if text.startswith(value, index)
                ),
                None,
            )
            if token is not None:
                index += len(token)
                consumed += len(token)
                continue
            char = text[index]
            if not self._is_separator(char):
                break
            index += 1
            consumed += 1
        return index

    def _is_separator(self, char: str) -> bool:
        return (
            char.isspace()
            or char in self.EXPLICIT_SEPARATORS
            or unicodedata.category(char) == "Cf"
        )
