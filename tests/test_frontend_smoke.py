from __future__ import annotations

from pathlib import Path

import pandas as pd

import frontend.streamlit_app as frontend_app


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
