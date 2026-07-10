class Sanitizer:
    def sanitize(self, text: str, matches: list[str]) -> str:
        sanitized = text
        for word in sorted(set(matches), key=len, reverse=True):
            if not word:
                continue
            sanitized = sanitized.replace(word, "***")
        return sanitized
