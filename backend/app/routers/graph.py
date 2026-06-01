from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.responses import DocumentGraphResponse, GraphExtractResponse
from app.services.graph_extraction_service import extract_and_store_graph, load_graph

router = APIRouter(tags=["graph"])


@router.post("/documents/{document_id}/extract-graph", response_model=GraphExtractResponse)
def extract_document_graph(document_id: int) -> GraphExtractResponse:
    """对指定文档的 chunks 调用 LLM 抽取实体/关系，写入 Neo4j。"""
    try:
        node_count, edge_count, message = extract_and_store_graph(document_id)
        return GraphExtractResponse(
            document_id=document_id,
            node_count=node_count,
            edge_count=edge_count,
            message=message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图谱抽取失败: {exc}") from exc


@router.get("/documents/{document_id}/graph", response_model=DocumentGraphResponse)
def get_document_graph(document_id: int) -> DocumentGraphResponse:
    """从 Neo4j 读取文档知识图谱；未抽取时返回空图，避免把正常流程显示成错误。"""
    graph = load_graph(document_id)
    if graph is None:
        return DocumentGraphResponse(document_id=document_id, nodes=[], edges=[], updated_at=None)
    return graph
