import json
from pathlib import Path


class TextNormalizer:
    def __init__(self, homophone_map_path: str, emoji_map_path: str):
        self.homophone_map = self._load_json(homophone_map_path)
        self.emoji_map = self._load_json(emoji_map_path)

    @staticmethod
    def _load_json(path: str) -> dict[str, str]:
        p = Path(path)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def normalize(self, text: str) -> str:
        normalized = text.strip()
        for src, target in self.emoji_map.items():
            normalized = normalized.replace(src, target)
        for src, target in self.homophone_map.items():
            normalized = normalized.replace(src, target)
        return normalized
