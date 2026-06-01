from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.responses import GraphEdge, GraphNode, QAResponse, QASource
from app.services.embedding_service import get_embedding_service
from app.services.graph_extraction_service import load_graph
from app.services.llm_client import log_llm_raw_response, require_openai_client
from app.database import get_database


def _clean_source_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        title = " ".join(line.split()).strip()
        if len(title) >= 3 and not title.rstrip(".)、").isdigit():
            return title[:32] + ("…" if len(title) > 32 else "")
    return fallback


def _question_terms(question: str) -> list[str]:
    q = question.strip()
    terms: list[str] = []
    for match in re.finditer(r"[\w]{2,}", q, flags=re.UNICODE):
        terms.append(match.group().lower())
    han = re.sub(r"[^\u4e00-\u9fff]", "", q)
    if len(han) >= 2:
        terms.append(han)
        for i in range(len(han) - 1):
            terms.append(han[i : i + 2])
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def _score_text(text: str, terms: list[str]) -> float:
    if not text or not terms:
        return 0.0
    lower = text.lower()
    score = 0.0
    for term in terms:
        if len(term) < 2:
            continue
        if term.lower() in lower or term in text:
            score += 1.0 + len(term) * 0.05
    return score


def _retrieve_chunk_ids(
    question: str,
    chunk_rows: list[dict[str, Any]],
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    top_k: int = 6,
) -> list[int]:
    terms = _question_terms(question)
    scores: dict[int, float] = {}
    chunk_ids = [int(row["chunk_id"]) for row in chunk_rows]

    try:
        semantic_rank = get_embedding_service().rank_chunks(question, chunk_ids, top_k=max(top_k, 10))
    except Exception:
        semantic_rank = []
    if semantic_rank:
        for rank, (cid, similarity) in enumerate(semantic_rank):
            rank_bonus = max(0.0, 1.0 - rank * 0.06)
            scores[cid] = scores.get(cid, 0.0) + max(0.0, similarity) * 8.0 + rank_bonus

    for node in graph_nodes:
        node_score = _score_text(node.label, terms) * 2.0
        if node_score <= 0:
            continue
        for cid in node.chunk_ids:
            scores[cid] = scores.get(cid, 0.0) + node_score

    for edge in graph_edges:
        edge_score = _score_text(edge.relation_type, terms) + _score_text(edge.evidence or "", terms)
        if edge_score <= 0:
            continue
        for cid in edge.chunk_ids:
            scores[cid] = scores.get(cid, 0.0) + edge_score

    for row in chunk_rows:
        cid = int(row["chunk_id"])
        scores[cid] = scores.get(cid, 0.0) + _score_text(row.get("text") or "", terms)

    if not scores:
        return [int(row["chunk_id"]) for row in chunk_rows[:top_k]]

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    positive = [cid for cid, value in ranked if value > 0][:top_k]
    if positive:
        return positive
    return [int(row["chunk_id"]) for row in chunk_rows[:top_k]]


