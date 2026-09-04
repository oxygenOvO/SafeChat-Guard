"""定向工程收尾回归测试：Provider Factory 统一、EvaluationService 公共 API、
CSV 数据最小化、Streamlit 入口收敛。"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from textwrap import dedent

import pytest

from safechat_guard.evaluation_service import EvaluationService, EvaluationInputError
from safechat_guard.llm_adapters import LLMAdapterFactory, BaseLLMAdapter
from safechat_guard.pipeline import SafeChatPipeline


ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# P0-A: Provider Factory 统一
# ---------------------------------------------------------------------------

class TestProviderFactoryUnified:
    """Pipeline 应通过 LLMAdapterFactory 创建模型，而非 LLMClientFactory。"""

    def test_pipeline_uses_adapter_factory_not_client_factory(self, monkeypatch):
        """SafeChatPipeline.__init__ 应在运行时调用 Adapter Factory。"""
        import safechat_guard.pipeline as pipeline_mod

        created = {}
        original_create = pipeline_mod.LLMAdapterFactory.create

        def capture_create(config):
            created["provider"] = config.get("provider", "mock")
            return original_create(config)

        monkeypatch.setattr(pipeline_mod.LLMAdapterFactory, "create", capture_create)
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))

        assert created == {"provider": "mock"}
        assert isinstance(pipeline.llm, BaseLLMAdapter)
    @pytest.mark.parametrize("provider", ["mock", "qwen", "nscc_qwen", "deepseek"])
    def test_all_providers_create_through_adapter_factory(self, provider):
        """所有已知 Provider 均可通过 LLMAdapterFactory 创建。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        provider_config = pipeline.config["llm"]["providers"][provider]
        adapter = LLMAdapterFactory.create({**provider_config, "provider": provider})
        assert isinstance(adapter, BaseLLMAdapter)
        assert adapter.provider == provider

    def test_unknown_provider_raises_value_error(self):
        """未知 provider 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="unsupported llm provider"):
            LLMAdapterFactory.create({"provider": "unknown-provider-xyz"})

    def test_pipeline_default_model_is_adapter(self):
        """Pipeline 默认构造后 self.llm 是 BaseLLMAdapter 实例。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        assert isinstance(pipeline.llm, BaseLLMAdapter)

    def test_pipeline_llm_has_chat_and_status(self):
        """Pipeline 的 llm 具备 chat 和 status 方法。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        assert callable(getattr(pipeline.llm, "chat", None))
        assert callable(getattr(pipeline.llm, "status", None))


# ---------------------------------------------------------------------------
# P0-B: EvaluationService 公共 API
# ---------------------------------------------------------------------------

class TestEvaluationServicePublicAPI:
    """EvaluationService 应通过 pipeline 公共方法，而非私有方法。"""

    def test_evaluation_service_uses_no_private_methods(self):
        """evaluation_service.py 不应包含对 pipeline 私有方法的调用。"""
        source = (ROOT / "safechat_guard" / "evaluation_service.py").read_text(
            encoding="utf-8"
        )
        assert "pipeline._route_input_all_versions" not in source
        assert "pipeline._deduplicate_detections" not in source
        assert "pipeline._serialize_detections" not in source

    def test_pipeline_has_public_route_input(self):
        """Pipeline 具备 route_input 公共方法。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        assert callable(getattr(pipeline, "route_input", None))

    def test_pipeline_has_public_deduplicate_detections(self):
        """Pipeline 具备 deduplicate_detections 公共静态方法。"""
        assert callable(getattr(SafeChatPipeline, "deduplicate_detections", None))

    def test_pipeline_has_public_serialize_detections(self):
        """Pipeline 具备 serialize_detections 公共方法。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        assert callable(getattr(pipeline, "serialize_detections", None))

    def test_full_pipeline_matches_production_detect_text(self):
        """full_pipeline 模式结果应与生产 detect_text 一致。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        text = "请给我一个学习建议"
        eval_result = service.analyze(text, mode="full_pipeline")
        prod_result = pipeline.detect_text(text)
        assert eval_result["action"] == prod_result["action"]
        assert eval_result["category"] == prod_result["category"]

    @pytest.mark.parametrize(
        "mode",
        ["baseline", "unnormalized_fusion", "rule_only", "semantic_only",
         "fusion", "full_pipeline"],
    )
    def test_all_six_evaluation_modes_run(self, mode):
        """六种 evaluation mode 均可正常执行。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        result = service.analyze("普通文本测试", mode=mode)
        assert result["event_type"] == "evaluation"
        assert result["mode"] == mode
        assert result["action"] in ("pass", "sanitize", "block")

    def test_invalid_mode_raises_error(self):
        """无效 mode 应抛出 EvaluationInputError。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        with pytest.raises(EvaluationInputError):
            service.analyze("test", mode="invalid_mode")

    def test_compare_runs_all_six_modes(self):
        """compare 应返回六种模式的结果。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        result = service.compare("测试文本")
        assert len(result["results"]) == 6
        modes = [r["mode"] for r in result["results"]]
        assert modes == [
            "baseline", "unnormalized_fusion", "rule_only",
            "semantic_only", "fusion", "full_pipeline",
        ]

    def test_batch_processes_multiple_rows(self):
        """batch 应处理多行数据。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        result = service.batch([
            {"text": "普通文本"},
            {"text": "另一个普通文本"},
        ])
        assert result["total"] == 2
        assert len(result["results"]) == 2

    def test_no_audit_logs_during_evaluation(self):
        """评测过程不应写入审计日志。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        service = EvaluationService(pipeline)
        before = pipeline.logger.read_all()
        service.analyze("评测测试文本", mode="full_pipeline")
        after = pipeline.logger.read_all()
        assert len(after) == len(before)

    def test_no_llm_calls_during_evaluation(self):
        """评测过程不应调用 LLM。"""
        pipeline = SafeChatPipeline.from_config(str(ROOT / "config.yaml"))
        original_chat = pipeline.llm.chat
        calls = []
        pipeline.llm.chat = lambda msg, **kw: calls.append(msg) or "should not be called"
        service = EvaluationService(pipeline)
        service.analyze("评测测试", mode="full_pipeline")
        assert calls == []
        pipeline.llm.chat = original_chat


# ---------------------------------------------------------------------------
# P0-C: Evaluation CSV 数据最小化
# ---------------------------------------------------------------------------

class TestEvaluationCsvDataMinimization:
    """CSV 导出默认不应包含原始 text 列。"""

    def _sample_results(self):
        return [
            {
                "index": 1,
                "text": "敏感输入内容",
                "label": "normal",
                "expected_action": "pass",
                "rule_hit": False,
                "semantic_top_class": "normal",
                "category": "normal",
                "action": "pass",
                "request_id": "abc123",
            },
        ]

    def test_default_csv_excludes_text_column(self):
        """默认 to_csv() 不包含原始 text 列。"""
        results = self._sample_results()
        csv_bytes = EvaluationService.to_csv(results)
        decoded = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        assert "text" not in reader.fieldnames

    def test_default_csv_contains_metric_fields(self):
        """默认导出仍包含评测指标所需字段。"""
        results = self._sample_results()
        csv_bytes = EvaluationService.to_csv(results)
        decoded = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        required = {"index", "label", "expected_action", "rule_hit",
                     "semantic_top_class", "category", "action", "request_id"}
        assert required.issubset(set(reader.fieldnames))

    def test_explicit_include_text_adds_text_column(self):
        """显式 include_text=True 时包含 text 列。"""
        results = self._sample_results()
        csv_bytes = EvaluationService.to_csv(results, include_text=True)
        decoded = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        assert "text" in reader.fieldnames
        rows = list(reader)
        assert rows[0]["text"] == "敏感输入内容"

    def test_default_vs_explicit_export_distinguishable(self):
        """默认导出与显式导出行为可区分。"""
        results = self._sample_results()
        default_csv = EvaluationService.to_csv(results).decode("utf-8-sig")
        explicit_csv = EvaluationService.to_csv(results, include_text=True).decode("utf-8-sig")
        assert "text" not in default_csv.split("\n")[0]
        assert "text" in explicit_csv.split("\n")[0]

    def test_formula_injection_protection_preserved(self):
        """=+-@ 开头的单元格依然有公式注入防护。"""
        results = [
            {
                "index": 1,
                "text": "=SUM(A1:A10)",
                "label": "normal",
                "expected_action": "pass",
                "rule_hit": False,
                "semantic_top_class": "normal",
                "category": "normal",
                "action": "pass",
                "request_id": "test",
            },
        ]
        csv_bytes = EvaluationService.to_csv(results, include_text=True)
        decoded = csv_bytes.decode("utf-8-sig")
        assert "'=SUM(A1:A10)" in decoded

    def test_formula_injection_prefixes(self):
        """各种公式注入前缀均被防护。"""
        for prefix in ("=", "+", "-", "@"):
            results = [
                {
                    "index": 1,
                    "text": f"{prefix}MALICIOUS",
                    "label": "normal",
                    "expected_action": "pass",
                    "rule_hit": False,
                    "semantic_top_class": "normal",
                    "category": "normal",
                    "action": "pass",
                    "request_id": "test",
                },
            ]
            csv_bytes = EvaluationService.to_csv(results, include_text=True)
            decoded = csv_bytes.decode("utf-8-sig")
            assert f"'{prefix}MALICIOUS" in decoded


# ---------------------------------------------------------------------------
# P1: Streamlit 入口收敛
# ---------------------------------------------------------------------------

class TestStreamlitEntrypointConvergence:
    """正式入口、产品实现和历史兼容模块应各自保持单一职责。"""

    def test_phase2_app_has_no_main_guard(self):
        """兼容模块不应成为另一个可执行入口。"""
        source = (ROOT / "frontend" / "phase2_app.py").read_text(encoding="utf-8")
        assert '__name__ == "__main__"' not in source
        assert "__name__ == '__main__'" not in source

    def test_product_and_compatibility_modules_share_main(self):
        """兼容导入应解析到正式产品入口，而不是复制实现。"""
        from frontend.phase2_app import main as compatibility_main
        from frontend.product_app import main as product_main

        assert compatibility_main is product_main

    def test_streamlit_app_exports_product_main(self):
        """正式 Streamlit 入口应直接委托给产品模块。"""
        from frontend.product_app import main as product_main
        from frontend.streamlit_app import main as streamlit_main

        assert streamlit_main is product_main
    def test_streamlit_app_has_main_guard(self):
        """streamlit_app.py 保留 __name__ == '__main__' 块作为正式入口。"""
        source = (ROOT / "frontend" / "streamlit_app.py").read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in source
