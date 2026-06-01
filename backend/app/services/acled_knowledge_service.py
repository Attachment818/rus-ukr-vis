from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Any

from app.database import get_database
from app.schemas.responses import GraphEdge, GraphNode
from app.services.conflict_store import get_conflict_store
from app.services.workspace_bootstrap import get_macro_workspace_id

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()
_derive_job: dict[str, Any] = {
    "status": "idle",
    "message": "尚未启动",
    "processed_events": 0,
    "total_events": 0,
    "entities": 0,
    "event_entity_links": 0,
    "evidences": 0,
    "relations": 0,
    "error": None,
}


class AcledKnowledgeService:
    """Derive a relational knowledge layer from structured ACLED events."""

    def _workspace_id(self) -> int:
        return get_macro_workspace_id()

    def start_rebuild_job(self) -> dict[str, Any]:
        with _job_lock:
            if _derive_job["status"] == "running":
                return dict(_derive_job)
            _derive_job.update(
                {
                    "status": "running",
                    "message": "正在派生 ACLED 知识层",
                    "processed_events": 0,
                    "total_events": get_conflict_store().count(),
                    "entities": 0,
                    "event_entity_links": 0,
                    "evidences": 0,
                    "relations": 0,
                    "error": None,
                }
            )
        worker = threading.Thread(target=self._run_rebuild_job, daemon=True)
        worker.start()
        return dict(_derive_job)

    def job_status(self) -> dict[str, Any]:
        with _job_lock:
            return dict(_derive_job)

    def _run_rebuild_job(self) -> None:
        try:
            result = self.rebuild()
        except Exception as exc:
            logger.exception("ACLED knowledge derivation failed")
            with _job_lock:
                _derive_job.update(
                    {
                        "status": "failed",
                        "message": "ACLED 知识层派生失败",
                        "error": str(exc),
                    }
                )
            return
        with _job_lock:
            _derive_job.update(
                {
                    "status": "completed",
                    "message": "已从 ACLED 事件派生实体、关系、事件链接与证据",
                    "error": None,
                    **result,
                }
            )

    @staticmethod
    def _update_job(**kwargs: Any) -> None:
        with _job_lock:
            _derive_job.update(kwargs)

    def rebuild(self, batch_size: int = 5000) -> dict[str, int]:
        workspace_id = self._workspace_id()
        self._clear_existing(workspace_id)

        entity_cache: dict[tuple[str, str], int] = {}
        counts = {"entities": 0, "event_entity_links": 0, "evidences": 0, "relations": 0}
        last_id = 0
        processed_count = 0
        relation_seen: set[tuple[int, int, str]] = set()

        while True:
            with get_database().session() as conn:
                rows = conn.execute(
                    """
                    SELECT id, event_code, event_date, event_type, sub_event_type,
                           actor1_name, actor1_assoc, actor1_type,
                           actor2_name, actor2_assoc, actor2_type,
                           interaction_type, country, admin1, admin2, admin3,
                           location_name, source_name, notes
                    FROM conflict_events
                    WHERE workspace_id = ? AND id > ?
                    ORDER BY id
                    LIMIT ?
                    """,
                    (workspace_id, last_id, batch_size),
                ).fetchall()
            if not rows:
                break

            links: list[dict[str, Any]] = []
            evidences: list[dict[str, Any]] = []
            relations: list[dict[str, Any]] = []

            with get_database().session() as conn:
                for row in rows:
                    last_id = int(row["id"])
                    event_id = int(row["id"])

                    actor1_id = self._ensure_entity_in_conn(
                        conn,
                        workspace_id,
                        row.get("actor1_name"),
                        "actor",
                        "acled",
                        entity_cache,
                        f"ACLED actor1 type: {row.get('actor1_type') or 'unknown'}",
                    )
                    if actor1_id:
                        links.append(_link(event_id, actor1_id, "actor1"))

                    actor2_id = self._ensure_entity_in_conn(
                        conn,
                        workspace_id,
                        row.get("actor2_name"),
                        "actor",
                        "acled",
                        entity_cache,
                        f"ACLED actor2 type: {row.get('actor2_type') or 'unknown'}",
                    )
                    if actor2_id:
                        links.append(_link(event_id, actor2_id, "actor2"))

                    source_id = self._ensure_entity_in_conn(
                        conn,
                        workspace_id,
                        row.get("source_name"),
                        "organization",
                        "acled",
                        entity_cache,
                        "ACLED source organization",
                    )
                    if source_id:
                        links.append(_link(event_id, source_id, "source"))

                    for value, entity_type, role_type in (
                        (row.get("country"), "country", "country"),
                        (row.get("admin1"), "location", "admin1"),
                        (row.get("admin2"), "location", "admin2"),
                        (row.get("admin3"), "location", "admin3"),
                        (row.get("location_name"), "location", "location"),
                    ):
                        entity_id = self._ensure_entity_in_conn(
                            conn,
                            workspace_id,
                            value,
                            entity_type,
                            "acled",
                            entity_cache,
                            f"ACLED {role_type}",
                        )
                        if entity_id:
                            links.append(_link(event_id, entity_id, role_type))

                    event_type_id = self._ensure_entity_in_conn(
                        conn,
                        workspace_id,
                        row.get("event_type"),
                        "topic",
                        "acled",
                        entity_cache,
                        "ACLED event type",
                    )
                    if event_type_id:
                        links.append(_link(event_id, event_type_id, "event_type"))

                    if row.get("notes"):
                        evidences.append(
                            {
                                "workspace_id": workspace_id,
                                "evidence_type": "acled_note",
                                "event_id": event_id,
                                "quote_text": row["notes"],
                                "source_label": row.get("source_name") or "ACLED",
                            }
                        )

                    relation_type = row.get("interaction_type") or "co_mentioned"
                    if actor1_id and actor2_id and actor1_id != actor2_id:
                        _append_relation(
                            relations,
                            relation_seen,
                            workspace_id,
                            actor1_id,
                            actor2_id,
                            relation_type,
                            _relation_description(row),
                        )
                    location_id = self._entity_lookup(entity_cache, "location", row.get("location_name"))
                    if actor1_id and location_id:
                        _append_relation(
                            relations,
                            relation_seen,
                            workspace_id,
                            actor1_id,
                            location_id,
                            "operates_in",
                            _relation_description(row),
                        )
                    if actor2_id and location_id:
                        _append_relation(
                            relations,
                            relation_seen,
                            workspace_id,
                            actor2_id,
                            location_id,
                            "operates_in",
                            _relation_description(row),
                        )

                counts["event_entity_links"] += self._insert_links_conn(conn, links)
                counts["evidences"] += self._insert_evidences_conn(conn, evidences)
                counts["relations"] += self._insert_relations_conn(conn, relations)
            logger.info("ACLED knowledge derived through conflict_events.id=%s", last_id)
            processed_count += len(rows)
            progress_counts = {**counts, "entities": len(entity_cache)}
            self._update_job(
                processed_events=processed_count,
                **progress_counts,
            )

        counts["entities"] = self._count_entities(workspace_id)
        return counts

    def summary(self) -> dict[str, int]:
        workspace_id = self._workspace_id()
        with get_database().session() as conn:
            entities = conn.execute(
                "SELECT COUNT(*) AS c FROM entities WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            ).fetchone()
            links = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM event_entity_links l
                JOIN conflict_events e ON e.id = l.event_id
                WHERE e.workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()
            evidences = conn.execute(
                "SELECT COUNT(*) AS c FROM evidences WHERE workspace_id = ? AND evidence_type = 'acled_note'",
                (workspace_id,),
            ).fetchone()
            relations = conn.execute(
                "SELECT COUNT(*) AS c FROM relations WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            ).fetchone()
        return {
            "entities": int(entities["c"]) if entities else 0,
            "event_entity_links": int(links["c"]) if links else 0,
            "evidences": int(evidences["c"]) if evidences else 0,
            "relations": int(relations["c"]) if relations else 0,
        }

    def graph(self, limit: int = 160, event_id_cnty: str | None = None) -> dict[str, list[dict[str, Any]]]:
        workspace_id = self._workspace_id()
        node_map: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        def add_node(node_id: str, label: str, node_type: str) -> None:
            if node_id not in node_map:
                node_map[node_id] = GraphNode(id=node_id, label=label, node_type=node_type, chunk_ids=[])

        def add_edge(source: str, target: str, relation_type: str, evidence: str | None = None) -> None:
            key = (source, target, relation_type)
            if key in seen_edges:
                return
            seen_edges.add(key)
            edges.append(GraphEdge(source=source, target=target, relation_type=relation_type, evidence=evidence))

        with get_database().session() as conn:
            if event_id_cnty:
                rows = conn.execute(
                    """
                    SELECT ce.event_code, ce.event_type, ce.event_date,
                           en.id AS entity_id, en.name, en.entity_type, l.role_type, en.description
                    FROM conflict_events ce
                    JOIN event_entity_links l ON l.event_id = ce.id
                    JOIN entities en ON en.id = l.entity_id
                    WHERE ce.workspace_id = ? AND ce.event_code = ?
                    ORDER BY FIELD(l.role_type, 'actor1', 'actor2', 'location', 'source', 'event_type'), en.name
                    LIMIT ?
                    """,
                    (workspace_id, event_id_cnty, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT en.id AS entity_id, en.name, en.entity_type,
                           COUNT(*) AS mention_count,
                           MIN(l.role_type) AS role_type
                    FROM entities en
                    JOIN event_entity_links l ON l.entity_id = en.id
                    JOIN conflict_events ce ON ce.id = l.event_id
                    WHERE en.workspace_id = ? AND en.source_origin = 'acled'
                    GROUP BY en.id, en.name, en.entity_type
                    ORDER BY mention_count DESC
                    LIMIT ?
                    """,
                    (workspace_id, limit),
                ).fetchall()
                relations = conn.execute(
                    """
                    SELECT r.source_entity_id, s.name AS source_name, s.entity_type AS source_type,
                           r.target_entity_id, t.name AS target_name, t.entity_type AS target_type,
                           r.relation_type, r.description
                    FROM relations r
                    JOIN entities s ON s.id = r.source_entity_id
                    JOIN entities t ON t.id = r.target_entity_id
                    WHERE r.workspace_id = ? AND r.source_origin = 'acled'
                    ORDER BY r.id DESC
                    LIMIT ?
                    """,
                    (workspace_id, max(limit * 3, limit)),
                ).fetchall()

        if event_id_cnty:
            event_node_id = f"event::{event_id_cnty}"
            for row in rows:
                add_node(
                    event_node_id,
                    f"{row.get('event_type') or '冲突事件'}\n{event_id_cnty}",
                    "冲突事件",
                )
                entity_node_id = f"entity::{row['entity_id']}"
                add_node(entity_node_id, row["name"], _display_entity_type(row["entity_type"]))
                add_edge(entity_node_id, event_node_id, row["role_type"], row.get("description"))
        else:
            node_cap = max(20, limit)
            for row in relations:
                source_id = int(row["source_entity_id"])
                target_id = int(row["target_entity_id"])
                source_node = f"entity::{source_id}"
                target_node = f"entity::{target_id}"
                source_exists = source_node in node_map
                target_exists = target_node in node_map
                if len(node_map) >= node_cap and not (source_exists or target_exists):
                    continue
                add_node(source_node, row["source_name"], _display_entity_type(row["source_type"]))
                add_node(target_node, row["target_name"], _display_entity_type(row["target_type"]))
                add_edge(source_node, target_node, row["relation_type"], row.get("description"))
                if len(node_map) >= node_cap and len(edges) >= limit:
                    break
            for row in rows:
                if len(node_map) >= node_cap:
                    break
                entity_id = int(row["entity_id"])
                label = f"{row['name']} ({int(row['mention_count'])})"
                add_node(f"entity::{entity_id}", label, _display_entity_type(row["entity_type"]))

        return {
            "nodes": [node.model_dump() for node in node_map.values()],
            "edges": [edge.model_dump() for edge in edges],
        }

    def event_evidence(self, event_id_cnty: str) -> dict[str, Any]:
        event = get_conflict_store().get_event(event_id_cnty)
        if not event:
            return {"event": None, "entities": [], "evidences": [], "graph": {"nodes": [], "edges": []}}

        workspace_id = self._workspace_id()
        with get_database().session() as conn:
            entity_rows = conn.execute(
                """
                SELECT en.id, en.name, en.entity_type, en.description, l.role_type
                FROM conflict_events ce
                JOIN event_entity_links l ON l.event_id = ce.id
                JOIN entities en ON en.id = l.entity_id
                WHERE ce.workspace_id = ? AND ce.event_code = ?
                ORDER BY FIELD(l.role_type, 'actor1', 'actor2', 'location', 'source', 'event_type'), en.name
                LIMIT 80
                """,
                (workspace_id, event_id_cnty),
            ).fetchall()
            evidence_rows = conn.execute(
                """
                SELECT ev.id, ev.evidence_type, ev.quote_text, ev.source_label
                FROM conflict_events ce
                JOIN evidences ev ON ev.event_id = ce.id
                WHERE ce.workspace_id = ? AND ce.event_code = ?
                ORDER BY ev.id
                LIMIT 20
                """,
                (workspace_id, event_id_cnty),
            ).fetchall()

        entities = [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "entity_type": row["entity_type"],
                "role_type": row["role_type"],
                "description": row.get("description"),
            }
            for row in entity_rows
        ]
        evidences = [
            {
                "id": int(row["id"]),
                "evidence_type": row["evidence_type"],
                "quote_text": row.get("quote_text"),
                "source_label": row.get("source_label"),
            }
            for row in evidence_rows
        ]
        return {
            "event": event,
            "entities": entities,
            "evidences": evidences,
            "graph": self.graph(limit=80, event_id_cnty=event_id_cnty),
        }

    def _clear_existing(self, workspace_id: int) -> None:
        with get_database().session() as conn:
            conn.execute(
                """
                DELETE l FROM event_entity_links l
                JOIN conflict_events e ON e.id = l.event_id
                WHERE e.workspace_id = ?
                """,
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM evidences WHERE workspace_id = ? AND evidence_type = 'acled_note'",
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM relations WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM entities WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            )

    def _ensure_entity(
        self,
        workspace_id: int,
        name: object,
        entity_type: str,
        source_origin: str,
        entity_cache: dict[tuple[str, str], int],
        description: str,
    ) -> int | None:
        clean = _clean_name(name)
        if not clean:
            return None
        key = (entity_type, clean.casefold())
        cached = entity_cache.get(key)
        if cached:
            return cached
        with get_database().session() as conn:
            conn.execute(
                """
                INSERT INTO entities (
                    workspace_id, name, normalized_name, entity_type, source_origin, description
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, clean, clean.casefold(), entity_type, source_origin, description),
            )
            entity_id = conn.lastrowid
            if not entity_id:
                row = conn.execute(
                    """
                    SELECT id
                    FROM entities
                    WHERE workspace_id = ? AND normalized_name = ? AND entity_type = ? AND source_origin = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (workspace_id, clean.casefold(), entity_type, source_origin),
                ).fetchone()
                entity_id = int(row["id"]) if row else 0
        if not entity_id:
            return None
        entity_cache[key] = entity_id
        return entity_id

    @staticmethod
    def _ensure_entity_in_conn(
        conn: Any,
        workspace_id: int,
        name: object,
        entity_type: str,
        source_origin: str,
        entity_cache: dict[tuple[str, str], int],
        description: str,
    ) -> int | None:
        clean = _clean_name(name)
        if not clean:
            return None
        key = (entity_type, clean.casefold())
        cached = entity_cache.get(key)
        if cached:
            return cached
        conn.execute(
            """
            INSERT INTO entities (
                workspace_id, name, normalized_name, entity_type, source_origin, description
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, clean, clean.casefold(), entity_type, source_origin, description),
        )
        entity_id = conn.lastrowid
        if not entity_id:
            row = conn.execute(
                """
                SELECT id
                FROM entities
                WHERE workspace_id = ? AND normalized_name = ? AND entity_type = ? AND source_origin = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (workspace_id, clean.casefold(), entity_type, source_origin),
            ).fetchone()
            entity_id = int(row["id"]) if row else 0
        if not entity_id:
            return None
        entity_cache[key] = entity_id
        return entity_id

    @staticmethod
    def _entity_lookup(
        entity_cache: dict[tuple[str, str], int],
        entity_type: str,
        name: object,
    ) -> int | None:
        clean = _clean_name(name)
        if not clean:
            return None
        return entity_cache.get((entity_type, clean.casefold()))

    @staticmethod
    def _insert_links(links: list[dict[str, Any]]) -> int:
        if not links:
            return 0
        with get_database().session() as conn:
            AcledKnowledgeService._insert_links_conn(conn, links)
        return len(links)

    @staticmethod
    def _insert_links_conn(conn: Any, links: list[dict[str, Any]]) -> int:
        if not links:
            return 0
        conn.executemany(
            """
            INSERT IGNORE INTO event_entity_links (event_id, entity_id, role_type)
            VALUES (%(event_id)s, %(entity_id)s, %(role_type)s)
            """,
            links,
        )
        return len(links)

    @staticmethod
    def _insert_evidences(evidences: list[dict[str, Any]]) -> int:
        if not evidences:
            return 0
        with get_database().session() as conn:
            AcledKnowledgeService._insert_evidences_conn(conn, evidences)
        return len(evidences)

    @staticmethod
    def _insert_evidences_conn(conn: Any, evidences: list[dict[str, Any]]) -> int:
        if not evidences:
            return 0
        conn.executemany(
            """
            INSERT INTO evidences (
                workspace_id, evidence_type, event_id, quote_text, source_label
            ) VALUES (
                %(workspace_id)s, %(evidence_type)s, %(event_id)s, %(quote_text)s, %(source_label)s
            )
            """,
            evidences,
        )
        return len(evidences)

    @staticmethod
    def _insert_relations(relations: list[dict[str, Any]]) -> int:
        if not relations:
            return 0
        entity_ids = sorted(
            {
                int(item["source_entity_id"])
                for item in relations
                if item.get("source_entity_id")
            }
            | {
                int(item["target_entity_id"])
                for item in relations
                if item.get("target_entity_id")
            }
        )
        if not entity_ids:
            return 0
        placeholders = ", ".join(["?"] * len(entity_ids))
        with get_database().session() as conn:
            existing_rows = conn.execute(
                f"SELECT id FROM entities WHERE id IN ({placeholders})",
                entity_ids,
            ).fetchall()
            existing_ids = {int(row["id"]) for row in existing_rows}
            filtered = [
                item
                for item in relations
                if int(item["source_entity_id"]) in existing_ids
                and int(item["target_entity_id"]) in existing_ids
            ]
            if not filtered:
                return 0
            conn.executemany(
                """
                INSERT INTO relations (
                    workspace_id, source_entity_id, target_entity_id,
                    relation_type, description, confidence, source_origin
                ) VALUES (
                    %(workspace_id)s, %(source_entity_id)s, %(target_entity_id)s,
                    %(relation_type)s, %(description)s, %(confidence)s, %(source_origin)s
                )
                """,
                filtered,
            )
        return len(filtered)

    @staticmethod
    def _insert_relations_conn(conn: Any, relations: list[dict[str, Any]]) -> int:
        if not relations:
            return 0
        conn.executemany(
            """
            INSERT INTO relations (
                workspace_id, source_entity_id, target_entity_id,
                relation_type, description, confidence, source_origin
            ) VALUES (
                %(workspace_id)s, %(source_entity_id)s, %(target_entity_id)s,
                %(relation_type)s, %(description)s, %(confidence)s, %(source_origin)s
            )
            """,
            relations,
        )
        return len(relations)

    @staticmethod
    def _count_entities(workspace_id: int) -> int:
        with get_database().session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM entities WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            ).fetchone()
        return int(row["c"]) if row else 0


def _link(event_id: int, entity_id: int, role_type: str) -> dict[str, Any]:
    return {"event_id": event_id, "entity_id": entity_id, "role_type": role_type}


def _append_relation(
    relations: list[dict[str, Any]],
    seen: set[tuple[int, int, str]],
    workspace_id: int,
    source_entity_id: int,
    target_entity_id: int,
    relation_type: str,
    description: str,
) -> None:
    key = (source_entity_id, target_entity_id, relation_type)
    if key in seen:
        return
    seen.add(key)
    relations.append(
        {
            "workspace_id": workspace_id,
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "relation_type": relation_type[:100],
            "description": description,
            "confidence": 1.0,
            "source_origin": "acled",
        }
    )


def _relation_description(row: dict[str, Any]) -> str:
    bits = [
        str(row.get("event_code") or ""),
        str(row.get("event_date") or ""),
        str(row.get("event_type") or ""),
        str(row.get("location_name") or row.get("admin1") or ""),
    ]
    return " | ".join(bit for bit in bits if bit)


def _clean_name(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text[:255]


def _display_entity_type(entity_type: str | None) -> str:
    mapping = {
        "actor": "行动主体",
        "location": "地理位置",
        "country": "国家",
        "organization": "来源机构",
        "topic": "事件类型",
    }
    return mapping.get(entity_type or "", entity_type or "实体")


@lru_cache(maxsize=1)
def get_acled_knowledge_service() -> AcledKnowledgeService:
    return AcledKnowledgeService()