def _build_subgraph(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    cited_chunk_ids: set[int],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    if not cited_chunk_ids or not nodes:
        return [], []

    seed_ids: set[str] = set()
    for node in nodes:
        if cited_chunk_ids.intersection(node.chunk_ids):
            seed_ids.add(node.id)

    if not seed_ids:
        return [], []

    expanded = set(seed_ids)
    for edge in edges:
        if edge.source in seed_ids or edge.target in seed_ids:
            expanded.add(edge.source)
            expanded.add(edge.target)

    sub_nodes = [node for node in nodes if node.id in expanded]
    node_id_set = {node.id for node in sub_nodes}
    sub_edges = [
        edge
        for edge in edges
        if edge.source in node_id_set and edge.target in node_id_set
    ]
    return sub_nodes, sub_edges


def _call_llm_answer(
    client: Any,
    model: str,
    question: str,
    context_blocks: list[dict[str, Any]],
    graph_triples: list[str],
    allowed_chunk_ids: list[int],
) -> tuple[str, list[int]]:
    chunks_text = "\n\n".join(
        f"[chunk_id={block['chunk_id']}]\n{block['text']}" for block in context_blocks
    )
    graph_text = "\n".join(graph_triples[:40]) if graph_triples else "（暂无图谱，仅依据文本块作答）"
    allowed = ", ".join(str(cid) for cid in allowed_chunk_ids)

    system = """你是军情与公开局势分析助手。根据提供的知识图谱摘要与文本块回答问题。
必须严格输出 JSON 对象，不要输出 markdown。格式：
{"answer": "完整中文回答", "cited_chunk_ids": [整数]}
要求：
1. cited_chunk_ids 只能使用上下文中出现的 chunk_id，且必须是回答所依据的块。
2. 若证据不足，在 answer 中明确说明不确定之处，cited_chunk_ids 可为空数组。
3. 回答简洁、客观，避免编造上下文中不存在的事实。"""

    user = f"""问题：{question}

知识图谱摘要（实体—关系）：
{graph_text}

文本块：
{chunks_text}

允许引用的 chunk_id 列表：{allowed}"""

    request = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
    log_llm_raw_response("document_qa_answer", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型返回非合法 JSON：{raw[:200]}…") from exc

    answer = str(payload.get("answer", "")).strip()
    if not answer:
        raise ValueError("模型未返回有效回答。")

    cited_raw = payload.get("cited_chunk_ids") or []
    allowed_set = set(allowed_chunk_ids)
    cited: list[int] = []
    if isinstance(cited_raw, list):
        for item in cited_raw:
            try:
                cid = int(item)
            except (TypeError, ValueError):
                continue
            if cid in allowed_set and cid not in cited:
                cited.append(cid)
    if not cited and allowed_chunk_ids:
        cited = allowed_chunk_ids[: min(3, len(allowed_chunk_ids))]
    return answer, cited


def _graph_triples_for_chunks(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    chunk_ids: set[int],
) -> list[str]:
    if not chunk_ids:
        return []
    node_by_id = {node.id: node for node in nodes}
    lines: list[str] = []
    for edge in edges:
        if not chunk_ids.intersection(edge.chunk_ids):
            continue
        source = node_by_id.get(edge.source)
        target = node_by_id.get(edge.target)
        if not source or not target:
            continue
        evidence = f" | 证据: {edge.evidence}" if edge.evidence else ""
        lines.append(f"- {source.label} —[{edge.relation_type}]→ {target.label}{evidence}")
    for node in nodes:
        if chunk_ids.intersection(node.chunk_ids):
            lines.append(f"- 实体: {node.label}（{node.node_type}）")
    return list(dict.fromkeys(lines))


def answer_document_question(document_id: int, question: str) -> QAResponse:
    q = question.strip()
    if not q:
        raise ValueError("问题不能为空。")

    db = get_database()
    with db.session() as conn:
        doc = conn.execute(
            """
            SELECT id, COALESCE(NULLIF(source_name, ''), NULLIF(title, ''), CONCAT('文档 ', id)) AS source_label
            FROM documents WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        if doc is None:
            raise ValueError("文档不存在。")
        rows = conn.execute(
            """
            SELECT id AS chunk_id, chunk_index AS paragraph_index, page_no AS page_number, text
            FROM document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        ).fetchall()
    chunk_rows = [dict(row) for row in rows]
    if not chunk_rows:
        raise ValueError("该文档没有可用的文本块，请先上传并解析文档。")

    graph = load_graph(document_id)
    graph_nodes = graph.nodes if graph else []
    graph_edges = graph.edges if graph else []

    selected_ids = _retrieve_chunk_ids(q, chunk_rows, graph_nodes, graph_edges, top_k=6)
    selected_set = set(selected_ids)
    context_blocks = [row for row in chunk_rows if int(row["chunk_id"]) in selected_set]
    context_blocks.sort(key=lambda row: selected_ids.index(int(row["chunk_id"])))

    triples = _graph_triples_for_chunks(graph_nodes, graph_edges, selected_set)
    client, model = require_openai_client()
    answer, cited_ids = _call_llm_answer(client, model, q, context_blocks, triples, selected_ids)

    cited_set = set(cited_ids)
    sources: list[QASource] = []
    for row in chunk_rows:
        cid = int(row["chunk_id"])
        if cid not in cited_set:
            continue
        text = (row.get("text") or "").strip()
        excerpt = text[:320] + ("…" if len(text) > 320 else "")
        sources.append(
            QASource(
                source_type="chunk",
                label=_clean_source_title(text, str(doc["source_label"])),
                chunk_id=cid,
                paragraph_index=int(row["paragraph_index"]),
                page_number=row.get("page_number"),
                excerpt=excerpt,
            )
        )
    sources.sort(
        key=lambda item: cited_ids.index(item.chunk_id)
        if item.chunk_id is not None and item.chunk_id in cited_ids
        else 999
    )

    sub_nodes, sub_edges = _build_subgraph(graph_nodes, graph_edges, cited_set)
    return QAResponse(
        answer=answer,
        mode="local",
        sources=sources,
        subgraph_nodes=sub_nodes,
        subgraph_edges=sub_edges,
    )
