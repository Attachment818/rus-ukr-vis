from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.config import GRAPH_CONFIG
from app.database import get_database
from app.schemas.responses import (
    GraphEdge,
    GraphNode,
    IntelligenceCaseEmbeddingResponse,
    IntelligenceCaseDocument,
    IntelligenceCaseRecord,
    IntelligenceCaseStage,
    IntelligenceCaseStatus,
    IntelligenceEntity,
    IntelligenceEvent,
    TimelinePoint,
)
from app.services.embedding_service import get_embedding_service
from app.services.llm_client import create_json_chat_completion, require_openai_client


CASE_FILE_LIMIT = 5
EXTRACTION_TIMEOUT_SEC = 45

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"),
    re.compile(r"(20\d{2})年"),
]

EVENT_KEYWORDS = {
    "炮击": "打击事件",
    "导弹": "打击事件",
    "无人机": "无人机事件",
    "空袭": "空袭事件",
    "袭击": "袭击事件",
    "交火": "交战事件",
    "冲突": "冲突事件",
    "部署": "部署事件",
    "撤离": "行动变化",
    "谈判": "外交事件",
    "制裁": "外交/经济事件",
}

WEAPON_KEYWORDS = [
    "无人机",
    "导弹",
    "火炮",
    "坦克",
    "装甲车",
    "防空系统",
    "战斗机",
    "舰艇",
    "地雷",
    "弹药",
]

KNOWN_LOCATIONS = [
    "乌克兰",
    "俄罗斯",
    "苏梅州",
    "赫尔松州",
    "顿涅茨克州",
    "卢甘斯克州",
    "哈尔科夫州",
    "扎波罗热州",
    "基辅",
    "敖德萨",
    "克里米亚",
]

KNOWN_ORGS = [
    "俄军",
    "乌军",
    "俄罗斯军队",
    "乌克兰军队",
    "俄罗斯国防部",
    "乌克兰国防部",
    "北约",
    "NATO",
    "欧盟",
    "联合国",
]


def _dt_iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _compact(text: str, limit: int = 260) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _normalize_iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return None


def _case_row_to_record(row: dict[str, Any]) -> IntelligenceCaseRecord:
    return IntelligenceCaseRecord(
        id=int(row["id"]),
        title=str(row["title"]),
        status=str(row.get("status") or "created"),
        created_at=_dt_iso(row.get("created_at")),
        updated_at=_dt_iso(row.get("updated_at")),
    )


def create_case(title: str | None = None) -> IntelligenceCaseRecord:
    resolved_title = (title or "").strip() or f"材料分析 {datetime.now().strftime('%m%d %H:%M')}"
    with get_database().session() as conn:
        conn.execute(
            "INSERT INTO intelligence_cases (title, status) VALUES (?, 'created')",
            (resolved_title,),
        )
        case_id = conn.lastrowid
        row = conn.execute(
            "SELECT id, title, status, created_at, updated_at FROM intelligence_cases WHERE id = ?",
            (case_id,),
        ).fetchone()
    return _case_row_to_record(row)


def get_case(case_id: int) -> IntelligenceCaseRecord:
    with get_database().session() as conn:
        row = conn.execute(
            "SELECT id, title, status, created_at, updated_at FROM intelligence_cases WHERE id = ?",
            (case_id,),
        ).fetchone()
    if row is None:
        raise ValueError("当前材料分析不存在。")
    return _case_row_to_record(row)


def count_case_documents(case_id: int) -> int:
    with get_database().session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM intelligence_case_documents WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def attach_document_to_case(case_id: int, document_id: int) -> None:
    get_case(case_id)
    with get_database().session() as conn:
        conn.execute(
            """
            INSERT INTO intelligence_case_documents (case_id, document_id, role)
            VALUES (?, ?, 'material')
            ON DUPLICATE KEY UPDATE role = VALUES(role)
            """,
            (case_id, document_id),
        )
        conn.execute(
            "UPDATE intelligence_cases SET status = 'parsed' WHERE id = ?",
            (case_id,),
        )


