"""文本归一化模块的对外统一门面（Facade）。

归一化是输入检测链路的第一步：攻击者常用同音字、拼音、Emoji、符号插入、
重复噪声等手段绕过关键词检测，本模块把这些变体文本还原成标准文本，
供后续关键词/正则/语义分类使用。

对外提供三种调用方式：
- ``normalize(text) -> str``：兼容旧调用方，只返回归一化后的文本；
- ``normalize_with_trace(text) -> NormalizationResult``：带完整归一化轨迹，
  可逐步审查每一步的 before/after，供决策解释服务使用；
- ``normalize_views(text)``：等价于 ``normalize_with_trace``，
  同时产出用于关键词匹配的对抗视图文本（adversarial_text）。
"""

from pathlib import Path

from .normalization.adversarial import AdversarialSeparatorNormalizer
from .normalization.base import NormalizationResult
from .normalization.normalizers.case import CaseNormalizer
from .normalization.normalizers.mapping import MappingNormalizer, TokenMappingNormalizer
from .normalization.normalizers.noise_char import NoiseCharNormalizer
from .normalization.normalizers.repeat_char import RepeatCharNormalizer
from .normalization.normalizers.unicode import UnicodeNormalizer
from .normalization.pipeline import NormalizationPipeline
from .normalization.providers import JsonMapProvider


class TextNormalizer:
    """归一化子系统兼容门面。

    旧调用方可以继续使用 ``normalize(text) -> str``；
    新代码建议调用 ``normalize_with_trace(text)`` 以获取每一步归一化轨迹。
    """

    def __init__(self, homophone_map_path: str, emoji_map_path: str):
        self.homophone_map_path = Path(homophone_map_path)
        self.emoji_map_path = Path(emoji_map_path)
        self.pipeline = self._build_pipeline()
        # 对抗分隔符归一化器：独立于主管线，用于生成对抗视图文本
        self.adversarial_normalizer = AdversarialSeparatorNormalizer()

    def _build_pipeline(self) -> NormalizationPipeline:
        """按固定顺序构建归一化管线。

        顺序有讲究：先做 Unicode/大小写等基础规整，再做 Emoji/符号映射，
        去掉噪声与重复字符后，最后做同音/拼音/缩写恢复（这些映射要求
        前面的噪声已经被清理，否则词条匹配不上）。管线尾部再跑一次噪声
        清理，兜底映射替换后新产生的干扰字符。
        """
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
        """重新加载全部映射表并重建管线（词库热更新时使用）。"""
        self.pipeline = self._build_pipeline()
        self.adversarial_normalizer = AdversarialSeparatorNormalizer()

    def normalize(self, text: str) -> str:
        """兼容入口：只返回归一化后的最终文本。"""
        return self.pipeline.normalize(text)

    def normalize_with_trace(self, text: str) -> NormalizationResult:
        """返回带逐步轨迹的归一化结果，并附加对抗视图文本。"""
        result = self.pipeline.normalize_with_trace(text)
        adversarial = self.adversarial_normalizer.normalize(
            result.normalized_text
        )
        return NormalizationResult(
            original_text=result.original_text,
            normalized_text=result.normalized_text,
            steps=result.steps,
            adversarial_text=adversarial.text,
            adversarial_to_normalized=adversarial.source_offsets,
        )

    def normalize_views(self, text: str) -> NormalizationResult:
        """与 normalize_with_trace 等价；语义上强调"多视图"供规则匹配使用。"""
        return self.normalize_with_trace(text)
