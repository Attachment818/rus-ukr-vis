from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import get_settings
from app.database import get_database
from app.schemas.responses import GraphEdge, GraphNode, QAResponse, QASource
from app.services.embedding_service import get_embedding_service
from app.services.llm_client import create_json_chat_completion, require_openai_client
from app.services.weibo_store import get_weibo_store

try:
    from langchain_core.prompts import ChatPromptTemplate
except Exception:  # pragma: no cover - optional dependency during transition
    ChatPromptTemplate = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


DATABASE_SCHEMA_PROMPT = """
你可以使用下列只读数据表进行公开情报分析。只能生成 SELECT 查询，不能修改数据库。

1. conflict_events：结构化冲突事件库，主要来自公开事件数据。
字段：
- event_code：事件编号，对应 event_id_cnty。
- event_date：事件日期。
- year：年份。
- disorder_type, event_type, sub_event_type：事件类型。
- actor1_name, actor1_assoc, actor1_type：主体1。
- actor2_name, actor2_assoc, actor2_type：主体2。
- interaction_type, civilian_targeting：互动类型与平民目标。
- region, country, admin1, admin2, admin3, location_name：空间位置。
- latitude, longitude, geo_precision：地理坐标与精度。
- source_name, source_scale, notes, tags, source_timestamp：来源和原始说明。
- fatalities：死亡人数。

2. public_opinion_posts：公开文本/舆论样本。
字段：
- created_at_dt, pub_time_dt：时间。
- msg_id, text：文本编号和正文。
- screen_name, source_device：发布主体和设备。
- reposts_count, comments_count, attitudes_count：互动指标。

3. documents 与 document_chunks：用户导入材料和切分文本。
字段：
- documents.id, title, source_name, source_type, file_type, file_path, created_at。
- document_chunks.id, document_id, chunk_index, text, page_no, start_offset, end_offset。

4. entities, relations, event_entity_links, evidences：结构化知识层。
字段：
- entities.name, normalized_name, entity_type, source_origin, description。
- relations.source_entity_id, target_entity_id, relation_type, confidence, source_origin。
- evidences.evidence_type, quote_text, source_label, document_id, chunk_id, event_id。

5. intelligence_cases、intelligence_case_documents：用户本轮上传材料的分析范围。
字段：
- intelligence_cases.id, title, status, created_at, updated_at。
- intelligence_case_documents.case_id, document_id, role, created_at。

6. intelligence_entities、intelligence_events、intelligence_relations、intelligence_evidences：当前上传材料范围的结构化抽取结果。
字段：
- intelligence_entities.case_id, document_id, chunk_id, name, normalized_name, entity_type, evidence_text。
- intelligence_events.case_id, document_id, chunk_id, event_title, event_date, event_time_raw, event_type, location_name, actor_names, summary, evidence_text。
- intelligence_relations.case_id, source_entity_id, target_entity_id, chunk_id, relation_type, evidence_text。
- intelligence_evidences.case_id, document_id, chunk_id, evidence_type, quote_text, source_label。

分析规则：
- 若问题询问“最近/最新/最后一次事件”，应查询 conflict_events 按 event_date DESC 排序。
- 若问题询问数量、分布、趋势、排名，应使用 COUNT/GROUP BY/ORDER BY 聚合。
- 若问题涉及地点、主体、事件类型或时间范围，应在 SQL 中使用对应字段过滤。
- 若用户提供或上传材料，应优先查询 intelligence_* 当前上传材料范围的结构化结果，并同时检索 document_chunks；必要时再与 conflict_events 公开事件库交叉印证。
- 若公开事件库无法验证用户材料，回答中必须说明无法独立核验，并在“假设材料为真”的前提下继续分析。
"""

EVENT_TYPE_LABELS = {
    "Explosions/Remote violence": "远程打击",
    "Battles": "战斗",
    "Violence against civilians": "针对平民的暴力",
    "Strategic developments": "战略动态",
    "Protests": "抗议",
    "Riots": "骚乱",
}

SUB_EVENT_TYPE_LABELS = {
    "Shelling/artillery/missile attack": "炮击/火炮/导弹袭击",
    "Armed clash": "武装交火",
    "Air/drone strike": "空袭/无人机打击",
    "Attack": "袭击",
    "Remote explosive/landmine/IED": "地雷/简易爆炸装置/遥控爆炸",
    "Abduction/forced disappearance": "绑架/强迫失踪",
    "Looting/property destruction": "掠夺/财产破坏",
    "Agreement": "协议/安排",
    "Arrests": "逮捕",
    "Non-state actor overtakes territory": "非国家行为体夺取地区",
}

ACTOR_TYPE_LABELS = {
    "State forces": "国家武装力量",
    "Rebel group": "反政府武装",
    "Political militia": "政治民兵",
    "Identity militia": "身份型民兵",
    "Civilians": "平民",
    "External/Other forces": "外部力量",
}

