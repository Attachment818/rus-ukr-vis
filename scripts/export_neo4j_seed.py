from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
SEED_LABEL = "__Neo4jSeedNode"
SEED_PROPERTY = "__neo4j_seed_id"
BATCH_SIZE = 500


def quote_name(value: str) -> str:
    return f"`{str(value).replace('`', '``')}`"


def string_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def cypher_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "null"
        return repr(value)
    if isinstance(value, str):
        return string_literal(value)
    if isinstance(value, (date, datetime)):
        return string_literal(value.isoformat())
    if hasattr(value, "iso_format"):
        return string_literal(value.iso_format())
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(cypher_value(item) for item in value if item is not None) + "]"
    return string_literal(str(value))


def cypher_map(properties: dict[str, Any]) -> str:
    items: list[str] = []
    for key, value in sorted(properties.items()):
        if value is None:
            continue
        items.append(f"{quote_name(key)}: {cypher_value(value)}")
    return "{" + ", ".join(items) + "}"


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def node_create_clause(labels: tuple[str, ...]) -> str:
    all_labels = (SEED_LABEL, *labels)
    return "".join(f":{quote_name(label)}" for label in all_labels)


def write_node_batch(handle, labels: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    payload = ",\n  ".join(
        f"{{seed: {string_literal(row['seed'])}, props: {cypher_map(row['props'])}}}"
        for row in rows
    )
    handle.write("UNWIND [\n  ")
    handle.write(payload)
    handle.write("\n] AS row\n")
    handle.write(f"CREATE (n{node_create_clause(labels)})\n")
    handle.write("SET n = row.props\n")
    handle.write(f"SET n.{quote_name(SEED_PROPERTY)} = row.seed;\n\n")


def write_relationship_batch(handle, rel_type: str, rows: list[dict[str, Any]]) -> None:
    payload = ",\n  ".join(
        (
            "{source: "
            f"{string_literal(row['source'])}, target: {string_literal(row['target'])}, "
            f"props: {cypher_map(row['props'])}}}"
        )
        for row in rows
    )
    safe_type = rel_type or "RELATED_TO"
    handle.write("UNWIND [\n  ")
    handle.write(payload)
    handle.write("\n] AS row\n")
    handle.write(f"MATCH (a:{quote_name(SEED_LABEL)} {{{quote_name(SEED_PROPERTY)}: row.source}})\n")
    handle.write(f"MATCH (b:{quote_name(SEED_LABEL)} {{{quote_name(SEED_PROPERTY)}: row.target}})\n")
    handle.write(f"CREATE (a)-[r:{quote_name(safe_type)}]->(b)\n")
    handle.write("SET r = row.props;\n\n")


def fetch_graph(uri: str, user: str, password: str, database: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) if database else driver.session() as session:
            nodes = session.run(
                """
                MATCH (n)
                RETURN elementId(n) AS seed, labels(n) AS labels, properties(n) AS props
                ORDER BY elementId(n)
                """
            ).data()
            relationships = session.run(
                """
                MATCH (a)-[r]->(b)
                RETURN elementId(a) AS source, elementId(b) AS target,
                       type(r) AS type, properties(r) AS props
                ORDER BY elementId(r)
                """
            ).data()
    finally:
        driver.close()
    return nodes, relationships


def export_seed(output: Path, include_clear: bool, database: str | None) -> None:
    load_dotenv(ROOT / ".env")
    import os

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is empty. Please fill it in .env first.")

    nodes, relationships = fetch_graph(uri, user, password, database)
    for node in nodes:
        if SEED_PROPERTY in (node.get("props") or {}):
            raise RuntimeError(f"Node already has reserved property {SEED_PROPERTY}; export stopped.")

    output.parent.mkdir(parents=True, exist_ok=True)
    grouped_nodes: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        labels = tuple(sorted(str(label) for label in (node.get("labels") or [])))
        grouped_nodes[labels].append(
            {
                "seed": str(node["seed"]),
                "props": dict(node.get("props") or {}),
            }
        )

    grouped_relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relationship in relationships:
        grouped_relationships[str(relationship.get("type") or "RELATED_TO")].append(
            {
                "source": str(relationship["source"]),
                "target": str(relationship["target"]),
                "props": dict(relationship.get("props") or {}),
            }
        )

    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("// Neo4j seed file generated by scripts/export_neo4j_seed.py\n")
        handle.write(f"// Nodes: {len(nodes)}, relationships: {len(relationships)}\n\n")
        if include_clear:
            handle.write("MATCH (n) DETACH DELETE n;\n\n")
        handle.write(
            f"CREATE INDEX neo4j_seed_lookup IF NOT EXISTS "
            f"FOR (n:{quote_name(SEED_LABEL)}) ON (n.{quote_name(SEED_PROPERTY)});\n\n"
        )
        for labels, rows in sorted(grouped_nodes.items(), key=lambda item: item[0]):
            for batch in chunked(rows, BATCH_SIZE):
                write_node_batch(handle, labels, batch)
        handle.write("CALL db.awaitIndexes();\n\n")
        for rel_type, rows in sorted(grouped_relationships.items(), key=lambda item: item[0]):
            for batch in chunked(rows, BATCH_SIZE):
                write_relationship_batch(handle, rel_type, batch)
        handle.write(
            f"MATCH (n:{quote_name(SEED_LABEL)}) "
            f"REMOVE n:{quote_name(SEED_LABEL)}, n.{quote_name(SEED_PROPERTY)};\n"
        )
        handle.write("DROP INDEX neo4j_seed_lookup IF EXISTS;\n")

    print(f"Exported {len(nodes)} nodes and {len(relationships)} relationships to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Neo4j graph data to an importable Cypher seed file.")
    parser.add_argument("--output", default=str(ROOT / "database" / "neo4j_seed.cypher"))
    parser.add_argument("--database", default=None, help="Neo4j database name, for example neo4j.")
    parser.add_argument("--include-clear", action="store_true", help="Add MATCH (n) DETACH DELETE n at file start.")
    args = parser.parse_args()
    export_seed(Path(args.output), include_clear=args.include_clear, database=args.database)


if __name__ == "__main__":
    main()
