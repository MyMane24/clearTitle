import React from 'react';

type PhaseAResultData = {
  property_identity?: unknown;
  title_chain_graph?: string;
  title_chain?: unknown;
  missing_documents?: unknown;
};

function displayLabel(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function hasValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') {
    return !['', 'not stated', 'null'].includes(value.trim().toLowerCase());
  }
  if (Array.isArray(value)) return value.some(hasValue);
  if (typeof value === 'object') return Object.values(value).some(hasValue);
  return true;
}

function ValueView({ value }: { value: unknown }): React.ReactNode {
  if (!hasValue(value)) return null;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return <span className="phase-a-value-text">{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="phase-a-empty-value">None recorded</span>;
    return (
      <div className="phase-a-value-list">
        {value.filter(hasValue).map((item, index) => (
          <div className="phase-a-value-list-item" key={index}>
            <ValueView value={item} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, nested]) => hasValue(nested));
    if (!entries.length) return <span className="phase-a-empty-value">No details</span>;
    return (
      <dl className="phase-a-nested-fields">
        {entries.map(([key, nested]) => (
          <div className="phase-a-nested-field" key={key}>
            <dt>{displayLabel(key)}</dt>
            <dd><ValueView value={nested} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className="phase-a-value-text">{String(value)}</span>;
}

function GraphSection({ graph }: { graph: string }) {
  return (
    <section className="phase-a-graph" aria-labelledby="phase-a-graph-title">
      <div className="phase-a-graph-heading">
        <div>
          <span className="phase-a-graph-kicker">OWNERSHIP THROUGH TIME</span>
          <h2 id="phase-a-graph-title">Title chain</h2>
        </div>
        <span className="phase-a-direction">Root <span aria-hidden="true">→</span> Current owner</span>
      </div>
      {graph ? (
        <pre className="phase-a-graph-content">{graph}</pre>
      ) : (
        <p className="phase-a-empty">The agent did not return a graph for this case.</p>
      )}
    </section>
  );
}

function PropertyIdentitySection({ identity }: { identity: unknown }) {
  if (!hasValue(identity)) return null;
  return (
    <section className="verification-property-identity" aria-labelledby="phase-a-property-identity-title">
      <div className="verification-property-identity-heading">
        <span className="verification-property-identity-kicker">TARGET PROPERTY</span>
        <h2 id="phase-a-property-identity-title">Property identity</h2>
        <p>Identifiers recorded from the property's documents.</p>
      </div>
      <ValueView value={identity} />
    </section>
  );
}

function pointText(point: unknown): string | null {
  if (typeof point === 'string') return point;
  if (point && typeof point === 'object' && typeof (point as Record<string, unknown>).text === 'string') {
    return String((point as Record<string, unknown>).text);
  }
  return null;
}

function pdfSourceNames(value: unknown): string[] {
  const filenames = new Set<string>();
  if (!Array.isArray(value)) return [];
  value.forEach(ref => {
    if (ref && typeof ref === 'object') {
      const filename = (ref as Record<string, unknown>).filename;
      const docId = (ref as Record<string, unknown>).doc_id;
      if (typeof filename === 'string' && filename) filenames.add(filename);
      else if (typeof docId === 'string' && docId) filenames.add(docId);
    }
  });
  return [...filenames];
}

function PointSources({ refs }: { refs: unknown }) {
  const filenames = pdfSourceNames(refs);
  if (!filenames.length) return null;
  return (
    <p className="phase-a-point-sources" aria-label={`Sources: ${filenames.join(', ')}`}>
      <span>Sources</span> {filenames.join(' · ')}
    </p>
  );
}

function ChainEntry({ entry, index }: {
  entry: unknown;
  index: number;
}) {
  const item = entry && typeof entry === 'object'
    ? entry as Record<string, unknown>
    : { details: entry };
  const transaction = item.documented_transaction && typeof item.documented_transaction === 'object'
    ? item.documented_transaction as Record<string, unknown>
    : item;
  const rawTransactionType = transaction.transaction_type || transaction.type || item.event_type;
  const transactionType = typeof rawTransactionType === 'string'
    ? rawTransactionType.replace(/\s*\(EC entry; instrument not supplied\)/i, '')
    : rawTransactionType;
  const summaryPoints = Array.isArray(transaction.summary_points)
    ? transaction.summary_points.map(pointText).filter((point): point is string => point !== null && hasValue(point))
    : [];
  const relatedEvents = Array.isArray(item.related_events) ? item.related_events : [];
  const number = transaction.transaction_number || transaction.registration_number;
  const date = transaction.executed_date || transaction.execution_date;
  const position = typeof item.chain_position === 'number' ? item.chain_position : index + 1;
  const evidenceLabels: Record<string, string> = {
    corroborated: 'Corroborated by multiple documents',
    register_reported: 'Reported in a history register',
    deed_reported: 'Reported in the transfer deed',
    recital_reported: 'Reported in a later deed’s recital',
  };
  const evidence = typeof transaction.evidence_status === 'string'
    ? evidenceLabels[transaction.evidence_status] || displayLabel(transaction.evidence_status)
    : 'Not stated';
  const { transaction_number: _number, registration_number: _registration, transaction_type: _type,
    type: _legacyType, executed_date: _date, execution_date: _executionDate,
    summary_points: _points, source_refs: _refs, evidence_status: _evidenceStatus,
    transferors: _transferors, transferees: _transferees,
    ...otherTransactionDetails } = transaction;
  const { tx_id: _txId, upstream_tx_ids: _upstream, continues_previous: _continues, related_events: _relatedEvents, chain_position: _position, documented_transaction: _documented, ...otherEntryDetails } = item;

  return (
    <article className="phase-a-chain-entry">
      <header className="phase-a-transaction-heading">
        <span className="phase-a-chain-marker" aria-hidden="true">{String(position).padStart(2, '0')}</span>
        <h3>Transaction {position} — <ValueView value={transactionType || 'Transfer'} /></h3>
      </header>
      <p className={`phase-a-continuity${index > 0 && item.continues_previous === false ? ' phase-a-continuity-gap' : ''}`}>
        {index === 0 ? 'Earliest recorded link'
          : item.continues_previous === true ? 'Continues the previous ownership link'
          : item.continues_previous === false ? 'Unresolved continuity with the previous link — see notes below'
          : 'Continuity not stated'}
      </p>
      <dl className="phase-a-transaction-meta">
        {hasValue(number) && <div><dt>Transaction number</dt><dd><ValueView value={number} /></dd></div>}
        {hasValue(transactionType) && <div><dt>Transaction type</dt><dd><ValueView value={transactionType} /></dd></div>}
        {hasValue(date) && <div><dt>Execution date</dt><dd><ValueView value={date} /></dd></div>}
      </dl>
      <div className="phase-a-parties">
        {hasValue(transaction.transferors) && <section aria-label="Transferors"><h4>From · Transferors</h4><ValueView value={transaction.transferors} /></section>}
        {hasValue(transaction.transferees) && <section aria-label="Transferees"><h4>To · Acquirers</h4><ValueView value={transaction.transferees} /></section>}
      </div>
      {hasValue(otherTransactionDetails) && (
        <section className="phase-a-record-details" aria-label="Instrument and property details">
          <h4>Instrument &amp; property details</h4>
          <ValueView value={otherTransactionDetails} />
        </section>
      )}
      <section className="phase-a-evidence-basis">
        {hasValue(evidence) && <><h4>Evidence basis</h4><p>{evidence}</p></>}
        <PointSources refs={transaction.source_refs} />
      </section>
      {summaryPoints.length > 0 && (
        <section className="phase-a-chain-notes">
        <h4>Recorded facts &amp; reconciliation notes</h4>
        <ul className="phase-a-summary-points">
          {summaryPoints.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}
        </ul>
        </section>
      )}
      {!!item.documented_transaction && hasValue(otherEntryDetails) && <div className="phase-a-legacy-details"><ValueView value={otherEntryDetails} /></div>}
      {relatedEvents.length > 0 && (
        <section className="phase-a-related-events" aria-label="Related property events">
          <h3>Related events</h3>
          {relatedEvents.map((event, eventIndex) => {
            const eventRecord = event && typeof event === 'object' ? event as Record<string, unknown> : {};
            const eventPoints = Array.isArray(eventRecord.summary_points)
              ? eventRecord.summary_points.map(pointText).filter((point): point is string => point !== null && hasValue(point))
              : [];
            return (
              <div className="phase-a-related-event" key={eventIndex}>
                {typeof eventRecord.type === 'string' && <h4>{eventRecord.type}</h4>}
                {eventPoints.length > 0 ? (
                  <ul className="phase-a-summary-points">{eventPoints.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>
                ) : <ValueView value={Object.fromEntries(Object.entries(eventRecord).filter(([key]) => key !== 'source_refs'))} />}
                <PointSources refs={eventRecord.source_refs} />
              </div>
            );
          })}
        </section>
      )}
    </article>
  );
}

function ChainDetails({ chain }: {
  chain: unknown;
}) {
  if (!Array.isArray(chain) || !chain.length) {
    return <div className="phase-a-empty">Detailed chain entries are not available in this result.</div>;
  }
  return (
    <section className="phase-a-chain-list" aria-label="Detailed title chain">
      {chain.map((entry, index) => <ChainEntry key={index} entry={entry} index={index} />)}
    </section>
  );
}

export function PhaseAChainView({
  result,
  onBack,
}: {
  result: PhaseAResultData;
  onBack: () => void;
}) {
  const chain = Array.isArray(result.title_chain) ? result.title_chain : [];
  return (
    <main className="phase-a-result phase-a-chain-view">
      <header className="phase-a-chain-page-heading">
        <div>
          <span className="phase-a-eyebrow">DETAILED RECORD</span>
          <h1>Title-chain details</h1>
      <p>{chain.length} entries · earliest supported link to current ownership</p>
        </div>
        <button className="phase-a-back-button" type="button" onClick={onBack}>← Back to upload</button>
      </header>
      <PropertyIdentitySection identity={result.property_identity} />
      <GraphSection graph={result.title_chain_graph || ''} />
      <div className="phase-a-chain-intro">
        <h2>Documents behind the chain</h2>
        <p>Parties, property details, supporting documents, and reconciliation notes for each transfer. This is a reconstructed chain; verification is a separate stage.</p>
      </div>
      <ChainDetails chain={result.title_chain} />
    </main>
  );
}
