from fastapi import APIRouter

from app.config import get_settings
from app.database import get_database
from app.schemas.responses import HealthResponse
from app.services.conflict_store import get_conflict_store
from app.services.neo4j_service import get_neo4j_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    neo4j_status = "unavailable"
    try:
        ok, msg = get_neo4j_service().verify()
        neo4j_status = "ok" if ok else f"error: {msg}"
    except Exception as exc:
        neo4j_status = f"error: {exc}"

    mysql_status = "unavailable"
    try:
        get_database().init()
        mysql_status = "ok"
    except Exception as exc:
        mysql_status = f"error: {exc}"

    conflict_count = 0
    try:
        store = get_conflict_store()
        conflict_count = store.count() if store.is_imported() else 0
    except Exception:
        conflict_count = 0

    overall = "ok" if mysql_status == "ok" else "degraded"

    return HealthResponse(
        status=overall,
        app=settings.app_name,
        mysql=mysql_status,
        neo4j=neo4j_status,
        conflict_events=conflict_count,
    )
