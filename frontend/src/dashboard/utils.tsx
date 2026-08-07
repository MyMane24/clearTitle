import React, { useState } from 'react';
import { Check, Database, List } from 'lucide-react';

export function escHtml(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function syntaxHighlight(json: string): string {
  return escHtml(json)
    .replace(/("(?:[^"\\]|\\.)*")(\s*:)/g, '<span class="jk">$1</span>$2')
    .replace(/:\s*("(?:[^"\\]|\\.)*")/g, ': <span class="js">$1</span>')
    .replace(/:\s*(-?\d+\.?\d*)/g, ': <span class="jn">$1</span>')
    .replace(/:\s*(true|false|null)/g, ': <span class="jb">$1</span>');
}

export interface FlatRow {
  key: string;
  value: unknown;
  raw: unknown;
}

export function flattenObj(obj: any, prefix: string, depth: number): FlatRow[] {
  if (depth > 4) return [];
  const rows: FlatRow[] = [];
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      rows.push(...flattenObj(v, key, depth + 1));
    } else if (Array.isArray(v)) {
      v.forEach((item, i) => {
        if (typeof item === "object" && item !== null) rows.push(...flattenObj(item, `${key}[${i}]`, depth + 1));
        else rows.push({ key: `${key}[${i}]`, value: item, raw: item });
      });
    } else {
      rows.push({ key, value: v, raw: v });
    }
  }
  return rows;
}

interface SummaryGroup {
  title: string;
  fields: { name: string; value: string }[];
}

export function buildSummaryGroups(structured: any): SummaryGroup[] {
  const rows = flattenObj(structured, "", 0)
    .filter(r => r.value !== null && r.value !== "" && !Array.isArray(r.raw));

  const groups: Record<string, SummaryGroup> = {};
  rows.forEach(r => {
    const parts = r.key.split('.');
    let category: string;
    let fieldName: string;
    if (parts.length > 1) {
      category = parts[0].replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      fieldName = parts.slice(1).join(' › ').replace(/\[(\d+)\]/g, ' #$1').replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase()).trim();
    } else {
      category = "General";
      fieldName = r.key.replace(/\[(\d+)\]/g, ' #$1').replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase()).trim();
    }
    if (!groups[category]) groups[category] = { title: category, fields: [] };
    groups[category].fields.push({ name: fieldName, value: String(r.value) });
  });

  return Object.values(groups);
}

const GROUP_COLORS = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

export function SummaryTable({ structured }: { structured: any }) {
  const groups = buildSummaryGroups(structured);
  if (!groups.length) {
    return <div className="vr-sheet-empty">No fields populated for this document.</div>;
  }
  return (
    <div className="vr-field-sheet">
      {groups.map((g, gi) => (
        <div className="vr-sheet-group" key={g.title}>
          <div className="vr-sheet-group-title">
            <span className="vr-sheet-group-dot" style={{ background: GROUP_COLORS[gi % 6] }}></span>
            {g.title}
            <span className="vr-sheet-group-count">{g.fields.length}</span>
          </div>
          <div className="vr-sheet-rows">
            {g.fields.map(f => (
              <div className="vr-sheet-row" key={`${g.title}-${f.name}`}>
                <div className="vr-sheet-key">{f.name}</div>
                <div className="vr-sheet-val">{f.value}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export interface DocResult {
  filename?: string;
  doc_type?: string;
  document_type?: string;
  structured?: any;
  structured_json?: any;
  total_pages?: number | string | null;
  chunks_used?: number | string | null;
  input_tokens?: number;
  output_tokens?: number;
}

export function DocPanel({ res }: { res: DocResult }) {
  const [view, setView] = useState<'json' | 'summary'>('json');
  const structured = res.structured || {};
  const jsonPretty = syntaxHighlight(JSON.stringify(structured, null, 2));
  const docType = res.doc_type || res.document_type || "";
  const pages = res.total_pages ?? "?";
  const chunks = res.chunks_used ?? "?";

  return (
    <div className="doc-panel-inner">
      <div className="doc-info-bar">
        <strong>{res.filename || ""}</strong>
        <span className="badge badge-blue">{docType}</span>
        <span style={{ color: 'var(--gray)' }}>Pages: <strong>{pages}</strong></span>
        <span style={{ color: 'var(--gray)' }}>Chunks: <strong>{chunks}</strong></span>
        {res.input_tokens ? (
          <span style={{ color: 'var(--gray)' }}>Tokens: <strong>{res.input_tokens} in / {res.output_tokens} out</strong></span>
        ) : null}
        <span className="badge badge-green"><Check size={11} style={{ verticalAlign: '-1px', marginRight: 4 }} /> complete</span>
      </div>
      <div className="view-toggle">
        <button className={`vt-btn ${view === 'json' ? 'active' : ''}`} onClick={() => setView('json')}><Database size={13} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Structured JSON</button>
        <button className={`vt-btn ${view === 'summary' ? 'active' : ''}`} onClick={() => setView('summary')}><List size={13} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Field Summary</button>
      </div>
      {view === 'json' && (
        <pre className="json-viewer" dangerouslySetInnerHTML={{ __html: jsonPretty }} />
      )}
      {view === 'summary' && <SummaryTable structured={structured} />}
    </div>
  );
}
