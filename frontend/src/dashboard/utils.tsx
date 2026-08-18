import React from 'react';
import {
  ArrowDownRight, ArrowUpRight, Building2, Check, ChevronLeft,
  ChevronRight, FileText, LandPlot, MapPin, Route,
  Ruler, Users, Wallet,
} from 'lucide-react';

const AVATAR_COLORS = ['#ea580c', '#0891b2', '#7c3aed', '#059669', '#d97706', '#dc2626'];

function humanize(k: string): string {
  return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

function money(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : Number(String(v).replace(/[^0-9.-]/g, ''));
  if (!Number.isNaN(n) && String(v).trim() !== '') {
    return '₹ ' + n.toLocaleString('en-IN');
  }
  return fmt(v);
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
}

function isFilled(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'object') return Object.keys(v as object).length > 0;
  return true;
}

function FactTile({ icon, label, value }: { icon?: React.ReactNode; label: string; value?: React.ReactNode }) {
  return (
    <div className="ds-tile">
      <div className="ds-tile-label">{icon}{label}</div>
      <div className="ds-tile-value">{value ?? '—'}</div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="ds-section">
      <div className="ds-section-title"><span className="ds-sec-ico">{icon}</span><span>{title}</span></div>
      {children}
    </div>
  );
}

function PartyCol({ title, icon, people }: { title: string; icon: React.ReactNode; people: any[] }) {
  return (
    <div className="ds-party-col">
      <div className="ds-party-col-title">{icon}<span>{title}</span></div>
      {people.length === 0 ? (
        <div className="ds-empty">Not stated</div>
      ) : people.map((p, i) => (
        <div className="ds-party" key={i}>
          <div className="ds-avatar" style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length] }}>
            {initials(p.entity_name || '')}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="ds-party-name">{fmt(p.entity_name)}</div>
            {isFilled(p.represented_by) && (
              <div className="ds-party-line"><span className="ds-party-tag">via</span> {fmt(p.represented_by)}</div>
            )}
            {isFilled(p.address) && (
              <div className="ds-party-line"><MapPin size={12} style={{ flexShrink: 0, color: 'var(--blue)', marginTop: 2 }} />{fmt(p.address)}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function isRoad(v: unknown): boolean {
  return /road|street|lane|nallah|nala|gali|highway|path/i.test(fmt(v));
}

function partyName(p: any): string {
  if (p == null) return '';
  if (typeof p === 'string') return p.trim();
  const v = p.entity_name ?? p.name ?? p.party_name ?? p.full_name ?? p.party;
  if (v == null) return '';
  const s = String(v).trim();
  return s === '—' ? '' : s;
}

function BoundaryPlot({ bounds }: { bounds: Record<string, unknown> }) {
  const hasN = isFilled(bounds.north);
  const hasS = isFilled(bounds.south);
  const hasE = isFilled(bounds.east);
  const hasW = isFilled(bounds.west);
  if (!hasN && !hasS && !hasE && !hasW) return null;

  const sides = [
    { dir: 'N', key: 'north', label: 'North' },
    { dir: 'S', key: 'south', label: 'South' },
    { dir: 'E', key: 'east', label: 'East' },
    { dir: 'W', key: 'west', label: 'West' },
  ].filter(s => isFilled(bounds[s.key]));

  return (
    <div className="ds-boundaries">
      <span className="ds-meta-label">BOUNDARIES</span>
      <div className="ds-compass">
        {hasN && (
          <div className="ds-compass-side top">
            <span className="ds-compass-dir">N</span>
            <span className="ds-compass-val">{isRoad(bounds.north) ? <><Route size={12} /> {fmt(bounds.north)}</> : fmt(bounds.north)}</span>
          </div>
        )}
        <div className="ds-compass-mid">
          {hasW && (
            <div className="ds-compass-side left">
              <span className="ds-compass-dir">W</span>
              <span className="ds-compass-val">{isRoad(bounds.west) ? <><Route size={12} /> {fmt(bounds.west)}</> : fmt(bounds.west)}</span>
            </div>
          )}
          <div className="ds-compass-center">
            <LandPlot size={22} />
            <span>PROPERTY</span>
          </div>
          {hasE && (
            <div className="ds-compass-side right">
              <span className="ds-compass-dir">E</span>
              <span className="ds-compass-val">{isRoad(bounds.east) ? <><Route size={12} /> {fmt(bounds.east)}</> : fmt(bounds.east)}</span>
            </div>
          )}
        </div>
        {hasS && (
          <div className="ds-compass-side bottom">
            <span className="ds-compass-dir">S</span>
            <span className="ds-compass-val">{isRoad(bounds.south) ? <><Route size={12} /> {fmt(bounds.south)}</> : fmt(bounds.south)}</span>
          </div>
        )}
      </div>
    </div>
  );
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

export interface DocSummaryData {
  filename?: string;
  doc_type?: string;
  document_type?: string;
  structured?: any;
  structured_json?: any;
}

const HANDLED_KEYS = [
  'document_type', 'file_metadata', 'document_metadata', 'financial_summary',
  'parties', 'property_schedule', 'property_identification',
  'statutory_valuation_endorsement', 'search_criteria', 'historical_ledger',
];

function FallbackSections({ structured }: { structured: any }) {
  const sections: React.ReactNode[] = [];
  for (const [key, value] of Object.entries(structured || {})) {
    if (HANDLED_KEYS.includes(key) || !isFilled(value)) continue;
    sections.push(
      <Section key={key} icon={<FileText size={15} />} title={humanize(key)}>
        <SummaryTable structured={{ [key]: value }} />
      </Section>
    );
  }
  return <>{sections}</>;
}

function SearchCriteriaSection({ crit }: { crit: any }) {
  const ident = crit?.target_identifiers || {};
  const tiles: { label: string; v: unknown }[] = [
    { label: 'Village', v: crit?.target_village },
    { label: 'Hobli', v: crit?.target_hobli },
    { label: 'District', v: crit?.target_district },
    { label: 'CTS Number', v: ident.cts_number },
    { label: 'Survey Number', v: ident.survey_number },
    { label: 'Converted Survey No.', v: ident.converted_survey_number },
    { label: 'Plot Number', v: ident.plot_number },
  ].filter(t => isFilled(t.v));
  if (!tiles.length) return null;
  return (
    <Section icon={<MapPin size={15} />} title="Search Criteria">
      <div className="ds-grid">
        {tiles.map((t, i) => <FactTile key={i} label={t.label} value={fmt(t.v)} />)}
      </div>
    </Section>
  );
}

function LedgerCard({ tx, index }: { tx: any; index: number }) {
  const fin = tx.financials || {};
  const parties = tx.parties || {};
  const prop = tx.property_details || {};
  const vendors = Array.isArray(parties.vendors) ? parties.vendors : [];
  const purchasers = Array.isArray(parties.purchasers) ? parties.purchasers : [];
  const vendorNames = vendors.map(partyName).filter(Boolean);
  const purchaserNames = purchasers.map(partyName).filter(Boolean);

  const chips = [
    { label: 'Market Value', value: isFilled(fin.market_value) ? money(fin.market_value) : null },
    { label: 'Consideration', value: isFilled(fin.consideration_amount) ? money(fin.consideration_amount) : null },
    { label: 'Transaction Type', value: isFilled(tx.transaction_type) ? fmt(tx.transaction_type) : null },
  ].filter(c => c.value) as { label: string; value: string }[];

  return (
    <div className="ds-ledger-card">
      <div className="ds-ledger-head">
        <span className="ds-ledger-index">Transaction {index + 1}</span>
        {isFilled(tx.execution_date) && <span className="ds-ledger-date">{fmt(tx.execution_date)}</span>}
      </div>

      {chips.length > 0 && (
        <div className="ds-ledger-chips">
          {chips.map((c, i) => (
            <div className="ds-ledger-chip" key={i}>
              <span className="ds-ledger-chip-label">{c.label}</span>
              <span className="ds-ledger-chip-value">{c.value}</span>
            </div>
          ))}
        </div>
      )}

      {(vendorNames.length > 0 || purchaserNames.length > 0) && (
        <div className="ds-ledger-people-row">
          {vendorNames.length > 0 && (
            <div className="ds-ledger-person">
              <div className="ds-ledger-person-label"><ArrowUpRight size={12} /> Vendor</div>
              <div className="ds-ledger-person-names">{vendorNames.join(', ')}</div>
            </div>
          )}
          {purchaserNames.length > 0 && (
            <div className="ds-ledger-person">
              <div className="ds-ledger-person-label"><ArrowDownRight size={12} /> Purchaser</div>
              <div className="ds-ledger-person-names">{purchaserNames.join(', ')}</div>
            </div>
          )}
        </div>
      )}

      <div className="ds-ledger-rows">
        {isFilled(tx.registration_reference) && (
          <div className="ds-ledger-row">
            <span className="ds-ledger-label">Registration</span>
            <span className="ds-ledger-desc">{fmt(tx.registration_reference)}</span>
          </div>
        )}
        {isFilled(prop.description) && (
          <div className="ds-ledger-row">
            <span className="ds-ledger-label">Property</span>
            <span className="ds-ledger-desc">{fmt(prop.description)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function LedgerSection({ ledger }: { ledger: any[] }) {
  const [idx, setIdx] = React.useState(0);
  if (!ledger || !ledger.length) return null;
  const total = ledger.length;
  const prev = () => setIdx(i => (i - 1 + total) % total);
  const next = () => setIdx(i => (i + 1) % total);

  const dotCount = Math.min(total, 3);
  let startIdx = 0;
  if (total > 3) {
    if (idx === 0) {
      startIdx = 0;
    } else if (idx === total - 1) {
      startIdx = total - 3;
    } else {
      startIdx = Math.min(idx - 1, total - 3);
    }
  }
  const visibleIndices = Array.from({ length: dotCount }, (_, i) => startIdx + i);

  return (
    <div className="ds-section">
      <div className="ds-section-title">
        <span className="ds-sec-ico"><FileText size={15} /></span>
        <span>Historical Ledger {total > 1 ? `(${idx + 1} of ${total})` : ''}</span>
      </div>
      <div className="ds-car-viewport">
        <div className="ds-car-track" style={{ transform: `translateX(-${idx * 100}%)` }}>
          {ledger.map((tx, i) => (
            <div className="ds-car-slide" key={i}><LedgerCard tx={tx} index={i} /></div>
          ))}
        </div>
      </div>
      {total > 1 && (
        <div className="ds-car-pager">
          <button className="ds-car-nav" onClick={prev} disabled={total <= 1} aria-label="Previous transaction">
            <ChevronLeft size={18} />
          </button>
          <div className="ds-car-dots">
            {visibleIndices.map((slideIdx) => (
              <button
                key={slideIdx}
                className={`ds-car-dot ${slideIdx === idx ? 'active' : ''}`}
                onClick={() => setIdx(slideIdx)}
                aria-label={`Go to transaction ${slideIdx + 1}`}
              />
            ))}
          </div>
          <button className="ds-car-nav" onClick={next} disabled={total <= 1} aria-label="Next transaction">
            <ChevronRight size={18} />
          </button>
        </div>
      )}
    </div>
  );
}

export function DocSummary({ res }: { res: DocSummaryData }) {
  const s = res.structured || {};
  const docType = res.doc_type || res.document_type || s.document_type || "";
  const meta = s.file_metadata || s.document_metadata || {};
  const fin = s.financial_summary || {};
  const parties = s.parties || {};
  const prop = s.property_schedule || s.property_identification || {};
  const measure = prop.measurements || {};
  const bounds = prop.boundaries || {};
  const payments = Array.isArray(fin.payment_breakdown) ? fin.payment_breakdown : [];

  const vendors = Array.isArray(parties.vendors) ? parties.vendors : [];
  const purchasers = Array.isArray(parties.purchasers) ? parties.purchasers : [];

  const propFields: [string, unknown][] = [
    ['CTS Number', prop.cts_number ?? prop.cts_no],
    ['Survey Number', prop.survey_number],
    ['Apartment / Shop No.', prop.apartment_or_shop_number],
    ['Floor / Location', prop.floor_location],
    ['Project Name', prop.project_name],
    ['Intended Usage', prop.intended_usage],
    ['Dimensions', measure.dimensions_text],
    ['Super Built-up Area', measure.super_built_up_area_sqft],
    ['Land Area', measure.total_land_area_sqmtr],
  ].filter(([, v]) => isFilled(v)) as [string, unknown][];

  const isEC = /encumbrance/i.test(docType);

  const hasFullDesc = isFilled(prop.full_schedule_description);
  const hasParties = vendors.length > 0 || purchasers.length > 0;
  const hasProperty = propFields.length > 0 || hasFullDesc
    || isFilled(bounds.north) || isFilled(bounds.east) || isFilled(bounds.west) || isFilled(bounds.south);
  const hasFin = isFilled(fin.declared_consideration_amount) || isFilled(fin.stamp_duty_paid_amount)
    || isFilled(fin.total_registration_fees) || payments.length > 0;

  return (
    <div className="ds">
      {/* ── Top Metadata Grid ── */}
      <div className="ds-meta-grid">
        <div className="ds-meta-cell">
          <span className="ds-meta-label">DOCUMENT TYPE</span>
          <span className="ds-meta-value headline">{docType || '—'}</span>
        </div>
        {isFilled(meta.execution_date) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">EXECUTED DATE</span>
            <span className="ds-meta-value mono">{fmt(meta.execution_date)}</span>
          </div>
        )}
        {isFilled(meta.registration_date) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">REGISTERED DATE</span>
            <span className="ds-meta-value mono">{fmt(meta.registration_date)}</span>
          </div>
        )}
        {isFilled(meta.registration_number) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">REGISTRATION NO</span>
            <span className="ds-meta-value mono accent">{fmt(meta.registration_number)}</span>
          </div>
        )}
        {isFilled(meta.issuing_office) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">ISSUING OFFICE</span>
            <span className="ds-meta-value mono">{fmt(meta.issuing_office)}</span>
          </div>
        )}
        {isFilled(meta.application_number) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">APPLICATION NO</span>
            <span className="ds-meta-value mono">{fmt(meta.application_number)}</span>
          </div>
        )}
        {isFilled(meta.certificate_number) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">CERTIFICATE NO</span>
            <span className="ds-meta-value mono">{fmt(meta.certificate_number)}</span>
          </div>
        )}
        {(isFilled(meta.search_start_date) || isFilled(meta.search_end_date)) && (
          <div className="ds-meta-cell">
            <span className="ds-meta-label">SEARCH PERIOD</span>
            <span className="ds-meta-value mono">{fmt(meta.search_start_date)} — {fmt(meta.search_end_date)}</span>
          </div>
        )}
      </div>

      {/* ── Parties ── */}
      {hasParties && (
        <div className="ds-block">
          <h3 className="ds-block-heading">
            <span className="ds-split-ico"><Users size={16} /></span>
            Parties
          </h3>
          <div className="ds-parties">
            <PartyCol title="Vendors (Seller)" icon={<Building2 size={13} />} people={vendors} />
            <PartyCol title="Purchasers (Buyer)" icon={<Users size={13} />} people={purchasers} />
          </div>
        </div>
      )}

      {/* ── Property Details ── */}
      {hasProperty && !isEC && (
        <div className="ds-block">
          <h3 className="ds-block-heading">
            <span className="ds-split-ico"><Ruler size={16} /></span>
            Property Details
          </h3>
          <div className="ds-prop-grid">
            {propFields.map(([label, value], i) => (
              <div className="ds-prop-cell" key={i}>
                <span className="ds-meta-label">{label.toUpperCase()}</span>
                <span className="ds-meta-value">{fmt(value)}</span>
              </div>
            ))}
          </div>
          {isFilled(prop.full_schedule_description) && (
            <div className="ds-schedule-block">
              <span className="ds-meta-label">SCHEDULE PROPERTY</span>
              <span className="ds-meta-value">{fmt(prop.full_schedule_description)}</span>
            </div>
          )}
          <BoundaryPlot bounds={bounds} />
        </div>
      )}

      {/* ── Consideration & Fees ── */}
      {hasFin && (
        <div className="ds-block">
          <h3 className="ds-block-heading">
            <span className="ds-split-ico"><Wallet size={16} /></span>
            Consideration &amp; Fees
          </h3>
          <div className="ds-fin-grid">
            {isFilled(fin.declared_consideration_amount) && (
              <div className="ds-fin-cell">
                <span className="ds-meta-label">DECLARED CONSIDERATION</span>
                <span className="ds-meta-value mono">{money(fin.declared_consideration_amount)}</span>
              </div>
            )}
            {isFilled(fin.stamp_duty_paid_amount) && (
              <div className="ds-fin-cell">
                <span className="ds-meta-label">STAMP DUTY PAID</span>
                <span className="ds-meta-value mono">{money(fin.stamp_duty_paid_amount)}</span>
              </div>
            )}
            {isFilled(fin.total_registration_fees) && (
              <div className="ds-fin-cell">
                <span className="ds-meta-label">REGISTRATION FEES</span>
                <span className="ds-meta-value mono">{money(fin.total_registration_fees)}</span>
              </div>
            )}
            {isFilled(fin.payment_dd_reference) && (
              <div className="ds-fin-cell">
                <span className="ds-meta-label">DD REFERENCE</span>
                <span className="ds-meta-value mono">{fmt(fin.payment_dd_reference)}</span>
              </div>
            )}
          </div>
          {payments.length > 0 && (
            <div className="ds-fin-list">
              {payments.map((p, i) => (
                <div className="ds-fin-card" key={i}>
                  <div className="ds-fin-head">
                    <span>Payment {payments.length > 1 ? `#${i + 1}` : ''}</span>
                    <strong>{money(p.amount)}</strong>
                  </div>
                  {isFilled(p.mode) && <div className="ds-fin-line">{fmt(p.mode)}</div>}
                  {isFilled(p.instrument_reference) && <div className="ds-fin-line">Ref: {fmt(p.instrument_reference)}</div>}
                  {isFilled(p.instrument_date) && <div className="ds-fin-line">Date: {fmt(p.instrument_date)}</div>}
                  {isFilled(p.bank_branch) && <div className="ds-fin-line">Branch: {fmt(p.bank_branch)}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Search Criteria (for ECs) ── */}
      <SearchCriteriaSection crit={s.search_criteria} />

      {/* ── Historical Ledger (for ECs — shows parties, financials, property per transaction) ── */}
      <LedgerSection ledger={Array.isArray(s.historical_ledger) ? s.historical_ledger : []} />

      {/* ── Fallback sections for any unhandled keys ── */}
      <FallbackSections structured={s} />
    </div>
  );
}
