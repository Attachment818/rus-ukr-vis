import { ChangeEvent, ClipboardEvent, FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import './app.css';
import { deleteJson, fetchJson, postEmpty, postFormData, postJson } from './lib/api';

type DatasetSummary = { dataset: string; total_rows: number; columns: string[] };
type CountResponse = { total: number };
type TimelinePoint = { date: string; value: number; label: string };
type ConflictEvent = {
  event_id_cnty: string;
  event_date: string;
  year?: number | null;
  event_type?: string;
  sub_event_type?: string;
  actor1?: string;
  actor2?: string;
  admin1?: string;
  location?: string;
  latitude?: number | null;
  longitude?: number | null;
  source?: string;
  notes?: string | null;
  fatalities?: number | null;
  relevance_score?: number | null;
  relevance_reasons?: string[];
};
type WeiboPost = {
  index: number;
  created_at?: string;
  text?: string;
  screen_name?: string;
  source?: string;
  attitudes_count?: number | null;
};
type Workspace = { id: number; name: string; description?: string | null; created_at: string };
type DocumentRecord = {
  id: number;
  workspace_id: number;
  file_name: string;
  document_topic: string;
  file_path: string;
  file_type: string;
  status: string;
  created_at: string;
};
type ParsedParagraph = {
  chunk_id: number;
  file_name: string;
  document_topic: string;
  paragraph_index: number;
  parsed_at_iso: string;
  file_modified_at_iso?: string | null;
  source_path: string;
  page_number?: number | null;
  start_offset?: number | null;
  end_offset?: number | null;
  text: string;
};

type GraphNode = { id: string; label: string; node_type: string; chunk_ids: number[] };
type GraphEdge = {
  source: string;
  target: string;
  relation_type: string;
  chunk_ids: number[];
  evidence?: string | null;
};
type DocumentGraphResponse = {
  document_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  updated_at?: string | null;
};
type GraphExtractResponse = { document_id: number; node_count: number; edge_count: number; message: string };
type QASource = {
  source_type: string;
  label: string;
  chunk_id?: number | null;
  event_id_cnty?: string | null;
  paragraph_index?: number | null;
  page_number?: number | null;
  excerpt: string;
};
type QAResponse = {
  answer: string;
  mode?: string;
  sources: QASource[];
  subgraph_nodes: GraphNode[];
  subgraph_edges: GraphEdge[];
  context_summary?: Record<string, unknown> | null;
};
type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: QASource[];
};

const CHUNK_LABEL_PATTERN = /^(?:文档\s*)?chunk\s*#?\d+$/i;