def case_document_ids(case_id: int) -> list[int]:
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT document_id
            FROM intelligence_case_documents
            WHERE case_id = ?
            ORDER BY id ASC
            """,
            (case_id,),
        ).fetchall()
    return [int(row["document_id"]) for row in rows]


def list_case_documents(case_id: int) -> list[IntelligenceCaseDocument]:
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT icd.id, d.id AS document_id,
                   COALESCE(d.source_name, d.title) AS file_name,
                   d.title AS document_topic,
                   COALESCE(d.file_type, '') AS file_type,
                   COALESCE(d.status, 'pending') AS status,
                   icd.created_at,
                   (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id = d.id) AS chunk_count,
                   (SELECT COUNT(*) FROM intelligence_entities ie WHERE ie.case_id = icd.case_id AND ie.document_id = d.id) AS entity_count,
                   (SELECT COUNT(*) FROM intelligence_events iev WHERE iev.case_id = icd.case_id AND iev.document_id = d.id) AS event_count,
                   (SELECT COUNT(*) FROM intelligence_evidences iv WHERE iv.case_id = icd.case_id AND iv.document_id = d.id) AS evidence_count
            FROM intelligence_case_documents icd
            JOIN documents d ON d.id = icd.document_id
            WHERE icd.case_id = ?
            ORDER BY icd.id ASC
            """,
            (case_id,),
        ).fetchall()
        relation_rows = conn.execute(
            """
            SELECT e.document_id, COUNT(DISTINCT r.id) AS relation_count
            FROM intelligence_relations r
            JOIN intelligence_entities e ON e.id = r.source_entity_id
            WHERE r.case_id = ?
            GROUP BY e.document_id
            """,
            (case_id,),
        ).fetchall()
    relation_counts = {int(row["document_id"]): int(row["relation_count"]) for row in relation_rows}
    embedding_service = get_embedding_service()
    documents: list[IntelligenceCaseDocument] = []
    for row in rows:
        document_id = int(row["document_id"])
        try:
            embedding_status = embedding_service.document_status(document_id)
            vector_ready = bool(embedding_status.get("ready"))
        except Exception:
            vector_ready = False
        documents.append(
            IntelligenceCaseDocument(
                id=int(row["id"]),
                document_id=document_id,
                file_name=str(row["file_name"]),
                document_topic=str(row["document_topic"]),
                file_type=str(row["file_type"]),
                status=str(row["status"]),
                chunk_count=int(row["chunk_count"] or 0),
                entity_count=int(row["entity_count"] or 0),
                event_count=int(row["event_count"] or 0),
                relation_count=relation_counts.get(document_id, 0),
                evidence_count=int(row["evidence_count"] or 0),
                vector_ready=vector_ready,
                graph_ready=int(row["entity_count"] or 0) > 0,
                created_at=_dt_iso(row["created_at"]),
            )
        )
    return documents


def _parse_date(text: str) -> tuple[str | None, str | None]:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(0)
        if len(match.groups()) >= 3:
            year, month, day = match.group(1), match.group(2), match.group(3)
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}", raw
        return None, raw
    return None, None


def _extract_entity_candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for location in KNOWN_LOCATIONS:
        if location in text:
            candidates.append((location, "地理位置"))
    for org in KNOWN_ORGS:
        if org in text:
            candidates.append((org, "军事组织"))
    for weapon in WEAPON_KEYWORDS:
        if weapon in text:
            candidates.append((weapon, "武器装备"))
    for value in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·\-\s]{2,24}(?:州|市|地区|机场|港口|基地|边境|前线)", text):
        candidates.append((value.strip(), "地理位置"))
    for value in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·\-\s]{2,30}(?:军|部队|旅|营|师|政府|组织|集团|武装)", text):
        candidates.append((value.strip(), "军事组织"))
    date_value, raw_date = _parse_date(text)
    if raw_date:
        candidates.append((raw_date, "时间节点"))
    if date_value:
        candidates.append((date_value, "时间节点"))
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for name, entity_type in candidates:
        clean = re.sub(r"\s+", " ", name).strip(" ，。；;:：")
        if len(clean) < 2 or len(clean) > 80:
            continue
        key = (clean.casefold(), entity_type)
        if key in seen:
            continue
        seen.add(key)
        result.append((clean, entity_type))
    return result[:12]


