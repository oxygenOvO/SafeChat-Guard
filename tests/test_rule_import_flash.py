import frontend.streamlit_app as frontend_app


def test_rule_import_success_survives_rerun_and_is_shown_once(monkeypatch):
    session_state = {"rule_import_success": "文件批量导入成功"}
    monkeypatch.setattr(frontend_app.st, "session_state", session_state)

    assert frontend_app.pop_rule_import_success() == "文件批量导入成功"
    assert "rule_import_success" not in session_state
    assert frontend_app.pop_rule_import_success() is None
