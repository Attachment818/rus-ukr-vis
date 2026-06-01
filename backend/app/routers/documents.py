from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.config import get_settings
from app.database import get_database
from app.schemas.responses import (
    DeleteResponse,
    DocumentRecord,
    EmbeddingIndexResponse,
    EmbeddingStatusResponse,
    ParsedParagraph,
    WorkspaceCreate,
    WorkspaceRecord,
)
from app.services.document_parser import parse_document
from app.services.embedding_service import get_embedding_service
from app.services.neo4j_service import get_neo4j_service
from app.services.vector_store import get_vector_store
from app.services.workspace_bootstrap import get_macro_workspace_id

router = APIRouter(tags=["documents"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@router.get("/workspaces", response_model=list[WorkspaceRecord])
def list_workspaces() -> list[WorkspaceRecord]:
    db = get_database()
    with db.session() as connection:
        rows = connection.execute(
            "SELECT id, name, description, created_at FROM workspaces ORDER BY id DESC"
        ).fetchall()
    return [
        WorkspaceRecord(
            id=row["id"],
            name=row["name"],
            description=row.get("description"),
            created_at=_dt_iso(row["created_at"]),
        )
        for row in rows
    ]


@router.get("/app/default-workspace", response_model=WorkspaceRecord)
def default_workspace() -> WorkspaceRecord:
    workspace_id = get_macro_workspace_id()
    with get_database().session() as connection:
        row = connection.execute(
            "SELECT id, name, description, created_at FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Default data domain is unavailable.")
    return WorkspaceRecord(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        created_at=_dt_iso(row["created_at"]),
    )


@router.post("/workspaces", response_model=WorkspaceRecord)
def create_workspace(payload: WorkspaceCreate) -> WorkspaceRecord:
    db = get_database()
    try:
        with db.session() as connection:
            connection.execute(
                "INSERT INTO workspaces (name, description) VALUES (?, ?)",
                (payload.name, payload.description),
            )
            row = connection.execute(
                "SELECT id, name, description, created_at FROM workspaces WHERE id = ?",
                (connection.lastrowid,),
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Create workspace failed: {exc}") from exc
    return WorkspaceRecord(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        created_at=_dt_iso(row["created_at"]),
    )


@router.delete("/workspaces/{workspace_id}", response_model=DeleteResponse)
def delete_workspace(workspace_id: int) -> DeleteResponse:
    settings = get_settings()
    db = get_database()
    workspace_dir = settings.upload_dir / str(workspace_id)
    if workspace_id == get_macro_workspace_id():
        raise HTTPException(status_code=400, detail="默认基础数据工作区不可删除。")
    with db.session() as connection:
        workspace = connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        document_rows = connection.execute(
            "SELECT id FROM documents WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        document_ids = [int(row["id"]) for row in document_rows]
        connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    neo4j = get_neo4j_service()
    vector_store = get_vector_store()
    for document_id in document_ids:
        try:
            neo4j.clear_document_graph(document_id)
        except Exception:
            pass
        try:
            vector_store.delete_document(document_id)
        except Exception:
            pass
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    return DeleteResponse(success=True, deleted_id=workspace_id, message="Workspace deleted.")


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentRecord])
def list_workspace_documents(workspace_id: int) -> list[DocumentRecord]:
    db = get_database()
    with db.session() as connection:
        rows = connection.execute(
            """
            SELECT id, workspace_id,
                   COALESCE(source_name, title) AS file_name,
                   title AS document_topic,
                   COALESCE(file_path, '') AS file_path,
                   COALESCE(file_type, '') AS file_type,
                   COALESCE(status, 'pending') AS status,
                   created_at
            FROM documents
            WHERE workspace_id = ?
            ORDER BY id DESC
            """,
            (workspace_id,),
        ).fetchall()
    return [
        DocumentRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            file_name=row["file_name"],
            document_topic=row["document_topic"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            status=row["status"],
            created_at=_dt_iso(row["created_at"]),
        )
        for row in rows
    ]


@router.get("/documents", response_model=list[DocumentRecord])
def list_documents() -> list[DocumentRecord]:
    db = get_database()
    with db.session() as connection:
        rows = connection.execute(
            """
            SELECT id, workspace_id,
                   COALESCE(source_name, title) AS file_name,
                   title AS document_topic,
                   COALESCE(file_path, '') AS file_path,
                   COALESCE(file_type, '') AS file_type,
                   COALESCE(status, 'pending') AS status,
                   created_at
            FROM documents
            ORDER BY id DESC
            """
        ).fetchall()
    return [
        DocumentRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            file_name=row["file_name"],
            document_topic=row["document_topic"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            status=row["status"],
            created_at=_dt_iso(row["created_at"]),
        )
        for row in rows
    ]


@router.delete("/documents/{document_id}", response_model=DeleteResponse)
def delete_document(document_id: int) -> DeleteResponse:
    db = get_database()
    with db.session() as connection:
        document = connection.execute(
            "SELECT id, file_path FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    try:
        get_neo4j_service().clear_document_graph(document_id)
    except Exception:
        pass
    try:
        get_vector_store().delete_document(document_id)
    except Exception:
        pass
    if document.get("file_path"):
        file_path = Path(document["file_path"])
        if file_path.exists():
            file_path.unlink(missing_ok=True)
    return DeleteResponse(success=True, deleted_id=document_id, message="Document deleted.")


@router.get("/documents/{document_id}/chunks", response_model=list[ParsedParagraph])
def list_document_chunks(
    document_id: int,
    limit: int = Query(default=80, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
) -> list[ParsedParagraph]:
    db = get_database()
    with db.session() as connection:
        document = connection.execute(
            """
            SELECT COALESCE(source_name, title) AS file_name, title AS document_topic
            FROM documents WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        clauses = ["document_id = ?"]
        params: list[object] = [document_id]
        if keyword:
            clauses.append("LOWER(text) LIKE ?")
            params.append(f"%{keyword.lower()}%")
        where = " WHERE " + " AND ".join(clauses)
        rows = connection.execute(
            f"""
            SELECT id AS chunk_id, chunk_index AS paragraph_index, page_no AS page_number,
                   text, created_at AS parsed_at_iso, file_modified_at AS file_modified_at_iso,
                   COALESCE(source_path, '') AS source_path,
                   start_offset, end_offset
            FROM document_chunks
            {where}
            ORDER BY chunk_index ASC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [
        ParsedParagraph(
            chunk_id=row["chunk_id"],
            file_name=document["file_name"],
            document_topic=document["document_topic"],
            paragraph_index=row["paragraph_index"],
            parsed_at_iso=_dt_iso(row["parsed_at_iso"]),
            file_modified_at_iso=_dt_iso(row["file_modified_at_iso"]) if row["file_modified_at_iso"] else None,
            source_path=row["source_path"] or "",
            page_number=row["page_number"],
            start_offset=row.get("start_offset"),
            end_offset=row.get("end_offset"),
            text=row["text"],
        )
        for row in rows
    ]


@router.get("/documents/{document_id}/chunks/count")
def document_chunks_count(
    document_id: int,
    keyword: str | None = Query(default=None),
) -> dict:
    clauses = ["document_id = ?"]
    params: list[object] = [document_id]
    if keyword:
        clauses.append("LOWER(text) LIKE ?")
        params.append(f"%{keyword.lower()}%")
    where = " WHERE " + " AND ".join(clauses)
    with get_database().session() as connection:
        document = connection.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM document_chunks
            {where}
            """,
            params,
        ).fetchone()
    return {"total": int(row["c"]) if row else 0}


@router.get("/documents/{document_id}/chunks/{chunk_id}/position")
def locate_document_chunk(
    document_id: int,
    chunk_id: int,
    limit: int = Query(default=12, ge=1, le=500),
) -> dict:
    with get_database().session() as connection:
        target = connection.execute(
            """
            SELECT chunk_index
            FROM document_chunks
            WHERE document_id = ? AND id = ?
            """,
            (document_id, chunk_id),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Chunk not found in this document.")
        row = connection.execute(
            """
            SELECT COUNT(*) AS position
            FROM document_chunks
            WHERE document_id = ? AND chunk_index <= ?
            """,
            (document_id, target["chunk_index"]),
        ).fetchone()
    position = int(row["position"]) if row else 1
    page = max(0, (position - 1) // limit)
    return {
        "chunk_id": chunk_id,
        "position": position,
        "page": page,
        "offset": page * limit,
    }


@router.get("/documents/{document_id}/embeddings/status", response_model=EmbeddingStatusResponse)
def document_embedding_status(document_id: int) -> EmbeddingStatusResponse:
    return EmbeddingStatusResponse(**get_embedding_service().document_status(document_id))


@router.post("/documents/{document_id}/embeddings", response_model=EmbeddingIndexResponse)
def build_document_embeddings(document_id: int, force: bool = False) -> EmbeddingIndexResponse:
    try:
        return EmbeddingIndexResponse(**get_embedding_service().index_document(document_id, force=force))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文档向量索引失败: {exc}") from exc


@router.post("/documents/parse", response_model=list[ParsedParagraph])
async def upload_and_parse_document(
    workspace_id: int | None = Form(default=None),
    file: UploadFile = File(...),
) -> list[ParsedParagraph]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, TXT are supported.")

    settings = get_settings()
    db = get_database()
    workspace_id = workspace_id or get_macro_workspace_id()
    with db.session() as connection:
        workspace = connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")

    workspace_dir = settings.upload_dir / str(workspace_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    target = workspace_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    paragraphs = parse_document(target)
    if not paragraphs:
        raise HTTPException(status_code=400, detail="No paragraphs were parsed from the document.")

    with db.session() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                workspace_id, title, source_name, source_type, file_type, file_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                paragraphs[0].document_topic,
                paragraphs[0].file_name,
                "report",
                suffix.lstrip("."),
                str(target),
                "processed",
            ),
        )
        document_id = connection.lastrowid
        connection.executemany(
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
        rows = connection.execute(
            """
            SELECT id AS chunk_id, chunk_index AS paragraph_index, page_no AS page_number, text,
                   created_at AS parsed_at_iso, start_offset, end_offset
            FROM document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        ).fetchall()

    by_index = {row["paragraph_index"]: dict(row) for row in rows}
    return [
        ParsedParagraph(
            chunk_id=by_index[item.paragraph_index]["chunk_id"],
            file_name=item.file_name,
            document_topic=item.document_topic,
            paragraph_index=item.paragraph_index,
            parsed_at_iso=_dt_iso(by_index[item.paragraph_index]["parsed_at_iso"]),
            file_modified_at_iso=item.file_modified_at_iso,
            source_path=item.source_path,
            page_number=item.page_number,
            start_offset=by_index[item.paragraph_index].get("start_offset"),
            end_offset=by_index[item.paragraph_index].get("end_offset"),
            text=item.text,
        )
        for item in paragraphs
    ]
