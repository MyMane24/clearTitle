import React from 'react';

type PhaseAResultData = {
  property_identity?: unknown;
  title_chain_graph?: string;
  title_chain?: unknown;
};

function displayLabel(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function ValueView({ value }: { value: unknown }): React.ReactNode {
  if (value == null || value === '') return <span className="phase-a-empty-value">Not stated</span>;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return <span className="phase-a-value-text">{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="phase-a-empty-value">None recorded</span>;
    return (
      <div className="phase-a-value-list">
        {value.map((item, index) => (
          <div className="phase-a-value-list-item" key={index}>
            <ValueView value={item} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
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

function IdentitySection({ identity }: { identity: unknown }) {
  const identityRecord = identity && typeof identity === 'object' && !Array.isArray(identity)
    ? identity as Record<string, unknown>
    : null;
  const details = identityRecord?.details;
  const additionalIdentity = identityRecord
    ? Object.fromEntries(Object.entries(identityRecord).filter(([key]) => key !== 'details'))
    : identity;

  return (
    <section className="phase-a-identity" aria-labelledby="phase-a-identity-title">
      <div className="phase-a-section-heading">
        <span className="phase-a-section-index">01</span>
        <div>
          <h2 id="phase-a-identity-title">Property being verified</h2>
          <p>Identifiers and descriptions recorded in the uploaded documents.</p>
        </div>
      </div>
      {Array.isArray(details) && details.length ? (
        <div className="phase-a-identity-grid">
          {details.map((detail, index) => {
            const item: Record<string, unknown> = detail && typeof detail === 'object'
              ? detail as Record<string, unknown>
              : { label: `Detail ${index + 1}`, value: detail };
            return (
              <article className="phase-a-identity-item" key={`${String(item.label || 'detail')}-${index}`}>
                <h3>{String(item.label || `Detail ${index + 1}`)}</h3>
                <ValueView value={item.value} />
                {Array.isArray(item.source_refs) && item.source_refs.length > 0 && (
                  <details className="phase-a-sources">
                    <summary>Evidence · {item.source_refs.length}</summary>
                    <ValueView value={item.source_refs} />
                  </details>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="phase-a-identity-item">
          <ValueView value={identity} />
        </div>
      )}
      {additionalIdentity && typeof additionalIdentity === 'object' && !Array.isArray(additionalIdentity) &&
        Object.keys(additionalIdentity as Record<string, unknown>).length > 0 && (
          <div className="phase-a-identity-extra"><ValueView value={additionalIdentity} /></div>
        )}
    </section>
  );
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
      if (typeof filename === 'string' && filename.toLowerCase().endsWith('.pdf')) filenames.add(filename);
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
    ? transaction.summary_points.map(pointText).filter((point): point is string => point !== null)
    : [];
  const relatedEvents = Array.isArray(item.related_events) ? item.related_events : [];
  const number = transaction.transaction_number || transaction.registration_number;
  const date = transaction.executed_date || transaction.execution_date;
  const { transaction_number: _number, registration_number: _registration, transaction_type: _type,
    type: _legacyType, executed_date: _date, execution_date: _executionDate,
    summary_points: _points, source_refs: _refs, evidence_status: _evidenceStatus,
    ...otherTransactionDetails } = transaction;
  const { related_events: _relatedEvents, chain_position: _position, documented_transaction: _documented, ...otherEntryDetails } = item;

  return (
    <article className="phase-a-chain-entry">
      <header className="phase-a-transaction-heading">
        <span className="phase-a-chain-marker" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <h3>Transaction {index + 1}</h3>
      </header>
      <dl className="phase-a-transaction-meta">
        <div><dt>Transaction number</dt><dd>{number ? <ValueView value={number} /> : <span className="phase-a-empty-value">Not stated</span>}</dd></div>
        <div><dt>Transaction type</dt><dd><ValueView value={transactionType || 'Not stated'} /></dd></div>
        <div><dt>Execution date</dt><dd>{date ? <ValueView value={date} /> : <span className="phase-a-empty-value">Not stated</span>}</dd></div>
      </dl>
      {summaryPoints.length > 0 ? (
        <ul className="phase-a-summary-points">
          {summaryPoints.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}
        </ul>
      ) : Object.keys(otherTransactionDetails).length > 0 ? (
        <div className="phase-a-legacy-details"><ValueView value={otherTransactionDetails} /></div>
      ) : (
        <p className="phase-a-empty-value">No additional transaction details were recorded.</p>
      )}
      <PointSources refs={transaction.source_refs} />
      {Object.keys(otherEntryDetails).length > 0 && <div className="phase-a-legacy-details"><ValueView value={otherEntryDetails} /></div>}
      {relatedEvents.length > 0 && (
        <section className="phase-a-related-events" aria-label="Related property events">
          <h3>Related events</h3>
          {relatedEvents.map((event, eventIndex) => {
            const eventRecord = event && typeof event === 'object' ? event as Record<string, unknown> : {};
            const eventPoints = Array.isArray(eventRecord.summary_points)
              ? eventRecord.summary_points.map(pointText).filter((point): point is string => point !== null)
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

export function PhaseAOverview({
  result,
  onOpenChain,
}: {
  result: PhaseAResultData;
  onOpenChain: () => void;
}) {
  return (
    <main className="phase-a-result">
      <header className="phase-a-page-heading">
        <span className="phase-a-eyebrow">PROPERTY INVESTIGATION</span>
        <h1>Property identity &amp; title chain</h1>
        <p>Built from the uploaded documents and their recorded evidence.</p>
      </header>
      <IdentitySection identity={result.property_identity} />
      <GraphSection graph={result.title_chain_graph || ''} />
      <div className="phase-a-overview-action">
        <span>{Array.isArray(result.title_chain) ? `${result.title_chain.length} linked records` : 'Detailed chain'}</span>
        <button type="button" onClick={onOpenChain}>Explore transaction details <span aria-hidden="true">→</span></button>
      </div>
    </main>
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
        <button className="phase-a-back-button" type="button" onClick={onBack}>← Property overview</button>
      </header>
      <GraphSection graph={result.title_chain_graph || ''} />
      <div className="phase-a-chain-intro">
        <h2>Documents behind the chain</h2>
        <p>Transactions and relevant property events, in chronological order.</p>
      </div>
      <ChainDetails chain={result.title_chain} />
    </main>
  );
}
