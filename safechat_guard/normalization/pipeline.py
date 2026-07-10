from __future__ import annotations

from .base import BaseNormalizer, NormalizationResult, NormalizationStep


class NormalizationPipeline:
    def __init__(self, normalizers: list[BaseNormalizer]):
        self.normalizers = normalizers

    def normalize(self, text: str) -> str:
        return self.normalize_with_trace(text).normalized_text

    def normalize_with_trace(self, text: str) -> NormalizationResult:
        original = text
        current = text
        steps: list[NormalizationStep] = []

        for normalizer in self.normalizers:
            if not getattr(normalizer, "enabled", True):
                continue
            before = current
            current, metadata = normalizer.normalize(current)
            step = NormalizationStep(
                normalizer=normalizer.name,
                before=before,
                after=current,
                metadata=metadata,
            )
            if step.changed:
                steps.append(step)

        return NormalizationResult(
            original_text=original,
            normalized_text=current,
            steps=steps,
        )
