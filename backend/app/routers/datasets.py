import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

from app.schemas.responses import (
    ActorPairItem,
    ConflictEvent,
    ConflictFiltersResponse,
    ConflictOverviewResponse,
    DatasetSummary,
    EventEvidenceResponse,
    EventChainDetailResponse,
    PhaseEvolutionResponse,
    KnowledgeGraphResponse,
    MapPoint,
    ProcessingPipelineResponse,
    RegionEventMatrixResponse,
    SourceStatsResponse,
    TimelinePoint,
    WeiboPost,
)
from app.services.acled_knowledge_service import get_acled_knowledge_service
from app.services.weibo_store import get_weibo_store
from app.services.conflict_store import get_conflict_store
from app.services.dataset_service import get_dataset_service
from app.services.neo4j_service import get_neo4j_service

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("/events/filters", response_model=ConflictFiltersResponse)
@router.get("/conflict/filters", response_model=ConflictFiltersResponse)
def conflict_filters() -> ConflictFiltersResponse:
    service = get_dataset_service()
    return ConflictFiltersResponse(**service.get_conflict_filters())


@router.get("/events/overview", response_model=ConflictOverviewResponse)
@router.get("/conflict/overview", response_model=ConflictOverviewResponse)
def conflict_overview() -> ConflictOverviewResponse:
    service = get_dataset_service()
    return ConflictOverviewResponse(**service.get_conflict_overview())


@router.post("/text-samples/reindex")
@router.post("/weibo/reindex")
def reindex_weibo(force: bool = Query(default=False)) -> dict:
    store = get_weibo_store()
    already_imported = store.is_imported()
    total = store.ensure_imported(force=force)
    if already_imported and not force:
        return {"message": "微博数据已存在，已复用当前 MySQL 数据", "total": total, "skipped": True}
    return {"message": "微博数据已导入 MySQL", "total": total, "skipped": False}


@router.get("/summary", response_model=list[DatasetSummary])
def dataset_summary() -> list[DatasetSummary]:
    service = get_dataset_service()
    return [DatasetSummary(**item) for item in service.summarize()]


@router.get("/pipeline-summary", response_model=ProcessingPipelineResponse)
def pipeline_summary() -> ProcessingPipelineResponse:
    service = get_dataset_service()
    return ProcessingPipelineResponse(**service.get_processing_pipeline())


@router.post("/events/reindex")
@router.post("/conflict/reindex")
def reindex_conflict(force: bool = Query(default=False)) -> dict:
    store = get_conflict_store()
    already_imported = store.is_imported()
    total = store.ensure_imported(force=force)
    if already_imported and not force:
        return {"message": "冲突事件已存在，已复用当前 MySQL 数据", "total": total, "skipped": True}
    return {"message": "冲突事件已重新导入 MySQL", "total": total, "skipped": False}


@router.post("/events/derive-knowledge")
@router.post("/conflict/derive-knowledge")
def derive_conflict_knowledge() -> dict:
    store = get_conflict_store()
    if not store.is_imported():
        raise HTTPException(
            status_code=400,
            detail="请先导入 ACLED 冲突事件，再派生实体、关系与证据。",
        )
    return get_acled_knowledge_service().start_rebuild_job()


@router.get("/events/derive-knowledge/status")
@router.get("/conflict/derive-knowledge/status")
def derive_conflict_knowledge_status() -> dict:
    return get_acled_knowledge_service().job_status()


@router.get("/events/knowledge-summary")
@router.get("/conflict/knowledge-summary")
def conflict_knowledge_summary() -> dict:
    return get_acled_knowledge_service().summary()


@router.get("/events/knowledge-graph", response_model=KnowledgeGraphResponse)
@router.get("/conflict/knowledge-graph", response_model=KnowledgeGraphResponse)
def conflict_knowledge_graph(
    limit: int = Query(default=160, ge=10, le=400),
    event_id_cnty: str | None = Query(default=None),
) -> KnowledgeGraphResponse:
    data = get_acled_knowledge_service().graph(limit=limit, event_id_cnty=event_id_cnty)
    return KnowledgeGraphResponse(**data)


@router.post("/events/sync-neo4j")
@router.post("/conflict/sync-neo4j")
def sync_conflict_neo4j(
    full: bool = Query(
        default=True,
        description="true=从 MySQL 全量同步至 Neo4j；false=仅同步 limit 条（按日期倒序）",
    ),
    limit: int | None = Query(default=None, ge=100, le=200000),
) -> dict:
    store = get_conflict_store()
    if not store.is_imported():
        raise HTTPException(
            status_code=400,
            detail="请先在 MySQL 中导入 ACLED（POST /datasets/conflict/reindex 或前端「导入 ACLED → MySQL」）。",
        )
    mysql_total = store.count()
    neo4j = get_neo4j_service()
    neo4j.ensure_constraints()
    synced = 0
    if full and limit is None:
        for batch in store.iter_event_batches(batch_size=2000):
            for i in range(0, len(batch), 500):
                synced += neo4j.upsert_conflict_events_batch(batch[i : i + 500])
            if synced % 10000 < 500:
                logger.info("Neo4j 全量同步进度: %s / %s", synced, mysql_total)
        mode = "full"
    else:
        cap = limit or 5000
        events = store.list_events(limit=cap)
        for i in range(0, len(events), 500):
            synced += neo4j.upsert_conflict_events_batch(events[i : i + 500])
        mode = "sample"
    neo4j_total = neo4j.count_conflict_events()
    return {
        "message": "已同步冲突事件至 Neo4j",
        "mode": mode,
        "mysql_total": mysql_total,
        "synced": synced,
        "neo4j_conflict_events": neo4j_total,
    }


