from __future__ import annotations

from functools import lru_cache

from app.database import get_database

MACRO_WORKSPACE_NAME = "默认基础事件数据"
MACRO_WORKSPACE_THEME = "default-structured-events"
LEGACY_MACRO_WORKSPACE_NAME = "俄乌冲突宏观数据"


@lru_cache(maxsize=1)
def get_macro_workspace_id() -> int:
    db = get_database()
    with db.session() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM workspaces
            WHERE theme = ? OR name IN (?, ?)
            ORDER BY CASE WHEN theme = ? THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (MACRO_WORKSPACE_THEME, MACRO_WORKSPACE_NAME, LEGACY_MACRO_WORKSPACE_NAME, MACRO_WORKSPACE_THEME),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE workspaces
                SET name = ?, description = ?, theme = ?
                WHERE id = ?
                """,
                (
                    MACRO_WORKSPACE_NAME,
                    "默认结构化事件数据工作区，可由 ACLED 等公开数据适配器填充",
                    MACRO_WORKSPACE_THEME,
                    int(row["id"]),
                ),
            )
            return int(row["id"])
        conn.execute(
            """
            INSERT INTO workspaces (name, description, theme)
            VALUES (?, ?, ?)
            """,
            (
                MACRO_WORKSPACE_NAME,
                "默认结构化事件数据工作区，可由 ACLED 等公开数据适配器填充",
                MACRO_WORKSPACE_THEME,
            ),
        )
        return int(conn.lastrowid)
