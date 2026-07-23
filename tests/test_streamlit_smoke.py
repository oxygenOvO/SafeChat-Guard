from pathlib import Path

import pytest


streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest


def test_primary_streamlit_app_starts_without_exception():
    app_path = Path(__file__).resolve().parents[1] / "frontend/streamlit_app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)

    app.run()

    assert len(app.exception) == 0