def _detect_event_type(text: str) -> str | None:
    for keyword, event_type in EVENT_KEYWORDS.items():
        if keyword in text:
            return event_type
    return None


def _rule_extract_chunk(text: str) -> dict[str, list[dict[str, Any]]]:
    entities = [
        {
            "name": name,
            "entity_type": entity_type,
            "evidence": _compact(text, 220),
        }
        for name, entity_type in _extract_entity_candidates(text)
    ]
    event_type = _detect_event_type(text)
    events: list[dict[str, Any]] = []
    if event_type:
        event_date, raw_date = _parse_date(text)
        location = next((item["name"] for item in entities if item["entity_type"] == "地理位置"), None)
        actors = [item["name"] for item in entities if item["entity_type"] == "军事组织"][:5]
        events.append(
            {
                "title": _event_title(text, event_type),
                "date": event_date,
                "time_text": raw_date,
                "event_type": event_type,
                "location": location,
                "actors": actors,
                "summary": _compact(text, 420),
                "evidence": _compact(text, 260),
            }
        )
    relations: list[dict[str, Any]] = []
    for index, source in enumerate(entities[:6]):
        for target in entities[index + 1 : 6]:
            relations.append(
                {
                    "source": source["name"],
                    "target": target["name"],
                    "relation_type": "共同出现",
                    "evidence": _compact(text, 220),
                }
            )
    return {"entities": entities, "events": events, "relations": relations}


def _llm_extract_chunk(text: str, chunk_id: int) -> dict[str, list[dict[str, Any]]]:
    client, model = require_openai_client()
    client = client.with_options(timeout=EXTRACTION_TIMEOUT_SEC, max_retries=0)
    allowed_nodes = "、".join(GRAPH_CONFIG["allowed_nodes"])
    allowed_rels = "、".join(GRAPH_CONFIG["allowed_relationships"])
    system = f"""你是公开情报材料结构化抽取器。请从给定材料段落中抽取可用于可视化和问答溯源的实体、事件、关系。

不要按固定关键词抽取，要依据语义识别人物、组织、地点、装备、行动、时间、事件和来源线索。
实体类型优先参考：{allowed_nodes}。若不匹配，可以使用更贴切的短类型名。
关系类型优先参考：{allowed_rels}。若不匹配，可以使用更贴切的短关系名。

必须严格输出 JSON：
{{
  "entities": [
    {{"name": "实体名称", "entity_type": "类型", "evidence": "短证据"}}
  ],
  "events": [
    {{
      "title": "事件标题",
      "date": "YYYY-MM-DD 或 null",
      "time_text": "原文时间表达",
      "event_type": "事件类型",
      "location": "地点或 null",
      "actors": ["主体1", "主体2"],
      "summary": "一句话概括",
      "evidence": "支撑事件的原文片段"
    }}
  ],
  "relations": [
    {{"source": "实体A", "target": "实体B", "relation_type": "关系", "evidence": "短证据"}}
  ]
}}

要求：
1. 一个段落中可以有多个事件，尤其要保留多个日期和日期范围中的关键节点。
2. date 字段只在能明确到具体日期时填写 ISO 日期；不能明确到日则填 null，并把原文时间写入 time_text。
3. evidence 必须来自当前段落，不要编造。
4. 为避免输出被截断，entities 最多 10 个，events 最多 5 个，relations 最多 8 条。
5. evidence 和 summary 都要短，优先保留可定位信息，不要展开分析。
6. 不要输出 Markdown，不要输出解释。"""
    payload = create_json_chat_completion(
        client,
        model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"chunk_id={chunk_id}\n\n{text[:3600]}"},
        ],
        temperature=0.1,
        max_tokens=1800,
        timeout=EXTRACTION_TIMEOUT_SEC,
    )
    entities = payload.get("entities") if isinstance(payload.get("entities"), list) else []
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    relations = payload.get("relations") if isinstance(payload.get("relations"), list) else []
    return {"entities": entities[:10], "events": events[:5], "relations": relations[:8]}


