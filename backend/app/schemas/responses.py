from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    mysql: str = "unknown"
    neo4j: str = "unknown"
    conflict_events: int = 0


class DatasetSummary(BaseModel):
    dataset: str
    total_rows: int
    columns: list[str]


class ConflictEvent(BaseModel):
    event_id_cnty: str
    event_date: str
    event_date_raw: str | None = None
    year: int | None = None
    time_precision: int | None = None
    disorder_type: str | None = None
    event_type: str | None = None
    sub_event_type: str | None = None
    actor1: str | None = None
    actor1_assoc: str | None = None
    actor1_type: str | None = None
    actor2: str | None = None
    actor2_assoc: str | None = None
    actor2_type: str | None = None
    interaction_type: str | None = None
    civilian_targeting: str | None = None
    iso_code: int | None = None
    region: str | None = None
    country: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    admin3: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_precision: int | None = None
    source: str | None = None
    source_scale: str | None = None
    notes: str | None = None
    fatalities: int | None = None
    tags: str | None = None
    source_timestamp: int | None = None
    relevance_score: float | None = None
    relevance_reasons: list[str] = Field(default_factory=list)


class TimelinePoint(BaseModel):
    date: str
    value: int
    label: str


class WeiboPost(BaseModel):
    index: int
    created_at: str | None = None
    pub_time: str | None = None
    msg_id: str | None = None
    text: str | None = None
    screen_name: str | None = None
    source: str | None = None
    reposts_count: int | None = None
    comments_count: int | None = None
    attitudes_count: int | None = None


class ParsedParagraph(BaseModel):
    chunk_id: int
    file_name: str
    document_topic: str
    paragraph_index: int
    parsed_at_iso: str
    file_modified_at_iso: str | None = None
    source_path: str
    page_number: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    text: str


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    chunk_ids: list[int] = Field(default_factory=list)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    chunk_ids: list[int] = Field(default_factory=list)
    evidence: str | None = None


class DocumentGraphResponse(BaseModel):
    document_id: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    updated_at: str | None = None


class GraphExtractResponse(BaseModel):
    document_id: int
    node_count: int
    edge_count: int
    message: str


class EmbeddingIndexResponse(BaseModel):
    document_id: int
    model: str | None = None
    dimension: int = 0
    indexed: int = 0
    skipped: int = 0
    total_chunks: int = 0
    vector_indexed: int = 0
    vector_store: str | None = None
    ready: bool = False
    message: str


class EmbeddingStatusResponse(BaseModel):
    document_id: int
    chunk_count: int = 0
    indexed_count: int = 0
    vector_indexed_count: int = 0
    model: str | None = None
    dimension: int | None = None
    vector_store: str | None = None
    ready: bool = False


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_id: int


class QASource(BaseModel):
    source_type: str = "chunk"
    label: str = ""
    chunk_id: int | None = None
    event_id_cnty: str | None = None
    paragraph_index: int | None = None
    page_number: int | None = None
    excerpt: str


class QAResponse(BaseModel):
    answer: str
    mode: str = "local"
    sources: list[QASource]
    subgraph_nodes: list[GraphNode] = Field(default_factory=list)
    subgraph_edges: list[GraphEdge] = Field(default_factory=list)
    context_summary: dict | None = None


class WorkspaceQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: str = "local"
    document_id: int | None = None
    event_id_cnty: str | None = None


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_id: int | None = None
    document_ids: list[int] = Field(default_factory=list)
    case_id: int | None = None
    event_id_cnty: str | None = None


class ChatSessionRecord(BaseModel):
    id: int
    title: str
    status: str = "active"
    created_at: str
    updated_at: str


