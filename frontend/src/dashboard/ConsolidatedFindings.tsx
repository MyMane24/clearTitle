import React from 'react';
import { FileSearch, AlertTriangle } from 'lucide-react';
import type { CaseFinding, CaseFindingContradiction, CaseFindingsResponse } from '../api/backend';

// Severity color mapping — same palette the dashboard already uses.
const SEVERITY_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  CRITICAL: { bg: '#fee2e2', color: '#b91c1c', border: '#fca5a5' },
  CAUTION: { bg: '#fef3c7', color: '#b45309', border: '#f59e0b' },
  POSITIVE: { bg: '#dcfce7', color: '#15803d', border: '#86efac' },
  INFORMATION: { bg: '#f1f5f9', color: '#475569', border: '#cbd5e1' },
};

function severityStyle(severity: string): { bg: string; color: string; border: string } {
  return SEVERITY_STYLES[String(severity || '').toUpperCase()] || SEVERITY_STYLES.INFORMATION;
}

function SeverityChip({ severity }: { severity: string }) {
  const s = severityStyle(severity);
  return (
    <span style={{
      marginLeft: 8, padding: '1px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, verticalAlign: 'middle',
    }}>
      {String(severity || 'INFO').toLowerCase()}
    </span>
  );
}

function TxChips({ txIds }: { txIds: string[] }) {
  if (!txIds.length) return null;
  return (
    <span style={{ marginLeft: 10, display: 'inline-flex', gap: 4, flexWrap: 'wrap', verticalAlign: 'middle' }}>
      {txIds.map(id => (
        <span key={id} style={{ padding: '1px 7px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: '#f5f5f4', color: '#57534e', border: '1px solid #d6d3d1' }}>
          {id}
        </span>
      ))}
    </span>
  );
}

function Contradiction({ item }: { item: CaseFindingContradiction }) {
  return (
    <li>
      <strong>{String(item.description || 'Contradiction')}</strong>
      <SeverityChip severity={item.severity} />
      <TxChips txIds={item.sides.map((s: any) => s?.tx_id).filter(Boolean)} />
      {item.resolution_guidance && (
        <div style={{ color: '#57534e', fontSize: 14, lineHeight: 1.8, marginTop: 4 }}>{item.resolution_guidance}</div>
      )}
    </li>
  );
}

function Finding({ finding }: { finding: CaseFinding }) {
  return (
    <li>
      <strong>
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#9a3412', marginRight: 6 }}>{finding.finding_id}</span>
        {finding.title}
      </strong>
      <SeverityChip severity={finding.severity} />
      <TxChips txIds={finding.affected_tx_ids || []} />
      <div style={{ color: '#57534e', fontSize: 14, lineHeight: 1.8, marginTop: 4 }}>{finding.description}</div>
      {!!(finding.evidence_gaps || []).length && (
        <div style={{ color: '#7c2d12', fontSize: 13, marginTop: 4 }}>
          Outstanding evidence: {finding.evidence_gaps.join('; ')}
        </div>
      )}
      {finding.implication && (
        <div style={{ color: '#44403c', fontSize: 13, marginTop: 4, fontStyle: 'italic' }}>{finding.implication}</div>
      )}
    </li>
  );
}

// Consolidated property-level findings (Phase C). The backend is the only
// source of truth for what exists; this section renders what is persisted and
// stays honest when nothing was consolidated.
export function ConsolidatedFindings({ data }: { data: CaseFindingsResponse | null }) {
  if (!data) return null;
  const generated = data.container_version != null;
  const hasContent = generated
    && (!!data.findings.length || !!data.contradictions.length || !!data.unresolved_dependencies.length);
  return (
    <section className="verification-case-findings" aria-label="Consolidated property findings">
      <span className="verification-section-kicker" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <FileSearch size={12} /> CONSOLIDATED PROPERTY FINDINGS
      </span>
      <h2>Property-level findings across all transactions</h2>
      {!generated && (
        <p className="verification-conclusion-headline">
          <AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
          Consolidated findings appear here after transaction verification completes for this case.
        </p>
      )}
      {generated && !hasContent && (
        <p className="verification-conclusion-headline">
          No consolidated findings are recorded for this case yet.
        </p>
      )}
      {!!data.findings.length && (
        <ul>
          {data.findings.map(f => <Finding key={f.finding_id} finding={f} />)}
        </ul>
      )}
      {!!data.contradictions.length && (
        <>
          <h3 style={{ margin: '18px 0 8px', fontSize: 15, fontWeight: 650, color: '#292524' }}>Conflicting records</h3>
          <ul>
            {data.contradictions.map((c, i) => <Contradiction key={i} item={c} />)}
          </ul>
        </>
      )}
      {!!data.unresolved_dependencies.length && (
        <>
          <h3 style={{ margin: '18px 0 8px', fontSize: 15, fontWeight: 650, color: '#292524' }}>Still unresolved</h3>
          <ul>
            {data.unresolved_dependencies.map(dep => (
              <li key={dep} style={{ color: '#57534e', fontSize: 14, lineHeight: 1.8 }}>{dep}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