def _extract_chunk_structured(text: str, chunk_id: int) -> dict[str, list[dict[str, Any]]]:
    try:
        llm_result = _llm_extract_chunk(text, chunk_id)
        if llm_result["entities"] or llm_result["events"] or llm_result["relations"]:
            if not llm_result["events"]:
                rule_result = _rule_extract_chunk(text)
                llm_result["events"] = rule_result["events"]
                if not llm_result["entities"]:
                    llm_result["entities"] = rule_result["entities"]
                if not llm_result["relations"]:
                    llm_result["relations"] = rule_result["relations"]
            return llm_result
    except Exception as exc:
        print(f"Intelligence extraction fallback for chunk {chunk_id}: {exc}", flush=True)
    return _rule_extract_chunk(text)


def _event_title(text: str, event_type: str) -> str:
    first_sentence = re.split(r"[。！？!?]\s*", _compact(text, 180))[0]
    if first_sentence:
        return first_sentence[:90]
    return event_type


def rebuild_case_extractions(case_id: int) -> None:
    document_ids = case_document_ids(case_id)
    with get_database().session() as conn:
        conn.execute("DELETE FROM intelligence_relations WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM intelligence_evidences WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM intelligence_events WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM intelligence_entities WHERE case_id = ?", (case_id,))
        if not document_ids:
            conn.execute("UPDATE intelligence_cases SET status = 'created' WHERE id = ?", (case_id,))
            return
        placeholders = ", ".join(["?"] * len(document_ids))
        chunks = conn.execute(
            f"""
            SELECT dc.id AS chunk_id, dc.document_id, dc.chunk_index, dc.page_no, dc.text,
                   COALESCE(d.source_name, d.title) AS source_name
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.document_id IN ({placeholders})
            ORDER BY dc.document_id ASC, dc.chunk_index ASC
            """,
            document_ids,
        ).fetchall()

        entity_ids_by_chunk: dict[int, list[int]] = {}
        entity_key_to_id: dict[tuple[str, str], int] = {}
        entity_label_to_id: dict[str, int] = {}
        evidence_by_chunk: dict[int, str] = {}
        structured_by_chunk: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for chunk in chunks:
            chunk_id = int(chunk["chunk_id"])
            text = str(chunk.get("text") or "")
            excerpt = _compact(text)
            evidence_by_chunk[chunk_id] = excerpt
            inserted_entity_ids: list[int] = []
            structured = _extract_chunk_structured(text, chunk_id)
            structured_by_chunk[chunk_id] = structured
            raw_entities = structured.get("entities") or []
            for item in raw_entities:
                if not isinstance(item, dict):
                    continue
                name = re.sub(r"\s+", " ", str(item.get("name") or "")).strip(" ，。；;:：")
                entity_type = re.sub(r"\s+", " ", str(item.get("entity_type") or "情报实体")).strip()[:100]
                if len(name) < 2 or len(name) > 120:
                    continue
                normalized_name = name.casefold()
                key = (normalized_name, entity_type)
                entity_id = entity_key_to_id.get(key)
                if entity_id is None:
                    evidence = _compact(str(item.get("evidence") or excerpt), 260)
                    conn.execute(
                        """
                        INSERT INTO intelligence_entities (
                            case_id, document_id, chunk_id, name, normalized_name, entity_type, evidence_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            case_id,
                            chunk["document_id"],
                            chunk["chunk_id"],
                            name,
                            normalized_name,
                            entity_type,
                            evidence,
                        ),
                    )
                    entity_id = conn.lastrowid
                    entity_key_to_id[key] = entity_id
                    entity_label_to_id[normalized_name] = entity_id
                if entity_id not in inserted_entity_ids:
                    inserted_entity_ids.append(entity_id)
            entity_ids_by_chunk[chunk_id] = inserted_entity_ids

            raw_events = structured.get("events") or []
            for item in raw_events:
                if not isinstance(item, dict):
                    continue
                title = _compact(str(item.get("title") or item.get("event_title") or ""), 180)
                event_type = _compact(str(item.get("event_type") or "事件线索"), 100)
                summary = _compact(str(item.get("summary") or item.get("evidence") or text), 420)
                if not title:
                    title = _event_title(summary or text, event_type)
                event_date = _normalize_iso_date(item.get("date"))
                raw_date = _compact(str(item.get("time_text") or item.get("date") or ""), 100) or None
                location = _compact(str(item.get("location") or ""), 255) or None
                actors_raw = item.get("actors") or []
                actors = [str(actor).strip() for actor in actors_raw if str(actor).strip()] if isinstance(actors_raw, list) else []
                evidence = _compact(str(item.get("evidence") or excerpt), 260)
                conn.execute(
                    """
                    INSERT INTO intelligence_events (
                        case_id, document_id, chunk_id, event_title, event_date, event_time_raw,
                        event_type, location_name, actor_names, summary, evidence_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        chunk["document_id"],
                        chunk["chunk_id"],
                        title,
                        event_date,
                        raw_date,
                        event_type,
                        location,
                        "、".join(actors),
                        summary,
                        evidence,
                    ),
                )
            conn.execute(
                """
                INSERT INTO intelligence_evidences (
                    case_id, document_id, chunk_id, evidence_type, quote_text, source_label
                ) VALUES (?, ?, ?, 'document_chunk', ?, ?)
                """,
                (
                    case_id,
                    chunk["document_id"],
                    chunk["chunk_id"],
                    excerpt,
                    str(chunk.get("source_name") or ""),
                ),
            )

        for chunk_id, entity_ids in entity_ids_by_chunk.items():
            chunk_evidence = evidence_by_chunk.get(chunk_id, "同一材料段落中共同出现。")
            for left_index, source_id in enumerate(entity_ids[:6]):
                for target_id in entity_ids[left_index + 1 : 6]:
                    conn.execute(
                        """
                        INSERT INTO intelligence_relations (
                            case_id, source_entity_id, target_entity_id, chunk_id, relation_type, evidence_text
                        ) VALUES (?, ?, ?, ?, '共同出现', ?)
                        ON DUPLICATE KEY UPDATE evidence_text = VALUES(evidence_text)
                        """,
                        (case_id, source_id, target_id, chunk_id, _compact(chunk_evidence, 220)),
                    )
        for chunk in chunks:
            chunk_id = int(chunk["chunk_id"])
            structured = structured_by_chunk.get(chunk_id) or {"relations": []}
            for item in structured.get("relations") or []:
                if not isinstance(item, dict):
                    continue
                source_label = str(item.get("source") or item.get("source_label") or "").strip().casefold()
                target_label = str(item.get("target") or item.get("target_label") or "").strip().casefold()
                source_id = entity_label_to_id.get(source_label)
                target_id = entity_label_to_id.get(target_label)
                if not source_id or not target_id or source_id == target_id:
                    continue
                relation_type = _compact(str(item.get("relation_type") or "关联"), 100)
                evidence = _compact(str(item.get("evidence") or "同一材料段落中存在关联。"), 260)
                conn.execute(
                    """
                    INSERT INTO intelligence_relations (
                        case_id, source_entity_id, target_entity_id, chunk_id, relation_type, evidence_text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE evidence_text = VALUES(evidence_text)
                    """,
                    (case_id, source_id, target_id, chunk_id, relation_type, evidence),
                )
        conn.execute(
            "UPDATE intelligence_cases SET status = 'processed' WHERE id = ?",
            (case_id,),
        )


