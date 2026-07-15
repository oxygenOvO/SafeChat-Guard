from pathlib import Path

from .normalization.base import NormalizationResult
from .normalization.normalizers.case import CaseNormalizer
from .normalization.normalizers.mapping import MappingNormalizer, TokenMappingNormalizer
from .normalization.normalizers.noise_char import NoiseCharNormalizer
from .normalization.normalizers.repeat_char import RepeatCharNormalizer
from .normalization.normalizers.unicode import UnicodeNormalizer
from .normalization.pipeline import NormalizationPipeline
from .normalization.providers import JsonMapProvider


class TextNormalizer:
    """Compatibility facade for the normalization subsystem.

    Existing callers can keep using ``normalize(text) -> str``. Newer code can
    call ``normalize_with_trace(text)`` to inspect every normalization step.
    """

    def __init__(self, homophone_map_path: str, emoji_map_path: str):
        self.homophone_map_path = Path(homophone_map_path)
        self.emoji_map_path = Path(emoji_map_path)
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> NormalizationPipeline:
        map_dir = self.homophone_map_path.parent
        return NormalizationPipeline(
            [
                UnicodeNormalizer(),
                CaseNormalizer(),
                MappingNormalizer(
                    "emoji",
                    JsonMapProvider(self.emoji_map_path),
                    category="emoji",
                ),
                MappingNormalizer(
                    "symbol_insertion",
                    JsonMapProvider(map_dir / "symbol_variant_map.json"),
                    category="symbol_insertion",
                ),
                NoiseCharNormalizer(),
                RepeatCharNormalizer(max_repeat=2),
                MappingNormalizer(
                    "variant_char",
                    JsonMapProvider(map_dir / "variant_char_map.json"),
                    category="variant_char",
                ),
                MappingNormalizer(
                    "homophone",
                    JsonMapProvider(self.homophone_map_path),
                    category="homophone",
                ),
                TokenMappingNormalizer(
                    "pinyin",
                    JsonMapProvider(map_dir / "pinyin_map.json"),
                    category="pinyin",
                ),
                TokenMappingNormalizer(
                    "abbreviation",
                    JsonMapProvider(map_dir / "abbreviation_map.json"),
                    category="abbreviation",
                ),
                NoiseCharNormalizer(),
            ]
        )

    def reload(self) -> None:
        self.pipeline = self._build_pipeline()

    def normalize(self, text: str) -> str:
        return self.pipeline.normalize(text)

    def normalize_with_trace(self, text: str) -> NormalizationResult:
        return self.pipeline.normalize_with_trace(text)
