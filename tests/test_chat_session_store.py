from __future__ import annotations

import json

from frontend.session_store import (
    MAX_MESSAGES_PER_SESSION,
    MAX_SESSIONS,
    ChatSessionStore,
)


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": text, "result": {"action": "pass"}}


def test_create_list_and_load_roundtrip(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")

    session = store.create_session(provider="mock")
    assert session["title"] == "新的对话"
    assert store.list_sessions()[0]["id"] == session["id"]

    messages = [_user("你好"), _assistant("你好！")]
    store.save_session(session["id"], messages, provider="deepseek")

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["provider"] == "deepseek"
    assert sessions[0]["title"] == "你好"

    loaded = store.load_session(session["id"])
    assert loaded is not None
    assert loaded["messages"][0] == _user("你好")
    assert loaded["messages"][1]["result"] == {"action": "pass"}


def test_list_sessions_sorted_by_updated_at_desc(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    first = store.create_session(provider="mock")
    second = store.create_session(provider="mock")

    store.save_session(first["id"], [_user("最早")], provider="mock")
    store.save_session(second["id"], [_user("最新")], provider="mock")

    titles = [item["title"] for item in store.list_sessions()]
    assert titles == ["最新", "最早"]


def test_delete_session(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    session = store.create_session(provider="mock")
    store.save_session(session["id"], [_user("x")], provider="mock")

    assert store.delete_session(session["id"]) is True
    assert store.list_sessions() == []
    assert store.delete_session(session["id"]) is False


def test_title_falls_back_when_no_user_message(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    session = store.create_session(provider="mock")

    store.save_session(session["id"], [_assistant("只有回复")], provider="mock")
    assert store.load_session(session["id"])["title"] == "新的对话"


def test_long_title_is_truncated(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    session = store.create_session(provider="mock")

    store.save_session(session["id"], [_user("一" * 50)], provider="mock")
    title = store.load_session(session["id"])["title"]
    assert len(title) == 25
    assert title.endswith("…")


def test_invalid_messages_are_dropped(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    session = store.create_session(provider="mock")
    messages = [
        {"role": "system", "content": "evil"},
        {"role": "user"},
        "not-a-dict",
        _user("正常消息"),
    ]

    store.save_session(session["id"], messages, provider="mock")
    stored = store.load_session(session["id"])["messages"]

    assert stored == [_user("正常消息")]


def test_message_history_is_capped(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    session = store.create_session(provider="mock")
    messages = [
        _user(f"消息{i}") if i % 2 == 0 else _assistant(f"回复{i}")
        for i in range(MAX_MESSAGES_PER_SESSION + 50)
    ]

    store.save_session(session["id"], messages, provider="mock")
    stored = store.load_session(session["id"])["messages"]

    assert len(stored) == MAX_MESSAGES_PER_SESSION
    assert stored[-1]["content"].startswith("回复")


def test_session_count_is_capped(tmp_path):
    store = ChatSessionStore(tmp_path / "chat_sessions.json")
    for _ in range(MAX_SESSIONS + 10):
        session = store.create_session(provider="mock")
        store.save_session(session["id"], [_user("x")], provider="mock")

    assert len(store.list_sessions()) == MAX_SESSIONS


def test_corrupted_store_recovers_to_empty(tmp_path):
    path = tmp_path / "chat_sessions.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = ChatSessionStore(path)

    assert store.list_sessions() == []
    session = store.create_session(provider="mock")
    store.save_session(session["id"], [_user("恢复")], provider="mock")

    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["version"] == 1
    assert len(state["sessions"]) == 1


def test_non_object_store_recovers_to_empty(tmp_path):
    path = tmp_path / "chat_sessions.json"
    path.write_text('[{"id": "legacy"}]', encoding="utf-8")
    store = ChatSessionStore(path)

    assert store.list_sessions() == []