def index_case_embeddings(case_id: int, force: bool = False) -> IntelligenceCaseEmbeddingResponse:
    get_case(case_id)
    documents = list_case_documents(case_id)
    if not documents:
        raise ValueError("当前材料没有可生成语义索引的文件。")

    embedding_service = get_embedding_service()
    indexed = 0
    skipped = 0
    total_chunks = 0
    vector_indexed = 0
    vector_store: str | None = None
    errors: list[str] = []

    for document in documents:
        try:
            result = embedding_service.index_document(document.document_id, force=force)
            indexed += int(result.get("indexed") or 0)
            skipped += int(result.get("skipped") or 0)
            total_chunks += int(result.get("total_chunks") or 0)
            vector_indexed += int(result.get("vector_indexed") or 0)
            vector_store = str(result.get("vector_store") or vector_store or "")
        except Exception as exc:
            errors.append(f"{document.file_name}: {exc}")

    status = get_case_status(case_id)
    ready_count = sum(1 for document in status.documents if document.vector_ready)
    message = (
        f"语义索引已处理：{ready_count}/{len(status.documents)} 份材料可用于语义检索。"
        if not errors
        else f"语义索引部分完成：{ready_count}/{len(status.documents)} 份材料可用。"
    )
    return IntelligenceCaseEmbeddingResponse(
        case_id=case_id,
        document_count=len(status.documents),
        ready_document_count=ready_count,
        indexed=indexed,
        skipped=skipped,
        total_chunks=total_chunks,
        vector_indexed=vector_indexed,
        vector_store=vector_store,
        errors=errors,
        status=status,
        message=message,
    )


