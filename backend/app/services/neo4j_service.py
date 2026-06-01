from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from app.config import get_settings
from app.schemas.responses import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class Neo4jService:
    def __init__(self) -> None:
        settings = get_settings()
        self._uri = settings.neo4j_uri
        self._user = settings.neo4j_user
        self._password = settings.neo4j_password
        self._driver = None

    def connect(self) -> None:
        if self._driver is not None:
            return
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def verify(self) -> tuple[bool, str]:
        try:
            self.connect()
            with self._driver.session() as session:
                record = session.run("RETURN 1 AS ok").single()
                if record and record["ok"] == 1:
                    return True, "connected"
            return False, "unexpected response"
        except Exception as exc:
            return False, str(exc)

    def _run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.connect()
        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def _property_key_exists(self, key: str) -> bool:
        rows = self._run(
            """
            CALL db.propertyKeys() YIELD propertyKey
            WHERE propertyKey = $key
            RETURN propertyKey
            LIMIT 1
            """,
            {"key": key},
        )
        return bool(rows)

    def _relationship_type_exists(self, relationship_type: str) -> bool:
        rows = self._run(
            """
            CALL db.relationshipTypes() YIELD relationshipType
            WHERE relationshipType = $relationship_type
            RETURN relationshipType
            LIMIT 1
            """,
            {"relationship_type": relationship_type},
        )
        return bool(rows)

    def ensure_constraints(self) -> None:
        statements = [
            "CREATE CONSTRAINT intel_entity_id IF NOT EXISTS FOR (n:IntelEntity) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT conflict_event_id IF NOT EXISTS FOR (n:ConflictEvent) REQUIRE n.event_id_cnty IS UNIQUE",
            "CREATE CONSTRAINT conflict_actor_name IF NOT EXISTS FOR (n:ConflictActor) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT conflict_location_name IF NOT EXISTS FOR (n:ConflictLocation) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT conflict_source_name IF NOT EXISTS FOR (n:ConflictSource) REQUIRE n.name IS UNIQUE",
        ]
        for statement in statements:
            try:
                self._run(statement)
            except Neo4jError as exc:
                logger.warning("Neo4j constraint skipped: %s", exc)

    def clear_document_graph(self, document_id: int) -> None:
        if not self._property_key_exists("document_id"):
            return
        self._run(
            "MATCH (n:IntelEntity {document_id: $document_id}) DETACH DELETE n",
            {"document_id": document_id},
        )

    def write_document_graph(
        self,
        document_id: int,
        workspace_id: int,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        self.clear_document_graph(document_id)
        for node in nodes:
            self._run(
                """
                MERGE (n:IntelEntity {id: $id})
                SET n.label = $label,
                    n.node_type = $node_type,
                    n.document_id = $document_id,
                    n.workspace_id = $workspace_id,
                    n.chunk_ids = $chunk_ids
                """,
                {
                    "id": node.id,
                    "label": node.label,
                    "node_type": node.node_type,
                    "document_id": document_id,
                    "workspace_id": workspace_id,
                    "chunk_ids": node.chunk_ids,
                },
            )
        for edge in edges:
            self._run(
                """
                MATCH (a:IntelEntity {id: $source})
                MATCH (b:IntelEntity {id: $target})
                MERGE (a)-[r:REL {relation_type: $relation_type, document_id: $document_id}]->(b)
                SET r.chunk_ids = $chunk_ids, r.evidence = $evidence
                """,
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation_type": edge.relation_type,
                    "document_id": document_id,
                    "chunk_ids": edge.chunk_ids,
                    "evidence": edge.evidence,
                },
            )

    def get_document_subgraph(self, document_id: int, limit: int = 200) -> tuple[list[GraphNode], list[GraphEdge]]:
        if not self._property_key_exists("document_id"):
            return [], []
        node_rows = self._run(
            """
            MATCH (n:IntelEntity {document_id: $document_id})
            RETURN n.id AS id, n.label AS label, n.node_type AS node_type, n.chunk_ids AS chunk_ids
            LIMIT $limit
            """,
            {"document_id": document_id, "limit": limit},
        )
        edge_rows: list[dict[str, Any]] = []
        if self._relationship_type_exists("REL"):
            edge_rows = self._run(
                """
                MATCH (a:IntelEntity {document_id: $document_id})-[r:REL {document_id: $document_id}]->(b:IntelEntity {document_id: $document_id})
                RETURN a.id AS source, b.id AS target, r.relation_type AS relation_type,
                       r.chunk_ids AS chunk_ids, r.evidence AS evidence
                LIMIT $limit
                """,
                {"document_id": document_id, "limit": limit},
            )
        nodes = [
            GraphNode(
                id=row["id"],
                label=row["label"],
                node_type=row["node_type"],
                chunk_ids=list(row.get("chunk_ids") or []),
            )
            for row in node_rows
        ]
        edges = [
            GraphEdge(
                source=row["source"],
                target=row["target"],
                relation_type=row["relation_type"],
                chunk_ids=list(row.get("chunk_ids") or []),
                evidence=row.get("evidence"),
            )
            for row in edge_rows
        ]
        return nodes, edges

    def search_nodes_by_terms(self, document_id: int, terms: list[str], limit: int = 30) -> list[str]:
        if not terms:
            return []
        if not self._property_key_exists("document_id") or not self._property_key_exists("label"):
            return []
        rows = self._run(
            """
            MATCH (n:IntelEntity {document_id: $document_id})
            WHERE ANY(term IN $terms WHERE toLower(n.label) CONTAINS toLower(term))
            RETURN n.id AS id
            LIMIT $limit
            """,
            {"document_id": document_id, "terms": terms[:20], "limit": limit},
        )
        return [row["id"] for row in rows]

    def expand_subgraph(self, document_id: int, seed_ids: list[str], depth: int = 2) -> tuple[list[GraphNode], list[GraphEdge]]:
        if not seed_ids:
            return self.get_document_subgraph(document_id)
        return self._expand_subgraph_bfs(document_id, seed_ids, depth)

    def _expand_subgraph_bfs(
        self, document_id: int, seed_ids: list[str], depth: int
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        if not self._property_key_exists("document_id") or not self._relationship_type_exists("REL"):
            return self.get_document_subgraph(document_id)
        visited: set[str] = set(seed_ids)
        frontier = list(seed_ids)
        all_edges: list[GraphEdge] = []
        for _ in range(max(depth, 1)):
            if not frontier:
                break
            edge_rows = self._run(
                """
                MATCH (a:IntelEntity {document_id: $document_id})-[r:REL {document_id: $document_id}]->(b:IntelEntity {document_id: $document_id})
                WHERE a.id IN $frontier OR b.id IN $frontier
                RETURN a.id AS source, b.id AS target, r.relation_type AS relation_type,
                       r.chunk_ids AS chunk_ids, r.evidence AS evidence
                """,
                {"document_id": document_id, "frontier": frontier},
            )
            next_frontier: list[str] = []
            for row in edge_rows:
                all_edges.append(
                    GraphEdge(
                        source=row["source"],
                        target=row["target"],
                        relation_type=row["relation_type"],
                        chunk_ids=list(row.get("chunk_ids") or []),
                        evidence=row.get("evidence"),
                    )
                )
                for node_id in (row["source"], row["target"]):
                    if node_id not in visited:
                        visited.add(node_id)
                        next_frontier.append(node_id)
            frontier = next_frontier

        node_rows = self._run(
            """
            MATCH (n:IntelEntity {document_id: $document_id})
            WHERE n.id IN $ids
            RETURN n.id AS id, n.label AS label, n.node_type AS node_type, n.chunk_ids AS chunk_ids
            """,
            {"document_id": document_id, "ids": list(visited)},
        )
        nodes = [
            GraphNode(
                id=row["id"],
                label=row["label"],
                node_type=row["node_type"],
                chunk_ids=list(row.get("chunk_ids") or []),
            )
            for row in node_rows
        ]
        seen_edges: set[tuple[str, str, str]] = set()
        unique_edges: list[GraphEdge] = []
        for edge in all_edges:
            key = (edge.source, edge.target, edge.relation_type)
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(edge)
        return nodes, unique_edges

    def upsert_conflict_events_batch(self, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        self._run(
            """
            UNWIND $events AS ev
            MERGE (e:ConflictEvent {event_id_cnty: ev.event_id_cnty})
            SET e.event_date = ev.event_date,
                e.year = ev.year,
                e.event_type = ev.event_type,
                e.sub_event_type = ev.sub_event_type,
                e.actor1 = ev.actor1,
                e.actor2 = ev.actor2,
                e.admin1 = ev.admin1,
                e.location = ev.location,
                e.latitude = ev.latitude,
                e.longitude = ev.longitude,
                e.source = ev.source,
                e.notes = ev.notes,
                e.fatalities = ev.fatalities
            """,
            {"events": events},
        )
        self._run(
            """
            UNWIND $events AS ev
            MATCH (e:ConflictEvent {event_id_cnty: ev.event_id_cnty})
            FOREACH (_ IN CASE WHEN ev.actor1 IS NULL OR ev.actor1 = '' THEN [] ELSE [1] END |
                MERGE (a1:ConflictActor {name: ev.actor1})
                SET a1.actor_type = coalesce(ev.actor1_type, a1.actor_type)
                MERGE (a1)-[:参与 {role: 'actor1'}]->(e)
            )
            FOREACH (_ IN CASE WHEN ev.actor2 IS NULL OR ev.actor2 = '' THEN [] ELSE [1] END |
                MERGE (a2:ConflictActor {name: ev.actor2})
                SET a2.actor_type = coalesce(ev.actor2_type, a2.actor_type)
                MERGE (a2)-[:参与 {role: 'actor2'}]->(e)
            )
            FOREACH (_ IN CASE WHEN ev.location IS NULL OR ev.location = '' THEN [] ELSE [1] END |
                MERGE (loc:ConflictLocation {name: ev.location})
                SET loc.admin1 = ev.admin1,
                    loc.latitude = ev.latitude,
                    loc.longitude = ev.longitude
                MERGE (e)-[:发生于]->(loc)
            )
            FOREACH (_ IN CASE WHEN ev.admin1 IS NULL OR ev.admin1 = '' THEN [] ELSE [1] END |
                MERGE (region:ConflictLocation {name: ev.admin1})
                SET region.level = 'admin1'
                MERGE (e)-[:位于地区]->(region)
            )
            FOREACH (_ IN CASE WHEN ev.source IS NULL OR ev.source = '' THEN [] ELSE [1] END |
                MERGE (src:ConflictSource {name: ev.source})
                MERGE (e)-[:来源于]->(src)
            )
            """,
            {"events": events},
        )
        return len(events)

    def count_conflict_events(self) -> int:
        rows = self._run("MATCH (n:ConflictEvent) RETURN count(n) AS c")
        return int(rows[0]["c"]) if rows else 0

    def graph_counts(self) -> dict[str, int]:
        node_rows = self._run(
            """
            MATCH (n)
            RETURN labels(n)[0] AS label, count(n) AS count
            """
        )
        rel_rows = self._run("MATCH ()-[r]->() RETURN count(r) AS count")
        counts = {str(row["label"] or "Unknown"): int(row["count"]) for row in node_rows}
        counts["relationships"] = int(rel_rows[0]["count"]) if rel_rows else 0
        return counts

    def search_conflict_event_ids(self, terms: list[str], limit: int = 12) -> list[str]:
        if not terms:
            return []
        rows = self._run(
            """
            MATCH (e:ConflictEvent)
            WHERE ANY(term IN $terms WHERE
                toLower(coalesce(e.notes, '')) CONTAINS toLower(term)
                OR toLower(coalesce(e.admin1, '')) CONTAINS toLower(term)
                OR toLower(coalesce(e.location, '')) CONTAINS toLower(term)
                OR toLower(coalesce(e.event_type, '')) CONTAINS toLower(term)
                OR toLower(coalesce(e.actor1, '')) CONTAINS toLower(term))
            RETURN e.event_id_cnty AS event_id_cnty
            LIMIT $limit
            """,
            {"terms": terms[:15], "limit": limit},
        )
        return [row["event_id_cnty"] for row in rows]

    def conflict_subgraph_for_events(
        self, event_ids: list[str], neighbor_per_seed: int = 6
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        if not event_ids:
            return [], []

        node_map: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        def add_node(node_id: str, label: str, node_type: str) -> None:
            if node_id not in node_map:
                node_map[node_id] = GraphNode(
                    id=node_id, label=label or node_id, node_type=node_type, chunk_ids=[]
                )

        def add_edge(source: str, target: str, relation_type: str, evidence: str | None = None) -> None:
            key = (source, target, relation_type)
            if key in seen_edges:
                return
            seen_edges.add(key)
            edges.append(
                GraphEdge(
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    chunk_ids=[],
                    evidence=evidence,
                )
            )

        seed_rows = self._run(
            """
            MATCH (e:ConflictEvent)
            WHERE e.event_id_cnty IN $ids
            RETURN e.event_id_cnty AS id, e.event_type AS event_type, e.admin1 AS admin1,
                   e.location AS location, e.actor1 AS actor1, e.actor2 AS actor2, e.notes AS notes
            """,
            {"ids": event_ids[:12]},
        )
        for row in seed_rows:
            eid = row["id"]
            add_node(eid, row.get("event_type") or eid, "冲突事件")
            actor1 = (row.get("actor1") or "").strip()
            actor2 = (row.get("actor2") or "").strip()
            admin1 = (row.get("admin1") or "").strip()
            loc = (row.get("location") or admin1 or "").strip()
            if actor1:
                aid = f"军事组织::{actor1}"
                add_node(aid, actor1, "军事组织")
                add_edge(aid, eid, "参与", (row.get("notes") or "")[:80])
            if actor2:
                bid = f"军事组织::{actor2}"
                add_node(bid, actor2, "军事组织")
                add_edge(bid, eid, "参与")
            if loc:
                lid = f"地理位置::{loc}"
                add_node(lid, loc, "地理位置")
                add_edge(eid, lid, "部署于")

        per_seed = max(2, neighbor_per_seed)
        for eid in event_ids[:4]:
            neighbor_rows = self._run(
                """
                MATCH (seed:ConflictEvent {event_id_cnty: $eid})
                MATCH (o:ConflictEvent)
                WHERE o.admin1 = seed.admin1 AND o.event_id_cnty <> seed.event_id_cnty
                RETURN o.event_id_cnty AS id, o.event_type AS event_type, o.admin1 AS admin1,
                       o.notes AS notes
                ORDER BY o.event_date DESC
                LIMIT $lim
                """,
                {"eid": eid, "lim": per_seed},
            )
            for nrow in neighbor_rows:
                oid = nrow["id"]
                add_node(oid, nrow.get("event_type") or oid, "冲突事件")
                add_edge(eid, oid, "导致", (nrow.get("notes") or "")[:60])

        return list(node_map.values()), edges


@lru_cache(maxsize=1)
def get_neo4j_service() -> Neo4jService:
    return Neo4jService()
