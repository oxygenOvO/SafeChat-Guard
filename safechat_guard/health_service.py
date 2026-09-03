"""组件与 Provider 的真实健康检查（不美化、不臆测，未实测即"未检测"）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .model_registry import ModelRegistry
from .pipeline import SafeChatPipeline


class HealthService:
    """健康检查服务：汇总安全链路各组件状态并给出 Fail-Closed 结论。

    ``model_calls_allowed`` 是关键安全开关：关键组件（CRITICAL_COMPONENTS）
    任一异常时为 False，前端与运维控制台据此暂停模型调用。
    语义分类器作为可降级组件，缺失只标记 degraded 而不阻断。
    """

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
        """构建一次完整健康快照：各组件状态 + 总体结论 + Provider 列表。

        status 取值：normal（关键组件全部正常且无降级）/
        degraded（正常但语义模型缺失）/ abnormal（关键组件异常）。
        """
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