ALLOWED_TABLES = {
    "conflict_events",
    "public_opinion_posts",
    "documents",
    "document_chunks",
    "entities",
    "relations",
    "event_entity_links",
    "evidences",
    "intelligence_cases",
    "intelligence_case_documents",
    "intelligence_entities",
    "intelligence_events",
    "intelligence_relations",
    "intelligence_evidences",
}

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|load|outfile|infile)\b",
    re.IGNORECASE,
)
SOURCE_MARKER_PATTERN = re.compile(r"\[(?:S|s)\d+\]")
CATALOG_SUFFIX_PATTERN = re.compile(r"\s*\((?:\d{4}-|\d{4}-\d{2,4})\)")
LEADING_DATABASE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:根据(?:当前)?(?:公开事件(?:库|数据库)?|结构化(?:事件)?数据库|事件数据库|数据库)(?:记录|检索结果|信息)?[，,:：]\s*)",
    re.IGNORECASE,
)
BROAD_QUERY_HINT_PATTERN = re.compile(r"(态势|趋势|总体|概览|近几年|近年|全年|演变|分布|阶段|格局|主要类型|热点)", re.IGNORECASE)
UKRAINE_REGION_HINTS = {
    "苏梅州": "苏梅州（Ukraine / Sumy Oblast）",
    "顿涅茨克州": "顿涅茨克州（Ukraine / Donetsk Oblast）",
    "卢甘斯克州": "卢甘斯克州（Ukraine / Luhansk Oblast）",
    "赫尔松州": "赫尔松州（Ukraine / Kherson Oblast）",
    "哈尔科夫州": "哈尔科夫州（Ukraine / Kharkiv Oblast）",
    "扎波罗热州": "扎波罗热州（Ukraine / Zaporizhzhia Oblast）",
    "尼古拉耶夫州": "尼古拉耶夫州（Ukraine / Mykolaiv Oblast）",
    "敖德萨州": "敖德萨州（Ukraine / Odesa Oblast）",
    "基辅州": "基辅州（Ukraine / Kyiv Oblast）",
}
LARGE_RESULT_THRESHOLD = 1800


def _chat_messages(system: str, user: str) -> list[dict[str, str]]:
    if ChatPromptTemplate is not None:
        # LangChain treats braces inside prompt text as template variables.
        safe_system = system.replace("{", "{{").replace("}", "}}")
        prompt = ChatPromptTemplate.from_messages([("system", safe_system), ("human", "{user_input}")])
        rendered = prompt.format_messages(user_input=user)
        messages: list[dict[str, str]] = []
        for message in rendered:
            role = "assistant"
            if message.type == "system":
                role = "system"
            elif message.type == "human":
                role = "user"
            messages.append({"role": role, "content": str(message.content)})
        return messages
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _json_preview(value: Any, limit: int = 900) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit] + ("..." if len(text) > limit else "")


def _clean_display_text(text: str, *, strip_leading_database_prefix: bool = False) -> str:
    value = str(text or "").replace("\r\n", "\n")
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = SOURCE_MARKER_PATTERN.sub("", value)
    value = CATALOG_SUFFIX_PATTERN.sub("", value)
    value = re.sub(r"(?m)^\s*[*•]\s+", "- ", value)
    value = value.replace("*", "")
    if strip_leading_database_prefix:
        value = LEADING_DATABASE_PREFIX_PATTERN.sub("", value, count=1)

    normalized_lines: list[str] = []
    previous_blank = False
    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


def _sanitize_answer_text(answer: str) -> str:
    value = _clean_display_text(answer)
    value = re.sub(r"^\s*结论[:：]\s*", "", value)
    value = LEADING_DATABASE_PREFIX_PATTERN.sub("", value, count=1)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value or "已完成检索，但模型未返回有效回答。"


def _remaining_budget_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


def _expand_question_with_geo_hints(question: str) -> str:
    value = question
    for alias, hint in UKRAINE_REGION_HINTS.items():
        if alias in value and hint not in value:
            value = value.replace(alias, hint)
    return value


def _is_broad_analysis_question(question: str) -> bool:
    text = question.strip()
    if not text:
        return False
    if "最近一次" in text or "最新事件" in text or "最后一次" in text:
        return False
    if "近几年" in text or "近年" in text:
        return True
    return bool(BROAD_QUERY_HINT_PATTERN.search(text) and re.search(r"(20\d{2}|全年|近年|近几年)", text))


def _compact_text(text: str, limit: int = 520) -> str:
    value = " ".join(_clean_display_text(text).split())
    return value[:limit] + ("..." if len(value) > limit else "")


def _localize_term(value: Any, mapping: dict[str, str]) -> str:
    text = str(value or "").strip()
    return _clean_display_text(mapping.get(text, text))


def _humanize_query_name(name: str) -> str:
    return name.replace("_", " ").strip()


def _format_location(row: dict[str, Any]) -> str:
    return " / ".join(
        [
            _clean_display_text(str(value))
            for value in (row.get("country"), row.get("admin1"), row.get("location_name"))
            if value not in (None, "")
        ]
    )


def _format_event_type(row: dict[str, Any]) -> str:
    main_type = _localize_term(row.get("event_type"), EVENT_TYPE_LABELS)
    sub_type = _localize_term(row.get("sub_event_type"), SUB_EVENT_TYPE_LABELS)
    if main_type and sub_type:
        return f"{main_type}（{sub_type}）"
    return main_type or sub_type


def _format_actor_summary(row: dict[str, Any]) -> str:
    actors = [
        _clean_display_text(str(value))
        for value in (row.get("actor1_name"), row.get("actor2_name"))
        if value not in (None, "")
    ]
    if actors:
        return "、".join(dict.fromkeys(actors))
    actor_types = [
        _localize_term(value, ACTOR_TYPE_LABELS)
        for value in (row.get("actor1_type"), row.get("actor2_type"))
        if value not in (None, "")
    ]
    return "、".join(dict.fromkeys(actor_types))


def _detect_count_key(row: dict[str, Any]) -> str | None:
    for key in row.keys():
        lowered = key.lower()
        if lowered in {"count", "total", "total_events", "event_count", "events", "occurrences"}:
            return key
        if lowered.endswith("_count") or lowered.endswith("_total"):
            return key
    return None


def _format_dimension_value(key: str, value: Any) -> str:
    if value in (None, ""):
        return ""
    if key == "event_type":
        return _localize_term(value, EVENT_TYPE_LABELS)
    if key == "sub_event_type":
        return _localize_term(value, SUB_EVENT_TYPE_LABELS)
    if key in {"actor1_name", "actor2_name", "admin1", "country", "location_name"}:
        return _clean_display_text(str(value))
    if key == "year":
        return f"{value}年"
    if key in {"entity_type", "relation_type", "event_title", "location_name", "actor_names", "source_label"}:
        return _clean_display_text(str(value))
    return _clean_display_text(str(value))


