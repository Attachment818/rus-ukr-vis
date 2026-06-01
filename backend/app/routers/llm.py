from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.llm_client import llm_status, test_embedding_connection, test_llm_connection

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
def get_llm_status() -> dict:
    """Return non-secret LLM configuration status."""
    return llm_status()


@router.post("/test")
def test_llm() -> dict:
    """Call the configured OpenAI-compatible chat endpoint once."""
    try:
        return test_llm_connection()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"大模型连接测试失败: {exc}") from exc


@router.post("/embedding/test")
def test_embedding() -> dict:
    """Call the configured OpenAI-compatible embeddings endpoint once."""
    try:
        return test_embedding_connection()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"embedding 模型连接测试失败: {exc}") from exc
