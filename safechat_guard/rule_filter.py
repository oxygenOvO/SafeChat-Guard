import json
import re
from pathlib import Path

from .models import Detection


CONTEXTUAL_WEAK_KEYWORDS = {
    "ad": {
        "网络": ("网络安全", "安全防护", "攻击检测", "课程", "实验", "防御"),
    },
    "sensitive": {
        "谣言": ("识别", "辨别", "核查", "治理", "辟谣", "防范", "制止"),
    },
}


class RuleFilter:
    def __init__(self, lexicon_dir: str, regex_path: str):
        self.lexicon_dir = Path(lexicon_dir)
        self.regex_path = Path(regex_path)
        self.words = self._load_words()
        self.regex_rules = self._load_regex_rules()

    def _load_words(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if not self.lexicon_dir.exists():
            return result
        for path in self.lexicon_dir.glob("*.txt"):
            category = path.stem
            words = []
            for line in path.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word and not word.startswith("#"):
                    words.append(word)
            result[category] = words
        return result

    def _load_regex_rules(self) -> list[dict]:
        if not self.regex_path.exists():
            return []
        rules = json.loads(self.regex_path.read_text(encoding="utf-8"))
        valid_rules = []
        for rule in rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error:
                continue
            valid_rules.append(rule)
        return valid_rules

    def detect(self, text: str) -> list[Detection]:
        detections: list[Detection] = []
        for category, words in self.words.items():
            matched = [word for word in words if word in text]
            matched = self._remove_safe_context_matches(category, matched, text)
            if matched:
                high_risk = category in {"porn", "violence"} or (
                    category == "abuse" and len(set(matched)) >= 2
                )
                detections.append(
                    Detection(
                        category=category,
                        level="high" if high_risk else "medium",
                        score=80 if high_risk else 55,
                        reason=f"matched {category} keyword lexicon",
                        source="keyword",
                        matches=matched,
                    )
                )
        for rule in self.regex_rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            matches = list(dict.fromkeys(
                match.group(0)
                for match in re.finditer(pattern, text, flags=re.IGNORECASE)
            ))
            if matches:
                detections.append(
                    Detection(
                        category=rule.get("category", "unknown"),
                        level=rule.get("level", "medium"),
                        score=int(rule.get("score", 60)),
                        reason=rule.get("reason", "matched regex rule"),
                        source="regex",
                        matches=matches,
                    )
                )
        return detections

    @staticmethod
    def _remove_safe_context_matches(
        category: str,
        matches: list[str],
        text: str,
    ) -> list[str]:
        weak_keywords = CONTEXTUAL_WEAK_KEYWORDS.get(category, {})
        if not matches or any(match not in weak_keywords for match in matches):
            return matches

        for match in matches:
            context_terms = weak_keywords[match]
            if not any(term in text for term in context_terms):
                return matches
        return []
