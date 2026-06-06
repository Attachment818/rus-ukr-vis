"""Export Neo4j graph data to JSON files for backup/sharing.

Produces two files:
  - neo4j_nodes.json      — all nodes with labels and properties
  - neo4j_relationships.json — all relationships with type and properties

Usage:
  python scripts/export_neo4j_json.py
  python scripts/export_neo4j_json.py --output ./my_backup/
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def connect():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    print(f"Connecting to Neo4j at {uri} as {user}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    # Verify connection
    with driver.session() as session:
        result = session.run("RETURN 1 AS ok").single()
        if not result or result["ok"] != 1:
            raise RuntimeError("Neo4j connection verification failed")
    print("Connected successfully.\n")
    return driver


def export_nodes(driver) -> list[dict]:
    """Export all nodes grouped by label."""
    with driver.session() as session:
        records = session.run("""
            MATCH (n)
            RETURN labels(n) AS labels, properties(n) AS props, elementId(n) AS neo4j_id
            ORDER BY elementId(n)
        """).data()

    nodes_by_label: dict[str, list[dict]] = {}
    for r in records:
        for label in r["labels"]:
            nodes_by_label.setdefault(label, []).append({
                "neo4j_id": r["neo4j_id"],
                "properties": r["props"],
            })
    return nodes_by_label


def export_relationships(driver) -> list[dict]:
    """Export all relationships grouped by type."""
    with driver.session() as session:
        records = session.run("""
            MATCH (a)-[r]->(b)
            RETURN type(r) AS type, properties(r) AS props,
                   elementId(r) AS neo4j_id,
                   labels(a) AS source_labels, elementId(a) AS source_id,
                   labels(b) AS target_labels, elementId(b) AS target_id
            ORDER BY elementId(r)
        """).data()

    rels_by_type: dict[str, list[dict]] = {}
    for r in records:
        rels_by_type.setdefault(r["type"], []).append({
            "neo4j_id": r["neo4j_id"],
            "source": {
                "neo4j_id": r["source_id"],
                "labels": r["source_labels"],
            },
            "target": {
                "neo4j_id": r["target_id"],
                "labels": r["target_labels"],
            },
            "properties": r["props"],
        })
    return rels_by_type


def get_counts(nodes_by_label: dict, rels_by_type: dict) -> dict:
    total_nodes = sum(len(v) for v in nodes_by_label.values())
    total_rels = sum(len(v) for v in rels_by_type.values())
    return {
        "total_nodes": total_nodes,
        "nodes_by_label": {k: len(v) for k, v in sorted(nodes_by_label.items())},
        "total_relationships": total_rels,
        "relationships_by_type": {k: len(v) for k, v in sorted(rels_by_type.items())},
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Neo4j data to JSON")
    parser.add_argument("--output", default=str(ROOT / "database"), help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = connect()
    try:
        # 1. Statistics
        with driver.session() as session:
            label_counts = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
            """).data()
            rel_counts = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
            """).data()

        print("=" * 60)
        print("  Neo4j Database Summary")
        print("=" * 60)
        print("\n  Nodes:")
        total_n = 0
        for row in label_counts:
            label = row["label"] or "Unknown"
            count = int(row["count"])
            total_n += count
            print(f"    {label:<30} {count:>8,}")
        print(f"    {'TOTAL':<30} {total_n:>8,}")

        print("\n  Relationships:")
        total_r = 0
        for row in rel_counts:
            rtype = row["type"]
            count = int(row["count"])
            total_r += count
            print(f"    {rtype:<30} {count:>8,}")
        print(f"    {'TOTAL':<30} {total_r:>8,}")
        print()

        # 2. Export nodes
        print("Exporting nodes...")
        nodes_by_label = export_nodes(driver)
        nodes_file = out_dir / "neo4j_nodes.json"
        with open(nodes_file, "w", encoding="utf-8") as f:
            json.dump(nodes_by_label, f, ensure_ascii=False, indent=2, default=str)
        print(f"  -> {nodes_file} ({nodes_file.stat().st_size / 1024:.0f} KB)")

        # 3. Export relationships
        print("Exporting relationships...")
        rels_by_type = export_relationships(driver)
        rels_file = out_dir / "neo4j_relationships.json"
        with open(rels_file, "w", encoding="utf-8") as f:
            json.dump(rels_by_type, f, ensure_ascii=False, indent=2, default=str)
        print(f"  -> {rels_file} ({rels_file.stat().st_size / 1024:.0f} KB)")

        # 4. Write summary
        summary = get_counts(nodes_by_label, rels_by_type)
        summary_file = out_dir / "neo4j_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"  -> {summary_file}")

        print(f"\nDone! Exported {summary['total_nodes']} nodes, "
              f"{summary['total_relationships']} relationships.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