def get_case_status(case_id: int) -> IntelligenceCaseStatus:
    case = get_case(case_id)
    documents = list_case_documents(case_id)
    metrics = case_metrics(case_id)
    stages = [
        IntelligenceCaseStage(
            id="input",
            name="材料输入",
            status="done" if metrics["documents"] else "pending",
            count=metrics["documents"],
            detail=f"{metrics['documents']} 份材料",
        ),
        IntelligenceCaseStage(
            id="chunking",
            name="分段与来源保留",
            status="done" if metrics["chunks"] else "pending",
            count=metrics["chunks"],
            detail=f"{metrics['chunks']} 个段落",
        ),
        IntelligenceCaseStage(
            id="extraction",
            name="结构化抽取",
            status="done" if metrics["entities"] or metrics["events"] else "pending",
            count=metrics["entities"] + metrics["events"],
            detail=f"实体 {metrics['entities']}，事件 {metrics['events']}",
        ),
        IntelligenceCaseStage(
            id="organization",
            name="知识组织",
            status="done" if metrics["relations"] else "pending",
            count=metrics["relations"],
            detail=f"{metrics['relations']} 条关系",
        ),
        IntelligenceCaseStage(
            id="retrieval",
            name="检索资产",
            status="done" if metrics["vector_ready_documents"] else "pending",
            count=metrics["vector_ready_documents"],
            detail=f"{metrics['vector_ready_documents']} 份材料已生成向量索引",
        ),
        IntelligenceCaseStage(
            id="visualization",
            name="可视化视图",
            status="done" if metrics["events"] or metrics["relations"] else "pending",
            count=metrics["events"] + metrics["relations"],
            detail="时间线与关系图可用" if metrics["events"] or metrics["relations"] else "等待结构化结果",
        ),
    ]
    return IntelligenceCaseStatus(case=case, documents=documents, stages=stages, metrics=metrics)


