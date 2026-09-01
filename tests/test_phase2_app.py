from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "streamlit_app.py"


def load_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    return app


def rendered_text(app: AppTest) -> str:
    return " ".join(
        str(item.value)
        for collection in (app.markdown, app.caption, app.info, app.error)
        for item in collection
    )


def test_phase2_navigation_starts_with_focused_safe_chat():
    app = load_app()

    assert app.radio[0].value == "安全对话"
    assert len(app.chat_input) == 1
    assert app.selectbox[0].value == "mock"
    assert "Security Operations" in rendered_text(app)


def test_dashboard_uses_runtime_data_and_has_honest_empty_state_or_rows():
    app = load_app()
    app.radio[0].set_value("系统总览").run()

    text = rendered_text(app)
    assert not app.exception
    assert "系统总览" in text
    assert len(app.metric) == 6
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
        app.radio[0].set_value(page).run()
        assert not app.exception
        assert expected in rendered_text(app)


def test_navigation_preserves_chat_session_state():
    app = load_app()
    app.chat_input[0].set_value("普通学习讨论").run()
    assert len(app.session_state["chat_messages"]) == 2

    app.radio[0].set_value("系统总览").run()
    app.radio[0].set_value("安全对话").run()

    assert not app.exception
    assert len(app.session_state["chat_messages"]) == 2
    assert len(app.chat_message) == 2
