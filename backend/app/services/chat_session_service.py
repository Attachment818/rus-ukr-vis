from __future__ import annotations

import json
from typing import Any

from app.database import get_database
from app.schemas.responses import QASource
from app.services.workspace_bootstrap import get_macro_workspace_id


def _dt_iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _session_title(text: str | None) -> str:
    value = " ".join((text or "").split())
    if not value:
        return "新的研判会话"
    return value[:60]


def _sources_to_json(sources: list[QASource] | None) -> str | None:
    if not sources:
        return None
    payload: list[dict[str, Any]] = []
    for source in sources:
        if hasattr(source, "model_dump"):
            payload.append(source.model_dump())
        else:
            payload.append(dict(source))
    return json.dumps(payload, ensure_ascii=False)


def _sources_from_json(value: str | None) -> list[QASource]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    sources: list[QASource] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            sources.append(QASource(**item))
        except Exception:
            continue
    return sources


def _row_to_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "status": row.get("status") or "active",
        "created_at": _dt_iso(row.get("created_at")),
        "updated_at": _dt_iso(row.get("updated_at")),
    }


def _row_to_message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "session_id": int(row["session_id"]),
        "role": row["role"],
        "content": row["content"],
        "sources": _sources_from_json(row.get("sources_json")),
        "created_at": _dt_iso(row.get("created_at")),
    }


def create_session(title: str | None = None, workspace_id: int | None = None) -> dict[str, Any]:
    resolved_workspace_id = workspace_id or get_macro_workspace_id()
    with get_database().session() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (workspace_id, title)
            VALUES (?, ?)
            """,
            (resolved_workspace_id, _session_title(title)),
        )
        row = conn.execute(
            """
            SELECT id, title, status, created_at, updated_at
            FROM chat_sessions
            WHERE id = ?
            """,
            (conn.lastrowid,),
        ).fetchone()
    if row is None:
        raise ValueError("会话创建失败。")
    return _row_to_session(row)


def get_session(session_id: int) -> dict[str, Any]:
    with get_database().session() as conn:
        row = conn.execute(
            """
            SELECT id, title, status, created_at, updated_at
            FROM chat_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        raise ValueError("会话不存在。")
    return _row_to_session(row)


def list_sessions(limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
    workspace_id = get_macro_workspace_id()
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT id, title, status, created_at, updated_at
            FROM chat_sessions
            WHERE workspace_id = ? AND status = 'active'
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (workspace_id, limit, offset),
        ).fetchall()
    return [_row_to_session(dict(row)) for row in rows]


def list_messages(session_id: int) -> list[dict[str, Any]]:
    get_session(session_id)
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, sources_json, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
    return [_row_to_message(dict(row)) for row in rows]


def add_message(
    session_id: int,
    role: str,
    content: str,
    sources: list[QASource] | None = None,
) -> dict[str, Any]:
    if role not in {"user", "assistant"}:
        raise ValueError("消息角色无效。")
    get_session(session_id)
    with get_database().session() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, sources_json)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, _sources_to_json(sources)),
        )
        message_id = conn.lastrowid
        conn.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )
        row = conn.execute(
            """
            SELECT id, session_id, role, content, sources_json, created_at
            FROM chat_messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
    if row is None:
        raise ValueError("消息保存失败。")
    return _row_to_message(row)


def rename_session_from_question(session_id: int, question: str) -> dict[str, Any]:
    title = _session_title(question)
    with get_database().session() as conn:
        conn.execute(
            """
            UPDATE chat_sessions
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, session_id),
        )
    return get_session(session_id)