def case_metrics(case_id: int) -> dict[str, int]:
    with get_database().session() as conn:
        rows = {
            "documents": conn.execute(
                "SELECT COUNT(*) AS c FROM intelligence_case_documents WHERE case_id = ?",
                (case_id,),
            ).fetchone(),
            "chunks": conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM document_chunks dc
                JOIN intelligence_case_documents icd ON icd.document_id = dc.document_id
                WHERE icd.case_id = ?
                """,
                (case_id,),
            ).fetchone(),
            "entities": conn.execute(
                "SELECT COUNT(*) AS c FROM intelligence_entities WHERE case_id = ?",
                (case_id,),
            ).fetchone(),
            "events": conn.execute(
                "SELECT COUNT(*) AS c FROM intelligence_events WHERE case_id = ?",
                (case_id,),
            ).fetchone(),
            "relations": conn.execute(
                "SELECT COUNT(*) AS c FROM intelligence_relations WHERE case_id = ?",
                (case_id,),
            ).fetchone(),
            "evidences": conn.execute(
                "SELECT COUNT(*) AS c FROM intelligence_evidences WHERE case_id = ?",
                (case_id,),
            ).fetchone(),
        }
    documents = list_case_documents(case_id)
    return {
        key: int(row["c"]) if row else 0
        for key, row in rows.items()
    } | {"vector_ready_documents": sum(1 for document in documents if document.vector_ready)}


def list_case_entities(case_id: int, limit: int = 120) -> list[IntelligenceEntity]:
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT id, document_id, chunk_id, name, entity_type, evidence_text
            FROM intelligence_entities
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (case_id, limit),
        ).fetchall()
    return [
        IntelligenceEntity(
            id=int(row["id"]),
            document_id=int(row["document_id"]),
            chunk_id=row.get("chunk_id"),
            name=str(row["name"]),
            entity_type=str(row["entity_type"]),
            evidence_text=row.get("evidence_text"),
        )
        for row in rows
    ]


def list_case_events(case_id: int, limit: int = 120) -> list[IntelligenceEvent]:
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT id, document_id, chunk_id, event_title, event_date, event_time_raw,
                   event_type, location_name, actor_names, summary, evidence_text
            FROM intelligence_events
            WHERE case_id = ?
            ORDER BY COALESCE(event_date, DATE(created_at)) ASC, id ASC
            LIMIT ?
            """,
            (case_id, limit),
        ).fetchall()
    return [
        IntelligenceEvent(
            id=int(row["id"]),
            document_id=int(row["document_id"]),
            chunk_id=row.get("chunk_id"),
            event_title=str(row["event_title"]),
            event_date=_dt_iso(row.get("event_date")) if row.get("event_date") else None,
            event_time_raw=row.get("event_time_raw"),
            event_type=row.get("event_type"),
            location_name=row.get("location_name"),
            actor_names=row.get("actor_names"),
            summary=row.get("summary"),
            evidence_text=row.get("evidence_text"),
        )
        for row in rows
    ]


