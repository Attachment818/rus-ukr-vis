import { FormEvent } from 'react';
import type { QAResponse } from '../types';

const SAMPLE_QUESTIONS = [
  '\u8be5\u6587\u6863\u6d89\u53ca\u54ea\u4e9b\u4e3b\u8981\u519b\u4e8b\u7ec4\u7ec7\u4e0e\u5730\u7406\u4f4d\u7f6e\uff1f',
  '\u6587\u4e2d\u6709\u54ea\u4e9b\u51b2\u7a81\u4e8b\u4ef6\u6216\u519b\u4e8b\u884c\u52a8\uff1f',
  '\u5404\u65b9\u6b66\u5668\u88c5\u5907\u4e0e\u90e8\u7f72\u5173\u7cfb\u662f\u4ec0\u4e48\uff1f',
];

type Props = {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  submitting: boolean;
  disabled: boolean;
  result: QAResponse | null;
  onCitationClick: (chunkId: number) => void;
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

function getSourceTitle(source: QAResponse['sources'][number]) {
  const label = (source.label || '').trim();
  if (label && !CHUNK_LABEL_PATTERN.test(label)) {
    return compactInlineText(label, 26);
  }
  const excerptTitle = firstMeaningfulExcerptLine(source.excerpt);
  if (excerptTitle) {
    return compactInlineText(excerptTitle, 26);
  }
  return source.source_type === 'chunk' ? '文档分段' : source.source_type;
}

function getSourceMeta(source: QAResponse['sources'][number]) {
  const parts: string[] = [];
  if (source.paragraph_index != null) {
    parts.push(`段落 ${source.paragraph_index}`);
  }
  if (source.page_number != null) {
    parts.push(`第 ${source.page_number} 页`);
  }
  return parts.join(' · ') || source.source_type;
}

export function QAPanel({
  question,
  onQuestionChange,
  onSubmit,
  submitting,
  disabled,
  result,
  onCitationClick,
}: Props) {
  return (
    <div className="qa-panel">
      <div className="panel-header">
        <h2>{'\u56fe\u8f85\u52a9\u95ee\u7b54'}</h2>
        <span>Graph RAG</span>
      </div>
      <div className="sample-questions">
        {SAMPLE_QUESTIONS.map((sample) => (
          <button
            key={sample}
            type="button"
            className="sample-chip"
            disabled={disabled}
            onClick={() => onQuestionChange(sample)}
          >
            {sample}
          </button>
        ))}
      </div>
      <form className="qa-form" onSubmit={onSubmit}>
        <label>
          {'\u8f93\u5165\u95ee\u9898'}
          <textarea
            rows={3}
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder="\u57fa\u4e8e\u5f53\u524d\u6587\u6863\u7684\u77e5\u8bc6\u56fe\u8c31\u4e0e\u6587\u672c\u5757\u4f5c\u7b54\uff0c\u5e76\u9644 chunk \u5f15\u7528"
          />
        </label>
        <button type="submit" disabled={submitting || disabled}>
          {submitting ? '\u68c0\u7d22\u56fe\u8c31\u5e76\u751f\u6210\u56de\u7b54\u2026' : '\u63d0\u4ea4\u95ee\u9898'}
        </button>
      </form>
      {result && (
        <div className="qa-result">
          <div className="qa-answer-card">
            <h3>{'\u6a21\u578b\u56de\u7b54'}</h3>
            <p className="qa-answer">{result.answer}</p>
          </div>
          {result.sources.length > 0 && (
            <div className="qa-citations">
              <h4>{'\u5f15\u7528\u6eaf\u6e90'} ({result.sources.length})</h4>
              <div className="qa-sources">
                {result.sources.map((source, index) => (
                  <button
                    key={source.chunk_id ?? `source-${index}`}
                    type="button"
                    className="qa-source-chip"
                    disabled={source.chunk_id == null}
                    onClick={() => {
                      if (source.chunk_id != null) {
                        onCitationClick(source.chunk_id);
                      }
                    }}
                  >
                    [{index + 1}] {getSourceTitle(source)}
                  </button>
                ))}
              </div>
              <div className="citation-list">
                {result.sources.map((source, index) => (
                  <button
                    key={source.chunk_id ?? `citation-${index}`}
                    type="button"
                    className="citation-item"
                    disabled={source.chunk_id == null}
                    onClick={() => {
                      if (source.chunk_id != null) {
                        onCitationClick(source.chunk_id);
                      }
                    }}
                  >
                    <span className="citation-index">[{index + 1}]</span>
                    <span className="citation-meta">{getSourceTitle(source)} · {getSourceMeta(source)}</span>
                    <span className="citation-excerpt">{source.excerpt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
