from __future__ import annotations

from typing import Any


class RepeatCharNormalizer:
    name = "repeat_char"
    enabled = True

    def __init__(self, max_repeat: int = 2):
        self.max_repeat = max_repeat

    def normalize(self, text: str) -> tuple[str, dict[str, Any]]:
        if not text:
            return text, {"max_repeat": self.max_repeat}

        output = [text[0]]
        run_char = text[0]
        run_length = 1
        compressed = 0

        for char in text[1:]:
            if char == run_char:
                run_length += 1
                if run_length <= self.max_repeat:
                    output.append(char)
                else:
                    compressed += 1
                continue
            run_char = char
            run_length = 1
            output.append(char)

        return "".join(output), {"max_repeat": self.max_repeat, "compressed": compressed}
