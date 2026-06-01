from __future__ import annotations

import logging
import re
import threading
import time
from functools import lru_cache
from typing import Any

import pandas as pd
from pymysql.err import OperationalError

from app.config import get_settings
from app.database import get_database
from app.services.workspace_bootstrap import get_macro_workspace_id

logger = logging.getLogger(__name__)
_import_lock = threading.Lock()


class WeiboStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.ru_path = self.settings.ru_dataset_path

    def _workspace_id(self) -> int:
        return get_macro_workspace_id()

    def is_imported(self) -> bool:
        db = get_database()
        with db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM public_opinion_posts WHERE workspace_id = ?",
                (self._workspace_id(),),
            ).fetchone()
            return bool(row and int(row["c"]) > 0)

    def count(self) -> int:
        db = get_database()
        with db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM public_opinion_posts WHERE workspace_id = ?",
                (self._workspace_id(),),
            ).fetchone()
            return int(row["c"]) if row else 0

    def _insert_batch(self, records: list[dict[str, Any]], max_retries: int = 5) -> None:
        sql = """
            INSERT INTO public_opinion_posts (
                workspace_id, row_index, created_at_raw, msg_id, text, text_length,
                source_device, reposts_count, comments_count, attitudes_count,
                screen_name, user_id
            ) VALUES (
                %(workspace_id)s, %(row_index)s, %(created_at_raw)s, %(msg_id)s, %(text)s,
                %(text_length)s, %(source_device)s, %(reposts_count)s, %(comments_count)s,
                %(attitudes_count)s, %(screen_name)s, %(user_id)s
            )
            ON DUPLICATE KEY UPDATE
                text = VALUES(text),
                screen_name = VALUES(screen_name),
                attitudes_count = VALUES(attitudes_count)
        """
        for attempt in range(max_retries):
            try:
                with get_database().session() as conn:
                    conn.executemany(sql, records)
                return
            except OperationalError as exc:
                if exc.args and exc.args[0] == 1213 and attempt < max_retries - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise

    def import_from_csv(self, batch_size: int = 3000) -> int:
        if not self.ru_path.exists():
            raise FileNotFoundError(f"微博数据文件不存在: {self.ru_path}")

        workspace_id = self._workspace_id()
        with get_database().session() as conn:
            conn.execute(
                "DELETE FROM public_opinion_posts WHERE workspace_id = ?",
                (workspace_id,),
            )

        total = 0
        for chunk in pd.read_csv(
            self.ru_path,
            chunksize=batch_size,
            dtype={"msg_id": str},
            low_memory=False,
        ):
            records: list[dict[str, Any]] = []
            for row in chunk.to_dict(orient="records"):
                msg_id = str(row.get("msg_id") or "").strip()
                if not msg_id or msg_id == "nan":
                    continue
                text = str(row.get("text") or "")
                records.append(
                    {
                        "workspace_id": workspace_id,
                        "row_index": int(row.get("index") or 0),
                        "created_at_raw": str(row.get("created_at") or "")[:100] or None,
                        "msg_id": msg_id,
                        "text": text,
                        "text_length": len(text),
                        "source_device": str(row.get("source") or "")[:255] or None,
                        "reposts_count": _safe_int(row.get("reposts_count")),
                        "comments_count": _safe_int(row.get("comments_count")),
                        "attitudes_count": _safe_int(row.get("attitudes_count")),
                        "screen_name": str(row.get("screen_name") or "")[:255] or None,
                        "user_id": str(row.get("user_id") or "")[:50] or None,
                    }
                )
            if records:
                self._insert_batch(records)
                total += len(records)
                logger.info("已导入微博 %s 条", total)
        return total

    def ensure_imported(self, force: bool = False) -> int:
        if not force and self.is_imported():
            return self.count()
        with _import_lock:
            if not force and self.is_imported():
                return self.count()
            return self.import_from_csv()

    def list_posts(self, limit: int = 100, offset: int = 0, keyword: str | None = None) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []
        clauses = ["workspace_id = ?"]
        params: list[Any] = [self._workspace_id()]
        if keyword:
            clauses.append("(LOWER(text) LIKE ? OR LOWER(screen_name) LIKE ?)")
            kw = f"%{keyword.lower()}%"
            params.extend([kw, kw])
        where = " WHERE " + " AND ".join(clauses)
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT row_index AS `index`, created_at_raw AS created_at, msg_id,
                       text, screen_name, source_device AS source,
                       reposts_count, comments_count, attitudes_count
                FROM public_opinion_posts
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return [dict(row) for row in rows]

    def count_posts(self, keyword: str | None = None) -> int:
        if not self.is_imported():
            return 0
        clauses = ["workspace_id = ?"]
        params: list[Any] = [self._workspace_id()]
        if keyword:
            clauses.append("(LOWER(text) LIKE ? OR LOWER(screen_name) LIKE ? OR LOWER(source_device) LIKE ?)")
            kw = f"%{keyword.lower()}%"
            params.extend([kw, kw, kw])
        where = " WHERE " + " AND ".join(clauses)
        with get_database().session() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM public_opinion_posts
                {where}
                """,
                params,
            ).fetchone()
        return int(row["c"]) if row else 0

    def search_posts(self, question: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = [t for t in re.split(r"\s+", question.replace("，", " ")) if len(t) >= 2]
        keyword = terms[0] if terms else question[:12]
        return self.list_posts(limit=limit, keyword=keyword)


def _safe_int(value: object) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


@lru_cache(maxsize=1)
def get_weibo_store() -> WeiboStore:
    return WeiboStore()
