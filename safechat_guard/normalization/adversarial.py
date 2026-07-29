from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class AdversarialView:
    text: str
    source_offsets: tuple[int, ...]


class AdversarialSeparatorNormalizer:
    """Join separators only inside confirmed high-risk Chinese fragments."""

    FRAGMENTS = frozenset({"炸药", "微信", "加微", "色情", "约炮"})
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
            fragment, right_index = matched
            output.extend(fragment)
            offsets.extend((index, right_index))
            index = right_index + 1
        offsets.append(len(text))
        return AdversarialView("".join(output), tuple(offsets))

    def _match_fragment(
        self, text: str, start: int
    ) -> tuple[str, int] | None:
        left = text[start]
        candidates = [term for term in self.FRAGMENTS if term[0] == left]
        if not candidates:
            return None
        for fragment in candidates:
            right_index = self._separator_end(text, start + 1)
            if (
                right_index > start + 1
                and right_index < len(text)
                and text[right_index] == fragment[1]
            ):
                return fragment, right_index
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