class ChatMessageRecord(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: list[QASource] = Field(default_factory=list)
    created_at: str


class ChatQueryResponse(BaseModel):
    session: ChatSessionRecord
    user_message: ChatMessageRecord
    assistant_message: ChatMessageRecord
    qa: QAResponse


class MapPoint(BaseModel):
    event_id_cnty: str
    event_date: str
    event_type: str | None = None
    admin1: str | None = None
    location: str | None = None
    latitude: float
    longitude: float
    actor1: str | None = None
    actor2: str | None = None
    fatalities: int | None = None


class SourceStatItem(BaseModel):
    name: str
    count: int
    source_type: str


class SourceStatsResponse(BaseModel):
    acled: list[SourceStatItem]
    weibo: list[SourceStatItem]


class ProcessingStage(BaseModel):
    id: str
    name: str
    count: int = 0
    status: str = "pending"
    detail: str = ""


class ProcessingEdge(BaseModel):
    source: str
    target: str
    value: int = 0
    label: str = ""


class ProcessingPipelineResponse(BaseModel):
    stages: list[ProcessingStage] = Field(default_factory=list)
    edges: list[ProcessingEdge] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


class CountItem(BaseModel):
    name: str
    count: int


class SeriesItem(BaseModel):
    name: str
    data: list[int] = Field(default_factory=list)


class PhaseEvolutionResponse(BaseModel):
    months: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    series: list[SeriesItem] = Field(default_factory=list)
    fatalities: list[int] = Field(default_factory=list)


class HeatmapCell(BaseModel):
    region: str
    event_type: str
    value: int


class RegionEventMatrixResponse(BaseModel):
    regions: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    cells: list[HeatmapCell] = Field(default_factory=list)


class ActorPairItem(BaseModel):
    source: str
    target: str
    relation_type: str | None = None
    count: int
    fatalities: int = 0


class KnowledgeSummary(BaseModel):
    entities: int = 0
    event_entity_links: int = 0
    evidences: int = 0
    relations: int = 0


class ConflictOverviewResponse(BaseModel):
    total_events: int = 0
    date_min: str | None = None
    date_max: str | None = None
    total_fatalities: int = 0
    geo_events: int = 0
    event_type_counts: list[CountItem] = Field(default_factory=list)
    admin1_counts: list[CountItem] = Field(default_factory=list)
    source_counts: list[CountItem] = Field(default_factory=list)
    yearly_counts: list[CountItem] = Field(default_factory=list)
    knowledge: KnowledgeSummary = Field(default_factory=KnowledgeSummary)


class EventChainDetailResponse(BaseModel):
    anchor: ConflictEvent | None = None
    chain: list[ConflictEvent] = Field(default_factory=list)
    before: list[ConflictEvent] = Field(default_factory=list)
    after: list[ConflictEvent] = Field(default_factory=list)
    same_region_timeline: list[TimelinePoint] = Field(default_factory=list)
    actor_counts: list[CountItem] = Field(default_factory=list)
    source_counts: list[CountItem] = Field(default_factory=list)
    map_points: list[MapPoint] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    analysis_notes: list[str] = Field(default_factory=list)


class KnowledgeGraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class EntityMention(BaseModel):
    id: int
    name: str
    entity_type: str
    role_type: str
    description: str | None = None


class EvidenceItem(BaseModel):
    id: int
    evidence_type: str
    quote_text: str | None = None
    source_label: str | None = None


class EventEvidenceResponse(BaseModel):
    event: ConflictEvent | None = None
    entities: list[EntityMention] = Field(default_factory=list)
    evidences: list[EvidenceItem] = Field(default_factory=list)
    graph: KnowledgeGraphResponse = Field(default_factory=KnowledgeGraphResponse)


class ConflictFiltersResponse(BaseModel):
    years: list[int] = Field(default_factory=list)
    admin1: list[dict[str, int | str]] = Field(default_factory=list)


class QueryHistoryItem(BaseModel):
    id: int
    query_text: str
    query_mode: str | None = None
    answer_text: str | None = None
    created_at: str


class ViewRecommendation(BaseModel):
    view_type: str
    title: str
    rationale: str
    priority: int = 1


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class WorkspaceRecord(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: str


class DocumentRecord(BaseModel):
    id: int
    workspace_id: int
    file_name: str
    document_topic: str
    file_path: str
    file_type: str
    status: str
    created_at: str


class DeleteResponse(BaseModel):
    success: bool
    deleted_id: int
    message: str


class IntelligenceCaseCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class IntelligenceCaseRecord(BaseModel):
    id: int
    title: str
    status: str = "created"
    created_at: str
    updated_at: str


class IntelligenceCaseDocument(BaseModel):
    id: int
    document_id: int
    file_name: str
    document_topic: str
    file_type: str
    status: str
    chunk_count: int = 0
    entity_count: int = 0
    event_count: int = 0
    relation_count: int = 0
    evidence_count: int = 0
    vector_ready: bool = False
    graph_ready: bool = False
    created_at: str


class IntelligenceCaseStage(BaseModel):
    id: str
    name: str
    status: str = "pending"
    count: int = 0
    detail: str = ""


class IntelligenceCaseStatus(BaseModel):
    case: IntelligenceCaseRecord
    documents: list[IntelligenceCaseDocument] = Field(default_factory=list)
    stages: list[IntelligenceCaseStage] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


class IntelligenceEntity(BaseModel):
    id: int
    document_id: int
    chunk_id: int | None = None
    name: str
    entity_type: str
    evidence_text: str | None = None


class IntelligenceEvent(BaseModel):
    id: int
    document_id: int
    chunk_id: int | None = None
    event_title: str
    event_date: str | None = None
    event_time_raw: str | None = None
    event_type: str | None = None
    location_name: str | None = None
    actor_names: str | None = None
    summary: str | None = None
    evidence_text: str | None = None


class IntelligenceCaseUploadResponse(BaseModel):
    case: IntelligenceCaseRecord
    documents: list[IntelligenceCaseDocument]
    status: IntelligenceCaseStatus


class IntelligenceCaseEmbeddingResponse(BaseModel):
    case_id: int
    document_count: int = 0
    ready_document_count: int = 0
    indexed: int = 0
    skipped: int = 0
    total_chunks: int = 0
    vector_indexed: int = 0
    vector_store: str | None = None
    errors: list[str] = Field(default_factory=list)
    status: IntelligenceCaseStatus
    message: str
