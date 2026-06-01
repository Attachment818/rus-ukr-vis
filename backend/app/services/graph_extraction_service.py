from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from app.config import GRAPH_CONFIG
from app.database import get_database
from app.schemas.responses import DocumentGraphResponse, GraphEdge, GraphNode
from app.services.llm_client import log_llm_raw_response, require_openai_client
from app.services.neo4j_service import get_neo4j_service


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_node_id(node_type: str, label: str) -> str:
    safe_type = (node_type or "未知").strip()
    safe_label = (label or "").strip()
    return f"{safe_type}::{safe_label}"


def _normalize_type(value: str, allowed: list[str], default: str) -> str:
    v = (value or "").strip()
    if v in allowed:
        return v
    for a in allowed:
        if a in v or v in a:
            return a
    return default


def _build_batch_text(chunks: list[dict[str, Any]], max_chars: int = 12000) -> tuple[str, int]:
    parts: list[str] = []
    total = 0
    used = 0
    for row in chunks:
        cid = row["chunk_id"]
        text = (row["text"] or "").strip()
        if not text:
            continue
        piece = f"[chunk_id={cid}]\n{text}\n"
        if total + len(piece) > max_chars:
            break
        parts.append(piece)
        total += len(piece)
        used += 1
    return "\n---\n".join(parts), used


