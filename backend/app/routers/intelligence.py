from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.config import get_settings
from app.database import get_database
from app.schemas.responses import (
    IntelligenceCaseCreate,
    IntelligenceCaseDocument,
    IntelligenceCaseEmbeddingResponse,
    IntelligenceCaseRecord,
    IntelligenceCaseStatus,
    IntelligenceCaseUploadResponse,
    IntelligenceEntity,
    IntelligenceEvent,
    KnowledgeGraphResponse,
    TimelinePoint,
)
from app.services.document_parser import parse_document
from app.services.intelligence_case_service import (
    CASE_FILE_LIMIT,
    attach_document_to_case,
    count_case_documents,
    create_case,
    get_case,
    get_case_graph,
    get_case_status,
    get_case_timeline,
    index_case_embeddings,
    list_case_documents,
    list_case_entities,
    list_case_events,
    rebuild_case_extractions,
)
from app.services.workspace_bootstrap import get_macro_workspace_id

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _dt_iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _mysql_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _store_uploaded_document(case_id: int, file: UploadFile) -> int:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX、TXT 材料。")

    settings = get_settings()
    workspace_id = get_macro_workspace_id()
    case_dir = settings.upload_dir / "cases" / str(case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    target = case_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    paragraphs = parse_document(target)
    if not paragraphs:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"{file.filename} 未解析出有效文本。")

    with get_database().session() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                workspace_id, title, source_name, source_type, file_type, file_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                paragraphs[0].document_topic,
                paragraphs[0].file_name,
                "intelligence_case",
                suffix.lstrip("."),
                str(target),
                "processed",
            ),
        )
        document_id = conn.lastrowid
        conn.executemany(
            """
            INSERT INTO document_chunks (
                document_id, chunk_index, text, page_no, source_path, file_modified_at,
                start_offset, end_offset
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    document_id,
                    item.paragraph_index,
                    item.text,
                    item.page_number,
                    item.source_path,
                    _mysql_datetime(item.file_modified_at_iso),
                    item.start_offset,
                    item.end_offset,
                )
                for item in paragraphs
            ],
        )
    return int(document_id)


@router.post("/cases", response_model=IntelligenceCaseRecord)
def create_intelligence_case(payload: IntelligenceCaseCreate | None = None) -> IntelligenceCaseRecord:
    return create_case(payload.title if payload else None)


@router.get("/cases/{case_id}", response_model=IntelligenceCaseStatus)
def intelligence_case_status(case_id: int) -> IntelligenceCaseStatus:
    try:
        return get_case_status(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_id}/documents", response_model=list[IntelligenceCaseDocument])
def intelligence_case_documents(case_id: int) -> list[IntelligenceCaseDocument]:
    try:
        get_case(case_id)
        return list_case_documents(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cases/{case_id}/documents", response_model=IntelligenceCaseUploadResponse)
def upload_intelligence_documents(
    case_id: int,
    files: list[UploadFile] = File(...),
) -> IntelligenceCaseUploadResponse:
    try:
        case = get_case(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not files:
        raise HTTPException(status_code=400, detail="请选择需要导入的材料。")
    existing_count = count_case_documents(case_id)
    if existing_count + len(files) > CASE_FILE_LIMIT:
        raise HTTPException(status_code=400, detail=f"一次分析最多支持 {CASE_FILE_LIMIT} 个文件。")

    try:
        for file in files:
            document_id = _store_uploaded_document(case_id, file)
            attach_document_to_case(case_id, document_id)
        rebuild_case_extractions(case_id)
        status = get_case_status(case_id)
        return IntelligenceCaseUploadResponse(case=status.case, documents=status.documents, status=status)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"情报材料处理失败: {exc}") from exc


@router.post("/cases/{case_id}/process", response_model=IntelligenceCaseStatus)
def process_intelligence_case(case_id: int) -> IntelligenceCaseStatus:
    try:
        get_case(case_id)
        rebuild_case_extractions(case_id)
        return get_case_status(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"情报材料处理失败: {exc}") from exc


@router.post("/cases/{case_id}/embeddings", response_model=IntelligenceCaseEmbeddingResponse)
def build_intelligence_case_embeddings(
    case_id: int,
    force: bool = Query(default=False),
) -> IntelligenceCaseEmbeddingResponse:
    try:
        return index_case_embeddings(case_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"语义索引生成失败: {exc}") from exc


@router.get("/cases/{case_id}/entities", response_model=list[IntelligenceEntity])
def intelligence_case_entities(
    case_id: int,
    limit: int = Query(default=120, ge=1, le=500),
) -> list[IntelligenceEntity]:
    try:
        get_case(case_id)
        return list_case_entities(case_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_id}/events", response_model=list[IntelligenceEvent])
def intelligence_case_events(
    case_id: int,
    limit: int = Query(default=120, ge=1, le=500),
) -> list[IntelligenceEvent]:
    try:
        get_case(case_id)
        return list_case_events(case_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_id}/graph", response_model=KnowledgeGraphResponse)
def intelligence_case_graph(case_id: int) -> KnowledgeGraphResponse:
    try:
        get_case(case_id)
        graph = get_case_graph(case_id)
        return KnowledgeGraphResponse(**graph)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_id}/timeline", response_model=list[TimelinePoint])
def intelligence_case_timeline(case_id: int) -> list[TimelinePoint]:
    return get_case_timeline(case_id)
