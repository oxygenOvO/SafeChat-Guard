"""本地聊天会话持久化（产品版会话管理的数据层）。

所有会话保存在单个被 Git 忽略的 JSON 文件（``data/runtime/chat_sessions.json``）
中，对话记录因此不会进入版本库，也不会进入脱敏审计日志。

能力：
- 创建 / 列表（按最近更新倒序）/ 加载 / 保存 / 删除会话；
- 每次保存自动刷新 updated_at 并从首条用户消息派生标题；
- 消息白名单清洗：只持久化 user/assistant 消息及其脱敏后的展示结果，
  非法条目直接丢弃；
- 容量上限：最多 MAX_SESSIONS 个会话、单会话 MAX_MESSAGES_PER_SESSION 条消息；
- 原子写入（临时文件 + fsync + os.replace），文件损坏/格式非法时
  自动降级为空存储，保证前端永不因历史文件而崩溃。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("safechat.frontend")

MAX_SESSIONS = 100
MAX_MESSAGES_PER_SESSION = 200
MAX_TITLE_CHARS = 24


class ChatSessionStore:
    """Create, list, load, save and delete local chat sessions atomically."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list_sessions(self) -> list[dict[str, Any]]:
        """全部会话按最近更新倒序（最新聊天的会话排在最前）。"""
        with self._lock:
            sessions = self._read().get("sessions", [])
            return sorted(
                sessions,
                key=lambda item: str(item.get("updated_at") or ""),
                reverse=True,
            )

    def create_session(self, *, provider: str = "mock") -> dict[str, Any]:
        """新建空会话并立即持久化（标题暂为"新的对话"，首条消息后自动更新）。"""
        with self._lock:
            session = {
                "id": uuid.uuid4().hex,
                "title": "新的对话",
                "provider": provider,
                "created_at": self._now(),
                "updated_at": self._now(),
                "messages": [],
            }
            state = self._read()
            sessions = state.setdefault("sessions", [])
            sessions.append(session)
            self._write(state)
            return dict(session)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """按 id 加载会话（含全部消息）；不存在返回 None。"""
        with self._lock:
            return next(
                (
                    dict(item)
                    for item in self._read().get("sessions", [])
                    if item.get("id") == session_id
                ),
                None,
            )

    def save_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        provider: str,
    ) -> None:
        """保存会话：消息白名单清洗 + 刷新 updated_at + 重派生标题。

        每次对话后调用即可实现"最新变化的会话自动置顶"。
        会话不存在时自动创建。
        """
        with self._lock:
            state = self._read()
            sessions = state.setdefault("sessions", [])
            target = next(
                (item for item in sessions if item.get("id") == session_id), None
            )
            safe_messages = self._sanitize_messages(messages)
            if target is None:
                target = {"id": session_id, "created_at": self._now()}
                sessions.append(target)
            target["messages"] = safe_messages
            target["provider"] = provider
            target["updated_at"] = self._now()
            target["title"] = self._derive_title(safe_messages)
            self._write(state)

    def delete_session(self, session_id: str) -> bool:
        """删除会话；删除成功返回 True，id 不存在返回 False。"""
        with self._lock:
            state = self._read()
            sessions = state.get("sessions", [])
            remaining = [item for item in sessions if item.get("id") != session_id]
            if len(remaining) == len(sessions):
                return False
            state["sessions"] = remaining
            self._write(state)
            return True

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _derive_title(messages: list[dict[str, Any]]) -> str:
        """从首条用户消息派生会话标题（压缩空白后截断），无用户消息用默认标题。"""
        for item in messages:
            if item.get("role") == "user" and isinstance(item.get("content"), str):
                text = " ".join(item["content"].split())
                if text:
                    return (
                        text[:MAX_TITLE_CHARS] + "…"
                        if len(text) > MAX_TITLE_CHARS
                        else text
                    )
        return "新的对话"

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """消息白名单清洗：仅保留 user/assistant 消息及脱敏展示结果，截断到上限。"""
        safe = []
        for item in messages[-MAX_MESSAGES_PER_SESSION:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            entry: dict[str, Any] = {"role": role, "content": content}
            result = item.get("result")
            if isinstance(result, dict):
                entry["result"] = result
            safe.append(entry)
        return safe

    def _read(self) -> dict[str, Any]:
        """读取存储文件；缺失/损坏/格式非法降级为空存储，超量时裁剪最旧会话。"""
        if not self.path.exists():
            return {"version": 1, "sessions": []}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("chat session store unavailable: %s", exc)
            return {"version": 1, "sessions": []}
        if not isinstance(state, dict) or not isinstance(
            state.get("sessions"), list
        ):
            return {"version": 1, "sessions": []}
        if len(state["sessions"]) > MAX_SESSIONS:
            state["sessions"] = sorted(
                state["sessions"],
                key=lambda item: str(item.get("updated_at") or ""),
                reverse=True,
            )[:MAX_SESSIONS]
        return state

    def _write(self, state: dict[str, Any]) -> None:
        """原子写入（临时文件 + fsync + os.replace）；失败仅告警，保留旧文件。"""
        state = {"version": 1, **state}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".chat-sessions-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            LOGGER.warning("chat sessions could not be saved: %s", exc)