def _row_to_source_excerpt(row: dict[str, Any]) -> str:
    for key in ("evidence_text", "quote_text", "summary", "text"):
        value = _compact_text(str(row.get(key) or ""), 180)
        if value:
            return value
    if row.get("event_title"):
        parts = [
            str(value)
            for value in (
                row.get("event_date") or row.get("event_time_raw"),
                row.get("location_name"),
                row.get("event_type"),
                row.get("event_title"),
            )
            if value not in (None, "")
        ]
        if parts:
            return "；".join(_clean_display_text(part) for part in parts)
    note = _compact_text(str(row.get("notes") or ""), 140)
    if note:
        return note
    event_type = _format_event_type(row)
    location = _format_location(row)
    date = row.get("event_date") or row.get("date")
    parts = [str(value) for value in (date, location, event_type) if value not in (None, "")]
    if parts:
        return "；".join(parts)
    return _compact_text(_json_preview(row, 180), 180)


def _summarize_generic_sql_result(result: dict[str, Any]) -> str:
    rows = result.get("rows") or []
    if not rows:
        return f"{_humanize_query_name(str(result.get('name') or '查询结果'))}未返回有效记录。"
    first = rows[0]
    count_key = _detect_count_key(first)
    if count_key:
        label_keys = [key for key in first.keys() if key != count_key][:2]
        lines = [f"围绕“{_humanize_query_name(str(result.get('name') or '查询结果'))}”，检索返回 {len(rows)} 条聚合结果。"]
        preview_items: list[str] = []
        for row in rows[:5]:
            labels = [_format_dimension_value(key, row.get(key)) for key in label_keys if row.get(key) not in (None, "")]
            if labels:
                preview_items.append(f"{' / '.join(labels)}：{row.get(count_key)}")
            else:
                preview_items.append(f"{row.get(count_key)}")
        if preview_items:
            lines.append("主要结果包括：" + "；".join(preview_items) + "。")
        return "\n".join(lines)

    if "event_date" in first and ("event_type" in first or "sub_event_type" in first):
        date = first.get("event_date") or "未知时间"
        location = _format_location(first)
        event_type = _format_event_type(first)
        actor_summary = _format_actor_summary(first)
        event_title = _clean_display_text(str(first.get("event_title") or ""))
        lines = [f"检索命中了 {len(rows)} 条事件记录，其中首条记录时间为 {date}。"]
        if event_title:
            lines.append(f"事件线索：{event_title}。")
        if location:
            lines.append(f"地点位于 {location}。")
        if event_type:
            lines.append(f"事件类型表现为 {event_type}。")
        if actor_summary:
            lines.append(f"相关主体包括 {actor_summary}。")
        note = _compact_text(str(first.get("notes") or first.get("summary") or first.get("evidence_text") or ""), 140)
        if note:
            lines.append(f"记录摘要：{note}")
        return "\n".join(lines)

    lines = [f"围绕“{_humanize_query_name(str(result.get('name') or '查询结果'))}”，当前返回 {len(rows)} 条记录。"]
    sample_pairs: list[str] = []
    for key, value in list(first.items())[:4]:
        if value in (None, ""):
            continue
        sample_pairs.append(f"{key}: {value}")
    if sample_pairs:
        lines.append("首条结果摘要：" + "；".join(sample_pairs) + "。")
    return "\n".join(lines)


def _build_sql_digest(sql_results: list[dict[str, Any]]) -> str:
    if not sql_results:
        return "无结构化数据库结果。"
    sections: list[str] = []
    for result in sql_results[:3]:
        sections.append(_summarize_generic_sql_result(result))
    return "\n\n".join(sections)


