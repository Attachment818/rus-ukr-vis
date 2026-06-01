from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from app.database import get_database
from app.services.llm_client import require_embedding_client
from app.services.vector_store import get_vector_store


def _normalize_text(text: str, max_chars: int = 1800) -> str:
    return " ".join((text or "").split())[:max_chars]


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


class EmbeddingService:
    def _embed_texts(self, texts: list[str]) -> tuple[str, list[list[float]]]:
        client, model = require_embedding_client()
        response = client.embeddings.create(
            model=model,
            input=texts,
        )
        vectors = [list(item.embedding) for item in response.data]
        return model, vectors

    def document_status(self, document_id: int) -> dict[str, Any]:
        with get_database().session() as conn:
            chunks = conn.execute(
                "SELECT COUNT(*) AS c FROM document_chunks WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            indexed = conn.execute(
                "SELECT COUNT(*) AS c, MAX(model) AS model, MAX(dimension) AS dimension FROM chunk_embeddings WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        chunk_count = int(chunks["c"]) if chunks else 0
        indexed_count = int(indexed["c"]) if indexed else 0
        model_name = indexed.get("model") if indexed else None
        vector_store = get_vector_store()
        vector_indexed_count = vector_store.count_document(document_id, str(model_name) if model_name else None)
        return {
            "document_id": document_id,
            "chunk_count": chunk_count,
            "indexed_count": indexed_count,
            "vector_indexed_count": vector_indexed_count,
            "model": model_name,
            "dimension": indexed.get("dimension") if indexed else None,
            "vector_store": str(vector_store.path),
            "ready": chunk_count > 0 and indexed_count >= chunk_count and vector_indexed_count >= chunk_count,
        }

    def index_document(self, document_id: int, batch_size: int = 24, force: bool = False) -> dict[str, Any]:
        db = get_database()
        with db.session() as conn:
            document = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
            if document is None:
                raise ValueError("文档不存在。")
            rows = conn.execute(
                """
                SELECT id AS chunk_id, text
                FROM document_chunks
                WHERE document_id = ?
                ORDER BY chunk_index
                """,
                (document_id,),
            ).fetchall()
        if not rows:
            raise ValueError("该文档没有可索引的 chunk，请先上传并解析文档。")

        _, active_model = require_embedding_client()
        vector_store = get_vector_store()
        vector_ready = vector_store.count_document(document_id, active_model) >= len(rows)
        if force:
            with db.session() as conn:
                conn.execute("DELETE FROM chunk_embeddings WHERE document_id = ?", (document_id,))
            vector_store.delete_document(document_id)

        inserted = 0
        skipped = 0
        model_used: str | None = None
        dimension = 0
        pending: list[dict[str, Any]] = []
        for row in rows:
            text = _normalize_text(row.get("text") or "")
            if not text:
                skipped += 1
                continue
            if not force:
                with db.session() as conn:
                    exists = conn.execute(
                        "SELECT id FROM chunk_embeddings WHERE chunk_id = ? AND model = ? LIMIT 1",
                        (row["chunk_id"], active_model),
                    ).fetchone()
                if exists and vector_ready:
                    skipped += 1
                    continue
            pending.append({"chunk_id": int(row["chunk_id"]), "text": text})

        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            model, vectors = self._embed_texts([item["text"] for item in batch])
            model_used = model
            if vectors:
                dimension = len(vectors[0])
            records = [
                (
                    document_id,
                    item["chunk_id"],
                    model,
                    len(vector),
                    json.dumps(vector, separators=(",", ":")),
                )
                for item, vector in zip(batch, vectors)
            ]
            vector_records = [
                {
                    "document_id": document_id,
                    "chunk_id": item["chunk_id"],
                    "model": model,
                    "dimension": len(vector),
                    "vector": vector,
                    "text_preview": item["text"],
                }
                for item, vector in zip(batch, vectors)
            ]
            with db.session() as conn:
                conn.executemany(
                    """
                    INSERT INTO chunk_embeddings (document_id, chunk_id, model, dimension, embedding_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        dimension = VALUES(dimension),
                        embedding_json = VALUES(embedding_json),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    records,
                )
            vector_store.upsert(vector_records)
            inserted += len(records)

        status = self.document_status(document_id)
        return {
            "document_id": document_id,
            "model": model_used or status.get("model"),
            "dimension": dimension or status.get("dimension") or 0,
            "indexed": inserted,
            "skipped": skipped,
            "total_chunks": len(rows),
            "vector_indexed": status.get("vector_indexed_count", 0),
            "vector_store": status.get("vector_store"),
            "ready": status["ready"],
            "message": "文档向量索引已生成，可用于语义检索。",
        }

    def rank_chunks(self, question: str, chunk_ids: list[int], top_k: int = 8) -> list[tuple[int, float]]:
        if not question.strip() or not chunk_ids:
            return []
        client, model = require_embedding_client()
        query_response = client.embeddings.create(
            model=model,
            input=[_normalize_text(question, max_chars=800)],
        )
        query_vector = list(query_response.data[0].embedding)
        vector_ranked = get_vector_store().rank_chunks(query_vector, chunk_ids, model, top_k=top_k)
        if vector_ranked:
            return vector_ranked
        placeholders = ", ".join(["?"] * len(chunk_ids))
        with get_database().session() as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, embedding_json
                FROM chunk_embeddings
                WHERE chunk_id IN ({placeholders}) AND model = ?
                """,
                [*chunk_ids, model],
            ).fetchall()
        ranked: list[tuple[int, float]] = []
        for row in rows:
            try:
                vector = json.loads(row["embedding_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(vector, list):
                score = _cosine_similarity(query_vector, [float(x) for x in vector])
                ranked.append((int(row["chunk_id"]), score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:top_k]


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