@router.get("/events/timeline", response_model=list[TimelinePoint])
@router.get("/conflict/timeline", response_model=list[TimelinePoint])
def conflict_timeline(
    limit: int = Query(default=2000, ge=10, le=10000),
    year: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    admin1: str | None = Query(default=None),
) -> list[TimelinePoint]:
    service = get_dataset_service()
    return [
        TimelinePoint(**item)
        for item in service.get_conflict_timeline(
            limit=limit, year=year, event_type=event_type, admin1=admin1
        )
    ]


@router.get("/events/map", response_model=list[MapPoint])
@router.get("/conflict/map", response_model=list[MapPoint])
def conflict_map(
    limit: int = Query(default=3000, ge=10, le=10000),
    year: int | None = Query(default=None),
    admin1: str | None = Query(default=None),
) -> list[MapPoint]:
    service = get_dataset_service()
    return [MapPoint(**item) for item in service.get_conflict_map(limit=limit, year=year, admin1=admin1)]


@router.get("/events/phase-evolution", response_model=PhaseEvolutionResponse)
@router.get("/conflict/phase-evolution", response_model=PhaseEvolutionResponse)
def conflict_phase_evolution() -> PhaseEvolutionResponse:
    service = get_dataset_service()
    return PhaseEvolutionResponse(**service.get_phase_evolution())


@router.get("/events/region-event-matrix", response_model=RegionEventMatrixResponse)
@router.get("/conflict/region-event-matrix", response_model=RegionEventMatrixResponse)
def conflict_region_event_matrix() -> RegionEventMatrixResponse:
    service = get_dataset_service()
    return RegionEventMatrixResponse(**service.get_region_event_matrix())


@router.get("/events/actor-pairs", response_model=list[ActorPairItem])
@router.get("/conflict/actor-pairs", response_model=list[ActorPairItem])
def conflict_actor_pairs(limit: int = Query(default=20, ge=5, le=80)) -> list[ActorPairItem]:
    service = get_dataset_service()
    return [ActorPairItem(**item) for item in service.get_actor_pair_stats(limit=limit)]


@router.get("/events", response_model=list[ConflictEvent])
@router.get("/conflict", response_model=list[ConflictEvent])
def conflict_events(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    year: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    admin1: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> list[ConflictEvent]:
    service = get_dataset_service()
    return [
        ConflictEvent(**item)
        for item in service.get_conflict_events(
            limit=limit, offset=offset, year=year, event_type=event_type, admin1=admin1, keyword=keyword
        )
    ]


@router.get("/events/count")
@router.get("/conflict/count")
def conflict_events_count(
    year: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    admin1: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> dict:
    store = get_conflict_store()
    return {
        "total": store.count_events(
            year=year,
            event_type=event_type,
            admin1=admin1,
            keyword=keyword,
        )
    }


@router.get("/events/{event_id_cnty}", response_model=ConflictEvent)
@router.get("/conflict/{event_id_cnty}", response_model=ConflictEvent)
def conflict_event_detail(event_id_cnty: str) -> ConflictEvent:
    service = get_dataset_service()
    row = service.get_conflict_event(event_id_cnty)
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    return ConflictEvent(**row)


@router.get("/events/{event_id_cnty}/chain", response_model=list[ConflictEvent])
@router.get("/conflict/{event_id_cnty}/chain", response_model=list[ConflictEvent])
def conflict_event_chain(
    event_id_cnty: str,
    limit: int = Query(default=40, ge=1, le=100),
) -> list[ConflictEvent]:
    service = get_dataset_service()
    return [ConflictEvent(**item) for item in service.get_event_chain(event_id_cnty, limit=limit)]


@router.get("/events/{event_id_cnty}/chain-detail", response_model=EventChainDetailResponse)
@router.get("/conflict/{event_id_cnty}/chain-detail", response_model=EventChainDetailResponse)
def conflict_event_chain_detail(
    event_id_cnty: str,
    limit: int = Query(default=40, ge=1, le=100),
) -> EventChainDetailResponse:
    service = get_dataset_service()
    data = service.get_event_chain_detail(event_id_cnty, limit=limit)
    return EventChainDetailResponse(**data)


@router.get("/events/{event_id_cnty}/evidence", response_model=EventEvidenceResponse)
@router.get("/conflict/{event_id_cnty}/evidence", response_model=EventEvidenceResponse)
def conflict_event_evidence(event_id_cnty: str) -> EventEvidenceResponse:
    data = get_acled_knowledge_service().event_evidence(event_id_cnty)
    return EventEvidenceResponse(**data)


@router.get("/sources/stats", response_model=SourceStatsResponse)
def source_stats() -> SourceStatsResponse:
    service = get_dataset_service()
    data = service.get_source_stats()
    return SourceStatsResponse(**data)


@router.get("/text-samples", response_model=list[WeiboPost])
@router.get("/weibo", response_model=list[WeiboPost])
def weibo_posts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
) -> list[WeiboPost]:
    service = get_dataset_service()
    return [WeiboPost(**item) for item in service.get_weibo_posts(limit=limit, offset=offset, keyword=keyword)]


@router.get("/text-samples/count")
@router.get("/weibo/count")
def weibo_posts_count(keyword: str | None = Query(default=None)) -> dict:
    service = get_dataset_service()
    return {"total": service.count_weibo_posts(keyword=keyword)}