def _build_chunk_digest(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "无材料片段命中。"
    lines: list[str] = []
    for row in chunks[:4]:
        title = str(row.get("document_title") or f"document-{row.get('document_id')}")
        chunk_index = int(row.get("chunk_index") or 0)
        excerpt = _compact_text(str(row.get("text") or ""), 180)
        lines.append(f"- {title} 第 {chunk_index + 1} 段：{excerpt}")
    return "\n".join(lines)


def _build_post_digest(posts: list[dict[str, Any]]) -> str:
    if not posts:
        return "无公开文本样本命中。"
    lines: list[str] = []
    for post in posts[:3]:
        label = str(post.get("screen_name") or post.get("msg_id") or "公开文本")
        excerpt = _compact_text(str(post.get("text") or ""), 140)
        lines.append(f"- {label}：{excerpt}")
    return "\n".join(lines)


def _material_context_note(
    document_id: int | None,
    document_ids: list[int] | None,
    case_id: int | None,
    chunks: list[dict[str, Any]],
) -> str:
    if document_id is None and not document_ids and case_id is None:
        return "本轮未附加任何用户材料，不得把历史上传文档视为当前问题证据。"
    if not chunks:
        return "本轮附加了用户材料，但当前没有命中可用片段。"
    if case_id is not None:
        return f"本轮附加了用户材料范围 case_id={case_id}，材料片段仅限本轮导入文件。"
    return "本轮附加了用户材料，以下材料片段仅限于当前关联文档。"


def _database_timeliness_note(sql_results: list[dict[str, Any]]) -> str:
    if not sql_results:
        return "当前回答未直接依赖结构化事件数据库。"
    uses_public_event_db = False
    uses_case_tables = False
    latest_dates: list[str] = []
    for result in sql_results:
        sql_text = str(result.get("sql") or "").lower()
        if "conflict_events" in sql_text:
            uses_public_event_db = True
        if "intelligence_" in sql_text:
            uses_case_tables = True
        for row in result.get("rows", [])[:5]:
            value = row.get("event_date") or row.get("date")
            if value not in (None, ""):
                latest_dates.append(str(value))
    if uses_case_tables and not uses_public_event_db:
        return "本次回答引用了当前上传材料的结构化抽取结果；抽取结果仍需结合原文证据判断可靠性。"
    latest_date = max(latest_dates) if latest_dates else ""
    if latest_date:
        return f"本次回答引用了结构化事件数据库；该数据库的相关记录最晚日期为 {latest_date}，可能存在采集、整理和发布延迟。"
    return "本次回答引用了结构化事件数据库，但数据库记录可能存在采集、整理和发布延迟。"


def _normalize_plan(
    plan: dict[str, Any],
    question: str,
    document_id: int | None,
    document_ids: list[int] | None = None,
    case_id: int | None = None,
) -> dict[str, Any]:
    sql_queries: list[dict[str, str]] = []
    raw_queries = plan.get("sql_queries")
    if isinstance(raw_queries, list):
        for item in raw_queries[:4]:
            if not isinstance(item, dict):
                continue
            sql_queries.append(
                {
                    "name": str(item.get("name") or f"query_{len(sql_queries) + 1}")[:80],
                    "sql": str(item.get("sql") or ""),
                    "purpose": str(item.get("purpose") or "").strip().lower()[:32],
                }
            )

    raw_doc = plan.get("document_retrieval")
    doc_query = question
    has_material_scope = bool(document_id or document_ids or case_id)
    doc_enabled = has_material_scope
    doc_limit = 8
    if isinstance(raw_doc, dict):
        doc_enabled = bool(raw_doc.get("enabled", doc_enabled))
        if raw_doc.get("query"):
            doc_query = str(raw_doc.get("query"))
        if raw_doc.get("limit") is not None:
            try:
                doc_limit = max(1, min(int(raw_doc.get("limit")), 12))
            except (TypeError, ValueError):
                doc_limit = 8
    elif plan.get("use_documents") is not None:
        doc_enabled = bool(plan.get("use_documents"))
    if not has_material_scope:
        doc_enabled = False
    else:
        doc_enabled = True

    raw_posts = plan.get("public_post_retrieval")
    post_query = question
    post_enabled = False
    post_limit = 5
    if isinstance(raw_posts, dict):
        post_enabled = bool(raw_posts.get("enabled", False))
        if raw_posts.get("query"):
            post_query = str(raw_posts.get("query"))
        if raw_posts.get("limit") is not None:
            try:
                post_limit = max(1, min(int(raw_posts.get("limit")), 10))
            except (TypeError, ValueError):
                post_limit = 5
    elif plan.get("use_public_posts") is not None:
        post_enabled = bool(plan.get("use_public_posts"))

    answer_style = plan.get("answer_style") if isinstance(plan.get("answer_style"), dict) else {}
    focus = str(answer_style.get("focus") or "先直接回答用户问题，再补充必要背景或依据。")
    structure = str(answer_style.get("structure") or "按问题复杂度自适应；简单问题直接作答，复杂问题可用总分或总分总。")

    risk_notes_raw = plan.get("material_risk_notes")
    risk_notes = [str(item) for item in risk_notes_raw[:5]] if isinstance(risk_notes_raw, list) else []
    query_strategy = str(plan.get("query_strategy") or "").strip().lower()
    if query_strategy not in {"direct_detail", "broad_summary", "mixed"}:
        query_strategy = "broad_summary" if _is_broad_analysis_question(question) else "direct_detail"

    return {
        "analysis_goal": str(plan.get("analysis_goal") or "综合回答用户问题"),
        "query_strategy": query_strategy,
        "sql_queries": sql_queries,
        "document_retrieval": {
            "enabled": doc_enabled,
            "query": doc_query,
            "limit": doc_limit,
        },
        "public_post_retrieval": {
            "enabled": post_enabled,
            "query": post_query,
            "limit": post_limit,
        },
        "answer_style": {
            "focus": focus,
            "structure": structure,
        },
        "material_risk_notes": risk_notes,
        "document_id": document_id,
        "document_ids": document_ids or [],
        "case_id": case_id,
    }


def _normalize_sql(sql: str) -> str:
    value = (sql or "").strip().strip("`")
    value = re.sub(r"```(?:sql)?|```", "", value, flags=re.IGNORECASE).strip()
    value = value.rstrip(";").strip()
    return value


def _validate_sql(sql: str) -> str:
    value = _normalize_sql(sql)
    if not value.lower().startswith("select"):
        raise ValueError("AI 生成了非 SELECT 查询，已拒绝执行。")
    if ";" in value or FORBIDDEN_SQL.search(value):
        raise ValueError("AI 生成的 SQL 包含不安全语句，已拒绝执行。")
    referenced = {name.lower() for name in re.findall(r"\b(?:from|join)\s+`?([a-zA-Z_][\w]*)`?", value, re.IGNORECASE)}
    if not referenced:
        raise ValueError("AI 生成的 SQL 未引用任何允许的数据表。")
    if not referenced.issubset(ALLOWED_TABLES):
        raise ValueError(f"AI 生成的 SQL 引用了未授权表：{', '.join(sorted(referenced - ALLOWED_TABLES))}")
    if not re.search(r"\blimit\s+\d+\b", value, flags=re.IGNORECASE):
        value = f"{value} LIMIT 20"
    else:
        value = re.sub(
            r"\blimit\s+(\d+)\b",
            lambda match: f"LIMIT {min(int(match.group(1)), 50)}",
            value,
            flags=re.IGNORECASE,
        )
    return value


def _is_simple_count_sql(sql: str) -> bool:
    lowered = _normalize_sql(sql).lower()
    return "count(" in lowered and " group by " not in lowered


def _is_detail_sql(sql: str) -> bool:
    lowered = _normalize_sql(sql).lower()
    aggregate_markers = ("count(", "sum(", "avg(", "min(", "max(", "group by ")
    return not any(marker in lowered for marker in aggregate_markers)


def _extract_conflict_events_where_clause(sql: str) -> str | None:
    normalized = re.sub(r"\s+", " ", _normalize_sql(sql))
    lowered = normalized.lower()
    if " join " in lowered:
        return None
    if not re.search(r"\bfrom\s+`?conflict_events`?\b", lowered):
        return None
    match = re.search(r"\bwhere\b\s+(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)", normalized, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _build_preflight_count_query(query: dict[str, str]) -> dict[str, str] | None:
    sql = str(query.get("sql") or "")
    if _is_simple_count_sql(sql):
        return None
    where_clause = _extract_conflict_events_where_clause(sql)
    if where_clause is None:
        return None
    count_sql = "SELECT COUNT(*) AS matched_rows FROM conflict_events"
    if where_clause:
        count_sql += f" WHERE {where_clause}"
    return {
        "name": f"{query.get('name') or 'query'} 匹配规模",
        "sql": count_sql,
        "purpose": "count",
        "source_name": str(query.get("name") or "query"),
    }


def _prepare_sql_queries_for_execution(plan: dict[str, Any], question: str) -> tuple[list[dict[str, str]], bool]:
    planned_queries = plan.get("sql_queries") if isinstance(plan.get("sql_queries"), list) else []
    query_strategy = str(plan.get("query_strategy") or "")
    broad_query = query_strategy == "broad_summary" or _is_broad_analysis_question(question)
    prepared: list[dict[str, str]] = []
    for item in planned_queries[:4]:
        if not isinstance(item, dict):
            continue
        query = {
            "name": str(item.get("name") or "planned_query"),
            "sql": str(item.get("sql") or ""),
            "purpose": str(item.get("purpose") or "").strip().lower(),
        }
        if broad_query:
            preflight = _build_preflight_count_query(query)
            if preflight:
                prepared.append(preflight)
        prepared.append(query)
    return prepared, broad_query


def _extract_result_count(result: dict[str, Any]) -> int | None:
    rows = result.get("rows") or []
    if not rows:
        return 0
    first = rows[0]
    count_key = _detect_count_key(first)
    if not count_key:
        return None
    try:
        return int(first.get(count_key) or 0)
    except (TypeError, ValueError):
        return None


def _plan_with_llm(
    question: str,
    document_id: int | None,
    document_ids: list[int] | None = None,
    case_id: int | None = None,
    request_timeout_sec: float | None = None,
) -> dict[str, Any]:
    client, model = require_openai_client()
    scoped_question = _expand_question_with_geo_hints(question)
    case_scope_rule = (
        f"当前问题携带了用户上传材料范围 case_id={case_id}。若查询 intelligence_* 表，必须在 SQL 中加入 case_id = {case_id}；"
        "应优先利用 intelligence_events、intelligence_entities、intelligence_relations、intelligence_evidences 获取当前上传材料的结构化结果。"
        if case_id is not None
        else "当前问题没有用户上传材料范围，除非用户问题明确指定，否则不要查询 intelligence_* 当前上传材料表。"
    )
    system = f"""你是公开情报系统的检索规划器。你不直接回答问题，只规划检索步骤。

{DATABASE_SCHEMA_PROMPT}

系统主题默认是俄乌冲突公开情报分析。若用户没有明确说明其他国家或战区，应优先把地名理解为俄乌语境下的地点，例如“苏梅州”默认对应 Ukraine / Sumy Oblast，而不是其他国家的相似拼写地区。

上传材料范围规则：
{case_scope_rule}

请严格输出 JSON：
{{
  "analysis_goal": "不超过30字的简短目标",
  "query_strategy": "direct_detail 或 broad_summary 或 mixed",
  "sql_queries": [
    {{"name": "短名称", "purpose": "count 或 aggregation 或 detail", "sql": "SELECT ... LIMIT 20"}}
  ],
  "document_retrieval": {{
    "enabled": false,
    "query": "",
    "limit": 6
  }},
  "public_post_retrieval": {{
    "enabled": false,
    "query": "",
    "limit": 4
  }},
  "answer_style": {{
    "focus": "不超过24字",
    "structure": "直接回答 或 总分 或 总分总"
  }}
}}

要求：
1. sql_queries 最多 4 条。
2. SQL 必须是 MySQL SELECT，只能使用上面列出的表和字段。
3. 若问题是“态势、趋势、近几年、全年、分布、主要类型、热点、阶段演变”等大范围问题，应把 query_strategy 设为 broad_summary。
4. broad_summary 必须优先生成 count/aggregation 查询，不要直接查询大量明细行；detail 查询最多 1 条，且仅用于少量背景样本。
5. direct_detail 只用于“最近一次事件、某个具体事件、某个具体地点的单一事实”这类窄问题。
6. 你还可以规划文档召回和公开文本召回，但若当前没有用户附加材料或 document_id={document_id}、document_ids={document_ids or []}、case_id={case_id} 都为空，document_retrieval.enabled 必须为 false，不能把历史上传文档当成当前问题证据。
7. 若 case_id 不为空，document_retrieval.enabled 通常应为 true，用当前材料原文片段补充结构化抽取结果。
8. 只有问题明确需要舆情/公开文本侧补充时，public_post_retrieval.enabled 才设为 true。
9. answer_style 只写很短的偏好，不要写成长段说明。
10. 不要把“模式”暴露给用户，不要输出多余解释，只返回 JSON。"""
    payload = create_json_chat_completion(
        client,
        model,
        messages=_chat_messages(system, f"用户问题：{scoped_question}"),
        temperature=0.1,
        max_tokens=900,
        timeout=request_timeout_sec,
    )
    return payload if isinstance(payload, dict) else {}


def _execute_sql_queries(queries: list[dict[str, str]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query in queries[:3]:
        name = str(query.get("name") or f"query_{len(results) + 1}")[:80]
        sql = _validate_sql(str(query.get("sql") or ""))
        with get_database().session() as conn:
            rows = conn.execute(sql).fetchall()
        results.append({"name": name, "sql": sql, "rows": [dict(row) for row in rows]})
    return results


def _resolve_material_document_ids(
    document_id: int | None = None,
    document_ids: list[int] | None = None,
    case_id: int | None = None,
) -> list[int]:
    resolved: list[int] = []
    if document_id:
        resolved.append(int(document_id))
    for item in document_ids or []:
        try:
            resolved.append(int(item))
        except (TypeError, ValueError):
            continue
    if case_id is not None:
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
        resolved.extend(int(row["document_id"]) for row in rows)
    unique: list[int] = []
    seen: set[int] = set()
    for item in resolved:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _retrieve_document_chunks(
    question: str,
    document_id: int | None = None,
    document_ids: list[int] | None = None,
    case_id: int | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    scoped_document_ids = _resolve_material_document_ids(document_id, document_ids, case_id)
    if scoped_document_ids:
        placeholders = ", ".join(["?"] * len(scoped_document_ids))
        clauses.append(f"dc.document_id IN ({placeholders})")
        params.extend(scoped_document_ids)
    else:
        return []
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_database().session() as conn:
        rows = conn.execute(
            f"""
            SELECT dc.id AS chunk_id, dc.document_id, dc.chunk_index, dc.page_no, dc.text,
                   COALESCE(d.source_name, d.title, CONCAT('document-', d.id)) AS document_title
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            {where}
            ORDER BY dc.id DESC
            LIMIT 800
            """,
            params,
        ).fetchall()
    chunk_rows = [dict(row) for row in rows]
    if not chunk_rows:
        return []
    chunk_ids = [int(row["chunk_id"]) for row in chunk_rows]
    try:
        ranked = get_embedding_service().rank_chunks(question, chunk_ids, top_k=limit)
        rank_map = {chunk_id: score for chunk_id, score in ranked if score >= 0.18}
        selected = [row for row in chunk_rows if int(row["chunk_id"]) in rank_map]
        selected.sort(key=lambda row: rank_map[int(row["chunk_id"])], reverse=True)
        if selected:
            return selected[:limit]
    except Exception:
        pass
    terms = [term for term in re.split(r"\s+", question) if len(term) >= 2]
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in chunk_rows:
        text = str(row.get("text") or "").lower()
        score = sum(1 for term in terms if term.lower() in text)
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for score, row in scored[:limit] if score > 0]


def _retrieve_public_posts(question: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        store = get_weibo_store()
        if not store.is_imported():
            return []
        return store.search_posts(question, limit=limit)
    except Exception:
        return []


def _sources_from_sql_results(sql_results: list[dict[str, Any]]) -> list[QASource]:
    sources: list[QASource] = []
    for result in sql_results:
        purpose = str(result.get("purpose") or "").strip().lower()
        if purpose == "count":
            excerpt = _summarize_generic_sql_result(result)
            sources.append(
                QASource(
                    source_type="database",
                    label=_humanize_query_name(str(result["name"])),
                    event_id_cnty=None,
                    excerpt=_compact_text(excerpt, 180),
                )
            )
            continue
        row_limit = 2 if purpose == "aggregation" else 4
        for row in result["rows"][:row_limit]:
            event_id = row.get("event_code") or row.get("event_id_cnty")
            date = row.get("event_date") or row.get("event_time_raw") or row.get("date") or ""
            label = f"{_humanize_query_name(str(result['name']))} · {date}".strip(" ·")
            excerpt = _row_to_source_excerpt(row)
            chunk_id = None
            try:
                if row.get("chunk_id") not in (None, ""):
                    chunk_id = int(row.get("chunk_id"))
            except (TypeError, ValueError):
                chunk_id = None
            source_type = "case" if "intelligence_" in str(result.get("sql") or "").lower() else "database"
            sources.append(
                QASource(
                    source_type=source_type,
                    label=label,
                    chunk_id=chunk_id,
                    event_id_cnty=str(event_id) if event_id else None,
                    excerpt=_compact_text(str(excerpt)),
                )
            )
    return sources


def _sources_from_chunks(chunks: list[dict[str, Any]]) -> list[QASource]:
    return [
        QASource(
            source_type="chunk",
            label=str(row.get("document_title") or f"document-{row.get('document_id')}"),
            chunk_id=int(row["chunk_id"]),
            paragraph_index=int(row.get("chunk_index") or 0),
            page_number=row.get("page_no"),
            excerpt=_compact_text(str(row.get("text") or "")),
        )
        for row in chunks
    ]


def _sources_from_posts(posts: list[dict[str, Any]]) -> list[QASource]:
    return [
        QASource(
            source_type="weibo",
            label=f"公开文本 · {post.get('screen_name') or post.get('msg_id') or 'unknown'}",
            excerpt=_compact_text(str(post.get("text") or "")),
        )
        for post in posts
    ]


def _generation_failure_message(
    stage: str,
    sql_results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    posts: list[dict[str, Any]],
) -> str:
    if stage == "planning":
        return "本次问题的检索规划未完成，模型服务超时或不可用，请稍后重试。"

    parts = ["本次检索已完成，但结论生成阶段未成功完成。"]
    if sql_results:
        parts.append(f"当前已取得 {len(sql_results)} 组结构化检索结果。")
    if chunks:
        parts.append(f"同时命中 {len(chunks)} 段材料片段。")
    if posts:
        parts.append(f"并召回 {len(posts)} 条公开文本样本。")
    parts.append("建议稍后重试，或缩小问题范围后再次提问。")
    return " ".join(parts)


def _synthesize_answer(
    question: str,
    plan: dict[str, Any],
    sql_results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    sources: list[QASource],
    compact: bool = False,
    request_timeout_sec: float | None = None,
) -> tuple[str, list[int]]:
    client, model = require_openai_client()
    evidence_lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        label = source.label or source.source_type
        meta_parts: list[str] = []
        if source.event_id_cnty:
            meta_parts.append(f"事件编号 {source.event_id_cnty}")
        if source.chunk_id:
            meta_parts.append(f"材料片段 {source.chunk_id}")
        meta = f"（{'；'.join(meta_parts)}）" if meta_parts else ""
        evidence_lines.append(f"证据{index}：{_clean_display_text(label)}{meta}：{_clean_display_text(source.excerpt)}")

    sql_digest = _build_sql_digest(sql_results[:2] if compact else sql_results)
    chunk_digest = _build_chunk_digest(chunks[:3] if compact else chunks)
    post_digest = _build_post_digest(posts[:2] if compact else posts)
    material_note = _material_context_note(
        plan.get("document_id"),
        plan.get("document_ids") if isinstance(plan.get("document_ids"), list) else [],
        plan.get("case_id"),
        chunks,
    )
    database_note = _database_timeliness_note(sql_results)

    system = f"""你是俄乌冲突公开情报综合分析助手。

你面向终端用户输出最终答案，不是输出数据库结果、系统中间态或程序日志。
你已经拿到了检索后的证据摘要，现在只负责把这些证据整理成自然、准确、可读的中文回答。

回答规则：
1. 第一行直接回答用户问题，不要用“根据数据库记录”“根据检索结果”“根据结构化事件库”等套话开头。
2. 回答结构要随问题复杂度自适应：简单事实问题可直接用 1 至 2 段短文；比较、趋势、核验问题可用总分或总分总，最多 4 个短点。
3. 不要输出 Markdown 语法、星号、加粗标记、井号、代码框、[S1] 这类引用编号。
4. 不要暴露 SQL、表名、字段名、内部实现、模式路由，也不要机械罗列数据库字段。
5. 避免输出无意义的实体尾注或目录后缀，例如“(2000-)”；除非它本身对答案有实质意义。
6. 只有当本轮确有用户材料时，才能讨论材料内容；如果本轮没有附加材料，严禁把历史上传文档当成当前问题证据。
7. 如果用户上传/粘贴材料，而公开事件库暂时无法核验，应明确写出“公开事件库暂无法独立核验该材料”，然后在“假设材料为真”的前提下继续分析。
8. 若回答依赖结构化事件数据库，可以在结尾自然补一句时效性提醒，但不要机械写成固定栏目，除非用户明确要求分析局限。
9. 不得编造证据中没有的具体事件编号、日期、伤亡数字、地点或来源。
10. 正文总长度控制在 800 个汉字以内；{'若仍失败，请压缩到 220-480 字。' if compact else '常规情况下控制在 180-800 字。'}
11. 输出必须是 JSON：{{"answer": "中文回答", "cited_source_numbers": [1, 2]}}。
12. cited_source_numbers 只能引用下方证据编号，答案正文不要出现这些编号。"""
    user = f"""用户问题：
{question}

分析目标：
{str(plan.get("analysis_goal") or "综合回答用户问题")}

回答重点偏好：
{str((plan.get("answer_style") or {}).get("focus") or "直接回答用户问题并保持分析性表达。")}

表达方式偏好：
{str((plan.get("answer_style") or {}).get("structure") or "按问题复杂度自适应组织内容")}

材料上下文说明：
{material_note}

如需提示时效，可参考：
{database_note}

结构化检索整理：
{sql_digest}

文档 RAG 片段：
{chunk_digest}

公开文本样本：
{post_digest}

可引用证据：
{chr(10).join(evidence_lines[:4] if compact else evidence_lines[:8]) if evidence_lines else "无"}"""
    payload = create_json_chat_completion(
        client,
        model,
        messages=_chat_messages(system, user),
        temperature=0.1,
        max_tokens=420 if compact else 680,
        timeout=request_timeout_sec,
    )
    answer = _sanitize_answer_text(str(payload.get("answer") or ""))
    cited_raw = payload.get("cited_source_numbers") or []
    cited: list[int] = []
    if isinstance(cited_raw, list):
        for item in cited_raw:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= len(sources) and number not in cited:
                cited.append(number)
    if not answer:
        answer = "已完成检索，但模型未返回有效回答。请换一种问法或检查模型服务。"
    if not cited and sources:
        cited = list(range(1, min(4, len(sources)) + 1))
    return answer, cited


def answer_unified_question(
    question: str,
    document_id: int | None = None,
    document_ids: list[int] | None = None,
    case_id: int | None = None,
) -> QAResponse:
    q = question.strip()
    if not q:
        raise ValueError("问题不能为空。")

    start = time.perf_counter()
    settings = get_settings()
    deadline = start + max(12.0, settings.qa_request_timeout_sec - 4.0)
    logger.info(
        "Unified QA planning stage started: document=%s documents=%s case=%s budget=%.1fs question=%s",
        document_id,
        document_ids or [],
        case_id,
        max(0.0, deadline - start),
        q[:160],
    )
    try:
        plan_timeout = min(settings.openai_request_timeout_sec, max(6.0, _remaining_budget_seconds(deadline)))
        raw_plan = _plan_with_llm(
            q,
            document_id,
            document_ids=document_ids or [],
            case_id=case_id,
            request_timeout_sec=plan_timeout,
        )
        plan = _normalize_plan(raw_plan, q, document_id, document_ids=document_ids or [], case_id=case_id)
        logger.info(
            "Unified QA planning stage finished: sql=%s use_documents=%s use_public_posts=%s",
            len(plan.get("sql_queries") or []),
            bool((plan.get("document_retrieval") or {}).get("enabled")),
            bool((plan.get("public_post_retrieval") or {}).get("enabled")),
        )
    except Exception as exc:
        logger.warning("Unified QA planner failed: %s", exc)
        return QAResponse(
            answer=_generation_failure_message("planning", [], [], []),
            mode="unified",
            sources=[],
            subgraph_nodes=[],
            subgraph_edges=[],
            context_summary={
                "planner_error": str(exc),
                "sql_results": [],
                "sql_errors": [],
                "document_chunks": 0,
                "public_posts": 0,
            },
        )

    queries, broad_query = _prepare_sql_queries_for_execution(plan, q)

    sql_results: list[dict[str, Any]] = []
    sql_errors: list[str] = []
    preflight_counts: dict[str, int] = {}
    for item in queries[:8]:
        purpose = str(item.get("purpose") or "").strip().lower()
        source_name = str(item.get("source_name") or item.get("name") or "")
        if broad_query and purpose != "count" and _is_detail_sql(str(item.get("sql") or "")):
            matched_rows = preflight_counts.get(source_name)
            if matched_rows is not None and matched_rows > LARGE_RESULT_THRESHOLD:
                sql_errors.append(f"{source_name} 预计命中 {matched_rows} 条原始事件，已跳过明细查询，保留聚合结果。")
                continue
        try:
            result = _execute_sql_queries([item])[0]
            result["purpose"] = purpose
            result["source_name"] = source_name
            sql_results.append(result)
            if purpose == "count":
                matched = _extract_result_count(result)
                if matched is not None and source_name:
                    preflight_counts[source_name] = matched
        except Exception as exc:
            sql_errors.append(str(exc))
    logger.info(
        "Unified QA retrieval stage finished: sql_results=%s sql_errors=%s broad_query=%s",
        len(sql_results),
        len(sql_errors),
        broad_query,
    )

    document_plan = plan.get("document_retrieval") if isinstance(plan.get("document_retrieval"), dict) else {}
    public_post_plan = plan.get("public_post_retrieval") if isinstance(plan.get("public_post_retrieval"), dict) else {}
    use_documents = bool(document_plan.get("enabled"))
    document_query = str(document_plan.get("query") or q)
    document_limit = int(document_plan.get("limit") or 8)
    chunks = (
        _retrieve_document_chunks(
            document_query,
            document_id=document_id,
            document_ids=document_ids or [],
            case_id=case_id,
            limit=document_limit,
        )
        if use_documents
        else []
    )
    use_public_posts = bool(public_post_plan.get("enabled", False))
    public_post_query = str(public_post_plan.get("query") or q)
    public_post_limit = int(public_post_plan.get("limit") or 5)
    posts = _retrieve_public_posts(public_post_query, limit=public_post_limit) if use_public_posts else []

    sources = [*_sources_from_sql_results(sql_results), *_sources_from_chunks(chunks), *_sources_from_posts(posts)]
    if not sql_results and not chunks and not posts:
        logger.info("Unified QA found no usable evidence for question=%s", q[:160])
        return QAResponse(
            answer="当前没有检索到足够证据来回答这个问题。建议换一个更具体的问法，或补充材料与时间、地点、主体等限定条件。",
            mode="unified",
            sources=[],
            subgraph_nodes=[],
            subgraph_edges=[],
            context_summary={
                "planner": plan,
                "sql_results": [],
                "sql_errors": sql_errors,
                "document_chunks": 0,
                "public_posts": 0,
            },
        )
    remaining_before_answer = _remaining_budget_seconds(deadline)
    logger.info(
        "Unified QA synthesis stage starting: remaining_budget=%.2fs chunks=%s posts=%s sources=%s",
        remaining_before_answer,
        len(chunks),
        len(posts),
        len(sources),
    )
    if remaining_before_answer < 6.0:
        logger.warning(
            "Unified QA skipped synthesis due to low remaining budget: %.2fs for question=%s",
            remaining_before_answer,
            q[:120],
        )
        cited_sources = sources[: min(4, len(sources))]
        return QAResponse(
            answer="检索已完成，但当前问题范围较大，模型没有足够时间在本轮内完成整理。建议把问题缩小到时间段、地区或主题后再问，例如限定某一年、某地区或某类事件。",
            mode="unified",
            sources=cited_sources,
            subgraph_nodes=[],
            subgraph_edges=[],
            context_summary={
                "planner": plan,
                "sql_results": [
                    {"name": result["name"], "sql": result["sql"], "row_count": len(result["rows"])}
                    for result in sql_results
                ],
                "sql_errors": sql_errors,
                "document_chunks": len(chunks),
                "public_posts": len(posts),
            },
        )
    try:
        answer, cited_numbers = _synthesize_answer(
            q,
            plan,
            sql_results,
            chunks,
            posts,
            sources,
            request_timeout_sec=min(settings.openai_request_timeout_sec, max(5.0, remaining_before_answer - 1.0)),
        )
    except Exception as exc:
        logger.warning("Unified QA answer generation failed, retry compact: %s", exc)
        remaining_for_retry = _remaining_budget_seconds(deadline)
        if remaining_for_retry < 5.0:
            answer = _generation_failure_message("answer", sql_results, chunks, posts)
            cited_numbers = list(range(1, min(4, len(sources)) + 1)) if sources else []
        else:
            try:
                answer, cited_numbers = _synthesize_answer(
                    q,
                    plan,
                    sql_results,
                    chunks,
                    posts,
                    sources,
                    compact=True,
                    request_timeout_sec=min(
                        settings.openai_request_timeout_sec,
                        max(4.0, remaining_for_retry - 0.5),
                    ),
                )
            except Exception as retry_exc:
                logger.warning("Unified QA compact answer generation failed: %s", retry_exc)
                answer = _generation_failure_message("answer", sql_results, chunks, posts)
                cited_numbers = list(range(1, min(4, len(sources)) + 1)) if sources else []
    cited_sources = [sources[number - 1] for number in cited_numbers] if sources else []
    if not cited_sources:
        cited_sources = sources[:6]

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "Unified QA finished in %sms (sql=%s, chunks=%s, posts=%s) for question=%s",
        elapsed_ms,
        len(sql_results),
        len(chunks),
        len(posts),
        q[:120],
    )

    return QAResponse(
        answer=answer,
        mode="unified",
        sources=cited_sources,
        subgraph_nodes=[],
        subgraph_edges=[],
        context_summary={
            "planner": plan,
            "sql_results": [
                {"name": result["name"], "sql": result["sql"], "row_count": len(result["rows"])}
                for result in sql_results
            ],
            "sql_errors": sql_errors,
            "document_chunks": len(chunks),
            "public_posts": len(posts),
        },
    )
