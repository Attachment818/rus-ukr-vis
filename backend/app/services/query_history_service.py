from __future__ import annotations

from app.database import get_database


def save_query_history(
    workspace_id: int,
    question: str,
    mode: str,
    answer: str,
) -> None:
    with get_database().session() as conn:
        conn.execute(
            """
            INSERT INTO query_history (workspace_id, query_text, query_mode, answer_text)
            VALUES (?, ?, ?, ?)
            """,
            (workspace_id, question[:4000], mode[:100], answer[:50000]),
        )


def list_query_history(
    workspace_id: int,
    limit: int = 20,
    offset: int = 0,
    keyword: str | None = None,
) -> list[dict]:
    clauses = ["workspace_id = ?"]
    params: list[object] = [workspace_id]
    if keyword:
        kw = f"%{keyword.lower()}%"
        clauses.append("(LOWER(query_text) LIKE ? OR LOWER(answer_text) LIKE ?)")
        params.extend([kw, kw])
    where = " WHERE " + " AND ".join(clauses)
    with get_database().session() as conn:
        rows = conn.execute(
            f"""
            SELECT id, query_text, query_mode, answer_text,
                   CAST(created_at AS CHAR) AS created_at
            FROM query_history
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


def count_query_history(
    workspace_id: int,
    keyword: str | None = None,
) -> int:
    clauses = ["workspace_id = ?"]
    params: list[object] = [workspace_id]
    if keyword:
        kw = f"%{keyword.lower()}%"
        clauses.append("(LOWER(query_text) LIKE ? OR LOWER(answer_text) LIKE ?)")
        params.extend([kw, kw])
    where = " WHERE " + " AND ".join(clauses)
    with get_database().session() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM query_history
            {where}
            """,
            params,
        ).fetchone()
    return int(row["c"]) if row else 0
