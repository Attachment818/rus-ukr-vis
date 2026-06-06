"""Sync MySQL conflict events, entities, relations to Neo4j graph database."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.neo4j_service import get_neo4j_service
from app.database import get_database


def sync_conflict_events():
    """Sync conflict_events from MySQL to Neo4j ConflictEvent nodes."""
    print("Syncing conflict events to Neo4j...")
    db = get_database()
    neo4j = get_neo4j_service()

    # Count in MySQL
    with db.session() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM conflict_events").fetchone()
        mysql_count = int(row["c"])
    print(f"  MySQL conflict_events: {mysql_count:,}")

    # Count in Neo4j
    neo4j_count = neo4j.count_conflict_events()
    print(f"  Neo4j ConflictEvent nodes: {neo4j_count:,}")

    if neo4j_count >= mysql_count:
        print("  Already synced, skipping.")
        return

    # Batch sync
    batch_size = 500
    offset = 0
    total_synced = 0

    while offset < mysql_count:
        with db.session() as conn:
            rows = conn.execute(
                """
                SELECT event_code, event_date, year, event_type, sub_event_type,
                       actor1_name, actor2_name, actor1_type, actor2_type,
                       admin1, location_name,
                       latitude, longitude, source_name,
                       notes, fatalities
                FROM conflict_events
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (batch_size, offset),
            ).fetchall()

        if not rows:
            break

        events = []
        for row in rows:
            events.append({
                "event_id_cnty": row["event_code"],
                "event_date": str(row["event_date"]) if row["event_date"] else None,
                "year": row["year"],
                "event_type": row["event_type"] or "",
                "sub_event_type": row["sub_event_type"] or "",
                "actor1": row["actor1_name"] or "",
                "actor1_type": row["actor1_type"] or "",
                "actor2": row["actor2_name"] or "",
                "actor2_type": row["actor2_type"] or "",
                "admin1": row["admin1"] or "",
                "location": row["location_name"] or "",
                "latitude": float(row["latitude"]) if row["latitude"] else None,
                "longitude": float(row["longitude"]) if row["longitude"] else None,
                "source": row["source_name"] or "",
                "notes": row["notes"] or "",
                "fatalities": int(row["fatalities"] or 0),
            })

        neo4j.upsert_conflict_events_batch(events)
        total_synced += len(events)
        offset += batch_size
        if offset % 5000 == 0:
            print(f"  Synced {total_synced:,} / {mysql_count:,}")

    print(f"  Done. Total synced: {total_synced:,}")


def sync_entities_and_relations():
    """Sync entities and relations from MySQL to Neo4j IntelEntity nodes."""
    print("\nSyncing entities & relations to Neo4j...")
    db = get_database()
    neo4j = get_neo4j_service()

    # Import entities as IntelEntity nodes (using workspace_id=1 as default)
    with db.session() as conn:
        entities = conn.execute(
            "SELECT id, name, entity_type, workspace_id FROM entities LIMIT 5000"
        ).fetchall()

    print(f"  Entities to sync: {len(entities):,}")

    for entity in entities:
        try:
            neo4j._run(
                """
                MERGE (n:IntelEntity {id: $id})
                SET n.label = $label,
                    n.node_type = $node_type,
                    n.workspace_id = $workspace_id
                """,
                {
                    "id": str(entity["id"]),
                    "label": entity["name"],
                    "node_type": entity["entity_type"],
                    "workspace_id": entity["workspace_id"],
                },
            )
        except Exception:
            pass

    # Import relations
    with db.session() as conn:
        relations = conn.execute(
            "SELECT id, source_entity_id, target_entity_id, relation_type, workspace_id FROM relations LIMIT 10000"
        ).fetchall()

    print(f"  Relations to sync: {len(relations):,}")

    synced_rels = 0
    for rel in relations:
        try:
            neo4j._run(
                """
                MATCH (a:IntelEntity {id: $source})
                MATCH (b:IntelEntity {id: $target})
                MERGE (a)-[r:REL {relation_type: $relation_type}]->(b)
                SET r.workspace_id = $workspace_id
                """,
                {
                    "source": str(rel["source_entity_id"]),
                    "target": str(rel["target_entity_id"]),
                    "relation_type": rel["relation_type"],
                    "workspace_id": rel["workspace_id"],
                },
            )
            synced_rels += 1
        except Exception:
            pass

    print(f"  Synced {synced_rels:,} relations.")


def main():
    neo4j = get_neo4j_service()

    # Verify Neo4j connection
    ok, msg = neo4j.verify()
    print(f"Neo4j: {msg}")
    if not ok:
        print("ERROR: Neo4j not available. Start it first.")
        sys.exit(1)

    # Ensure constraints
    print("Ensuring Neo4j constraints...")
    neo4j.ensure_constraints()

    # Show current state
    counts = neo4j.graph_counts()
    print(f"Current Neo4j graph: {counts}")

    # Sync data
    sync_conflict_events()

    # Final stats
    counts = neo4j.graph_counts()
    print(f"\nFinal Neo4j graph: {counts}")
    neo4j.close()
    print("\nSync complete!")


if __name__ == "__main__":
    main()
