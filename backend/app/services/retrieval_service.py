from __future__ import annotations

import json
import re
from typing import Any

from app.database import get_database
from app.schemas.responses import GraphEdge, GraphNode, QAResponse, QASource
from app.services.conflict_store import get_conflict_store
from app.services.graph_extraction_service import load_graph
from app.services.llm_client import create_json_chat_completion, require_openai_client
from app.services.neo4j_service import get_neo4j_service
from app.services.query_history_service import save_query_history
from app.services.weibo_store import get_weibo_store
from app.services.qa_service import (
    _build_subgraph,
    _call_llm_answer,
    _graph_triples_for_chunks,
    _question_terms,
    _retrieve_chunk_ids,
    answer_document_question,
)


def _acled_source(event: dict[str, Any], index: int) -> QASource:
    notes = (event.get("notes") or "").strip()
    excerpt = notes[:320] + ("…" if len(notes) > 320 else "")
    source_name = (event.get("source") or "ACLED").strip()
    return QASource(
        source_type="acled",
        label=f"{source_name} · {event.get('event_date', '')}",
        event_id_cnty=event.get("event_id_cnty"),
        excerpt=excerpt or f"{event.get('event_type', '')} @ {event.get('location', '')}",
    )


def _call_llm_global(
    question: str,
    stats: dict[str, Any],
    events: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    client, model = require_openai_client()
    events_text = "\n\n".join(
        f"[{ev['event_id_cnty']}] {ev.get('event_date')} | {ev.get('event_type')} | {ev.get('admin1')} | {ev.get('notes', '')[:200]}"
        for ev in events[:10]
    )
    stats_text = json.dumps(stats, ensure_ascii=False, indent=2)
    system = """你是俄乌冲突公开情报分析助手。根据 ACLED 结构化事件统计与样本作答。
输出 JSON：{"answer": "中文分析", "cited_event_ids": ["UKR...", ...]}
不要编造未出现在材料中的具体数字。"""
    user = f"问题：{question}\n\n统计摘要：\n{stats_text}\n\n事件样本：\n{events_text}"
    payload = create_json_chat_completion(
        client,
        model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    )
    answer = str(payload.get("answer", "")).strip()
    cited = payload.get("cited_event_ids") or []
    if not isinstance(cited, list):
        cited = []
    return answer, [str(x) for x in cited[:8]]


def _weibo_source(post: dict[str, Any], index: int) -> QASource:
    text = (post.get("text") or "").strip()
    excerpt = text[:280] + ("…" if len(text) > 280 else "")
    return QASource(
        source_type="weibo",
        label=f"微博 · {post.get('screen_name') or '未知'}",
        excerpt=excerpt or "（无正文）",
    )


def answer_global(question: str) -> QAResponse:
    store = get_conflict_store()
    stats = store.aggregate_stats(question)
    events = store.search_for_global(question, limit=12)
    answer, cited_ids = _call_llm_global(question, stats, events)
    event_by_id = {e["event_id_cnty"]: e for e in events}
    sources: list[QASource] = []
    for eid in cited_ids:
        if eid in event_by_id:
            sources.append(_acled_source(event_by_id[eid], len(sources)))
    if not sources:
        sources = [_acled_source(ev, i) for i, ev in enumerate(events[:5])]

    subgraph_nodes: list[GraphNode] = []
    subgraph_edges: list[GraphEdge] = []
    try:
        neo4j = get_neo4j_service()
        terms = _question_terms(question)
        neo_ids = neo4j.search_conflict_event_ids(terms, limit=10)
        seed_ids = list(dict.fromkeys([*neo_ids, *[e["event_id_cnty"] for e in events[:6]]]))[:10]
        if seed_ids:
            subgraph_nodes, subgraph_edges = neo4j.conflict_subgraph_for_events(seed_ids)
    except Exception:
        pass

    return QAResponse(
        answer=answer,
        mode="global",
        sources=sources,
        subgraph_nodes=subgraph_nodes,
        subgraph_edges=subgraph_edges,
        context_summary=stats,
    )


def answer_event_chain(question: str, event_id_cnty: str | None) -> QAResponse:
    store = get_conflict_store()
    if not event_id_cnty:
        hits = store.search_for_global(question, limit=1)
        if not hits:
            raise ValueError("未找到相关冲突事件，请提供 event_id_cnty 或更具体的问题。")
        event_id_cnty = hits[0]["event_id_cnty"]
    chain = store.event_chain(event_id_cnty, limit=25)
    seed = chain[0]
    lines = [
        f"- {ev['event_date']}: {ev.get('event_type')} @ {ev.get('location')} ({ev.get('actor1')} vs {ev.get('actor2')})"
        for ev in chain[:15]
    ]
    client, model = require_openai_client()
    payload = create_json_chat_completion(
        client,
        model,
        messages=[
            {
                "role": "system",
                "content": '输出 JSON：{"answer": "事件链分析"}，基于给定事件序列，不要编造。',
            },
            {
                "role": "user",
                "content": f"问题：{question}\n锚点事件：{seed.get('notes', '')[:300]}\n相关事件：\n" + "\n".join(lines),
            },
        ],
        temperature=0.3,
    )
    answer = str(payload.get("answer", "")).strip() or "已根据同地区邻近事件构建事件链。"

    sources = [_acled_source(ev, i) for i, ev in enumerate(chain[:8])]
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    try:
        neo4j = get_neo4j_service()
        chain_ids = [ev["event_id_cnty"] for ev in chain[:12]]
        nodes, edges = neo4j.conflict_subgraph_for_events(chain_ids, neighbor_per_seed=4)
    except Exception:
        prev_id: str | None = None
        for ev in chain[:12]:
            eid = ev["event_id_cnty"]
            nid = f"冲突事件::{eid}"
            nodes.append(GraphNode(id=nid, label=eid, node_type="冲突事件", chunk_ids=[]))
            if prev_id:
                edges.append(
                    GraphEdge(
                        source=prev_id,
                        target=nid,
                        relation_type="导致",
                        chunk_ids=[],
                        evidence=(ev.get("notes") or "")[:80],
                    )
                )
            prev_id = nid

    return QAResponse(
        answer=answer,
        mode="event_chain",
        sources=sources,
        subgraph_nodes=nodes,
        subgraph_edges=edges,
        context_summary={"anchor": event_id_cnty, "chain_size": len(chain)},
    )


def answer_evidence(question: str, document_id: int | None) -> QAResponse:
    store = get_conflict_store()
    events = store.search_for_global(question, limit=6)
    sources = [_acled_source(ev, i) for i, ev in enumerate(events)]

    weibo = get_weibo_store()
    if weibo.is_imported():
        for i, post in enumerate(weibo.search_posts(question, limit=4)):
            sources.append(_weibo_source(post, i))

    if document_id:
        try:
            doc_resp = answer_document_question(document_id, question)
            for src in doc_resp.sources:
                sources.insert(
                    0,
                    QASource(
                        source_type="chunk",
                        label=src.label,
                        chunk_id=src.chunk_id,
                        paragraph_index=src.paragraph_index,
                        page_number=src.page_number,
                        excerpt=src.excerpt,
                    ),
                )
            return QAResponse(
                answer=doc_resp.answer,
                mode="evidence",
                sources=sources[:12],
                subgraph_nodes=doc_resp.subgraph_nodes,
                subgraph_edges=doc_resp.subgraph_edges,
            )
        except ValueError:
            pass

    excerpts = "\n".join(f"[{s.event_id_cnty}] {s.excerpt}" for s in sources[:6])
    return QAResponse(
        answer=f"根据公开冲突事件库检索到 {len(sources)} 条相关证据片段：\n{excerpts[:1200]}",
        mode="evidence",
        sources=sources,
    )


def answer_local_with_neo4j(document_id: int, question: str) -> QAResponse:
    base = answer_document_question(document_id, question)
    try:
        neo4j = get_neo4j_service()
        terms = _question_terms(question)
        seed_ids = neo4j.search_nodes_by_terms(document_id, terms)
        if seed_ids:
            sub_nodes, sub_edges = neo4j.expand_subgraph(document_id, seed_ids, depth=2)
            if sub_nodes:
                base.subgraph_nodes = sub_nodes
                base.subgraph_edges = sub_edges
        base.mode = "local"
        db = get_database()
        with db.session() as conn:
            doc = conn.execute(
                """
                SELECT COALESCE(source_name, title) AS file_name
                FROM documents WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        if doc:
            fname = doc["file_name"]
            for src in base.sources:
                src.source_type = "chunk"
                src.label = fname
    except Exception:
        base.mode = "local"
    return base


def run_workspace_query(
    question: str,
    mode: str,
    document_id: int | None = None,
    event_id_cnty: str | None = None,
    workspace_id: int | None = None,
) -> QAResponse:
    mode = (mode or "local").strip().lower()
    allowed = {"global", "local", "event_chain", "evidence"}
    if mode not in allowed:
        raise ValueError(f"不支持的查询模式: {mode}，可选: {', '.join(sorted(allowed))}")

    if mode == "global":
        result = answer_global(question)
    elif mode == "event_chain":
        result = answer_event_chain(question, event_id_cnty)
    elif mode == "evidence":
        result = answer_evidence(question, document_id)
    elif not document_id:
        raise ValueError("local 模式需要选择已解析的文档（document_id）。")
    else:
        result = answer_local_with_neo4j(document_id, question)

    if workspace_id is not None:
        try:
            save_query_history(workspace_id, question, mode, result.answer)
        except Exception:
            pass
    return result


def recommend_views(mode: str, question: str) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = [
        {
            "view_type": "timeline",
            "title": "冲突事件时间线",
            "rationale": "ACLED 数据含完整 event_date，适合观察阶段演化。",
            "priority": 1,
        },
        {
            "view_type": "map",
            "title": "战场空间分布图",
            "rationale": "事件记录含经纬度，可展示地理聚集与热点地区。",
            "priority": 2,
        },
    ]
    if mode in ("local", "evidence"):
        recs.append(
            {
                "view_type": "graph",
                "title": "文档知识图谱",
                "rationale": "当前为文档级问答，关系子图可辅助理解实体联系。",
                "priority": 1,
            }
        )
    if "来源" in question or "舆论" in question:
        recs.append(
            {
                "view_type": "bar",
                "title": "情报来源分布",
                "rationale": "问题涉及来源，适合对比 ACLED 机构与微博账号。",
                "priority": 1,
            }
        )
    if mode == "event_chain":
        recs.insert(
            0,
            {
                "view_type": "timeline",
                "title": "事件链时间线",
                "rationale": "事件链模式应优先使用时间序视图。",
                "priority": 0,
            },
        )
    return recs
