"""Graph API — fetch entity/relationship data from Neo4j for D3 visualization."""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.neo4j_service import get_neo4j_service

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/entities")
def graph_entities(
    entity_type: str | None = Query(default=None, description="Filter: ConflictEvent, ConflictActor, ConflictLocation, ConflictSource"),
    limit: int = Query(default=500, ge=10, le=5000),
) -> dict:
    """Return nodes from Neo4j for force-directed graph visualization."""
    neo4j = get_neo4j_service()
    neo4j.connect()

    type_filter = ""
    params: dict = {"limit": limit}
    if entity_type:
        type_filter = ":" + entity_type

    nodes = neo4j._run(
        f"""
        MATCH (n{type_filter})
        RETURN labels(n)[0] AS label, properties(n) AS props, id(n) AS neo4j_id
        LIMIT $limit
        """,
        params,
    )

    return {
        "nodes": [
            {
                "id": str(r["neo4j_id"]),
                "label": r["label"],
                "type": r["label"],
                "name": (r["props"].get("name") or r["props"].get("label") or r["props"].get("event_type") or r["props"].get("event_id_cnty") or str(r["neo4j_id"]))[:80],
                "props": {k: v for k, v in r["props"].items() if k not in ("latitude", "longitude")},
            }
            for r in nodes
        ],
    }


@router.get("/relationships")
def graph_relationships(
    limit: int = Query(default=1000, ge=10, le=10000),
    source_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
) -> dict:
    """Return edges from Neo4j for graph visualization."""
    neo4j = get_neo4j_service()
    neo4j.connect()

    conditions: list[str] = []
    params: dict = {"limit": limit}

    if source_id:
        conditions.append("id(a) = $source_id")
        params["source_id"] = int(source_id)
    if target_id:
        conditions.append("id(b) = $target_id")
        params["target_id"] = int(target_id)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    edges = neo4j._run(
        f"""
        MATCH (a)-[r]->(b)
        {where}
        RETURN id(a) AS source, id(b) AS target,
               type(r) AS relation_type, properties(r) AS props
        LIMIT $limit
        """,
        params,
    )

    return {
        "edges": [
            {
                "source": str(e["source"]),
                "target": str(e["target"]),
                "relation_type": e["relation_type"],
                "props": e["props"] or {},
            }
            for e in edges
        ],
    }


@router.get("/full-graph")
def full_graph(
    entity_type: str | None = Query(default=None),
    node_limit: int = Query(default=400, ge=10, le=2000),
    edge_limit: int = Query(default=800, ge=10, le=5000),
) -> dict:
    """Return complete graph (nodes + edges) in one call."""
    neo4j = get_neo4j_service()
    neo4j.connect()

    type_filter = ""
    params: dict = {"node_limit": node_limit, "edge_limit": edge_limit}
    if entity_type:
        type_filter = ":" + entity_type

    # Get top nodes by degree (most connected)
    nodes = neo4j._run(
        f"""
        MATCH (n{type_filter})-[r]-()
        WITH n, count(r) AS degree
        ORDER BY degree DESC
        LIMIT $node_limit
        RETURN labels(n)[0] AS label, properties(n) AS props, elementId(n) AS neo4j_id, degree
        """,
        params,
    )

    node_ids = [r["neo4j_id"] for r in nodes]

    # Get edges: any edge where source OR target is in the top nodes
    # This ensures we show connections even if the other end isn't a top node
    edges = neo4j._run(
        """
        MATCH (a)-[r]->(b)
        WHERE elementId(a) IN $node_ids OR elementId(b) IN $node_ids
        RETURN elementId(a) AS source, elementId(b) AS target,
               type(r) AS relation_type, properties(r) AS props
        LIMIT $edge_limit
        """,
        {"node_ids": node_ids, "edge_limit": edge_limit},
    )

    # Collect additional nodes referenced by edges
    edge_node_ids = set(node_ids)
    for e in edges:
        edge_node_ids.add(e["source"])
        edge_node_ids.add(e["target"])

    # Fetch any missing nodes (the ones in edges but not in top nodes)
    missing_ids = edge_node_ids - set(node_ids)
    if missing_ids:
        extra_nodes = neo4j._run(
            """
            MATCH (n)
            WHERE elementId(n) IN $ids
            RETURN labels(n)[0] AS label, properties(n) AS props, elementId(n) AS neo4j_id,
                   size([(n)-[]-() | 1]) AS degree
            """,
            {"ids": list(missing_ids)},
        )
        for r in extra_nodes:
            nodes.append(r)

    return {
        "nodes": [
            {
                "id": str(r["neo4j_id"]),
                "type": r["label"],
                "name": (r["props"].get("name") or r["props"].get("label") or r["props"].get("event_type") or str(r["neo4j_id"]))[:80],
                "degree": int(r["degree"]),
                "props": {k: v for k, v in r["props"].items() if k not in ("latitude", "longitude")},
            }
            for r in nodes
        ],
        "edges": [
            {
                "source": str(e["source"]),
                "target": str(e["target"]),
                "relation_type": e["relation_type"],
            }
            for e in edges
        ],
    }
