import type { GraphNode, ParsedParagraph } from '../types';

type Props = {
  chunks: ParsedParagraph[];
  displayChunks: ParsedParagraph[];
  highlightChunkId: number | null;
  selectedNode: GraphNode | null;
  onClearNode: () => void;
};

export function ChunkPanel({ chunks, displayChunks, highlightChunkId, selectedNode, onClearNode }: Props) {
  const filterIds = selectedNode ? new Set(selectedNode.chunk_ids) : null;
  const visible = displayChunks.filter((chunk) => !filterIds || filterIds.has(chunk.chunk_id));

  return (
    <div className="chunk-panel">
      <div className="panel-header">
        <h2>文本溯源</h2>
        <span>{chunks.length} chunks</span>
      </div>
      {selectedNode && (
        <div className="node-filter-banner">
          <div>
            <strong>{selectedNode.label}</strong>
            <span className="muted"> · {selectedNode.node_type}</span>
          </div>
          <button type="button" className="btn-ghost" onClick={onClearNode}>
            显示全部
          </button>
        </div>
      )}
      <div className="chunk-scroll">
        {chunks.length === 0 && <div className="feed-card empty-card">请先上传并解析文档。</div>}
        {visible.map((chunk) => (
          <article
            key={chunk.chunk_id}
            id={`chunk-${chunk.chunk_id}`}
            className={`chunk-card${highlightChunkId === chunk.chunk_id ? ' chunk-highlight' : ''}${
              filterIds?.has(chunk.chunk_id) ? ' chunk-linked' : ''
            }`}
          >
            <div className="chunk-card-head">
              <span className="chunk-badge">#{chunk.chunk_id}</span>
              <span className="muted">
                段落 {chunk.paragraph_index}
                {chunk.page_number != null ? ` · 第 ${chunk.page_number} 页` : ''}
              </span>
            </div>
            <p className="chunk-text">{chunk.text}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
