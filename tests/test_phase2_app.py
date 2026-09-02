from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import frontend.chat_app as chat_app
import frontend.phase2_app as phase2_app

from safechat_guard.model_registry import ModelRegistry

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "streamlit_app.py"


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep AppTest independent from the user's local runtime provider state."""
    monkeypatch.delenv("NSCC_MAAS_API_KEY", raising=False)
    monkeypatch.setattr(chat_app, "MODEL_STATE_PATH", tmp_path / "model_registry.json")
    chat_app.get_model_registry.clear()
    chat_app.get_chat_adapter.clear()
    phase2_app.get_operations_pipeline.clear()
    yield
    chat_app.get_model_registry.clear()
    chat_app.get_chat_adapter.clear()
    phase2_app.get_operations_pipeline.clear()


def load_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    return app


def rendered_text(app: AppTest) -> str:
    return " ".join(
        str(item.value)
        for collection in (app.markdown, app.caption, app.info, app.error)
        for item in collection
    )


def click_nav(app: AppTest, label: str) -> AppTest:
    button = next(item for item in app.button if item.label == label)
    button.click().run()
    return app


def test_phase2_navigation_starts_with_focused_safe_chat():
    app = load_app()

    assert not app.radio
    assert app.session_state["active_page"] == "安全对话"
    nav_labels = {item.label for item in app.button}
    assert {"安全对话", "系统总览", "模型管理", "安全策略", "安全日志", "风险统计", "安全评测", "系统状态", "系统设置"} <= nav_labels
    assert len(app.chat_input) == 1
    assert app.selectbox[0].value == "mock"
    assert "SECURITY OPS" in rendered_text(app)
    assert 'data-ui="sidebar-status"' in rendered_text(app)


def test_dashboard_uses_runtime_data_and_has_honest_empty_state_or_rows():
    app = load_app()
    click_nav(app, "系统总览")

    text = rendered_text(app)
    assert not app.exception
    assert "系统总览" in text
    assert text.count('data-ui="kpi-card"') == 6
    assert "成功率" not in text
    assert "+12.8%" not in text


def test_model_logs_analytics_health_and_settings_pages_start_without_traceback():
    app = load_app()
    for page, expected in (
        ("模型管理", "模型管理"),
        ("安全日志", "安全日志"),
        ("风险统计", "风险统计"),
        ("系统状态", "系统状态"),
        ("系统设置", "SafeChat-Guard V1.0"),
    ):
        click_nav(app, page)
        assert not app.exception
        assert expected in rendered_text(app)


def test_phase3_policy_and_evaluation_pages_start_without_traceback():
    app = load_app()
    for page, expected in (("安全策略", "安全策略中心"), ("安全评测", "安全评测实验室")):
        click_nav(app, page)
        assert not app.exception
        assert expected in rendered_text(app)


def test_model_management_shows_nscc_qwen35_metadata_and_missing_key():
    app = load_app()
    click_nav(app, "模型管理")

    text = rendered_text(app)
    assert not app.exception
    assert "Offline Mock" in text
    assert "Qwen3.5" in text
    assert "NSCC-CS MaaS" in text
    assert "DeepSeek" in text
    assert "未配置" in text


def test_nscc_qwen35_mock_401_is_shown_as_authentication_failure(monkeypatch):
    def authentication_failure(self, provider):
        assert provider == "nscc_qwen"
        return {
            "provider": provider,
            "status": "authentication_failed",
            "checked_at": "2026-09-01T00:00:00+00:00",
            "latency_ms": 12,
        }

    monkeypatch.setattr(ModelRegistry, "test_connection", authentication_failure)
    app = load_app()
    click_nav(app, "模型管理")
    app.selectbox[0].select("nscc_qwen").run()
    test_button = next(item for item in app.button if item.label == "测试连接")
    test_button.click().run()

    assert not app.exception
    assert "认证失败，请检查 API Key 配置" in rendered_text(app)


def test_navigation_preserves_chat_session_state():
    app = load_app()
    app.chat_input[0].set_value("普通学习讨论").run()
    assert len(app.session_state["chat_messages"]) == 2

    click_nav(app, "系统总览")
    click_nav(app, "安全对话")

    assert not app.exception
    assert len(app.session_state["chat_messages"]) == 2
    assert len(app.chat_message) == 2
