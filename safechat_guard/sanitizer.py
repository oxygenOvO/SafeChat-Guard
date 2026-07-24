class Sanitizer:
    CONTACT_CUES = {
        "加微信",
        "联系微信",
    }

    def sanitize(self, text: str, matches: list[str]) -> str:
        sanitized = text
        for word in sorted(set(matches), key=len, reverse=True):
            if not word:
                continue
            replacement = (
                "[联系方式已隐藏]"
                if word in self.CONTACT_CUES
                else "***"
            )
            sanitized = sanitized.replace(word, replacement)
        return sanitized
