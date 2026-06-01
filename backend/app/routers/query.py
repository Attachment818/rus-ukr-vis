from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.schemas.responses import (
    ChatMessageRecord,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionCreate,
    ChatSessionRecord,
    QAResponse,
    QueryHistoryItem,
    ViewRecommendation,
    WorkspaceQueryRequest,
)
from app.services.chat_session_service import (
    add_message,
    create_session,
    get_session,
    list_messages,
    list_sessions,
    rename_session_from_question,
)
from app.services.ai_analyst_service import answer_unified_question
from app.services.query_history_service import count_query_history, list_query_history
from app.services.retrieval_service import recommend_views, run_workspace_query
from app.services.workspace_bootstrap import get_macro_workspace_id

router = APIRouter(tags=["query"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get("/chat/sessions", response_model=list[ChatSessionRecord])
def chat_sessions(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ChatSessionRecord]:
    return [ChatSessionRecord(**row) for row in list_sessions(limit=limit, offset=offset)]


@router.post("/chat/sessions", response_model=ChatSessionRecord)
def create_chat_session(payload: ChatSessionCreate | None = None) -> ChatSessionRecord:
    row = create_session(title=payload.title if payload else None)
    return ChatSessionRecord(**row)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageRecord])
def chat_session_messages(session_id: int) -> list[ChatMessageRecord]:
    try:
        return [ChatMessageRecord(**row) for row in list_messages(session_id)]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _run_chat_session_query(session_id: int, payload: ChatQueryRequest) -> ChatQueryResponse:
    started = time.perf_counter()
    logger.info(
        "Chat session query started: session=%s document=%s documents=%s case=%s question=%s",
        session_id,
        payload.document_id,
        payload.document_ids,
        payload.case_id,
        payload.question[:160],
    )
    before = list_messages(session_id)
    session = rename_session_from_question(session_id, payload.question) if not before else get_session(session_id)
    user_message = add_message(session_id, "user", payload.question)
    qa = answer_unified_question(
        question=payload.question,
        document_id=payload.document_id,
        document_ids=payload.document_ids,
        case_id=payload.case_id,
    )
    assistant_message = add_message(session_id, "assistant", qa.answer, qa.sources)
    try:
        from app.services.query_history_service import save_query_history

        save_query_history(get_macro_workspace_id(), payload.question, "unified", qa.answer)
    except Exception:
        pass
    session = get_session(session_id)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Chat session query finished: session=%s elapsed=%sms sources=%s",
        session_id,
        elapsed_ms,
        len(qa.sources),
    )
    return ChatQueryResponse(
        session=ChatSessionRecord(**session),
        user_message=ChatMessageRecord(**user_message),
        assistant_message=ChatMessageRecord(**assistant_message),
        qa=qa,
    )


@router.post("/chat/sessions/{session_id}/query", response_model=ChatQueryResponse)
async def chat_session_query(session_id: int, payload: ChatQueryRequest) -> ChatQueryResponse:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_chat_session_query, session_id, payload),
            timeout=settings.qa_request_timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        logger.warning(
            "Chat session query hit route timeout: session=%s timeout=%ss question=%s",
            session_id,
            settings.qa_request_timeout_sec,
            payload.question[:160],
        )
        raise HTTPException(status_code=504, detail="智能问答处理超时，请缩小问题范围或稍后重试。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"会话问答失败: {exc}") from exc


@router.post("/workspaces/{workspace_id}/query", response_model=QAResponse)
async def workspace_query(workspace_id: int, payload: WorkspaceQueryRequest) -> QAResponse:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_workspace_query,
                question=payload.question,
                mode=payload.mode,
                document_id=payload.document_id,
                event_id_cnty=payload.event_id_cnty,
                workspace_id=workspace_id,
            ),
            timeout=settings.qa_request_timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="问答处理超时，请缩小问题范围或稍后重试。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc


@router.get("/workspaces/{workspace_id}/viz/recommend", response_model=list[ViewRecommendation])
def viz_recommend(
    workspace_id: int,
    mode: str = Query(default="local"),
    question: str = Query(default=""),
) -> list[ViewRecommendation]:
    items = recommend_views(mode, question or "冲突分析")
    return [ViewRecommendation(**item) for item in items]


@router.get("/workspaces/{workspace_id}/query/history", response_model=list[QueryHistoryItem])
def query_history(
    workspace_id: int,
    limit: int = Query(default=15, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
) -> list[QueryHistoryItem]:
    rows = list_query_history(workspace_id, limit=limit, offset=offset, keyword=keyword)
    return [QueryHistoryItem(**row) for row in rows]


@router.get("/workspaces/{workspace_id}/query/history/count")
def query_history_count(
    workspace_id: int,
    keyword: str | None = Query(default=None),
) -> dict:
    return {"total": count_query_history(workspace_id, keyword=keyword)}
