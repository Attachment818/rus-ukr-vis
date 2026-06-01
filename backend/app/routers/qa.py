from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas.responses import QAResponse
from app.services.qa_service import answer_document_question

router = APIRouter(tags=["qa"])


class QAQuestionPayload(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/documents/{document_id}/qa", response_model=QAResponse)
def ask_document(document_id: int, payload: QAQuestionPayload) -> QAResponse:
    """图辅助检索 + LLM 作答，返回回答、chunk 溯源与子图。"""
    try:
        return answer_document_question(document_id, payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"问答失败: {exc}") from exc
