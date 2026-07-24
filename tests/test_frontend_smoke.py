from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

import frontend.streamlit_app as frontend_app
from frontend.adapter import FrontendPipelineAdapter
from safechat_guard.pipeline import SafeChatPipeline


@pytest.fixture
def no_real_llm_adapter(monkeypatch):
    pipeline = SafeChatPipeline.from_config(str(frontend_app.PROJECT_ROOT / "config.yaml"))

    def forbidden(message):
        raise AssertionError("display and batch paths must not call the real LLM")

    monkeypatch.setattr(pipeline.llm, "chat", forbidden)
    adapter = FrontendPipelineAdapter(pipeline)
    monkeypatch.setattr(frontend_app, "get_adapter", lambda: adapter)
    return adapter


def minimal_case(**overrides):
    row = {
        "input_text": "普通输入",
        "expected_category": "normal",
        "expected_action": "pass",
        "expected_output_action": "pass",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def fake_pipeline_result():
    return {
        "baseline_category": "normal",
        "baseline_action": "pass",
        "category": "normal",
        "risk": "none",
        "action": "pass",
        "semantic_score": 1.0,
        "output_action": "pass",
    }


def test_frontend_module_imports_with_expected_pages():
    assert callable(frontend_app.main)
    assert callable(frontend_app.render_detection_workspace)
    assert callable(frontend_app.render_batch_page)
    assert callable(frontend_app.render_logs_page)


def test_frontend_demo_dataset_is_portable_and_formal():
    path = frontend_app.FRONTEND_CASES
    cases = frontend_app.sample_test_cases()

    assert path == Path(frontend_app.PROJECT_ROOT) / "data" / "test_cases" / "frontend_demo_cases_v2.csv"
    assert isinstance(cases, pd.DataFrame)
    assert not cases.empty
    assert set(cases["expected_category"]) <= {"normal", "ad", "porn", "violence", "sensitive"}
    assert not path.is_absolute() or path.is_relative_to(frontend_app.PROJECT_ROOT)


def test_frontend_source_never_renders_pipeline_raw_reply():
    source = Path(frontend_app.__file__).read_text(encoding="utf-8")

    assert 'result["raw_reply"]' not in source
    assert "模型原始输出</b>" not in source


def test_frontend_init_does_not_call_llm(monkeypatch):
    session_state = MagicMock()
    session_state.__contains__.return_value = False
    monkeypatch.setattr(frontend_app.st, "session_state", session_state)
    monkeypatch.setattr(
        frontend_app,
        "run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("initialization must not run the chat pipeline")
        ),
    )

    frontend_app.init_state()

    assert session_state.last_result is None
    assert session_state.last_run_signature is None


def test_overview_does_not_call_real_llm(no_real_llm_adapter, monkeypatch):
    monkeypatch.setattr(frontend_app.st, "session_state", {})

    result = frontend_app.dashboard_df()

    assert len(result) == len(frontend_app.sample_test_cases())
    assert set(result["action"]) <= {"pass", "sanitize", "block"}


def test_compare_page_uses_deterministic_override(no_real_llm_adapter, monkeypatch):
    captured = []
    original = frontend_app.run_pipeline

    def capture(text, *, raw_reply_override, persist=False):
        captured.append((raw_reply_override, persist))
        return original(
            text,
            raw_reply_override=raw_reply_override,
            persist=persist,
        )

    fake_st = MagicMock()
    fake_st.text_input.return_value = "加 V-X 领取优 惠 券，名额有限"
    monkeypatch.setattr(frontend_app, "st", fake_st)
    monkeypatch.setattr(frontend_app, "render_compare_block", lambda result: None)
    monkeypatch.setattr(frontend_app, "run_pipeline", capture)

    frontend_app.render_compare_page()

    assert captured == [(frontend_app.SAFE_DEMO_REPLY, False)]


def test_rewrite_page_uses_deterministic_override(no_real_llm_adapter, monkeypatch):
    captured = []
    original = frontend_app.run_pipeline

    def capture(text, *, raw_reply_override, persist=False):
        captured.append((raw_reply_override, persist))
        return original(
            text,
            raw_reply_override=raw_reply_override,
            persist=persist,
        )

    fake_st = MagicMock()
    fake_st.text_area.return_value = "想领取课程资料可以加微信私聊。"
    monkeypatch.setattr(frontend_app, "st", fake_st)
    monkeypatch.setattr(frontend_app, "render_rewrite_block", lambda result: None)
    monkeypatch.setattr(frontend_app, "run_pipeline", capture)

    frontend_app.render_rewrite_page()

    assert captured == [(frontend_app.SAFE_DEMO_REPLY, False)]


def test_batch_evaluation_never_calls_real_llm(no_real_llm_adapter):
    result = frontend_app.build_case_results(minimal_case())

    assert len(result) == 1
    assert result.iloc[0]["actual_output_action"] == "pass"
    assert bool(result.iloc[0]["demo_only"]) is True


def test_batch_uses_exact_mock_model_output(monkeypatch):
    exact_output = "  CSV 中的精确模拟输出  "
    captured = []

    def fake_run(text, *, raw_reply_override, persist=False):
        captured.append((raw_reply_override, persist))
        return fake_pipeline_result()

    monkeypatch.setattr(frontend_app, "run_pipeline", fake_run)
    frontend_app.build_case_results(
        minimal_case(mock_model_output=exact_output, demo_only=True)
    )

    assert captured == [(exact_output, False)]


def test_builtin_cases_are_demo_only():
    cases = frontend_app.prepare_case_dataframe(frontend_app.sample_test_cases())

    assert len(cases) == 8
    assert cases["demo_only"].all()


def test_demo_cases_are_not_reported_as_formal_metrics():
    demo_results = pd.DataFrame(
        {
            "demo_only": [True, True],
            "action_match": [True, False],
            "expected_action": ["pass", "block"],
        }
    )

    selected, scope = frontend_app.select_metric_results(demo_results)
    source = Path(frontend_app.__file__).read_text(encoding="utf-8")

    assert scope == "演示"
    assert len(selected) == 2
    assert "内置样例仅用于功能演示，不代表正式独立评估结果。" in source
    assert "正式误判率" not in source
    assert "正式拦截率" not in source


def test_uploaded_csv_missing_required_columns_is_rejected():
    cases = pd.DataFrame({"input_text": ["普通输入"]})

    missing = frontend_app.validate_case_dataframe(cases)

    assert missing == [
        "expected_action",
        "expected_category",
        "expected_output_action",
    ]
    with pytest.raises(ValueError, match="CSV 缺少必需列"):
        frontend_app.prepare_case_dataframe(cases)


def test_uploaded_csv_without_demo_only_defaults_to_demo():
    prepared = frontend_app.prepare_case_dataframe(minimal_case())

    assert "demo_only" in prepared
    assert bool(prepared.iloc[0]["demo_only"]) is True
