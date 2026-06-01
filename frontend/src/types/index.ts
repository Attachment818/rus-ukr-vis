export type DatasetSummary = { dataset: string; total_rows: number; columns: string[] };
export type TimelinePoint = { date: string; value: number; label: string };
export type ConflictEvent = {
  event_id_cnty: string;
  event_date: string;
  event_type?: string;
  sub_event_type?: string;
  actor1?: string;
  actor2?: string;
  admin1?: string;
  location?: string;
  source?: string;
};
export type WeiboPost = {
  index: number;
  created_at?: string;
  text?: string;
  screen_name?: string;
  source?: string;
  attitudes_count?: number | null;
};
export type Workspace = { id: number; name: string; description?: string | null; created_at: string };
export type DocumentRecord = {
  id: number;
  workspace_id: number;
  file_name: string;
  document_topic: string;
  file_path: string;
  file_type: string;
  status: string;
  created_at: string;
};
export type ParsedParagraph = {
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
export type GraphNode = { id: string; label: string; node_type: string; chunk_ids: number[] };
export type GraphEdge = {
  source: string;
  target: string;
  relation_type: string;
  chunk_ids: number[];
  evidence?: string | null;
};
export type DocumentGraphResponse = {
  document_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  updated_at?: string | null;
};
export type GraphExtractResponse = { document_id: number; node_count: number; edge_count: number; message: string };
export type QASource = {
  source_type: string;
  label: string;
  chunk_id?: number | null;
  event_id_cnty?: string | null;
  paragraph_index?: number | null;
  page_number?: number | null;
  excerpt: string;
};
export type QAResponse = {
  answer: string;
  mode?: string;
  sources: QASource[];
  subgraph_nodes: GraphNode[];
  subgraph_edges: GraphEdge[];
  context_summary?: Record<string, unknown> | null;
};
export type MapPoint = {
  event_id_cnty: string;
  event_date: string;
  event_type?: string;
  admin1?: string;
  location?: string;
  latitude: number;
  longitude: number;
  actor1?: string;
  actor2?: string;
  fatalities?: number | null;
};
export type HealthInfo = {
  status: string;
  app: string;
  mysql: string;
  neo4j: string;
  conflict_events: number;
};
export type QueryMode = 'local' | 'global' | 'event_chain' | 'evidence';

export type AppTab = 'overview' | 'analysis';