function compactInlineText(value: string, maxLength = 22) {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}…`;
}

function firstMeaningfulExcerptLine(excerpt?: string) {
  return (excerpt ?? '')
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .find((line) => line.length >= 3 && !/^\d+[.)、]?$/.test(line));
}

function getSourceTitle(source: QASource) {
  const label = (source.label || '').trim();
  if (label && !CHUNK_LABEL_PATTERN.test(label)) {
    return compactInlineText(label, 26);
  }
  const excerptTitle = firstMeaningfulExcerptLine(source.excerpt);
  if (excerptTitle) {
    return compactInlineText(excerptTitle, 26);
  }
  if (source.event_id_cnty) {
    return source.event_id_cnty;
  }
  return source.source_type === 'chunk' ? '文档分段' : source.source_type;
}

function getSourceMeta(source: QASource) {
  const parts: string[] = [];
  if (source.paragraph_index != null) {
    parts.push(`段落 ${source.paragraph_index}`);
  }
  if (source.page_number != null) {
    parts.push(`第 ${source.page_number} 页`);
  }
  if (source.event_id_cnty) {
    parts.push(source.event_id_cnty);
  }
  return parts.join(' · ') || source.source_type;
}

function sanitizeAnswerLine(line: string) {
  return line
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/^\s*结论[:：]\s*/u, '')
    .replace(/^\s*根据(?:当前)?(?:公开事件(?:库|数据库)?|结构化(?:事件)?数据库|事件数据库|数据库)(?:记录|检索结果|信息)?[，,:：]\s*/u, '')
    .replace(/\[(?:S|s)\d+\]/g, '')
    .replace(/\s+\((?:\d{4}-|\d{4}-\d{2,4})\)/g, '')
    .replace(/\*/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function sanitizeAnswerContent(content: string) {
  const normalized = content
    .replace(/\r\n/g, '\n')
    .replace(
      /^(?:根据(?:当前)?(?:公开事件(?:库|数据库)?|结构化(?:事件)?数据库|事件数据库|数据库)(?:记录|检索结果|信息)?[，,:：]\s*)/u,
      '',
    );
  const lines = normalized
    .split('\n')
    .map((line) => sanitizeAnswerLine(line))
    .filter((line, index, all) => line.length > 0 || (index > 0 && all[index - 1].length > 0));
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

function renderStructuredAnswer(content: string) {
  const cleanedContent = sanitizeAnswerContent(content);
  const blocks = cleanedContent
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  return blocks.map((block, index) => {
    const lines = block
      .split(/\n/)
      .map((line) => line.trimEnd())
      .filter(Boolean);
    const orderedLinePattern = /^\d+[.、)]/u;
    const headingWithList =
      lines.length > 1 &&
      /[:：]$/.test(lines[0].trim()) &&
      lines.slice(1).every((line) => /^(?:\d+[.、)]|[-•])/u.test(line.trim()));
    const isListBlock = lines.length > 1 && lines.every((line) => /^(?:\d+[.、)]|[-•])/u.test(line.trim()));
    const listItems = lines.map((line) => line.replace(/^(?:\d+[.、)]|[-•])\s*/u, ''));
    const useOrderedList = lines.every((line) => orderedLinePattern.test(line.trim()));
    if (headingWithList) {
      const subItems = lines.slice(1).map((line) => line.replace(/^(?:\d+[.、)]|[-•])\s*/u, ''));
      const orderedSubList = lines.slice(1).every((line) => orderedLinePattern.test(line.trim()));
      return (
        <div key={`answer-block-${index}`} className="assistant-block">
          <p className="assistant-heading">{lines[0]}</p>
          {orderedSubList ? (
            <ol className="assistant-list">
              {subItems.map((line, itemIndex) => (
                <li key={`answer-item-${index}-${itemIndex}`}>{line}</li>
              ))}
            </ol>
          ) : (
            <ul className="assistant-list">
              {subItems.map((line, itemIndex) => (
                <li key={`answer-item-${index}-${itemIndex}`}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    if (isListBlock) {
      return useOrderedList ? (
        <ol key={`answer-block-${index}`} className="assistant-list">
          {listItems.map((line, itemIndex) => (
            <li key={`answer-item-${index}-${itemIndex}`}>{line}</li>
          ))}
        </ol>
      ) : (
        <ul key={`answer-block-${index}`} className="assistant-list">
          {listItems.map((line, itemIndex) => (
            <li key={`answer-item-${index}-${itemIndex}`}>{line}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={`answer-block-${index}`} className="assistant-paragraph">
        {block}
      </p>
    );
  });
}
type ChatSessionRecord = {
  id: number;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};
type ChatMessageRecord = {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  sources: QASource[];
  created_at: string;
};
type ChatQueryResponse = {
  session: ChatSessionRecord;
  user_message: ChatMessageRecord;
  assistant_message: ChatMessageRecord;
  qa: QAResponse;
};
type MapPoint = {
  event_id_cnty: string;
  event_date: string;
  event_type?: string;
  admin1?: string;
  location?: string;
  latitude: number;
  longitude: number;
  actor1?: string | null;
  actor2?: string | null;
  fatalities?: number | null;
};
type HealthInfo = {
  status: string;
  app: string;
  mysql: string;
  neo4j: string;
  conflict_events: number;
};
type LlmStatus = {
  configured: boolean;
  api_key_present: boolean;
  base_url: string;
  model: string;
  provider: string;
  used_for: string[];
  message: string;
  embedding?: {
    configured: boolean;
    api_key_present: boolean;
    base_url: string;
    model: string;
    provider: string;
    used_for: string[];
    message: string;
  };
};
type LlmTestResponse = {
  ok: boolean;
  model: string;
  base_url: string;
  reply: string;
  latency_ms: number;
};
type EmbeddingTestResponse = {
  ok: boolean;
  model: string;
  base_url: string;
  dimension: number;
  latency_ms: number;
};
type EmbeddingStatus = {
  document_id: number;
  chunk_count: number;
  indexed_count: number;
  vector_indexed_count?: number;
  model?: string | null;
  dimension?: number | null;
  vector_store?: string | null;
  ready: boolean;
};
type EmbeddingIndexResponse = {
  document_id: number;
  model?: string | null;
  dimension: number;
  indexed: number;
  skipped: number;
  total_chunks: number;
  vector_indexed?: number;
  vector_store?: string | null;
  ready: boolean;
  message: string;
};
type DeleteResponse = { success: boolean; deleted_id: number; message: string };
type ProcessingStage = {
  id: string;
  name: string;
  count: number;
  status: string;
  detail: string;
};
type ProcessingEdge = {
  source: string;
  target: string;
  value: number;
  label: string;
};
type ProcessingPipeline = {
  stages: ProcessingStage[];
  edges: ProcessingEdge[];
  metrics: Record<string, number>;
};
type IntelligenceCaseRecord = {
  id: number;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};
type IntelligenceCaseDocument = {
  id: number;
  document_id: number;
  file_name: string;
  document_topic: string;
  file_type: string;
  status: string;
  chunk_count: number;
  entity_count: number;
  event_count: number;
  relation_count: number;
  evidence_count: number;
  vector_ready: boolean;
  graph_ready: boolean;
  created_at: string;
};
type IntelligenceCaseStatus = {
  case: IntelligenceCaseRecord;
  documents: IntelligenceCaseDocument[];
  stages: ProcessingStage[];
  metrics: Record<string, number>;
};
type IntelligenceCaseUploadResponse = {
  case: IntelligenceCaseRecord;
  documents: IntelligenceCaseDocument[];
  status: IntelligenceCaseStatus;
};
type IntelligenceCaseEmbeddingResponse = {
  case_id: number;
  document_count: number;
  ready_document_count: number;
  indexed: number;
  skipped: number;
  total_chunks: number;
  vector_indexed: number;
  vector_store?: string | null;
  errors: string[];
  status: IntelligenceCaseStatus;
  message: string;
};
type IntelligenceEvent = {
  id: number;
  document_id: number;
  chunk_id?: number | null;
  event_title: string;
  event_date?: string | null;
  event_time_raw?: string | null;
  event_type?: string | null;
  location_name?: string | null;
  actor_names?: string | null;
  summary?: string | null;
  evidence_text?: string | null;
};
type IntelligenceEntity = {
  id: number;
  document_id: number;
  chunk_id?: number | null;
  name: string;
  entity_type: string;
  evidence_text?: string | null;
};
type ActiveView = 'home' | 'situation' | 'chain' | 'knowledge' | 'workspace' | 'qa';
type QaRunState = 'idle' | 'running' | 'success' | 'error';
type ViewRecommendation = { view_type: string; title: string; rationale: string; priority: number };
type QueryHistoryItem = {
  id: number;
  query_text: string;
  query_mode?: string | null;
  answer_text?: string | null;
  created_at: string;
};
type ConflictFilters = { years: number[]; admin1: { name: string; count: number }[] };
type SourceStats = { acled: { name: string; count: number; source_type: string }[]; weibo: { name: string; count: number; source_type: string }[] };
type CountItem = { name: string; count: number };
type SeriesItem = { name: string; data: number[] };
type PhaseEvolutionResponse = {
  months: string[];
  event_types: string[];
  series: SeriesItem[];
  fatalities: number[];
};
type HeatmapCell = { region: string; event_type: string; value: number };
type RegionEventMatrixResponse = {
  regions: string[];
  event_types: string[];
  cells: HeatmapCell[];
};
type ActorPairItem = {
  source: string;
  target: string;
  relation_type?: string | null;
  count: number;
  fatalities: number;
};
type ConflictOverview = {
  total_events: number;
  date_min?: string | null;
  date_max?: string | null;
  total_fatalities: number;
  geo_events: number;
  event_type_counts: CountItem[];
  admin1_counts: CountItem[];
  source_counts: CountItem[];
  yearly_counts: CountItem[];
  knowledge: {
    entities: number;
    event_entity_links: number;
    evidences: number;
    relations: number;
  };
};
type EventChainDetail = {
  anchor: ConflictEvent | null;
  chain: ConflictEvent[];
  before: ConflictEvent[];
  after: ConflictEvent[];
  same_region_timeline: TimelinePoint[];
  actor_counts: CountItem[];
  source_counts: CountItem[];
  map_points: MapPoint[];
  notes: string[];
  analysis_notes: string[];
};
type KnowledgeGraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};
type EntityMention = {
  id: number;
  name: string;
  entity_type: string;
  role_type: string;
  description?: string | null;
};
type EvidenceItem = {
  id: number;
  evidence_type: string;
  quote_text?: string | null;
  source_label?: string | null;
};
type EventEvidenceResponse = {
  event: ConflictEvent | null;
  entities: EntityMention[];
  evidences: EvidenceItem[];
  graph: KnowledgeGraphResponse;
};
type KnowledgeDeriveJob = {
  status: 'idle' | 'running' | 'completed' | 'failed';
  message: string;
  processed_events: number;
  total_events: number;
  entities: number;
  event_entity_links: number;
  evidences: number;
  relations: number;
  error?: string | null;
};

function buildFilterQuery(year: number | '', admin1: string) {
  const params = new URLSearchParams();
  if (year !== '') params.set('year', String(year));
  if (admin1) params.set('admin1', admin1);
  const q = params.toString();
  return q ? `&${q}` : '';
}

const EVENT_PAGE_SIZE = 12;
const CHUNK_PAGE_SIZE = 12;
const POST_PAGE_SIZE = 8;
const HISTORY_PAGE_SIZE = 8;
const MAX_ASK_FILES = 3;
const ASK_FILE_EXTENSIONS = new Set(['pdf', 'docx', 'txt']);

function fileExtension(name: string) {
  const index = name.lastIndexOf('.');
  return index >= 0 ? name.slice(index + 1).toLowerCase() : '';
}

function pageOffset(page: number, size: number) {
  return Math.max(0, page) * size;
}

function pageRangeLabel(page: number, size: number, total: number, count: number) {
  if (total <= 0 || count <= 0) return '0';
  const start = pageOffset(page, size) + 1;
  return `${start}-${Math.min(total, start + count - 1)}`;
}

function totalPages(total: number, size: number) {
  return Math.max(1, Math.ceil(total / size));
}

function visiblePages(currentPage: number, pages: number) {
  const start = Math.max(0, Math.min(currentPage - 2, pages - 5));
  const end = Math.min(pages, start + 5);
  return Array.from({ length: end - start }, (_, index) => start + index);
}

function pct(value: number, total: number) {
  if (!total) return '0%';
  return `${Math.round((value / total) * 100)}%`;
}

const VIEW_TABS: Array<{ id: ActiveView; label: string; short: string }> = [
  { id: 'home', label: '首页', short: '首' },
  { id: 'situation', label: '态势分析', short: '势' },
  { id: 'chain', label: '事件追踪', short: '链' },
  { id: 'knowledge', label: '关系网络', short: '网' },
  { id: 'workspace', label: '情报管理', short: '情' },
  { id: 'qa', label: '智能研判', short: '问' },
];
const CURRENT_CASE_STORAGE_KEY = 'rus-ukr-current-intelligence-case';
const CASE_FILE_LIMIT = 5;

export default function App() {
  const [summaries, setSummaries] = useState<DatasetSummary[]>([]);
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [events, setEvents] = useState<ConflictEvent[]>([]);
  const [posts, setPosts] = useState<WeiboPost[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [chunks, setChunks] = useState<ParsedParagraph[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<number | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<number | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [qaRunState, setQaRunState] = useState<QaRunState>('idle');
  const [activeView, setActiveView] = useState<ActiveView>('home');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<DocumentGraphResponse | null>(null);
  const [graphHint, setGraphHint] = useState<string | null>(null);
  const [qaQuestion, setQaQuestion] = useState('2024年苏梅州冲突事件的主要类型有哪些？');
  const [qaResult, setQaResult] = useState<QAResponse | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatSessions, setChatSessions] = useState<ChatSessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [globalAskDraft, setGlobalAskDraft] = useState('');
  const [askFiles, setAskFiles] = useState<File[]>([]);
  const [showHistoryPanel, setShowHistoryPanel] = useState(false);
  const [selectedSource, setSelectedSource] = useState<QASource | null>(null);
  const [activeSessionTitle, setActiveSessionTitle] = useState('新的研判会话');
  const [highlightChunkId, setHighlightChunkId] = useState<number | null>(null);
  const [mapPoints, setMapPoints] = useState<MapPoint[]>([]);
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [pipelineSummary, setPipelineSummary] = useState<ProcessingPipeline | null>(null);
  const [chainInsight, setChainInsight] = useState<QAResponse | null>(null);
  const [filterYear, setFilterYear] = useState<number | ''>('');
  const [filterAdmin1, setFilterAdmin1] = useState('');
  const [eventPage, setEventPage] = useState(0);
  const [eventKeyword, setEventKeyword] = useState('');
  const [eventTotal, setEventTotal] = useState(0);
  const [chunkPage, setChunkPage] = useState(0);
  const [chunkKeyword, setChunkKeyword] = useState('');
  const [chunkTotal, setChunkTotal] = useState(0);
  const [postPage, setPostPage] = useState(0);
  const [postKeyword, setPostKeyword] = useState('');
  const [postTotal, setPostTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyKeyword, setHistoryKeyword] = useState('');
  const [historyTotal, setHistoryTotal] = useState(0);
  const [showOpsPanel, setShowOpsPanel] = useState(false);
  const [filters, setFilters] = useState<ConflictFilters | null>(null);
  const [anchorEventId, setAnchorEventId] = useState('');
  const [viewRecs, setViewRecs] = useState<ViewRecommendation[]>([]);
  const [queryHistory, setQueryHistory] = useState<QueryHistoryItem[]>([]);
  const [sourceStats, setSourceStats] = useState<SourceStats | null>(null);
  const [currentCase, setCurrentCase] = useState<IntelligenceCaseRecord | null>(null);
  const [caseStatus, setCaseStatus] = useState<IntelligenceCaseStatus | null>(null);
  const [caseDocuments, setCaseDocuments] = useState<IntelligenceCaseDocument[]>([]);
  const [caseFiles, setCaseFiles] = useState<File[]>([]);
  const [caseGraph, setCaseGraph] = useState<KnowledgeGraphResponse | null>(null);
  const [caseTimeline, setCaseTimeline] = useState<TimelinePoint[]>([]);
  const [caseEvents, setCaseEvents] = useState<IntelligenceEvent[]>([]);
  const [caseEntities, setCaseEntities] = useState<IntelligenceEntity[]>([]);
  const [selectedCaseEventId, setSelectedCaseEventId] = useState<number | null>(null);
  const [selectedCaseEntityId, setSelectedCaseEntityId] = useState<number | null>(null);
  const [phaseEvolution, setPhaseEvolution] = useState<PhaseEvolutionResponse | null>(null);
  const [regionMatrix, setRegionMatrix] = useState<RegionEventMatrixResponse | null>(null);
  const [actorPairs, setActorPairs] = useState<ActorPairItem[]>([]);
  const [overview, setOverview] = useState<ConflictOverview | null>(null);
  const [chainDetail, setChainDetail] = useState<EventChainDetail | null>(null);
  const [knowledgeGraph, setKnowledgeGraph] = useState<KnowledgeGraphResponse | null>(null);
  const [eventEvidence, setEventEvidence] = useState<EventEvidenceResponse | null>(null);
  const [deriveJob, setDeriveJob] = useState<KnowledgeDeriveJob | null>(null);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const pipelineRef = useRef<HTMLDivElement | null>(null);
  const sourceStatsRef = useRef<HTMLDivElement | null>(null);
  const phaseEvolutionRef = useRef<HTMLDivElement | null>(null);
  const regionMatrixRef = useRef<HTMLDivElement | null>(null);
  const actorPairsRef = useRef<HTMLDivElement | null>(null);
  const chainTimelineRef = useRef<HTMLDivElement | null>(null);
  const chainActorRef = useRef<HTMLDivElement | null>(null);
  const knowledgeGraphRef = useRef<HTMLDivElement | null>(null);
  const caseTimelineChartRef = useRef<HTMLDivElement | null>(null);
  const caseGraphRef = useRef<HTMLDivElement | null>(null);
  const askFileInputRef = useRef<HTMLInputElement | null>(null);
  const chartInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const mapInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const timelineInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const pipelineInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const sourceStatsInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const phaseEvolutionInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const regionMatrixInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const actorPairsInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const chainTimelineInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const chainActorInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const knowledgeGraphInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const caseTimelineInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);
  const caseGraphInstance = useRef<{ dispose: () => void; resize: () => void } | null>(null);

  const chartGraph = useMemo(() => {
    if (qaResult?.subgraph_nodes?.length) {
      return {
        document_id: selectedDocumentId ?? 0,
        nodes: qaResult.subgraph_nodes,
        edges: qaResult.subgraph_edges,
        updated_at: graphData?.updated_at ?? null,
      };
    }
    return graphData;
  }, [qaResult, graphData, selectedDocumentId]);

  const displayChunks = chunks;

  async function ensureDefaultWorkspaceId() {
    if (selectedWorkspaceId) return selectedWorkspaceId;
    const workspace = await fetchJson<Workspace>('/app/default-workspace');
    setWorkspaces([workspace]);
    setSelectedWorkspaceId(workspace.id);
    return workspace.id;
  }

  function chatMessageFromRecord(message: ChatMessageRecord): ChatMessage {
    return {
      id: String(message.id),
      role: message.role,
      content: message.content,
      sources: message.sources ?? [],
    };
  }

  async function loadChatSessions() {
    const sessions = await fetchJson<ChatSessionRecord[]>('/chat/sessions?limit=40');
    setChatSessions(sessions);
  }

  async function openChatSession(session: ChatSessionRecord) {
    try {
      setSubmitting(true);
      const messages = await fetchJson<ChatMessageRecord[]>(`/chat/sessions/${session.id}/messages`);
      const mapped = messages.map(chatMessageFromRecord);
      setActiveSessionId(session.id);
      setActiveSessionTitle(session.title);
      setChatMessages(mapped);
      setSelectedSource(null);
      setShowHistoryPanel(false);
      const lastAssistant = [...mapped].reverse().find((message) => message.role === 'assistant');
      if (lastAssistant) {
        setQaRunState('success');
        setQaResult({
          answer: lastAssistant.content,
          mode: 'chat',
          sources: lastAssistant.sources ?? [],
          subgraph_nodes: [],
          subgraph_edges: [],
        });
      } else {
        setQaRunState('idle');
        setQaResult(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '历史会话加载失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function loadGraphForDocument(documentId: number | null) {
    if (!documentId) {
      setGraphData(null);
      setGraphHint(null);
      setEmbeddingStatus(null);
      return;
    }
    try {
      const graph = await fetchJson<DocumentGraphResponse>(`/documents/${documentId}/graph`);
      setGraphData(graph);
      setGraphHint(
        graph.nodes.length
          ? null
          : '该文档已解析，但尚未生成结构化关系。完成关系提取后会展示节点、关系和证据片段。',
      );
    } catch {
      setGraphData(null);
      setGraphHint('暂无结构化关系。请选择文档并完成关系提取。');
    }
    try {
      setEmbeddingStatus(await fetchJson<EmbeddingStatus>(`/documents/${documentId}/embeddings/status`));
    } catch {
      setEmbeddingStatus(null);
    }
  }

  async function loadDocumentChunks(documentId: number, page = chunkPage, keyword = chunkKeyword) {
    const params = new URLSearchParams();
    params.set('limit', String(CHUNK_PAGE_SIZE));
    params.set('offset', String(pageOffset(page, CHUNK_PAGE_SIZE)));
    const countParams = new URLSearchParams();
    const trimmed = keyword.trim();
    if (trimmed) {
      params.set('keyword', trimmed);
      countParams.set('keyword', trimmed);
    }
    const [chunkRows, count] = await Promise.all([
      fetchJson<ParsedParagraph[]>(`/documents/${documentId}/chunks?${params.toString()}`),
      fetchJson<CountResponse>(`/documents/${documentId}/chunks/count?${countParams.toString()}`),
    ]);
    setChunks(chunkRows);
    setChunkTotal(count.total);
  }

  async function loadWorkspaceDocuments(workspaceId?: number) {
    if (!workspaceId) {
      await ensureDefaultWorkspaceId();
    }
    const documentData = await fetchJson<DocumentRecord[]>('/documents');
    setDocuments(documentData);
    setQaResult(null);
    setHighlightChunkId(null);
    if (documentData.length > 0) {
      const currentStillExists = selectedDocumentId
        ? documentData.some((document) => document.id === selectedDocumentId)
        : false;
      const documentId = currentStillExists && selectedDocumentId ? selectedDocumentId : documentData[0].id;
      setSelectedDocumentId(documentId);
      const page = currentStillExists ? chunkPage : 0;
      const keyword = currentStillExists ? chunkKeyword : '';
      if (!currentStillExists) {
        setChunkPage(0);
        setChunkKeyword('');
      }
      await loadDocumentChunks(documentId, page, keyword);
      await loadGraphForDocument(documentId);
    } else {
      setSelectedDocumentId(null);
      setChunks([]);
      setChunkTotal(0);
      setChunkPage(0);
      setChunkKeyword('');
      await loadGraphForDocument(null);
    }
  }

  async function loadIntelligenceCase(caseId: number) {
    const status = await fetchJson<IntelligenceCaseStatus>(`/intelligence/cases/${caseId}`);
    const [graphResult, timelineResult, eventResult, entityResult] = await Promise.allSettled([
      fetchJson<KnowledgeGraphResponse>(`/intelligence/cases/${caseId}/graph`),
      fetchJson<TimelinePoint[]>(`/intelligence/cases/${caseId}/timeline`),
      fetchJson<IntelligenceEvent[]>(`/intelligence/cases/${caseId}/events?limit=80`),
      fetchJson<IntelligenceEntity[]>(`/intelligence/cases/${caseId}/entities?limit=80`),
    ]);
    const graph = graphResult.status === 'fulfilled' ? graphResult.value : { nodes: [], edges: [] };
    const caseTimelineRows = timelineResult.status === 'fulfilled' ? timelineResult.value : [];
    const caseEventRows = eventResult.status === 'fulfilled' ? eventResult.value : [];
    const caseEntityRows = entityResult.status === 'fulfilled' ? entityResult.value : [];
    [graphResult, timelineResult, eventResult, entityResult].forEach((result) => {
      if (result.status === 'rejected') {
        console.warn('[情报管理] 附属视图加载失败', result.reason);
      }
    });
    setCurrentCase(status.case);
    setCaseStatus(status);
    setCaseDocuments(status.documents);
    setCaseGraph(graph);
    setCaseTimeline(caseTimelineRows);
    setCaseEvents(caseEventRows);
    setCaseEntities(caseEntityRows);
    setSelectedCaseEventId((previous) => (
      previous && caseEventRows.some((event) => event.id === previous)
        ? previous
        : caseEventRows[0]?.id ?? null
    ));
    setSelectedCaseEntityId((previous) => (
      previous && caseEntityRows.some((entity) => entity.id === previous)
        ? previous
        : null
    ));
    const selectedStillExists = selectedDocumentId
      ? status.documents.some((document) => document.document_id === selectedDocumentId)
      : false;
    const nextDocumentId = selectedStillExists
      ? selectedDocumentId
      : status.documents[0]?.document_id ?? null;
    setSelectedDocumentId(nextDocumentId);
    if (nextDocumentId) {
      await loadDocumentChunks(nextDocumentId, selectedStillExists ? chunkPage : 0, selectedStillExists ? chunkKeyword : '');
      await loadGraphForDocument(nextDocumentId);
    } else {
      setChunks([]);
      setChunkTotal(0);
      setGraphData(null);
      setEmbeddingStatus(null);
    }
  }

  async function ensureCurrentCase() {
    if (currentCase) return currentCase.id;
    const stored = window.sessionStorage.getItem(CURRENT_CASE_STORAGE_KEY);
    if (stored) {
      const storedId = Number(stored);
      if (Number.isFinite(storedId) && storedId > 0) {
        try {
          await loadIntelligenceCase(storedId);
          return storedId;
        } catch {
          window.sessionStorage.removeItem(CURRENT_CASE_STORAGE_KEY);
        }
      }
    }
    const created = await postJson<IntelligenceCaseRecord>('/intelligence/cases', {
      title: '当前分析',
    });
    window.sessionStorage.setItem(CURRENT_CASE_STORAGE_KEY, String(created.id));
    setCurrentCase(created);
    setCaseStatus({
      case: created,
      documents: [],
      stages: [],
      metrics: {},
    });
    setCaseDocuments([]);
    setCaseGraph({ nodes: [], edges: [] });
    setCaseTimeline([]);
    setCaseEvents([]);
    setCaseEntities([]);
    setSelectedCaseEventId(null);
    setSelectedCaseEntityId(null);
    return created.id;
  }

  async function createFreshIntelligenceCase() {
    try {
      setSubmitting(true);
      setError(null);
      const created = await postJson<IntelligenceCaseRecord>('/intelligence/cases', {
        title: '当前分析',
      });
      window.sessionStorage.setItem(CURRENT_CASE_STORAGE_KEY, String(created.id));
      setCurrentCase(created);
      setCaseStatus({ case: created, documents: [], stages: [], metrics: {} });
      setCaseDocuments([]);
      setCaseFiles([]);
      setCaseGraph({ nodes: [], edges: [] });
      setCaseTimeline([]);
      setCaseEvents([]);
      setCaseEntities([]);
      setSelectedCaseEventId(null);
      setSelectedCaseEntityId(null);
      setSelectedDocumentId(null);
      setChunks([]);
      setChunkTotal(0);
      setGraphData(null);
      setEmbeddingStatus(null);
      setSuccess('已开始新的材料分析。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '新建材料分析失败');
    } finally {
      setSubmitting(false);
    }
  }

  function addCaseFiles(fileList: FileList | File[]) {
    const incoming = Array.from(fileList).filter((file) => /\.(pdf|docx|txt)$/i.test(file.name));
    const available = Math.max(0, CASE_FILE_LIMIT - caseDocuments.length - caseFiles.length);
    if (incoming.length > available) {
      setError(`当前分析最多支持 ${CASE_FILE_LIMIT} 个文件，当前还可添加 ${available} 个。`);
    }
    setCaseFiles((previous) => [...previous, ...incoming.slice(0, available)]);
  }

  function removeCaseFile(index: number) {
    setCaseFiles((previous) => previous.filter((_, itemIndex) => itemIndex !== index));
  }

  async function uploadCaseFiles() {
    if (!caseFiles.length) {
      setError('请选择需要导入的 PDF/DOCX/TXT 材料。');
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      setSuccess(null);
      const caseId = await ensureCurrentCase();
      const formData = new FormData();
      caseFiles.forEach((file) => formData.append('files', file));
      const response = await postFormData<IntelligenceCaseUploadResponse>(
        `/intelligence/cases/${caseId}/documents`,
        formData,
      );
      window.sessionStorage.setItem(CURRENT_CASE_STORAGE_KEY, String(response.case.id));
      setCurrentCase(response.case);
      setCaseStatus(response.status);
      setCaseDocuments(response.documents);
      setCaseFiles([]);
      await loadIntelligenceCase(response.case.id);
      setSuccess('情报材料已完成导入、分段与结构化抽取。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '情报材料导入失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function processCurrentCase() {
    const caseId = await ensureCurrentCase();
    try {
      setSubmitting(true);
      setError(null);
      const status = await postEmpty<IntelligenceCaseStatus>(`/intelligence/cases/${caseId}/process`);
      setCaseStatus(status);
      setCaseDocuments(status.documents);
      await loadIntelligenceCase(caseId);
      setSuccess('材料已重新完成结构化处理。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '情报材料处理失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function buildCaseEmbeddingIndex(force = false) {
    const caseId = await ensureCurrentCase();
    if (!caseDocuments.length) {
      setError('请先上传并处理至少一份情报材料。');
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      setSuccess(null);
      const result = await postEmpty<IntelligenceCaseEmbeddingResponse>(
        `/intelligence/cases/${caseId}/embeddings${force ? '?force=true' : ''}`,
      );
      setCaseStatus(result.status);
      setCaseDocuments(result.status.documents);
      await loadIntelligenceCase(caseId);
      const errorSuffix = result.errors.length ? `；${result.errors.length} 个文件未完成` : '';
      setSuccess(
        `语义索引已更新：新建 ${result.indexed} 个向量，跳过 ${result.skipped} 个，覆盖 ${result.vector_indexed}/${result.total_chunks} 个段落${errorSuffix}。`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '语义索引生成失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function importAcledToMysql(force = false) {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<{ message: string; total: number; skipped?: boolean }>(
        `/datasets/events/reindex${force ? '?force=true' : ''}`,
      );
      setSuccess(`事件库已更新，共 ${result.total.toLocaleString()} 条记录${result.skipped ? '' : '。'}`);
      const health = await fetchJson<HealthInfo>('/health');
      setHealthInfo(health);
      await loadDashboard();
    } catch (err) {
      setError(err instanceof Error ? err.message : '事件数据导入失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function syncAcledToNeo4j() {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<{
        message: string;
        mode: string;
        mysql_total: number;
        synced: number;
        neo4j_conflict_events: number;
      }>('/datasets/events/sync-neo4j?full=true');
      setSuccess(
        `关系库已更新 · 事件 ${result.mysql_total.toLocaleString()} 条 · 本次刷新 ${result.synced.toLocaleString()} 条 · 关系节点 ${result.neo4j_conflict_events.toLocaleString()} 个`,
      );
      const health = await fetchJson<HealthInfo>('/health');
      setHealthInfo(health);
    } catch (err) {
      setError(err instanceof Error ? err.message : '关系库更新失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function deriveAcledKnowledge() {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<KnowledgeDeriveJob>('/datasets/events/derive-knowledge');
      setDeriveJob(result);
      setSuccess(
        result.status === 'running'
          ? '知识层派生任务已启动，后台正在处理；可在“知识组织”页查看进度。'
          : `${result.message}：实体 ${result.entities.toLocaleString()} · 链接 ${result.event_entity_links.toLocaleString()} · 证据 ${result.evidences.toLocaleString()} · 关系 ${result.relations.toLocaleString()}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '事件知识层派生失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function testLlmConnection() {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<LlmTestResponse>('/llm/test');
      setSuccess(`大模型连接正常：${result.model} · ${result.latency_ms} ms · ${result.reply}`);
      setLlmStatus(await fetchJson<LlmStatus>('/llm/status'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型服务连接失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function testEmbeddingConnection() {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<EmbeddingTestResponse>('/llm/embedding/test');
      setSuccess(`向量服务连接正常：${result.model} · ${result.dimension} 维 · ${result.latency_ms} ms`);
      setLlmStatus(await fetchJson<LlmStatus>('/llm/status'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '向量服务连接失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function buildEmbeddingIndex(force = false) {
    if (!selectedDocumentId) {
      setError('请先选择已解析的文档。');
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await postEmpty<EmbeddingIndexResponse>(
        `/documents/${selectedDocumentId}/embeddings${force ? '?force=true' : ''}`,
      );
      setSuccess(
        `${result.message} 模型 ${result.model || 'unknown'} · ${result.dimension} 维 · 新建 ${result.indexed} · 向量库 ${result.vector_indexed ?? 0}/${result.total_chunks} · 跳过 ${result.skipped}`,
      );
      setEmbeddingStatus(await fetchJson<EmbeddingStatus>(`/documents/${selectedDocumentId}/embeddings/status`));
      setPipelineSummary(await fetchJson<ProcessingPipeline>('/datasets/pipeline-summary'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '文档向量索引失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function generateEventChainInsight() {
    const eventId = anchorEventId || chainDetail?.anchor?.event_id_cnty;
    if (!eventId) {
      setError('请先在事件链页选择一个锚点事件。');
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const workspaceId = await ensureDefaultWorkspaceId();
      const question = [
        `请基于锚点事件 ${eventId} 生成事件链解读。`,
        '要求说明：1）锚点前后事件如何关联；2）同地区演化特征；3）涉及的主要主体；4）可以引用哪些公开来源摘录作为证据；5）有哪些不确定性。',
      ].join('');
      const result = await postJson<QAResponse>(`/workspaces/${workspaceId}/query`, {
        question,
        mode: 'event_chain',
        document_id: null,
        event_id_cnty: eventId,
      });
      setChainInsight(result);
      setQaResult(result);
      setSuccess('已生成事件链智能解读，并更新问答相关关系。');
      setHistoryPage(0);
      await loadQueryHistoryList(workspaceId, 0, historyKeyword);
      await loadViewRecommendations();
    } catch (err) {
      setError(err instanceof Error ? err.message : '事件链智能解读失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function loadConflictViz(
    year: number | '' = filterYear,
    admin1: string = filterAdmin1,
    page = eventPage,
    keyword = eventKeyword,
  ) {
    const fq = buildFilterQuery(year, admin1);
    const eventParams = new URLSearchParams();
    eventParams.set('limit', String(EVENT_PAGE_SIZE));
    eventParams.set('offset', String(pageOffset(page, EVENT_PAGE_SIZE)));
    const eventCountParams = new URLSearchParams();
    if (year !== '') eventParams.set('year', String(year));
    if (year !== '') eventCountParams.set('year', String(year));
    if (admin1) {
      eventParams.set('admin1', admin1);
      eventCountParams.set('admin1', admin1);
    }
    const trimmed = keyword.trim();
    if (trimmed) {
      eventParams.set('keyword', trimmed);
      eventCountParams.set('keyword', trimmed);
    }
    const [timelineData, eventData, eventCount, mapData] = await Promise.all([
      fetchJson<TimelinePoint[]>(`/datasets/events/timeline?limit=3000${fq}`),
      fetchJson<ConflictEvent[]>(`/datasets/events?${eventParams.toString()}`),
      fetchJson<CountResponse>(`/datasets/events/count?${eventCountParams.toString()}`),
      fetchJson<MapPoint[]>(`/datasets/events/map?limit=1500${fq}`),
    ]);
    setTimeline(timelineData);
    setEvents(eventData);
    setEventTotal(eventCount.total);
    setMapPoints(mapData);
    if (eventData[0] && (!anchorEventId || !eventData.some((event) => event.event_id_cnty === anchorEventId))) {
      setAnchorEventId(eventData[0].event_id_cnty);
    }
  }

  async function loadEventChainDetail(eventId: string) {
    if (!eventId) {
      setChainDetail(null);
      return;
    }
    try {
      const data = await fetchJson<EventChainDetail>(`/datasets/events/${encodeURIComponent(eventId)}/chain-detail?limit=40`);
      setChainDetail(data);
    } catch (err) {
      setChainDetail(null);
      setError(err instanceof Error ? err.message : '事件链详情加载失败');
    }
  }

  async function loadKnowledgeGraph(eventId?: string) {
    try {
      const query = eventId ? `?event_id_cnty=${encodeURIComponent(eventId)}&limit=120` : '?limit=180';
      const data = await fetchJson<KnowledgeGraphResponse>(`/datasets/events/knowledge-graph${query}`);
      setKnowledgeGraph(data);
    } catch {
      setKnowledgeGraph({ nodes: [], edges: [] });
    }
  }

  async function loadEventEvidence(eventId: string) {
    if (!eventId) {
      setEventEvidence(null);
      return;
    }
    try {
      const data = await fetchJson<EventEvidenceResponse>(`/datasets/events/${encodeURIComponent(eventId)}/evidence`);
      setEventEvidence(data);
    } catch {
      setEventEvidence(null);
    }
  }

  async function loadViewRecommendations() {
    if (!selectedWorkspaceId) return;
    const q = encodeURIComponent(qaQuestion.slice(0, 80));
    const recs = await fetchJson<ViewRecommendation[]>(
      `/workspaces/${selectedWorkspaceId}/viz/recommend?mode=unified&question=${q}`,
    );
    setViewRecs(recs.sort((a, b) => a.priority - b.priority));
  }

  async function loadQueryHistoryList(
    workspaceId: number | null = selectedWorkspaceId,
    page = historyPage,
    keyword = historyKeyword,
  ) {
    if (!workspaceId) return;
    const params = new URLSearchParams();
    params.set('limit', String(HISTORY_PAGE_SIZE));
    params.set('offset', String(pageOffset(page, HISTORY_PAGE_SIZE)));
    const countParams = new URLSearchParams();
    const trimmed = keyword.trim();
    if (trimmed) {
      params.set('keyword', trimmed);
      countParams.set('keyword', trimmed);
    }
    const [items, count] = await Promise.all([
      fetchJson<QueryHistoryItem[]>(`/workspaces/${workspaceId}/query/history?${params.toString()}`),
      fetchJson<CountResponse>(`/workspaces/${workspaceId}/query/history/count?${countParams.toString()}`),
    ]);
    setQueryHistory(items);
    setHistoryTotal(count.total);
  }

  async function importWeiboToMysql(force = false) {
    setSubmitting(true);
    setError(null);
    try {
      const result = await postEmpty<{ message: string; total: number; skipped?: boolean }>(
        `/datasets/text-samples/reindex${force ? '?force=true' : ''}`,
      );
      setSuccess(`${result.message}，共 ${result.total.toLocaleString()} 条文本样本`);
      await loadDashboard();
    } catch (err) {
      setError(err instanceof Error ? err.message : '文本样本导入失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function loadDashboard() {
    const warnings: string[] = [];
    const safeFetch = async <T,>(label: string, request: Promise<T>, fallback: T): Promise<T> => {
      try {
        return await request;
      } catch (err) {
        warnings.push(label);
        console.warn(`${label} 加载失败`, err);
        return fallback;
      }
    };

    const fallbackOverview: ConflictOverview = {
      total_events: 0,
      date_min: null,
      date_max: null,
      total_fatalities: 0,
      geo_events: 0,
      event_type_counts: [],
      admin1_counts: [],
      source_counts: [],
      yearly_counts: [],
      knowledge: { entities: 0, event_entity_links: 0, evidences: 0, relations: 0 },
    };

    const [defaultWorkspace, health] = await Promise.all([
      safeFetch<Workspace | null>('默认数据域', fetchJson<Workspace>('/app/default-workspace'), null),
      safeFetch<HealthInfo>('健康检查', fetchJson<HealthInfo>('/health'), {
        status: 'unknown',
        app: 'Russo-Ukrainian War Monitor',
        mysql: 'unknown',
        neo4j: 'unknown',
        conflict_events: 0,
      }),
    ]);
    setFilters({ years: [], admin1: [] });
    setOverview(fallbackOverview);
    setHealthInfo(health);
    const workspaceData = defaultWorkspace ? [defaultWorkspace] : [];
    setWorkspaces(workspaceData);

    if (defaultWorkspace) {
      setSelectedWorkspaceId(defaultWorkspace.id);
    } else {
      setSelectedWorkspaceId(null);
      setDocuments([]);
      setSelectedDocumentId(null);
      setChunks([]);
      setGraphData(null);
      setGraphHint(null);
    }

    if (warnings.length) {
      setError(`部分数据加载失败：${Array.from(new Set(warnings)).join('、')}。核心界面仍会继续显示。`);
    }

    Promise.all([
      safeFetch<ConflictFilters>('态势筛选项', fetchJson<ConflictFilters>('/datasets/events/filters'), {
        years: [],
        admin1: [],
      }),
      safeFetch<ConflictOverview>('态势总览', fetchJson<ConflictOverview>('/datasets/events/overview'), fallbackOverview),
    ]).then(([filterData, overviewData]) => {
      setFilters(filterData);
      setOverview(overviewData);
    });

    fetchJson<LlmStatus>('/llm/status')
      .then((status) => setLlmStatus(status))
      .catch((err) => console.warn('模型状态加载失败', err));

    fetchJson<ChatSessionRecord[]>('/chat/sessions?limit=40')
      .then(setChatSessions)
      .catch((err) => console.warn('会话历史加载失败', err));
  }

  async function loadSituationViewData() {
    try {
      await Promise.all([
        loadConflictViz(),
        fetchJson<PhaseEvolutionResponse>('/datasets/events/phase-evolution').then(setPhaseEvolution),
        fetchJson<RegionEventMatrixResponse>('/datasets/events/region-event-matrix').then(setRegionMatrix),
        fetchJson<ActorPairItem[]>('/datasets/events/actor-pairs?limit=18').then(setActorPairs),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '态势分析数据加载失败');
    }
  }

  async function loadWeiboPosts(page = postPage, keyword = postKeyword) {
    const params = new URLSearchParams();
    params.set('limit', String(POST_PAGE_SIZE));
    params.set('offset', String(pageOffset(page, POST_PAGE_SIZE)));
    const countParams = new URLSearchParams();
    const trimmed = keyword.trim();
    if (trimmed) {
      params.set('keyword', trimmed);
      countParams.set('keyword', trimmed);
    }
    const [items, count] = await Promise.all([
      fetchJson<WeiboPost[]>(`/datasets/text-samples?${params.toString()}`),
      fetchJson<CountResponse>(`/datasets/text-samples/count?${countParams.toString()}`),
    ]);
    setPosts(items);
    setPostTotal(count.total);
  }

  async function loadDataViewData(page = postPage, keyword = postKeyword) {
    try {
      const [summaryData, statsData, pipelineData] = await Promise.all([
        fetchJson<DatasetSummary[]>('/datasets/summary'),
        fetchJson<SourceStats>('/datasets/sources/stats'),
        fetchJson<ProcessingPipeline>('/datasets/pipeline-summary'),
      ]);
      setSummaries(summaryData);
      setSourceStats(statsData);
      setPipelineSummary(pipelineData);
      await loadWeiboPosts(page, keyword);
    } catch (err) {
      setError(err instanceof Error ? err.message : '数据来源页加载失败');
    }
  }

  async function loadWorkspaceViewData() {
    try {
      const caseId = await ensureCurrentCase();
      await loadIntelligenceCase(caseId);
      const workspaceId = await ensureDefaultWorkspaceId();
      await loadQueryHistoryList(workspaceId);
      await loadChatSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : '情报管理加载失败');
    }
  }

  async function loadKnowledgeViewData() {
    try {
      await loadKnowledgeGraph(anchorEventId || undefined);
      if (anchorEventId) {
        await loadEventEvidence(anchorEventId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '知识组织页加载失败');
    }
  }

  async function loadChainViewData() {
    try {
      if (!events.length) {
        await loadConflictViz();
      }
      if (anchorEventId) {
        await loadEventChainDetail(anchorEventId);
        await loadEventEvidence(anchorEventId);
        await loadKnowledgeGraph(anchorEventId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '事件链页加载失败');
    }
  }

  useEffect(() => {
    let cancelled = false;
    const bootTimer = window.setTimeout(() => {
      if (cancelled) return;
      setLoading(false);
      setError('初始化数据加载较慢，已先进入界面。请检查后端服务或刷新当前页面。');
    }, 8000);

    async function load() {
      try {
        setLoading(true);
        setError(null);
        await loadDashboard();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        window.clearTimeout(bootTimer);
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(bootTimer);
    };
  }, []);

  useEffect(() => {
    if (loading) return;
    if (activeView === 'home') {
      void loadWorkspaceViewData();
    } else if (activeView === 'situation') {
      void loadSituationViewData();
    } else if (activeView === 'chain') {
      void loadChainViewData();
    } else if (activeView === 'knowledge') {
      void loadKnowledgeViewData();
    } else if (activeView === 'workspace' || activeView === 'qa') {
      void loadWorkspaceViewData();
    }
  }, [activeView, loading]);

  async function handleDocumentChange(event: ChangeEvent<HTMLSelectElement>) {
    const documentId = Number(event.target.value);
    setSelectedDocumentId(documentId);
    setQaResult(null);
    setHighlightChunkId(null);
    setChunkPage(0);
    setChunkKeyword('');
    try {
      await loadDocumentChunks(documentId, 0, '');
      await loadGraphForDocument(documentId);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '段落加载失败');
    }
  }

  async function scrollToChunk(chunkId: number) {
    setHighlightChunkId(chunkId);
    const current = document.getElementById(`chunk-${chunkId}`);
    if (current) {
      current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    if (!selectedDocumentId) return;
    try {
      const position = await fetchJson<{ page: number }>(
        `/documents/${selectedDocumentId}/chunks/${chunkId}/position?limit=${CHUNK_PAGE_SIZE}`,
      );
      setChunkKeyword('');
      setChunkPage(position.page);
      await loadDocumentChunks(selectedDocumentId, position.page, '');
      window.setTimeout(() => {
        document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 80);
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法定位引用段落');
    }
  }

  async function focusMaterialChunk(documentId: number, chunkId?: number | null) {
    setSelectedDocumentId(documentId);
    setChunkKeyword('');
    if (!chunkId) {
      setChunkPage(0);
      await loadDocumentChunks(documentId, 0, '');
      return;
    }
    setHighlightChunkId(chunkId);
    try {
      const position = await fetchJson<{ page: number }>(
        `/documents/${documentId}/chunks/${chunkId}/position?limit=${CHUNK_PAGE_SIZE}`,
      );
      setChunkPage(position.page);
      await loadDocumentChunks(documentId, position.page, '');
      window.setTimeout(() => {
        document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 80);
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法定位材料原文');
    }
  }

  function openCaseEvent(event: IntelligenceEvent) {
    setSelectedCaseEventId(event.id);
    setSelectedCaseEntityId(null);
    void focusMaterialChunk(event.document_id, event.chunk_id);
  }

  function openCaseEntity(entity: IntelligenceEntity) {
    setSelectedCaseEntityId(entity.id);
    setSelectedCaseEventId(null);
    void focusMaterialChunk(entity.document_id, entity.chunk_id);
  }

  function openCaseDate(date: string) {
    const event = caseEvents.find((item) => (item.event_date || item.event_time_raw || '未标注时间') === date);
    if (event) {
      openCaseEvent(event);
    }
  }

  function handleEventSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEventPage(0);
    void loadConflictViz(filterYear, filterAdmin1, 0, eventKeyword);
  }

  function changeEventPage(delta: number) {
    const page = Math.min(totalPages(eventTotal, EVENT_PAGE_SIZE) - 1, Math.max(0, eventPage + delta));
    setEventPage(page);
    void loadConflictViz(filterYear, filterAdmin1, page, eventKeyword);
  }

  function jumpEventPage(page: number) {
    const nextPage = Math.min(totalPages(eventTotal, EVENT_PAGE_SIZE) - 1, Math.max(0, page));
    setEventPage(nextPage);
    void loadConflictViz(filterYear, filterAdmin1, nextPage, eventKeyword);
  }

  function handleChunkSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDocumentId) return;
    setChunkPage(0);
    void loadDocumentChunks(selectedDocumentId, 0, chunkKeyword);
  }

  function changeChunkPage(delta: number) {
    if (!selectedDocumentId) return;
    const page = Math.min(totalPages(chunkTotal, CHUNK_PAGE_SIZE) - 1, Math.max(0, chunkPage + delta));
    setChunkPage(page);
    void loadDocumentChunks(selectedDocumentId, page, chunkKeyword);
  }

  function jumpChunkPage(page: number) {
    if (!selectedDocumentId) return;
    const nextPage = Math.min(totalPages(chunkTotal, CHUNK_PAGE_SIZE) - 1, Math.max(0, page));
    setChunkPage(nextPage);
    void loadDocumentChunks(selectedDocumentId, nextPage, chunkKeyword);
  }

  function handlePostSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPostPage(0);
    void loadWeiboPosts(0, postKeyword);
  }

  function changePostPage(delta: number) {
    const page = Math.min(totalPages(postTotal, POST_PAGE_SIZE) - 1, Math.max(0, postPage + delta));
    setPostPage(page);
    void loadWeiboPosts(page, postKeyword);
  }

  function jumpPostPage(page: number) {
    const nextPage = Math.min(totalPages(postTotal, POST_PAGE_SIZE) - 1, Math.max(0, page));
    setPostPage(nextPage);
    void loadWeiboPosts(nextPage, postKeyword);
  }

  function handleHistorySearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHistoryPage(0);
    void loadQueryHistoryList(selectedWorkspaceId, 0, historyKeyword);
  }

  function changeHistoryPage(delta: number) {
    const page = Math.min(totalPages(historyTotal, HISTORY_PAGE_SIZE) - 1, Math.max(0, historyPage + delta));
    setHistoryPage(page);
    void loadQueryHistoryList(selectedWorkspaceId, page, historyKeyword);
  }

  function jumpHistoryPage(page: number) {
    const nextPage = Math.min(totalPages(historyTotal, HISTORY_PAGE_SIZE) - 1, Math.max(0, page));
    setHistoryPage(nextPage);
    void loadQueryHistoryList(selectedWorkspaceId, nextPage, historyKeyword);
  }

  function addAskFiles(fileList: FileList | File[]) {
    const incoming = Array.from(fileList);
    if (!incoming.length) return;

    const accepted: File[] = [];
    const rejected: string[] = [];
    for (const file of incoming) {
      if (ASK_FILE_EXTENSIONS.has(fileExtension(file.name))) {
        accepted.push(file);
      } else {
        rejected.push(file.name);
      }
    }

    setAskFiles((previous) => {
      const merged = [...previous];
      let overflow = false;
      for (const file of accepted) {
        const exists = merged.some(
          (item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified,
        );
        if (exists) continue;
        if (merged.length >= MAX_ASK_FILES) {
          overflow = true;
          continue;
        }
        merged.push(file);
      }
      if (rejected.length) {
        setError(`仅支持 PDF、DOCX、TXT：${rejected.join('、')}`);
      } else if (overflow) {
        setError(`一次最多添加 ${MAX_ASK_FILES} 个文件。`);
      } else {
        setError(null);
      }
      return merged;
    });
  }

  function removeAskFile(index: number) {
    setAskFiles((previous) => previous.filter((_, itemIndex) => itemIndex !== index));
  }

  function handleAskFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) {
      addAskFiles(event.target.files);
    }
    event.target.value = '';
  }

  function handleAskPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files || []);
    if (files.length) {
      addAskFiles(files);
    }
  }

  async function uploadAskFiles(files: File[]) {
    const workspaceId = await ensureDefaultWorkspaceId();
    const previousIds = new Set(documents.map((document) => document.id));
    for (const file of files) {
      const formData = new FormData();
      formData.append('workspace_id', String(workspaceId));
      formData.append('file', file);
      await postFormData<ParsedParagraph[]>('/documents/parse', formData);
    }
    const freshDocuments = await fetchJson<DocumentRecord[]>('/documents');
    setDocuments(freshDocuments);
    return freshDocuments.filter((document) => !previousIds.has(document.id));
  }

  async function runAskQuestion(
    questionText: string,
    startNewSession = false,
    documentIdOverride?: number | null,
    caseIdOverride?: number | null,
  ) {
    const question = questionText.trim();
    const effectiveDocumentId = documentIdOverride !== undefined ? documentIdOverride : null;
    if (!question) {
      setError('请输入问题。');
      return;
    }
    try {
      setSubmitting(true);
      setQaRunState('running');
      setSuccess(null);
      setError(null);
      let sessionId = activeSessionId;
      if (startNewSession) {
        const session = await postJson<ChatSessionRecord>('/chat/sessions', {
          title: question.length > 60 ? `${question.slice(0, 60)}...` : question,
        });
        sessionId = session.id;
        setActiveSessionId(session.id);
        setQaResult(null);
        setChatMessages([]);
        setHighlightChunkId(null);
        setSelectedSource(null);
        setActiveSessionTitle(session.title);
      } else if (!sessionId) {
        const session = await postJson<ChatSessionRecord>('/chat/sessions', {
          title: question.length > 60 ? `${question.slice(0, 60)}...` : question,
        });
        sessionId = session.id;
        setActiveSessionId(session.id);
        setActiveSessionTitle(session.title);
      }
      if (!sessionId) {
        throw new Error('会话创建失败。');
      }
      const userMessage: ChatMessage = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: question,
      };
      setChatMessages((previous) => (startNewSession ? [userMessage] : [...previous, userMessage]));
      const response = await postJson<ChatQueryResponse>(`/chat/sessions/${sessionId}/query`, {
        question,
        document_id: effectiveDocumentId ?? null,
        document_ids: [],
        case_id: caseIdOverride ?? null,
        event_id_cnty: anchorEventId || events[0]?.event_id_cnty || null,
      });
      const result = response.qa;
      setQaResult(result);
      setActiveSessionTitle(response.session.title);
      setChatMessages((previous) => [
        ...previous,
        {
          id: String(response.assistant_message.id),
          role: 'assistant',
          content: result.answer,
          sources: result.sources,
        },
      ]);
      setSuccess('问答完成，已加载相关关系与引用。');
      setQaRunState('success');
      setError(null);
      setHistoryPage(0);
      if (selectedWorkspaceId) {
        await loadQueryHistoryList(selectedWorkspaceId, 0, historyKeyword);
      }
      await loadChatSessions();
      await loadViewRecommendations();
      const firstChunk = result.sources.find((s) => s.chunk_id != null);
      if (firstChunk?.chunk_id != null) {
        await scrollToChunk(firstChunk.chunk_id);
      }
    } catch (err) {
      setQaRunState('error');
      setError(err instanceof Error ? err.message : '问答失败');
    } finally {
      setSubmitting(false);
    }
  }

  function startNewChatSession() {
    if (!chatMessages.length && !qaResult && !globalAskDraft && !askFiles.length) return;
    setChatMessages([]);
    setQaResult(null);
    setQaQuestion('');
    setGlobalAskDraft('');
    setAskFiles([]);
    setSelectedSource(null);
    setActiveSessionId(null);
    setActiveSessionTitle('新的研判会话');
    setHighlightChunkId(null);
    setQaRunState('idle');
  }

  function qaRunStateLabel(state: QaRunState) {
    if (state === 'running') return '研判中';
    if (state === 'success') return '已完成';
    if (state === 'error') return '失败';
    return '';
  }

  function openSource(source: QASource) {
    setSelectedSource(source);
    if (source.chunk_id != null) {
      void scrollToChunk(source.chunk_id);
    }
  }

  async function handleGlobalAskSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rawQuestion = globalAskDraft.trim();
    const attachedFiles = [...askFiles];
    if (!rawQuestion && !attachedFiles.length) {
      setError('请输入问题，或添加需要核验的 PDF/DOCX/TXT 材料。');
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      let documentIdForQuery: number | null = null;
      let caseIdForQuery: number | null = null;
      let uploadedNames: string[] = [];

      if (attachedFiles.length && activeView === 'workspace') {
        const caseId = await ensureCurrentCase();
        const formData = new FormData();
        attachedFiles.forEach((file) => formData.append('files', file));
        const response = await postFormData<IntelligenceCaseUploadResponse>(
          `/intelligence/cases/${caseId}/documents`,
          formData,
        );
        uploadedNames = attachedFiles.map((file) => file.name);
        caseIdForQuery = response.case.id;
        window.sessionStorage.setItem(CURRENT_CASE_STORAGE_KEY, String(response.case.id));
        setCurrentCase(response.case);
        setCaseStatus(response.status);
        setCaseDocuments(response.documents);
        await loadIntelligenceCase(response.case.id);
      } else if (attachedFiles.length) {
        const uploadedDocuments = await uploadAskFiles(attachedFiles);
        uploadedNames = attachedFiles.map((file) => file.name);
        documentIdForQuery = uploadedDocuments[0]?.id ?? null;
        if (documentIdForQuery) {
          setSelectedDocumentId(documentIdForQuery);
          setChunkPage(0);
          setChunkKeyword('');
          await loadDocumentChunks(documentIdForQuery, 0, '');
          await loadGraphForDocument(documentIdForQuery);
        }
      } else if (activeView === 'workspace' && currentCase && caseDocuments.length) {
        caseIdForQuery = currentCase.id;
      }

      const fileInstruction = uploadedNames.length && activeView !== 'workspace'
        ? `\n\n本轮上传材料：${uploadedNames.join('、')}。请优先核验这些材料；若公开事件库无法判断真伪，请明确说明无法独立核实，并在假设材料为真的前提下回答。`
        : '';
      const question = `${rawQuestion || '请核验并分析上传材料。'}${fileInstruction}`;

      setQaQuestion(question);
      const shouldStartNewSession = activeView !== 'qa' || chatMessages.length === 0 || !activeSessionId;
      setActiveView('qa');
      setGlobalAskDraft('');
      setAskFiles([]);
      await runAskQuestion(question, shouldStartNewSession, documentIdForQuery, caseIdForQuery);
    } catch (err) {
      setError(err instanceof Error ? err.message : '材料导入或分析失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function uploadCurrentFile() {
    if (!uploadFile) {
      setError('请选择需要导入的文件。');
      return;
    }
    try {
      setSubmitting(true);
      const workspaceId = await ensureDefaultWorkspaceId();
      const formData = new FormData();
      formData.append('workspace_id', String(workspaceId));
      formData.append('file', uploadFile);
      await postFormData<ParsedParagraph[]>('/documents/parse', formData);
      await loadWorkspaceDocuments(workspaceId);
      setQaResult(null);
      setHighlightChunkId(null);
      setSuccess('文档已解析。可继续提取结构化关系或生成语义索引。');
      setUploadFile(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '文档上传失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteDocument(documentId = selectedDocumentId) {
    if (!documentId) {
      setError('请先选择要删除的文档。');
      return;
    }
    const target = documents.find((document) => document.id === documentId);
    const confirmed = window.confirm(
      `确认删除资料“${target?.file_name ?? `文档 ${documentId}`}”吗？其分段、图谱和向量索引会一并移除。`,
    );
    if (!confirmed) {
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      setSuccess(null);
      await deleteJson<DeleteResponse>(`/documents/${documentId}`);
      await loadWorkspaceDocuments(selectedWorkspaceId ?? undefined);
      setQaResult(null);
      setHighlightChunkId(null);
      setSuccess('资料已删除，相关分段、图谱和向量索引已同步清理。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '资料删除失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUploadSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await uploadCurrentFile();
  }

  async function handleExtractGraph() {
    if (!selectedDocumentId) {
      setError('请先选择已解析的文档。');
      return;
    }
    try {
      setSubmitting(true);
      const result = await postEmpty<GraphExtractResponse>(`/documents/${selectedDocumentId}/extract-graph`);
      setSuccess(`${result.message}（节点 ${result.node_count}，关系 ${result.edge_count}）`);
      setQaResult(null);
      setHighlightChunkId(null);
      setError(null);
      await loadGraphForDocument(selectedDocumentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '图谱抽取失败');
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;

    chartInstance.current?.dispose();
    chartInstance.current = null;

    if (!chartGraph?.nodes.length || !chartRef.current) {
      return () => {
        cancelled = true;
      };
    }

    const snapshot = chartGraph;

    void import('echarts').then((echartsModule) => {
      if (cancelled || !chartRef.current) {
        return;
      }
      const echarts = echartsModule as { init: (dom: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } };
      const chart = echarts.init(chartRef.current);
      if (cancelled) {
        chart.dispose();
        return;
      }
      chartInstance.current = chart;

      const categories = Array.from(new Set(snapshot.nodes.map((node) => node.node_type))).map((name) => ({ name }));
      const categoryIndex = new Map(categories.map((item, index) => [item.name, index]));
      const nodes = snapshot.nodes.map((node) => ({
        id: node.id,
        name: node.label,
        category: categoryIndex.get(node.node_type) ?? 0,
        symbolSize: 18 + Math.min(22, (node.chunk_ids?.length ?? 0) * 2),
        value: node.label,
      }));
      const links = snapshot.edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        value: edge.relation_type,
        label: { show: true, formatter: edge.relation_type, fontSize: 10 },
      }));

      chart.setOption({
        tooltip: {},
        legend: [{ data: categories.map((c) => c.name) }],
        series: [
          {
            type: 'graph',
            layout: 'force',
            roam: true,
            draggable: true,
            categories,
            data: nodes,
            links,
            label: { show: true, position: 'right' },
            lineStyle: { color: 'source', curveness: 0.12 },
            emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
            force: { repulsion: 320, edgeLength: [80, 160], gravity: 0.1 },
          },
        ],
      });

      if (cancelled) {
        chart.dispose();
        chartInstance.current = null;
        return;
      }
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });

    return () => {
      cancelled = true;
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler);
      }
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, [chartGraph, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    mapInstance.current?.dispose();
    mapInstance.current = null;
    if (!mapPoints.length || !mapRef.current) {
      return () => {
        cancelled = true;
      };
    }
    void import('echarts').then((echartsModule) => {
      if (cancelled || !mapRef.current) return;
      const echarts = echartsModule as {
        init: (dom: HTMLElement) => {
          setOption: (o: unknown) => void;
          dispose: () => void;
          resize: () => void;
          on: (event: string, handler: (params: { data?: { eventId?: string } }) => void) => void;
          off: (event: string) => void;
        };
      };
      const chart = echarts.init(mapRef.current);
      if (cancelled) {
        chart.dispose();
        return;
      }
      mapInstance.current = chart;
      chart.setOption({
        backgroundColor: 'transparent',
        textStyle: { color: '#475569' },
        tooltip: { trigger: 'item' },
        xAxis: { name: '经度', scale: true, splitLine: { lineStyle: { color: '#e2e8f0' } } },
        yAxis: { name: '纬度', scale: true, splitLine: { lineStyle: { color: '#e2e8f0' } } },
        series: [
          {
            type: 'scatter',
            symbolSize: (value: unknown, params: { data?: { eventId?: string } }) =>
              params.data?.eventId === anchorEventId ? 14 : 6,
            data: mapPoints.map((p) => ({
              value: [p.longitude, p.latitude],
              name: p.location || p.admin1 || p.event_id_cnty,
              eventId: p.event_id_cnty,
              itemStyle: {
                color: p.event_id_cnty === anchorEventId ? '#ef4444' : '#2563eb',
                opacity: p.event_id_cnty === anchorEventId ? 0.95 : 0.55,
              },
            })),
          },
        ],
      });
      chart.on('click', (params) => {
        if (params.data?.eventId) {
          setAnchorEventId(params.data.eventId);
        }
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      (mapInstance.current as { off?: (event: string) => void } | null)?.off?.('click');
      mapInstance.current?.dispose();
      mapInstance.current = null;
    };
  }, [mapPoints, anchorEventId, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    timelineInstance.current?.dispose();
    timelineInstance.current = null;
    if (!timeline.length || !timelineRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !timelineRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(timelineRef.current);
      timelineInstance.current = chart;
      chart.setOption({
        backgroundColor: 'transparent',
        textStyle: { color: '#475569' },
        tooltip: { trigger: 'axis' },
        grid: { left: 16, right: 24, top: 24, bottom: 72, containLabel: true },
        xAxis: { type: 'category', data: timeline.map((p) => p.date), axisLabel: { rotate: 35, fontSize: 10 } },
        yAxis: { type: 'value', name: '事件数', splitLine: { lineStyle: { color: '#e2e8f0' } } },
        dataZoom: [
          { type: 'slider', xAxisIndex: 0, height: 18, bottom: 18 },
          { type: 'inside', xAxisIndex: 0 },
        ],
        series: [{
          type: 'line',
          smooth: true,
          areaStyle: { opacity: 0.12, color: '#3b82f6' },
          lineStyle: { color: '#2563eb', width: 2 },
          itemStyle: { color: '#1d4ed8' },
          data: timeline.map((p) => p.value),
        }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      timelineInstance.current?.dispose();
      timelineInstance.current = null;
    };
  }, [timeline, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    phaseEvolutionInstance.current?.dispose();
    phaseEvolutionInstance.current = null;
    const data = phaseEvolution;
    if (!data?.months.length || !phaseEvolutionRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !phaseEvolutionRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(phaseEvolutionRef.current);
      phaseEvolutionInstance.current = chart;
      chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0, type: 'scroll', textStyle: { color: '#64748b' } },
        grid: { left: 16, right: 58, top: 46, bottom: 76, containLabel: true },
        xAxis: { type: 'category', data: data.months, axisLabel: { rotate: 35, fontSize: 10 } },
        yAxis: [
          { type: 'value', name: '事件数', splitLine: { lineStyle: { color: '#e2e8f0' } } },
          { type: 'value', name: 'fatalities', splitLine: { show: false } },
        ],
        series: [
          ...data.series.map((item) => ({
            name: item.name,
            type: 'bar',
            stack: 'events',
            emphasis: { focus: 'series' },
            data: item.data,
          })),
          {
            name: 'Fatalities',
            type: 'line',
            yAxisIndex: 1,
            smooth: true,
            symbolSize: 4,
            lineStyle: { color: '#dc2626', width: 2 },
            itemStyle: { color: '#dc2626' },
            data: data.fatalities,
          },
        ],
        dataZoom: [
          { type: 'slider', xAxisIndex: 0, height: 18, bottom: 20 },
          { type: 'inside', xAxisIndex: 0 },
        ],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      phaseEvolutionInstance.current?.dispose();
      phaseEvolutionInstance.current = null;
    };
  }, [phaseEvolution, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    regionMatrixInstance.current?.dispose();
    regionMatrixInstance.current = null;
    const matrix = regionMatrix;
    if (!matrix?.regions.length || !matrix.event_types.length || !regionMatrixRef.current) return () => { cancelled = true; };
    const eventIndex = new Map(matrix.event_types.map((name, index) => [name, index]));
    const regionIndex = new Map(matrix.regions.map((name, index) => [name, index]));
    const values = matrix.cells.map((cell) => [
      eventIndex.get(cell.event_type) ?? 0,
      regionIndex.get(cell.region) ?? 0,
      cell.value,
    ]);
    const maxValue = Math.max(1, ...matrix.cells.map((cell) => cell.value));
    void import('echarts').then((mod) => {
      if (cancelled || !regionMatrixRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(regionMatrixRef.current);
      regionMatrixInstance.current = chart;
      chart.setOption({
        tooltip: {
          position: 'top',
          formatter: (params: { value?: [number, number, number] }) => {
            const [x = 0, y = 0, value = 0] = params.value ?? [0, 0, 0];
            return `${matrix.regions[y]}<br/>${matrix.event_types[x]}：${value}`;
          },
        },
        grid: { left: 16, right: 24, top: 22, bottom: 96, containLabel: true },
        xAxis: { type: 'category', data: matrix.event_types, axisLabel: { rotate: 35, fontSize: 10 } },
        yAxis: { type: 'category', data: matrix.regions, inverse: true, axisLabel: { fontSize: 10 } },
        visualMap: { min: 0, max: maxValue, orient: 'horizontal', left: 'center', bottom: 8, inRange: { color: ['#e0f2fe', '#2563eb', '#7f1d1d'] } },
        dataZoom: [
          { type: 'slider', xAxisIndex: 0, height: 16, bottom: 48 },
          { type: 'inside', xAxisIndex: 0 },
          { type: 'slider', yAxisIndex: 0, width: 14, right: 4 },
          { type: 'inside', yAxisIndex: 0 },
        ],
        series: [{ type: 'heatmap', data: values, label: { show: false }, emphasis: { itemStyle: { borderColor: '#0f172a', borderWidth: 1 } } }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      regionMatrixInstance.current?.dispose();
      regionMatrixInstance.current = null;
    };
  }, [regionMatrix, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    actorPairsInstance.current?.dispose();
    actorPairsInstance.current = null;
    if (!actorPairs.length || !actorPairsRef.current) return () => { cancelled = true; };
    const items = actorPairs.slice(0, 16).reverse();
    void import('echarts').then((mod) => {
      if (cancelled || !actorPairsRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(actorPairsRef.current);
      actorPairsInstance.current = chart;
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          formatter: (params: Array<{ dataIndex: number; value: number }>) => {
            const item = items[params[0]?.dataIndex ?? 0];
            return `${item.source}<br/>→ ${item.target}<br/>事件：${item.count}<br/>fatalities：${item.fatalities}`;
          },
        },
        grid: { left: 16, right: 36, top: 16, bottom: 42, containLabel: true },
        xAxis: { type: 'value' },
        yAxis: {
          type: 'category',
          data: items.map((item) => `${item.source} → ${item.target}`),
          axisLabel: { fontSize: 10 },
        },
        dataZoom: [
          { type: 'slider', yAxisIndex: 0, width: 14, right: 4, start: 0, end: Math.min(100, 8 / Math.max(1, items.length) * 100) },
          { type: 'inside', yAxisIndex: 0 },
        ],
        series: [{ type: 'bar', data: items.map((item) => item.count), itemStyle: { color: '#0f766e' } }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      actorPairsInstance.current?.dispose();
      actorPairsInstance.current = null;
    };
  }, [actorPairs, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    sourceStatsInstance.current?.dispose();
    sourceStatsInstance.current = null;
    if (!sourceStats || !sourceStatsRef.current) return () => { cancelled = true; };
    const names = [...sourceStats.acled.slice(0, 8).map((s) => s.name.slice(0, 24)), ...sourceStats.weibo.slice(0, 6).map((s) => s.name.slice(0, 16))];
    const values = [...sourceStats.acled.slice(0, 8).map((s) => s.count), ...sourceStats.weibo.slice(0, 6).map((s) => s.count)];
    void import('echarts').then((mod) => {
      if (cancelled || !sourceStatsRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(sourceStatsRef.current);
      sourceStatsInstance.current = chart;
      chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 16, right: 36, top: 12, bottom: 36, containLabel: true },
        xAxis: { type: 'value' },
        yAxis: { type: 'category', data: names, inverse: true, axisLabel: { fontSize: 10 } },
        dataZoom: [
          { type: 'slider', yAxisIndex: 0, width: 14, right: 4 },
          { type: 'inside', yAxisIndex: 0 },
        ],
        series: [{ type: 'bar', data: values, itemStyle: { color: '#3b82f6' } }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      sourceStatsInstance.current?.dispose();
      sourceStatsInstance.current = null;
    };
  }, [sourceStats, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    pipelineInstance.current?.dispose();
    pipelineInstance.current = null;
    const data = pipelineSummary;
    if (!data?.stages.length || !pipelineRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !pipelineRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(pipelineRef.current);
      pipelineInstance.current = chart;
      chart.setOption({
        tooltip: {
          trigger: 'item',
          triggerOn: 'mousemove',
          formatter: (params: { dataType?: string; data?: { name?: string; value?: number; label?: string }; name?: string; value?: number }) => {
            if (params.dataType === 'edge') {
              return `${params.data?.label || params.name}<br/>${Number(params.value ?? 0).toLocaleString()}`;
            }
            const stage = data.stages.find((item) => item.name === params.name);
            return `${params.name}<br/>${Number(stage?.count ?? params.value ?? 0).toLocaleString()}<br/>${stage?.detail ?? ''}`;
          },
        },
        series: [
          {
            type: 'sankey',
            left: 12,
            right: 18,
            top: 18,
            bottom: 18,
            nodeGap: 18,
            draggable: true,
            emphasis: { focus: 'adjacency' },
            label: { color: '#0f172a', fontSize: 11 },
            lineStyle: { color: 'gradient', curveness: 0.48, opacity: 0.35 },
            data: data.stages.map((stage) => ({
              name: stage.name,
              value: Math.max(1, stage.count),
              itemStyle: {
                color: stage.status === 'done' ? '#0f766e' : '#94a3b8',
              },
            })),
            links: data.edges.map((edge) => ({
              source: edge.source,
              target: edge.target,
              value: Math.max(1, edge.value),
              label: edge.label,
            })),
          },
        ],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      pipelineInstance.current?.dispose();
      pipelineInstance.current = null;
    };
  }, [pipelineSummary, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    chainTimelineInstance.current?.dispose();
    chainTimelineInstance.current = null;
    const points = chainDetail?.same_region_timeline ?? [];
    if (!points.length || !chainTimelineRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !chainTimelineRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(chainTimelineRef.current);
      chainTimelineInstance.current = chart;
      chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 16, right: 18, top: 20, bottom: 64, containLabel: true },
        xAxis: { type: 'category', data: points.map((p) => p.date), axisLabel: { rotate: 35, fontSize: 10 } },
        yAxis: { type: 'value', name: '同地区事件' },
        dataZoom: [
          { type: 'slider', xAxisIndex: 0, height: 16, bottom: 18 },
          { type: 'inside', xAxisIndex: 0 },
        ],
        series: [{
          type: 'bar',
          data: points.map((p) => p.value),
          itemStyle: { color: '#0f766e' },
        }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      chainTimelineInstance.current?.dispose();
      chainTimelineInstance.current = null;
    };
  }, [chainDetail, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    chainActorInstance.current?.dispose();
    chainActorInstance.current = null;
    const items = chainDetail?.actor_counts ?? [];
    if (!items.length || !chainActorRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !chainActorRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(chainActorRef.current);
      chainActorInstance.current = chart;
      chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 16, right: 32, top: 12, bottom: 36, containLabel: true },
        xAxis: { type: 'value' },
        yAxis: { type: 'category', data: items.map((i) => i.name), inverse: true, axisLabel: { fontSize: 10 } },
        dataZoom: [
          { type: 'slider', yAxisIndex: 0, width: 14, right: 4 },
          { type: 'inside', yAxisIndex: 0 },
        ],
        series: [{ type: 'bar', data: items.map((i) => i.count), itemStyle: { color: '#7c3aed' } }],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      chainActorInstance.current?.dispose();
      chainActorInstance.current = null;
    };
  }, [chainDetail, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    knowledgeGraphInstance.current?.dispose();
    knowledgeGraphInstance.current = null;
    const graph = knowledgeGraph;
    if (!graph?.nodes.length || !knowledgeGraphRef.current) return () => { cancelled = true; };
    void import('echarts').then((mod) => {
      if (cancelled || !knowledgeGraphRef.current) return;
      const chart = (mod as { init: (d: HTMLElement) => { setOption: (o: unknown) => void; dispose: () => void; resize: () => void } }).init(knowledgeGraphRef.current);
      knowledgeGraphInstance.current = chart;
      const categories = Array.from(new Set(graph.nodes.map((node) => node.node_type))).map((name) => ({ name }));
      const categoryIndex = new Map(categories.map((item, index) => [item.name, index]));
      chart.setOption({
        tooltip: {
          trigger: 'item',
          formatter: (params: { dataType?: string; data?: { name?: string; value?: string } }) => {
            if (params.dataType === 'edge') return params.data?.value ?? '';
            return params.data?.name ?? '';
          },
        },
        legend: { data: categories.map((c) => c.name), bottom: 0, textStyle: { color: '#64748b' } },
        series: [
          {
            type: 'graph',
            layout: 'force',
            roam: true,
            draggable: true,
            categories,
            data: graph.nodes.map((node) => ({
              id: node.id,
              name: node.label,
              value: node.node_type,
              category: categoryIndex.get(node.node_type) ?? 0,
              symbolSize: node.node_type === '冲突事件' ? 34 : 18 + Math.min(18, node.label.length * 0.35),
            })),
            links: graph.edges.map((edge) => ({
              source: edge.source,
              target: edge.target,
              value: edge.relation_type,
              label: { show: true, formatter: edge.relation_type, fontSize: 9, color: '#64748b' },
            })),
            label: { show: true, position: 'right', fontSize: 10, color: '#0f172a' },
            lineStyle: { color: 'source', curveness: 0.12, opacity: 0.72 },
            emphasis: { focus: 'adjacency' },
            force: { repulsion: 520, edgeLength: [90, 190], gravity: 0.06 },
          },
        ],
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      knowledgeGraphInstance.current?.dispose();
      knowledgeGraphInstance.current = null;
    };
  }, [knowledgeGraph, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    caseTimelineInstance.current?.dispose();
    caseTimelineInstance.current = null;
    if (activeView !== 'workspace' || !caseTimeline.length || !caseTimelineChartRef.current) {
      return () => { cancelled = true; };
    }
    void import('echarts').then((mod) => {
      if (cancelled || !caseTimelineChartRef.current) return;
      const chart = (mod as {
        init: (d: HTMLElement) => {
          setOption: (o: unknown) => void;
          dispose: () => void;
          resize: () => void;
          on: (event: string, handler: (params: { name?: string }) => void) => void;
        };
      }).init(caseTimelineChartRef.current);
      caseTimelineInstance.current = chart;
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          formatter: (params: Array<{ name: string; value: number }>) => {
            const point = params[0];
            return point ? `${point.name}<br/>${point.value} 条事件线索` : '';
          },
        },
        grid: { left: 18, right: 18, top: 28, bottom: 54, containLabel: true },
        xAxis: {
          type: 'category',
          data: caseTimeline.map((point) => point.date),
          axisLabel: { color: '#64748b', rotate: caseTimeline.length > 5 ? 28 : 0 },
          axisLine: { lineStyle: { color: '#cbd5d1' } },
        },
        yAxis: {
          type: 'value',
          minInterval: 1,
          axisLabel: { color: '#64748b' },
          splitLine: { lineStyle: { color: '#e5ece8' } },
        },
        series: [{
          type: 'bar',
          barMaxWidth: 42,
          data: caseTimeline.map((point) => point.value),
          itemStyle: { color: '#0f766e', borderRadius: [5, 5, 0, 0] },
          emphasis: { itemStyle: { color: '#134e4a' } },
        }],
      });
      chart.on('click', (params) => {
        if (params.name) openCaseDate(params.name);
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      caseTimelineInstance.current?.dispose();
      caseTimelineInstance.current = null;
    };
  }, [caseTimeline, caseEvents, activeView]);

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;
    caseGraphInstance.current?.dispose();
    caseGraphInstance.current = null;
    const graph = caseGraph;
    if (activeView !== 'workspace' || !graph?.nodes.length || !caseGraphRef.current) {
      return () => { cancelled = true; };
    }
    void import('echarts').then((mod) => {
      if (cancelled || !caseGraphRef.current) return;
      const chart = (mod as {
        init: (d: HTMLElement) => {
          setOption: (o: unknown) => void;
          dispose: () => void;
          resize: () => void;
          on: (event: string, handler: (params: { dataType?: string; data?: { id?: string } }) => void) => void;
        };
      }).init(caseGraphRef.current);
      caseGraphInstance.current = chart;
      const categories = Array.from(new Set(graph.nodes.map((node) => node.node_type))).map((name) => ({ name }));
      const categoryIndex = new Map(categories.map((item, index) => [item.name, index]));
      chart.setOption({
        tooltip: {
          trigger: 'item',
          formatter: (params: { dataType?: string; data?: { name?: string; value?: string } }) => (
            params.dataType === 'edge' ? params.data?.value ?? '' : params.data?.name ?? ''
          ),
        },
        legend: {
          data: categories.map((category) => category.name),
          bottom: 0,
          type: 'scroll',
          textStyle: { color: '#64748b' },
        },
        series: [{
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories,
          data: graph.nodes.map((node) => ({
            id: node.id,
            name: node.label,
            value: node.node_type,
            category: categoryIndex.get(node.node_type) ?? 0,
            symbolSize: node.node_type === '冲突事件' ? 38 : 20 + Math.min(18, node.label.length * 0.32),
            itemStyle: node.id.endsWith(`event::${selectedCaseEventId}`) || node.id.endsWith(`entity::${selectedCaseEntityId}`)
              ? { borderColor: '#0f766e', borderWidth: 3 }
              : undefined,
          })),
          links: graph.edges.map((edge) => ({
            source: edge.source,
            target: edge.target,
            value: edge.relation_type,
            label: { show: true, formatter: edge.relation_type, fontSize: 9, color: '#64748b' },
          })),
          label: { show: true, position: 'right', fontSize: 10, color: '#0f172a' },
          lineStyle: { color: 'source', curveness: 0.16, opacity: 0.68 },
          emphasis: { focus: 'adjacency' },
          force: { repulsion: 560, edgeLength: [88, 180], gravity: 0.05 },
        }],
      });
      chart.on('click', (params) => {
        if (params.dataType === 'edge') return;
        const id = String(params.data?.id ?? '');
        const eventMatch = id.match(/event::(\d+)$/);
        if (eventMatch) {
          const event = caseEvents.find((item) => item.id === Number(eventMatch[1]));
          if (event) openCaseEvent(event);
          return;
        }
        const entityMatch = id.match(/entity::(\d+)$/);
        if (entityMatch) {
          const entity = caseEntities.find((item) => item.id === Number(entityMatch[1]));
          if (entity) openCaseEntity(entity);
        }
      });
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });
    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener('resize', resizeHandler);
      caseGraphInstance.current?.dispose();
      caseGraphInstance.current = null;
    };
  }, [caseGraph, caseEvents, caseEntities, selectedCaseEventId, selectedCaseEntityId, activeView]);

  useEffect(() => {
    if (!loading && selectedWorkspaceId) {
      void loadViewRecommendations();
    }
  }, [selectedWorkspaceId]);

  useEffect(() => {
    if (!loading && anchorEventId && activeView === 'chain') {
      void loadEventChainDetail(anchorEventId);
      void loadEventEvidence(anchorEventId);
      void loadKnowledgeGraph(anchorEventId);
    } else if (!loading && anchorEventId && activeView === 'knowledge') {
      void loadEventEvidence(anchorEventId);
      void loadKnowledgeGraph(anchorEventId);
    }
  }, [anchorEventId, loading, activeView]);

  useEffect(() => {
    if (deriveJob?.status !== 'running') return;
    const timer = window.setInterval(() => {
      void fetchJson<KnowledgeDeriveJob>('/datasets/events/derive-knowledge/status')
        .then(async (job) => {
          setDeriveJob(job);
          if (job.status === 'completed') {
            setSuccess(
              `${job.message}：实体 ${job.entities.toLocaleString()} · 链接 ${job.event_entity_links.toLocaleString()} · 证据 ${job.evidences.toLocaleString()} · 关系 ${job.relations.toLocaleString()}`,
            );
            setOverview(await fetchJson<ConflictOverview>('/datasets/events/overview'));
            await loadKnowledgeGraph(anchorEventId || undefined);
            if (anchorEventId) {
              await loadEventEvidence(anchorEventId);
            }
          } else if (job.status === 'failed') {
            setError(job.error || job.message || '知识层派生失败');
          }
        })
        .catch((err) => setError(err instanceof Error ? err.message : '知识层任务状态查询失败'));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [deriveJob?.status, anchorEventId]);

  useEffect(() => {
    setChainInsight(null);
  }, [anchorEventId]);

  useEffect(() => {
    if (!error && !success) return;
    if (error) {
      console.error('[系统提示]', error);
    }
    if (success) {
      console.info('[系统提示]', success);
    }
    const timer = window.setTimeout(() => {
      setError(null);
      setSuccess(null);
    }, 3600);
    return () => window.clearTimeout(timer);
  }, [error, success]);

  useEffect(() => {
    if (!healthInfo) return;
    console.info('[系统状态]', {
      dataService: healthInfo.mysql,
      graphEngine: healthInfo.neo4j,
      events: healthInfo.conflict_events,
      model: llmStatus?.configured ? llmStatus.model : 'not configured',
      embedding: llmStatus?.embedding?.configured ? llmStatus.embedding.model : 'not configured',
    });
  }, [healthInfo, llmStatus]);

  const hasGraph = Boolean(graphData?.nodes.length);
  const selectedDocument = caseDocuments.find((document) => document.document_id === selectedDocumentId) ?? null;
  const selectedCaseEvent = (
    selectedCaseEventId ? caseEvents.find((event) => event.id === selectedCaseEventId) : null
  ) ?? caseEvents[0] ?? null;
  const selectedCaseEntity = selectedCaseEntityId
    ? caseEntities.find((entity) => entity.id === selectedCaseEntityId) ?? null
    : null;
  const selectedCaseChunkId = selectedCaseEntity?.chunk_id ?? selectedCaseEvent?.chunk_id ?? null;
  const selectedCaseChunk = selectedCaseChunkId
    ? displayChunks.find((chunk) => chunk.chunk_id === selectedCaseChunkId) ?? null
    : null;
  const chainLogicCards = buildChainLogicCards(chainDetail);

  function buildChainLogicCards(detail: EventChainDetail | null) {
    if (!detail?.anchor) return [];
    const related = detail.chain.filter((event) => event.event_id_cnty !== detail.anchor?.event_id_cnty);
    const reasonCounts = new Map<string, number>();
    related.forEach((event) => {
      (event.relevance_reasons ?? []).forEach((reason) => {
        const label = String(reason).split('：')[0];
        reasonCounts.set(label, (reasonCounts.get(label) ?? 0) + 1);
      });
    });
    const reasons = Array.from(reasonCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([name, count]) => `${name} ${count}`)
      .join(' · ');
    const scores = related
      .map((event) => Number(event.relevance_score ?? 0))
      .filter((score) => Number.isFinite(score) && score > 0);
    const averageScore = scores.length ? (scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(1) : '-';
    const dominantActor = detail.actor_counts[0]?.name ?? '暂无';
    const peak = detail.same_region_timeline.reduce<TimelinePoint | null>(
      (best, item) => (!best || item.value > best.value ? item : best),
      null,
    );
    return [
      {
        label: '邻近事件',
        value: `${related.length}`,
        detail: `前序 ${detail.before.length} · 后续 ${detail.after.length}`,
      },
      {
        label: '平均评分',
        value: averageScore,
        detail: reasons || '同地区 · 同主体 · 同类型',
      },
      {
        label: '高频主体',
        value: dominantActor,
        detail: detail.actor_counts.slice(0, 3).map((item) => `${item.name} ${item.count}`).join(' · ') || '暂无',
      },
      {
        label: '地区峰值',
        value: peak ? `${peak.value}` : '-',
        detail: peak ? `${peak.date}` : '暂无时间序列',
      },
    ];
  }

  function renderPager({
    page,
    total,
    size,
    count,
    disabled = false,
    onPage,
  }: {
    page: number;
    total: number;
    size: number;
    count: number;
    disabled?: boolean;
    onPage: (page: number) => void;
  }) {
    const pages = totalPages(total, size);
    return (
      <div className="pager">
        <button type="button" className="btn-secondary" disabled={disabled || page <= 0} onClick={() => onPage(page - 1)}>
          上一页
        </button>
        <div className="page-buttons" aria-label="分页页码">
          {visiblePages(page, pages).map((item) => (
            <button
              key={item}
              type="button"
              className={`page-number${item === page ? ' is-active' : ''}`}
              disabled={disabled || item === page}
              onClick={() => onPage(item)}
            >
              {item + 1}
            </button>
          ))}
        </div>
        <button type="button" className="btn-secondary" disabled={disabled || page >= pages - 1} onClick={() => onPage(page + 1)}>
          下一页
        </button>
        <span className="pager-meta">
          {pageRangeLabel(page, size, total, count)} / 共 {total.toLocaleString()} 条
        </span>
      </div>
    );
  }

  function renderAskDock() {
    return (
      <form className="ask-dock" onSubmit={handleGlobalAskSubmit}>
        <input
          ref={askFileInputRef}
          className="visually-hidden"
          id="ask-file-input"
          name="askFiles"
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          onChange={handleAskFileChange}
        />
        <button
          type="button"
          className="attach-button"
          title={`添加材料，最多 ${MAX_ASK_FILES} 个`}
          disabled={submitting || askFiles.length >= MAX_ASK_FILES}
          onClick={() => askFileInputRef.current?.click()}
        >
          +
        </button>
        <textarea
          id="global-ask"
          name="globalAsk"
          rows={2}
          value={globalAskDraft}
          onChange={(event) => setGlobalAskDraft(event.target.value)}
          onPaste={handleAskPaste}
          placeholder="询问俄乌冲突态势，或粘贴材料内容；也可以点击 + 添加 PDF/DOCX/TXT"
        />
        <button type="submit" disabled={submitting}>
          {submitting ? '研判中…' : '发送'}
        </button>
        {askFiles.length > 0 && (
          <div className="ask-files">
            {askFiles.map((file, index) => (
              <span key={`${file.name}-${file.size}-${file.lastModified}`}>
                {file.name}
                <button type="button" onClick={() => removeAskFile(index)} disabled={submitting}>
                  移除
                </button>
              </span>
            ))}
          </div>
        )}
      </form>
    );
  }

  function renderAssistantAnswer(message: ChatMessage) {
    const sources = message.sources ?? [];
    return (
      <div className="assistant-answer">
        <div className="assistant-answer-text">{renderStructuredAnswer(message.content)}</div>
        {sources.length > 0 && (
          <div className="answer-citations">
            {sources.map((source, index) => (
              <button
                key={`answer-source-${message.id}-${source.chunk_id ?? source.event_id_cnty ?? index}`}
                type="button"
                onClick={() => openSource(source)}
              >
                [{index + 1}] {getSourceTitle(source)}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`app-frame${isSidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className={`side-nav${isSidebarCollapsed ? ' is-collapsed' : ''}`} aria-label="主导航">
        <button
          type="button"
          className="side-toggle"
          onClick={() => setIsSidebarCollapsed((value) => !value)}
          title={isSidebarCollapsed ? '展开菜单' : '收起菜单'}
        >
          {isSidebarCollapsed ? '›' : '‹'}
        </button>
        <div className="side-brand">
          <span>RU</span>
          <div>
            <strong>Russo-Ukrainian War Monitor</strong>
            <small>公开情报分析工作台</small>
          </div>
        </div>
        <nav className="side-menu">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`side-menu-item${activeView === tab.id ? ' is-active' : ''}`}
              onClick={() => setActiveView(tab.id)}
              title={tab.id === 'qa' && qaRunState !== 'idle' ? `${tab.label} · ${qaRunStateLabel(qaRunState)}` : tab.label}
            >
              <span className="menu-short-wrap">
                <span className="menu-short">{tab.short}</span>
                {tab.id === 'qa' && qaRunState !== 'idle' && (
                  <span className={`menu-state-dot is-${qaRunState}`} aria-hidden="true" />
                )}
              </span>
              <span className="side-menu-text">
                <strong>{tab.label}</strong>
                {tab.id === 'qa' && qaRunState !== 'idle' && (
                  <small className={`menu-state-text is-${qaRunState}`}>{qaRunStateLabel(qaRunState)}</small>
                )}
              </span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <span>公开情报分析台</span>
          <small>{healthInfo ? `${healthInfo.conflict_events.toLocaleString()} 条事件记录` : '连接中'}</small>
        </div>
      </aside>

      <div className="page-shell">
      {(error || success) && (
        <div className={`toast-message${error ? ' error' : ' success'}`} role="status">
          {error || success}
        </div>
      )}
      {loading && <div className="page-loading">正在连接数据与模型服务…</div>}

      <>
        <main className="dashboard-grid">
          {activeView === 'home' && (
            <>
          <section className="panel panel-span-2 home-hero">
            <div>
              <p className="eyebrow">Intelligence Desk</p>
              <h2>俄乌冲突公开情报分析</h2>
              <p className="subtitle">
                以公开事件数据为基础参照，结合上传材料、来源证据、关系网络与问答检索，支持态势研判和材料核验。
              </p>
            </div>
            <div className="home-brief">
              <span>交互入口</span>
              <strong>态势、材料与问答联动</strong>
              <p>底部输入栏可随时发起研判，并支持添加最多 3 份材料。</p>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><h2>态势快照</h2><span>Snapshot</span></div>
            <div className="home-metrics">
              <article>
                <span>事件记录</span>
                <strong>{(overview?.total_events ?? healthInfo?.conflict_events ?? 0).toLocaleString()}</strong>
              </article>
              <article>
                <span>地理坐标</span>
                <strong>{(overview?.geo_events ?? mapPoints.length).toLocaleString()}</strong>
              </article>
              <article>
                <span>关系实体</span>
                <strong>{(overview?.knowledge.entities ?? 0).toLocaleString()}</strong>
              </article>
              <article>
                <span>当前材料</span>
                <strong>{caseDocuments.length.toLocaleString()}</strong>
              </article>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><h2>工作入口</h2><span>Actions</span></div>
            <div className="home-actions">
              <button type="button" className="feed-card" onClick={() => setActiveView('situation')}>
                <strong>查看态势</strong>
                <span>时间线、地图、阶段演化与地区矩阵</span>
              </button>
              <button type="button" className="feed-card" onClick={() => setActiveView('workspace')}>
                <strong>管理情报</strong>
                <span>上传 PDF/DOCX/TXT，进入处理链并生成视图</span>
              </button>
              <button type="button" className="feed-card" onClick={() => setActiveView('qa')}>
                <strong>进入研判会话</strong>
                <span>基于事件、材料与证据进行问答</span>
              </button>
            </div>
          </section>

            </>
          )}

          {activeView === 'situation' && (
            <>
          <div className="section-head panel-span-2" id="situation">
            <h2>态势分析台</h2>
            <span>总览 · 时间 · 空间 · 事件链</span>
          </div>

          <section className="panel panel-span-2 situation-hero">
            <div>
              <p className="eyebrow">Operational Picture</p>
              <h2>战场事件态势与阶段演化</h2>
              <p className="subtitle">
                聚合公开冲突事件、地理坐标、行动主体和来源说明，用于快速识别高频地区、事件类型和演化节奏。
              </p>
            </div>
            <div className="metric-strip">
              <article className="metric-card">
                <span>事件总数</span>
                <strong>{(overview?.total_events ?? healthInfo?.conflict_events ?? 0).toLocaleString()}</strong>
                <small>结构化公开事件</small>
              </article>
              <article className="metric-card">
                <span>时间范围</span>
                <strong>{overview?.date_min ?? '—'} → {overview?.date_max ?? '—'}</strong>
                <small>按 event_date 统计</small>
              </article>
              <article className="metric-card">
                <span>地理事件</span>
                <strong>{(overview?.geo_events ?? mapPoints.length).toLocaleString()}</strong>
                <small>{pct(overview?.geo_events ?? 0, overview?.total_events ?? 0)} 含坐标</small>
              </article>
              <article className="metric-card">
                <span>知识层</span>
                <strong>{(overview?.knowledge.entities ?? 0).toLocaleString()}</strong>
                <small>实体 · {(overview?.knowledge.evidences ?? 0).toLocaleString()} 证据</small>
              </article>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><h2>Top 地区</h2><span>Admin1</span></div>
            <div className="rank-list">
              {(overview?.admin1_counts ?? []).map((item, index) => (
                <button
                  key={item.name}
                  type="button"
                  className={`rank-row${filterAdmin1 === item.name ? ' is-selected' : ''}`}
                  onClick={() => {
                    setFilterAdmin1(item.name);
                    setEventPage(0);
                    void loadConflictViz(filterYear, item.name, 0, eventKeyword);
                  }}
                >
                  <span>{index + 1}</span>
                  <strong>{item.name}</strong>
                  <em>{item.count.toLocaleString()}</em>
                </button>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><h2>Top 事件类型</h2><span>Event Type</span></div>
            <div className="rank-list">
              {(overview?.event_type_counts ?? []).map((item, index) => (
                <div key={item.name} className="rank-row static">
                  <span>{index + 1}</span>
                  <strong>{item.name}</strong>
                  <em>{item.count.toLocaleString()}</em>
                </div>
              ))}
            </div>
          </section>

          <section className="panel panel-span-2">
            <div className="panel-header"><h2>态势筛选</h2><span>Filters</span></div>
            <div className="filter-row">
              <label>
                年份
                <select
                  id="filter-year"
                  name="filterYear"
                  value={filterYear === '' ? '' : String(filterYear)}
                  onChange={(e) => setFilterYear(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">全部</option>
                  {(filters?.years ?? []).map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </label>
              <label>
                地区
                <select id="filter-admin1" name="filterAdmin1" value={filterAdmin1} onChange={(e) => setFilterAdmin1(e.target.value)}>
                  <option value="">全部</option>
                  {(filters?.admin1 ?? []).map((a) => (
                    <option key={a.name} value={a.name}>{a.name} ({a.count})</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={submitting}
                onClick={() => {
                  setEventPage(0);
                  void loadConflictViz(filterYear, filterAdmin1, 0, eventKeyword);
                }}
              >
                应用筛选
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={submitting}
                onClick={() => {
                  setFilterYear('');
                  setFilterAdmin1('');
                  setEventKeyword('');
                  setEventPage(0);
                  void loadConflictViz('', '', 0, '');
                }}
              >
                重置
              </button>
            </div>
          </section>

          <section className="panel panel-span-2">
            <div className="panel-header"><h2>冲突事件时间线</h2><span>Timeline</span></div>
            <div ref={timelineRef} className="chart-box tall" />
          </section>

          <section className="panel panel-span-2">
            <div className="panel-header">
              <h2>阶段演化视图</h2>
              <span>Monthly Stacked Types + Fatalities</span>
            </div>
            <div ref={phaseEvolutionRef} className="chart-box tall" />
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>地区-事件类型矩阵</h2>
              <span>Heatmap</span>
            </div>
            <div ref={regionMatrixRef} className="chart-box tall" />
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>主体关系排行</h2>
              <span>Actor Pairs</span>
            </div>
            <div ref={actorPairsRef} className="chart-box tall" />
          </section>
            </>
          )}

          {activeView === 'chain' && (
            <>
          <div className="section-head panel-span-2" id="chain">
            <h2>事件链分析</h2>
            <span>事件追踪</span>
          </div>

          <section className="panel">
            <div className="panel-header"><h2>事件列表</h2></div>
            <form className="list-toolbar" onSubmit={handleEventSearchSubmit}>
              <input
                id="event-keyword"
                name="eventKeyword"
                value={eventKeyword}
                onChange={(e) => setEventKeyword(e.target.value)}
                placeholder="搜索地点、主体或 notes"
              />
              <button type="submit" disabled={submitting}>搜索</button>
              <button
                type="button"
                className="btn-secondary"
                disabled={submitting || (!eventKeyword && eventPage === 0)}
                onClick={() => {
                  setEventKeyword('');
                  setEventPage(0);
                  void loadConflictViz(filterYear, filterAdmin1, 0, '');
                }}
              >
                清空
              </button>
            </form>
            {renderPager({
              page: eventPage,
              total: eventTotal,
              size: EVENT_PAGE_SIZE,
              count: events.length,
              disabled: submitting,
              onPage: jumpEventPage,
            })}
            <div className="card-list">
              {events.length === 0 && <div className="feed-card muted">没有匹配的事件，请调整筛选或关键词。</div>}
              {events.map((event) => (
                <article
                  key={event.event_id_cnty}
                  className={`feed-card${anchorEventId === event.event_id_cnty ? ' chunk-highlight' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setAnchorEventId(event.event_id_cnty);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      setAnchorEventId(event.event_id_cnty);
                    }
                  }}
                >
                  <div className="feed-topline"><strong>{event.event_type || 'Unknown'}</strong><span>{event.event_date}</span></div>
                  <p className="feed-title">{event.location || 'Unknown location'} · {event.admin1 || 'Unknown region'}</p>
                  <p className="feed-body">{event.actor1 || 'Unknown actor'} {event.actor2 ? `vs ${event.actor2}` : ''}</p>
                  <p className="feed-meta">{event.event_id_cnty} · {event.source || 'Unknown source'}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>空间热点分布</h2>
            </div>
            <div ref={mapRef} className="chart-box tall" />
          </section>

          <section className="panel panel-span-2 event-chain-panel">
            <div className="panel-header">
              <h2>事件链分析</h2>
              <div className="panel-actions">
                <span>{chainDetail?.anchor?.event_id_cnty || anchorEventId || 'No Anchor'}</span>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={submitting || !anchorEventId}
                  onClick={() => void generateEventChainInsight()}
                >
                  生成智能解读
                </button>
              </div>
            </div>
            {chainDetail?.anchor ? (
              <div className="event-chain-grid">
                <article className="anchor-card">
                  <span className="chip">{chainDetail.anchor.event_type || 'Unknown'}</span>
                  <h3>{chainDetail.anchor.location || chainDetail.anchor.admin1 || chainDetail.anchor.event_id_cnty}</h3>
                  <p>{chainDetail.anchor.notes || '暂无 notes。'}</p>
                  <div className="anchor-meta">
                    <span>{chainDetail.anchor.event_date}</span>
                    <span>{chainDetail.anchor.actor1 || 'Unknown actor'} {chainDetail.anchor.actor2 ? `vs ${chainDetail.anchor.actor2}` : ''}</span>
                    <span>{chainDetail.anchor.source || 'Unknown source'}</span>
                  </div>
                </article>
                <div className="chain-chart-card chain-timeline-card">
                  <h3 className="compact-title">同地区演化</h3>
                  <div ref={chainTimelineRef} className="chart-box compact" />
                </div>
                <div className="chain-chart-card chain-actor-card">
                  <h3 className="compact-title">涉及主体排行</h3>
                  <div ref={chainActorRef} className="chart-box compact" />
                </div>
                <div className="chain-list">
                  <h3 className="compact-title">前后邻近事件</h3>
                  <div className="mini-timeline">
                    {chainDetail.chain.slice(0, 12).map((event) => (
                      <button
                        key={event.event_id_cnty}
                        type="button"
                        className={`mini-event${event.event_id_cnty === anchorEventId ? ' is-selected' : ''}`}
                        onClick={() => setAnchorEventId(event.event_id_cnty)}
                      >
                        <span>{event.event_date}</span>
                        <strong>{event.location || event.admin1 || event.event_id_cnty}</strong>
                        <em>
                          {(event.relevance_reasons ?? [event.event_type || 'Unknown']).slice(0, 2).join(' · ')}
                          {event.relevance_score && event.event_id_cnty !== anchorEventId ? ` · score ${event.relevance_score}` : ''}
                        </em>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="evidence-notes chain-source-notes">
                  <h3 className="compact-title">来源 notes</h3>
                  {(chainDetail.notes.length ? chainDetail.notes : ['暂无可展示的 notes']).map((note, index) => (
                    <p key={`${index}-${note.slice(0, 18)}`}>{note}</p>
                  ))}
                </div>
                <div className="evidence-notes chain-logic">
                  <h3 className="compact-title">链路逻辑</h3>
                  <div className="chain-logic-grid">
                    {chainLogicCards.map((item) => (
                      <article key={item.label} className="chain-logic-card">
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                        <em>{item.detail}</em>
                      </article>
                    ))}
                  </div>
                  {(chainDetail.analysis_notes.length ? chainDetail.analysis_notes : ['当前链路按同地区、同主体、同类型和时间距离进行结构化匹配。']).map((note, index) => (
                    <p key={`logic-${index}`}>{note}</p>
                  ))}
                </div>
                {chainInsight && (
                  <div className="chain-insight">
                    <h3 className="compact-title">智能链路解读</h3>
                    <p className="qa-answer">{chainInsight.answer}</p>
                    {chainInsight.sources.length > 0 && (
                      <div className="insight-sources">
                        {chainInsight.sources.slice(0, 8).map((source, index) => (
                          <button
                            key={`chain-source-${source.event_id_cnty ?? index}`}
                            type="button"
                            className="qa-source-chip"
                            onClick={() => {
                              if (source.event_id_cnty) setAnchorEventId(source.event_id_cnty);
                            }}
                          >
                            [{index + 1}] {source.event_id_cnty || source.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="feed-card muted">选择一个事件后，这里会展示前后邻近事件、同地区时间演化、涉及主体、地图定位和来源摘录。</div>
            )}
          </section>
            </>
          )}

          {activeView === 'knowledge' && (
            <>
          <div className="section-head panel-span-2" id="knowledge">
            <h2>关系网络</h2>
            <span>主体 · 地点 · 来源 · 证据</span>
          </div>

          <section className="panel panel-span-2 knowledge-panel">
            <div className="panel-header">
              <h2>行动主体关系网</h2>
              <span>
                {(knowledgeGraph?.nodes.length ?? 0).toLocaleString()} 节点 · {(knowledgeGraph?.edges.length ?? 0).toLocaleString()} 关系
              </span>
            </div>
            <div className="knowledge-toolbar">
              <p className="muted">
                从公开事件中提取主体、地点、来源和事件类型，支持从全局网络切换到单个事件的证据关系。
              </p>
              <div>
                <button type="button" className="btn-secondary" onClick={() => void loadKnowledgeGraph()}>
                  全局网络
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={!anchorEventId}
                  onClick={() => void loadKnowledgeGraph(anchorEventId)}
                >
                  事件关系
                </button>
              </div>
            </div>
            {deriveJob && (
              <div className={`derive-progress ${deriveJob.status}`}>
                <div>
                  <strong>{deriveJob.message}</strong>
                  <span>
                    {deriveJob.status === 'running'
                      ? `${deriveJob.processed_events.toLocaleString()} / ${deriveJob.total_events.toLocaleString()} 条事件`
                      : deriveJob.status}
                  </span>
                </div>
                <progress
                  max={Math.max(deriveJob.total_events || 1, 1)}
                  value={Math.min(deriveJob.processed_events, deriveJob.total_events || deriveJob.processed_events)}
                />
                <p>
                  实体 {deriveJob.entities.toLocaleString()} · 链接 {deriveJob.event_entity_links.toLocaleString()} ·
                  证据 {deriveJob.evidences.toLocaleString()} · 关系 {deriveJob.relations.toLocaleString()}
                </p>
              </div>
            )}
            {knowledgeGraph?.nodes.length ? (
              <div ref={knowledgeGraphRef} className="chart-box graph-tall" />
            ) : (
              <div className="feed-card muted">
                暂无结构化关系。完成关系层生成后，可查看主体、地点、来源和事件之间的关联。
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>锚点事件实体</h2>
              <span>{eventEvidence?.entities.length ?? 0} 个实体</span>
            </div>
            <div className="entity-chip-grid">
              {(eventEvidence?.entities ?? []).slice(0, 36).map((entity) => (
                <article key={`${entity.role_type}-${entity.id}`} className="entity-chip">
                  <span>{entity.role_type}</span>
                  <strong>{entity.name}</strong>
                  <em>{entity.entity_type}</em>
                </article>
              ))}
              {!eventEvidence?.entities.length && (
                <div className="feed-card muted">选择事件并生成关系层后，这里会列出行动主体、地区、来源和事件类型实体。</div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>事件证据原文</h2>
              <span>{eventEvidence?.evidences.length ?? 0} evidence</span>
            </div>
            <div className="evidence-list">
              {(eventEvidence?.evidences ?? []).map((item, index) => (
                <article key={item.id} className="evidence-card">
                  <div className="feed-topline">
                    <strong>[{index + 1}] {item.source_label || '公开事件'}</strong>
                    <span>{item.evidence_type}</span>
                  </div>
                  <p>{item.quote_text || '暂无原文摘录。'}</p>
                </article>
              ))}
              {!eventEvidence?.evidences.length && (
                <div className="feed-card muted">当前锚点事件还没有可展示的证据记录，或尚未生成关系层。</div>
              )}
            </div>
          </section>
            </>
          )}

          {activeView === 'workspace' && (
            <>

          <div className="section-head panel-span-2" id="workspace">
            <h2>情报管理</h2>
            <span>文件导入与结构化结果</span>
          </div>
          <section className="panel panel-span-2">
            <div className="panel-header">
              <h2>材料导入</h2>
              <button type="button" className="btn-secondary" onClick={() => void createFreshIntelligenceCase()} disabled={submitting}>
                重新开始
              </button>
            </div>
            <div className="workspace-flow">
              <div className="workspace-step-card">
                <span className="step-kicker">导入</span>
                <div className="workspace-current">
                  <strong>{caseDocuments.length ? `${caseDocuments.length.toLocaleString()} 份材料已导入` : '尚未导入材料'}</strong>
                  <span>PDF/DOCX/TXT，上限五个文件</span>
                </div>
                <label className="file-drop">
                  <input
                    id="case-upload"
                    name="caseUpload"
                    type="file"
                    accept=".pdf,.docx,.txt"
                    multiple
                    onChange={(event) => {
                      if (event.target.files) addCaseFiles(event.target.files);
                      event.target.value = '';
                    }}
                  />
                  <span>选择文件</span>
                  <em>支持 PDF、DOCX、TXT</em>
                </label>
                {caseFiles.length > 0 && (
                  <div className="case-file-list">
                    {caseFiles.map((file, index) => (
                      <div key={`${file.name}-${index}`} className="case-file-pill">
                        <span title={file.name}>{file.name}</span>
                        <button
                          type="button"
                          aria-label={`移除 ${file.name}`}
                          onClick={() => removeCaseFile(index)}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <button type="button" onClick={() => void uploadCaseFiles()} disabled={submitting || !caseFiles.length}>
                  导入并处理
                </button>
              </div>

              <div className="workspace-step-card">
                <span className="step-kicker">材料</span>
                <label>
                  文件
                  <select id="document-select" name="documentId" value={selectedDocumentId ?? ''} onChange={handleDocumentChange}>
                    <option value="" disabled>{caseDocuments.length ? '选择材料' : '暂无材料'}</option>
                    {caseDocuments.map((document) => (
                      <option key={document.document_id} value={document.document_id}>{document.file_name}</option>
                    ))}
                  </select>
                </label>
                <div className="workspace-current">
                  <strong>{selectedDocument ? `${selectedDocument.chunk_count.toLocaleString()} 个段落` : '等待导入'}</strong>
                  <span>{selectedDocument ? `${selectedDocument.file_type.toUpperCase()} · ${selectedDocument.document_topic}` : '等待选择文件'}</span>
                </div>
                <div className="case-document-list">
                  {caseDocuments.map((document) => (
                    <button
                      key={document.document_id}
                      type="button"
                      className={`case-document-row${selectedDocumentId === document.document_id ? ' is-active' : ''}`}
                      onClick={() => {
                        setSelectedDocumentId(document.document_id);
                        void loadDocumentChunks(document.document_id, 0, '');
                        void loadGraphForDocument(document.document_id);
                      }}
                    >
                      <strong>{document.file_name}</strong>
                      <span>
                        段落 {document.chunk_count} · 实体 {document.entity_count} · 事件 {document.event_count}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="workspace-step-card">
                <span className="step-kicker">处理</span>
                <div className="document-action-row">
                  <button type="button" onClick={() => void processCurrentCase()} disabled={submitting || !currentCase}>
                    重新处理
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => void buildCaseEmbeddingIndex()} disabled={submitting || !caseDocuments.length}>
                    生成语义索引
                  </button>
                </div>
                <div className="case-stage-list">
                  {(caseStatus?.stages ?? []).map((stage) => (
                    <div key={stage.id} className={`case-stage ${stage.status}`}>
                      <strong>{stage.name}</strong>
                      <span>{stage.detail || `${stage.count} 项`}</span>
                    </div>
                  ))}
                </div>
                <div className="workspace-current">
                  <strong>{caseGraph ? `${caseGraph.nodes.length} 节点 · ${caseGraph.edges.length} 关系` : '关系待生成'}</strong>
                  <span>用于时间线、关系图和问答引用</span>
                </div>
              </div>
            </div>
          </section>

          <section className="panel panel-span-2 case-visual-panel">
            <div className="panel-header">
              <h2>材料时间线</h2>
              <span>{caseTimeline.length ? `${caseTimeline.length} 个时间点` : '待抽取'}</span>
            </div>
            {caseTimeline.length ? (
              <div className="case-timeline-visual">
                <div ref={caseTimelineChartRef} className="case-chart-box" />
                <div className="case-event-list">
                  <div className="case-list-title">事件线索</div>
                  {caseEvents.slice(0, 10).map((event) => (
                    <button
                      key={event.id}
                      type="button"
                      className={`case-event-row${selectedCaseEvent?.id === event.id ? ' is-active' : ''}`}
                      onClick={() => openCaseEvent(event)}
                    >
                      <strong>{event.event_date || event.event_time_raw || '未标注时间'}</strong>
                      <span>{event.event_title}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="muted">尚未抽取到时间线索。</p>
            )}
          </section>

          <section className="panel panel-span-2 case-visual-panel">
            <div className="panel-header">
              <h2>当前材料关系图</h2>
              <span>{caseGraph ? `${caseGraph.nodes.length} 节点 · ${caseGraph.edges.length} 关系` : '待生成'}</span>
            </div>
            {caseGraph?.nodes.length ? (
              <div className="case-graph-layout">
                <div ref={caseGraphRef} className="case-graph-box" />
                <aside className="case-evidence-panel">
                  <div className="case-evidence-head">
                    <span>{selectedCaseEntity ? '实体证据' : '事件证据'}</span>
                    <strong>
                      {selectedCaseEntity?.name ?? selectedCaseEvent?.event_title ?? '选择图中节点查看证据'}
                    </strong>
                  </div>
                  {selectedCaseEntity ? (
                    <p>{selectedCaseEntity.evidence_text || '暂无实体证据摘录。'}</p>
                  ) : selectedCaseEvent ? (
                    <>
                      <p>{selectedCaseEvent.summary || selectedCaseEvent.evidence_text || '暂无事件摘要。'}</p>
                      <dl className="case-evidence-meta">
                        <div><dt>时间</dt><dd>{selectedCaseEvent.event_date || selectedCaseEvent.event_time_raw || '未标注'}</dd></div>
                        <div><dt>地点</dt><dd>{selectedCaseEvent.location_name || '未标注'}</dd></div>
                        <div><dt>主体</dt><dd>{selectedCaseEvent.actor_names || '未标注'}</dd></div>
                      </dl>
                    </>
                  ) : (
                    <p>点击图中的事件或实体节点，可查看其来源摘录。</p>
                  )}
                  {selectedCaseChunk && (
                    <blockquote>{selectedCaseChunk.text}</blockquote>
                  )}
                  {(selectedCaseEvent?.chunk_id || selectedCaseEntity?.chunk_id) && (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        const documentId = selectedCaseEntity?.document_id ?? selectedCaseEvent?.document_id;
                        const chunkId = selectedCaseEntity?.chunk_id ?? selectedCaseEvent?.chunk_id;
                        if (documentId) void focusMaterialChunk(documentId, chunkId);
                      }}
                    >
                      定位原文段落
                    </button>
                  )}
                </aside>
              </div>
            ) : (
              <p className="muted">尚未生成可视化关系。</p>
            )}
          </section>

          <section className="panel panel-span-2">
            <div className="panel-header"><h2>结构化结果</h2></div>
            <div className="case-asset-grid">
              <div>
                <strong>事件线索</strong>
                {caseEvents.slice(0, 8).map((event) => (
                  <button
                    key={event.id}
                    type="button"
                    className="case-inline-item"
                    onClick={() => openCaseEvent(event)}
                  >
                    {event.event_date || event.event_time_raw || '未标注时间'} · {event.event_title}
                  </button>
                ))}
                {!caseEvents.length && <p className="muted">暂无事件。</p>}
              </div>
              <div>
                <strong>实体线索</strong>
                <div className="chips">
                  {caseEntities.slice(0, 16).map((entity) => (
                    <button key={entity.id} type="button" className="chip" onClick={() => openCaseEntity(entity)}>
                      {entity.entity_type} · {entity.name}
                    </button>
                  ))}
                </div>
                {!caseEntities.length && <p className="muted">暂无实体。</p>}
              </div>
            </div>
          </section>

            </>
          )}

          {activeView === 'qa' && (
            <>

          <section className={`qa-workspace panel-span-2${selectedSource ? ' has-source' : ''}`}>
            <div className="qa-topbar">
              <div>
                <h2>{activeSessionTitle}</h2>
                <span>{chatMessages.length ? `${Math.ceil(chatMessages.length / 2)} 轮对话` : '新的研判会话'}</span>
              </div>
              <div className="qa-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    void loadChatSessions();
                    setShowHistoryPanel((value) => !value);
                  }}
                >
                  历史
                </button>
                <button type="button" className="btn-secondary" onClick={startNewChatSession}>
                  新会话
                </button>
              </div>
              {showHistoryPanel && (
                <aside className="history-panel">
                  <div className="history-head">
                    <strong>历史会话</strong>
                    <button type="button" onClick={() => setShowHistoryPanel(false)}>关闭</button>
                  </div>
                  <div className="history-list">
                    {chatSessions.length === 0 && <div className="muted">暂无历史会话。</div>}
                    {chatSessions.map((item) => (
                      <button
                        type="button"
                        key={item.id}
                        onClick={() => void openChatSession(item)}
                      >
                        <strong>{item.title}</strong>
                        <span>{item.updated_at || item.created_at}</span>
                      </button>
                    ))}
                  </div>
                </aside>
              )}
            </div>

            <div className="qa-chat-layout">
              <div className="qa-chat-main">
                {chatMessages.length === 0 ? (
                  <div className="qa-empty-state">
                    <h2>有什么可以研判的？</h2>
                    <p>询问俄乌冲突态势，或点击下方加号添加公开材料进行核验。</p>
                  </div>
                ) : (
                  <div className="chat-stream">
                    {chatMessages.map((message) => (
                      <article key={message.id} className={`chat-message ${message.role}`}>
                        {message.role === 'assistant' ? (
                          renderAssistantAnswer(message)
                        ) : (
                          <div className="user-answer">
                            <div className="user-answer-text">{message.content}</div>
                          </div>
                        )}
                      </article>
                    ))}
                    {submitting && chatMessages[chatMessages.length - 1]?.role === 'user' && (
                      <article className="chat-message assistant pending" aria-live="polite">
                        <div className="assistant-answer pending-answer">
                          <span>正在研判</span>
                          <span className="typing-dots" aria-hidden="true">
                            <i />
                            <i />
                            <i />
                          </span>
                        </div>
                      </article>
                    )}
                  </div>
                )}
              </div>

              {selectedSource && (
                <aside className="source-drawer">
                  <div className="source-drawer-head">
                    <div>
                      <strong>{getSourceTitle(selectedSource)}</strong>
                      <span>{getSourceMeta(selectedSource)}</span>
                    </div>
                    <button type="button" onClick={() => setSelectedSource(null)}>关闭</button>
                  </div>
                  <p>{selectedSource.excerpt}</p>
                </aside>
              )}
            </div>
          </section>

            </>
          )}
        </main>
        {renderAskDock()}
        </>
      </div>
    </div>
  );
}