def _select_chunks_for_graph(chunk_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(chunk_rows)
    if total <= 60:
        return chunk_rows
    max_chunks = min(120, max(60, math.ceil(total * 0.35)))
    if total <= max_chunks:
        return chunk_rows
    if max_chunks <= 1:
        return chunk_rows[:1]
    indices = sorted(
        {
            min(total - 1, round(i * (total - 1) / (max_chunks - 1)))
            for i in range(max_chunks)
        }
    )
    return [chunk_rows[index] for index in indices]


def _call_llm_json(client: OpenAI, model: str, user_content: str) -> dict[str, Any]:
    allowed_nodes = "、".join(GRAPH_CONFIG["allowed_nodes"])
    allowed_rels = "、".join(GRAPH_CONFIG["allowed_relationships"])
    system = f"""你是军事情报与公开局势分析助手。根据给定文本块抽取知识图谱三元组。
节点类型必须从以下集合中选择（若无法匹配则选最接近的一项）：{allowed_nodes}
关系类型必须从以下集合中选择（若无法匹配则选最接近的一项）：{allowed_rels}
必须严格输出 JSON 对象，且不要输出 markdown。结构如下：
{{
  "nodes": [{{"label": "名称", "node_type": "类型", "chunk_ids": [整数]}}],
  "edges": [{{"source_label": "源节点名称", "target_label": "目标节点名称", "relation_type": "关系", "chunk_ids": [整数], "evidence": "一句证据原文"}}]
}}
要求：
1. chunk_ids 只能使用文本块标记中的 chunk_id 整数。
2. 节点 label 简短明确；同一实体在不同块出现时可重复给出，后端会合并。
3. 若没有可靠关系，edges 可为空数组。"""

    request = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        response = client.chat.completions.create(
            **request,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        if "response_format" not in str(exc):
            raise
        response = client.chat.completions.create(**request)
    raw = response.choices[0].message.content or "{}"
    log_llm_raw_response("document_graph_extract", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型返回非合法 JSON：{raw[:200]}…") from exc


def _parse_llm_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes_raw = payload.get("nodes") or []
    edges_raw = payload.get("edges") or []
    if not isinstance(nodes_raw, list):
        nodes_raw = []
    if not isinstance(edges_raw, list):
        edges_raw = []
    return nodes_raw, edges_raw


def _merge_batch_results_fixed(
    batches: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Merge nodes first from all batches, then attach edges."""
    node_map: dict[str, GraphNode] = {}
    default_nt = GRAPH_CONFIG["allowed_nodes"][0]

    for nodes_raw, _ in batches:
        for item in nodes_raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            nt = _normalize_type(str(item.get("node_type", "")), GRAPH_CONFIG["allowed_nodes"], default_nt)
            cid_raw = item.get("chunk_ids") or item.get("chunk_id")
            if isinstance(cid_raw, int):
                cids = [cid_raw]
            elif isinstance(cid_raw, list):
                cids = []
                for x in cid_raw:
                    try:
                        cids.append(int(x))
                    except (TypeError, ValueError):
                        continue
            else:
                cids = []
            nid = _stable_node_id(nt, label)
            if nid in node_map:
                merged = sorted({*node_map[nid].chunk_ids, *cids})
                node_map[nid] = GraphNode(id=nid, label=label, node_type=nt, chunk_ids=merged)
            else:
                node_map[nid] = GraphNode(id=nid, label=label, node_type=nt, chunk_ids=sorted(set(cids)))

    default_rel = GRAPH_CONFIG["allowed_relationships"][0]
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def _resolve_label(label: str) -> str | None:
        if label in {n.label for n in node_map.values()}:
            for nid, n in node_map.items():
                if n.label == label:
                    return nid
        for nid, n in node_map.items():
            if label and (label in n.label or n.label in label):
                return nid
        return None

    for _, edges_raw in batches:
        for item in edges_raw:
            if not isinstance(item, dict):
                continue
            sl = str(item.get("source_label", item.get("source", ""))).strip()
            tl = str(item.get("target_label", item.get("target", ""))).strip()
            if not sl or not tl:
                continue
            rt = _normalize_type(str(item.get("relation_type", item.get("type", ""))), GRAPH_CONFIG["allowed_relationships"], default_rel)
            cid_raw = item.get("chunk_ids") or []
            if isinstance(cid_raw, int):
                ecids = [cid_raw]
            elif isinstance(cid_raw, list):
                ecids = []
                for x in cid_raw:
                    try:
                        ecids.append(int(x))
                    except (TypeError, ValueError):
                        continue
            else:
                ecids = []
            ev = item.get("evidence")
            evidence = str(ev).strip() if ev is not None else None

            sid = _resolve_label(sl)
            tid = _resolve_label(tl)
            if not sid or not tid or sid == tid:
                continue
            key = (sid, tid, rt)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                GraphEdge(
                    source=sid,
                    target=tid,
                    relation_type=rt,
                    chunk_ids=sorted(set(ecids)),
                    evidence=evidence,
                )
            )

    return list(node_map.values()), edges


def _scope_graph_to_document(
    document_id: int,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    id_map = {node.id: f"doc::{document_id}::{node.id}" for node in nodes}
    scoped_nodes = [
        GraphNode(
            id=id_map[node.id],
            label=node.label,
            node_type=node.node_type,
            chunk_ids=node.chunk_ids,
        )
        for node in nodes
    ]
    scoped_edges = [
        GraphEdge(
            source=id_map[edge.source],
            target=id_map[edge.target],
            relation_type=edge.relation_type,
            chunk_ids=edge.chunk_ids,
            evidence=edge.evidence,
        )
        for edge in edges
        if edge.source in id_map and edge.target in id_map
    ]
    return scoped_nodes, scoped_edges


def extract_and_store_graph(document_id: int) -> tuple[int, int, str]:
    db = get_database()
    with db.session() as conn:
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            raise ValueError("文档不存在。")
        rows = conn.execute(
            """
            SELECT id AS chunk_id, text
            FROM document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        ).fetchall()
        chunk_rows = [dict(r) for r in rows]

    if not chunk_rows:
        raise ValueError("该文档没有可用的文本块。")

    client, model = require_openai_client()

    selected_chunk_rows = _select_chunks_for_graph(chunk_rows)
    batches_payload: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    i = 0
    while i < len(selected_chunk_rows):
        batch_rows = selected_chunk_rows[i : i + 4]
        batch_text, used = _build_batch_text(batch_rows, max_chars=10000)
        if used == 0:
            break
        i += used
        user_msg = f"以下文本块来自同一文档，请抽取节点与边：\n\n{batch_text}"
        payload = _call_llm_json(client, model, user_msg)
        nodes_raw, edges_raw = _parse_llm_payload(payload)
        batches_payload.append((nodes_raw, edges_raw))

    nodes, edges = _merge_batch_results_fixed(batches_payload)
    if not nodes:
        raise ValueError("模型未返回有效节点，请检查模型或稍后重试。")
    nodes, edges = _scope_graph_to_document(document_id, nodes, edges)

    workspace_id = 0
    with db.session() as conn:
        doc_row = conn.execute(
            "SELECT workspace_id FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if doc_row:
            workspace_id = int(doc_row["workspace_id"])
        conn.execute(
            "UPDATE documents SET status = ? WHERE id = ?",
            ("processed", document_id),
        )

    neo4j = get_neo4j_service()
    neo4j.ensure_constraints()
    neo4j.write_document_graph(document_id, workspace_id, nodes, edges)
    updated = _utc_now_iso()
    scope = (
        f"覆盖 {len(selected_chunk_rows)} / {len(chunk_rows)} 个段落"
        if len(selected_chunk_rows) < len(chunk_rows)
        else f"覆盖全部 {len(chunk_rows)} 个段落"
    )
    return len(nodes), len(edges), f"图谱已写入 Neo4j（{scope}，MySQL 文档状态已更新）。更新时间 {updated}"


def load_graph(document_id: int) -> DocumentGraphResponse | None:
    try:
        neo4j = get_neo4j_service()
        nodes, edges = neo4j.get_document_subgraph(document_id)
    except Exception:
        return None
    if not nodes:
        return None
    return DocumentGraphResponse(
        document_id=document_id,
        nodes=nodes,
        edges=edges,
        updated_at=_utc_now_iso(),
    )
