from __future__ import annotations

import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class LocalVectorStore:
    """Small local vector database for document chunks.

    The project can later swap this for Qdrant, Milvus, Chroma, or pgvector.
    Keeping the interface here lets the rest of the backend already use a
    vector-store boundary instead of querying MySQL JSON blobs directly.
    """

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "vector_store.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    text_preview TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chunk_id, model)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_vectors_document ON chunk_vectors(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_vectors_model ON chunk_vectors(model)")

    def upsert(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        rows = [
            (
                int(record["document_id"]),
                int(record["chunk_id"]),
                str(record["model"]),
                int(record["dimension"]),
                json.dumps(record["vector"], separators=(",", ":")),
                str(record.get("text_preview") or "")[:500],
            )
            for record in records
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO chunk_vectors (
                    document_id, chunk_id, model, dimension, vector_json, text_preview
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, model) DO UPDATE SET
                    document_id = excluded.document_id,
                    dimension = excluded.dimension,
                    vector_json = excluded.vector_json,
                    text_preview = excluded.text_preview,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
        return len(rows)

    def delete_document(self, document_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunk_vectors WHERE document_id = ?", (document_id,))

    def count_document(self, document_id: int, model: str | None = None) -> int:
        with self._connect() as conn:
            if model:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM chunk_vectors WHERE document_id = ? AND model = ?",
                    (document_id, model),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM chunk_vectors WHERE document_id = ?",
                    (document_id,),
                ).fetchone()
        return int(row["c"]) if row else 0

    def rank_chunks(
        self,
        query_vector: list[float],
        chunk_ids: list[int],
        model: str,
        top_k: int = 8,
    ) -> list[tuple[int, float]]:
        if not query_vector or not chunk_ids:
            return []
        placeholders = ", ".join(["?"] * len(chunk_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, vector_json
                FROM chunk_vectors
                WHERE chunk_id IN ({placeholders}) AND model = ?
                """,
                [*chunk_ids, model],
            ).fetchall()
        ranked: list[tuple[int, float]] = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(vector, list):
                score = _cosine_similarity(query_vector, [float(x) for x in vector])
                ranked.append((int(row["chunk_id"]), score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:top_k]


@lru_cache(maxsize=1)
def get_vector_store() -> LocalVectorStore:
    return LocalVectorStore()
