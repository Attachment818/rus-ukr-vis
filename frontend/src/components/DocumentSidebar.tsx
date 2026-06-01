import { ChangeEvent, FormEvent } from 'react';
import type { DocumentRecord, Workspace } from '../types';
import { WorkflowSteps } from './WorkflowSteps';

type Props = {
  workspaces: Workspace[];
  documents: DocumentRecord[];
  selectedWorkspaceId: number | null;
  selectedDocumentId: number | null;
  workspaceName: string;
  workspaceDescription: string;
  uploadFile: File | null;
  submitting: boolean;
  hasDocument: boolean;
  hasGraph: boolean;
  hasQa: boolean;
  onWorkspaceNameChange: (value: string) => void;
  onWorkspaceDescriptionChange: (value: string) => void;
  onWorkspaceSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onWorkspaceChange: (event: ChangeEvent<HTMLSelectElement>) => void;
  onDocumentChange: (event: ChangeEvent<HTMLSelectElement>) => void;
  onFileChange: (file: File | null) => void;
  onUpload: () => void;
  onExtractGraph: () => void;
};

export function DocumentSidebar(props: Props) {
  const selectedDoc = props.documents.find((d) => d.id === props.selectedDocumentId);

  return (
    <aside className="doc-sidebar">
      <WorkflowSteps hasDocument={props.hasDocument} hasGraph={props.hasGraph} hasQa={props.hasQa} />
      <form className="sidebar-block" onSubmit={props.onWorkspaceSubmit}>
        <h3>{'\u521b\u5efa\u5de5\u4f5c\u7a7a\u95f4'}</h3>
        <label>
          {'\u540d\u79f0'}
          <input value={props.workspaceName} onChange={(e) => props.onWorkspaceNameChange(e.target.value)} />
        </label>
        <label>
          {'\u63cf\u8ff0'}
          <textarea
            rows={2}
            value={props.workspaceDescription}
            onChange={(e) => props.onWorkspaceDescriptionChange(e.target.value)}
          />
        </label>
        <button type="submit" disabled={props.submitting}>
          {'\u521b\u5efa'}
        </button>
      </form>
      <div className="sidebar-block">
        <h3>{'\u6587\u6863\u4e0e\u4e0a\u4f20'}</h3>
        <label>
          {'\u5de5\u4f5c\u7a7a\u95f4'}
          <select value={props.selectedWorkspaceId ?? ''} onChange={props.onWorkspaceChange}>
            <option value="" disabled>
              {'\u8bf7\u9009\u62e9'}
            </option>
            {props.workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {'\u6587\u6863'}
          <select value={props.selectedDocumentId ?? ''} onChange={props.onDocumentChange}>
            <option value="" disabled>
              {props.documents.length ? '\u8bf7\u9009\u62e9\u6587\u6863' : '\u6682\u65e0\u6587\u6863'}
            </option>
            {props.documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.file_name}
              </option>
            ))}
          </select>
        </label>
        {selectedDoc && (
          <p className="doc-meta">
            <span className="doc-meta-type">{selectedDoc.file_type.toUpperCase()}</span>
            <span>{selectedDoc.document_topic}</span>
          </p>
        )}
        <label className="file-input-label">
          PDF / DOCX / TXT
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => props.onFileChange(e.target.files?.[0] ?? null)}
          />
        </label>
        <button
          type="button"
          className="btn-secondary"
          disabled={props.submitting || !props.selectedWorkspaceId || !props.uploadFile}
          onClick={props.onUpload}
        >
          {'\u4e0a\u4f20\u5e76\u89e3\u6790'}
        </button>
        <button
          type="button"
          disabled={props.submitting || !props.selectedDocumentId}
          onClick={props.onExtractGraph}
        >
          {'\u62bd\u53d6\u77e5\u8bc6\u56fe\u8c31'}
        </button>
      </div>
    </aside>
  );
}