def get_case_graph(case_id: int, limit: int = 220) -> dict[str, list[dict[str, Any]]]:
    with get_database().session() as conn:
        entity_rows = conn.execute(
            """
            SELECT id, name, entity_type, chunk_id
            FROM intelligence_entities
            WHERE case_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (case_id, limit),
        ).fetchall()
        event_rows = conn.execute(
            """
            SELECT id, event_title, event_type, chunk_id
            FROM intelligence_events
            WHERE case_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (case_id, max(20, limit // 4)),
        ).fetchall()
        relation_rows = conn.execute(
            """
            SELECT r.source_entity_id, r.target_entity_id, r.relation_type, r.chunk_id, r.evidence_text
            FROM intelligence_relations r
            WHERE r.case_id = ?
            ORDER BY r.id ASC
            LIMIT ?
            """,
            (case_id, limit),
        ).fetchall()
        event_entity_rows = conn.execute(
            """
            SELECT event_id, entity_id, entity_type
            FROM (
                SELECT iev.id AS event_id, r.source_entity_id AS entity_id, ie.entity_type
                FROM intelligence_events iev
                JOIN intelligence_relations r
                  ON r.case_id = iev.case_id
                 AND r.chunk_id = iev.chunk_id
                JOIN intelligence_entities ie ON ie.id = r.source_entity_id
                WHERE iev.case_id = ?
                UNION
                SELECT iev.id AS event_id, r.target_entity_id AS entity_id, ie.entity_type
                FROM intelligence_events iev
                JOIN intelligence_relations r
                  ON r.case_id = iev.case_id
                 AND r.chunk_id = iev.chunk_id
                JOIN intelligence_entities ie ON ie.id = r.target_entity_id
                WHERE iev.case_id = ?
            ) linked
            ORDER BY event_id ASC, entity_id ASC
            LIMIT ?
            """,
            (case_id, case_id, limit),
        ).fetchall()
    nodes: list[GraphNode] = []
    entity_node_ids: set[int] = set()
    event_node_ids: set[int] = set()
    for row in entity_rows:
        entity_id = int(row["id"])
        entity_node_ids.add(entity_id)
        nodes.append(
            GraphNode(
                id=f"case::{case_id}::entity::{entity_id}",
                label=str(row["name"]),
                node_type=str(row["entity_type"]),
                chunk_ids=[int(row["chunk_id"])] if row.get("chunk_id") else [],
            )
        )
    for row in event_rows:
        event_id = int(row["id"])
        event_node_ids.add(event_id)
        nodes.append(
            GraphNode(
                id=f"case::{case_id}::event::{event_id}",
                label=str(row["event_title"])[:40],
                node_type="冲突事件",
                chunk_ids=[int(row["chunk_id"])] if row.get("chunk_id") else [],
            )
        )
    edges: list[GraphEdge] = []
    for row in relation_rows:
        source_id = int(row["source_entity_id"])
        target_id = int(row["target_entity_id"])
        if source_id not in entity_node_ids or target_id not in entity_node_ids:
            continue
        edges.append(
            GraphEdge(
                source=f"case::{case_id}::entity::{source_id}",
                target=f"case::{case_id}::entity::{target_id}",
                relation_type=str(row["relation_type"]),
                chunk_ids=[int(row["chunk_id"])] if row.get("chunk_id") else [],
                evidence=row.get("evidence_text"),
            )
        )
    event_entity_seen: set[tuple[int, int]] = set()
    for row in event_entity_rows:
        event_id = int(row["event_id"])
        entity_id = int(row["entity_id"])
        key = (event_id, entity_id)
        if key in event_entity_seen or event_id not in event_node_ids or entity_id not in entity_node_ids:
            continue
        event_entity_seen.add(key)
        edges.append(
            GraphEdge(
                source=f"case::{case_id}::event::{event_id}",
                target=f"case::{case_id}::entity::{entity_id}",
                relation_type="涉及",
                chunk_ids=[],
                evidence=f"该事件线索与{row.get('entity_type') or '实体'}在同一材料段落中出现。",
            )
        )
    return {
        "nodes": [node.dict() for node in nodes],
        "edges": [edge.dict() for edge in edges],
    }


def get_case_timeline(case_id: int) -> list[TimelinePoint]:
    with get_database().session() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(DATE_FORMAT(event_date, '%%Y-%%m-%%d'), event_time_raw, '未标注时间') AS label,
                   COUNT(*) AS value
            FROM intelligence_events
            WHERE case_id = ?
            GROUP BY label
            ORDER BY MIN(event_date) ASC, label ASC
            """,
            (case_id,),
        ).fetchall()
    return [
        TimelinePoint(date=str(row["label"]), label=str(row["label"]), value=int(row["value"]))
        for row in rows
    ]
