"""Truthful component and provider health inspection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .model_registry import ModelRegistry
from .pipeline import SafeChatPipeline


class HealthService:
    CRITICAL_COMPONENTS = {
        "SafeChatPipeline",
        "TextNormalizer",
        "RuleFilter",
        "ActionRouter",
        "Sanitizer",
        "OutputGuard",
        "EventLogger",
    }

    def __init__(self, pipeline: SafeChatPipeline, registry: ModelRegistry) -> None:
        self.pipeline = pipeline
        self.registry = registry

    def snapshot(self) -> dict[str, Any]:
        semantic = self.pipeline.semantic_classifier.status()
        components = [
            self._component("SafeChatPipeline", self.pipeline is not None),
            self._component("TextNormalizer", self.pipeline.normalizer is not None),
            self._component("RuleFilter", self.pipeline.rule_filter is not None),
            self._component(
                "SemanticClassifier",
                bool(semantic.get("loaded")),
                optional=not self.pipeline.semantic_required,
                detail=str(semantic.get("error") or "loaded"),
            ),
            self._component("ActionRouter", self.pipeline.action_router is not None),
            self._component("Sanitizer", self.pipeline.sanitizer is not None),
            self._component("OutputGuard", self.pipeline.output_guard is not None),
            self._component(
                "EventLogger",
                self.pipeline.logger is not None and self.pipeline.logger.path.parent.exists(),
            ),
        ]
        critical_ok = all(
            item["status"] == "normal"
            for item in components
            if item["name"] in self.CRITICAL_COMPONENTS
        )
        degraded = any(item["status"] == "unloaded" for item in components)
        return {
            "status": "normal" if critical_ok and not degraded else ("degraded" if critical_ok else "abnormal"),
            "model_calls_allowed": critical_ok,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": components,
            "providers": self.registry.snapshot()["providers"],
        }

    @staticmethod
    def _component(
        name: str,
        ready: bool,
        *,
        optional: bool = False,
        detail: str | None = None,
    ) -> dict[str, Any]:
        status = "normal" if ready else ("unloaded" if optional else "abnormal")
        return {"name": name, "status": status, "detail": detail}
