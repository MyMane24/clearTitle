import React from 'react';
import {
  ArrowDownRight, ArrowUpRight, Building2, CalendarDays, Check, ChevronLeft,
  ChevronRight, FileText, Fingerprint, Hash, Landmark, LandPlot, MapPin, Route,
  Ruler, ShieldCheck, Users, Wallet,
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

  const sides: { dir: string; key: string; cls: string }[] = [
    { dir: 'N', key: 'north', cls: 'ds-plot-n h' },
    { dir: 'E', key: 'east', cls: 'ds-plot-e' },
    { dir: 'S', key: 'south', cls: 'ds-plot-s h' },
    { dir: 'W', key: 'west', cls: 'ds-plot-w' },
  ];
  const filled = sides.filter(s => isFilled(bounds[s.key]));

  const topRow = hasN ? 'n n n' : '. . .';
  const midRow = `${hasW ? 'w' : '.'} c ${hasE ? 'e' : '.'}`;
  const botRow = hasS ? 's s s' : '. . .';
  const cols = hasW || hasE ? 'minmax(110px, 1fr) minmax(180px, 2fr) minmax(110px, 1fr)' : '1fr';

  return (
    <div className="ds-plot-wrap">
      <div className="ds-plot-title">Boundaries</div>
      <div
        className="ds-plot"
        style={{
          gridTemplateAreas: `"${topRow}" "${midRow}" "${botRow}"`,
          gridTemplateColumns: cols,
        }}
      >
        {filled.map(s => (
          <div className={`ds-plot-side ${s.cls} ${isRoad(bounds[s.key]) ? 'road' : ''}`} key={s.key}>
            <span className="ds-plot-dir">{s.dir}</span>
            {isRoad(bounds[s.key]) ? (
              <span className="ds-plot-val road"><Route size={13} /> {fmt(bounds[s.key])}</span>
            ) : (
              <span className="ds-plot-val">{fmt(bounds[s.key])}</span>
            )}
          </div>
        ))}
        <div className="ds-plot-center">
          <LandPlot size={26} />
          <span>Plot</span>
        </div>
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
    <div className="ds-section ds-section-flat">
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
  const stat = s.statutory_valuation_endorsement || {};
  const payments = Array.isArray(fin.payment_breakdown) ? fin.payment_breakdown : [];

  const overview: { icon: React.ReactNode; label: string; value: string }[] = [];
  if (docType) overview.push({ icon: <Fingerprint size={13} />, label: 'Document Type', value: docType });
  if (isFilled(meta.execution_date)) overview.push({ icon: <CalendarDays size={13} />, label: 'Executed On', value: fmt(meta.execution_date) });
  if (isFilled(meta.registration_date)) overview.push({ icon: <CalendarDays size={13} />, label: 'Registered On', value: fmt(meta.registration_date) });
  if (isFilled(meta.issuing_office)) overview.push({ icon: <Landmark size={13} />, label: 'Issuing Office', value: fmt(meta.issuing_office) });
  if (isFilled(meta.registration_number)) overview.push({ icon: <Hash size={13} />, label: 'Registration No.', value: fmt(meta.registration_number) });
  if (isFilled(meta.application_number)) overview.push({ icon: <Hash size={13} />, label: 'Application No.', value: fmt(meta.application_number) });
  if (isFilled(meta.certificate_number)) overview.push({ icon: <Hash size={13} />, label: 'Certificate No.', value: fmt(meta.certificate_number) });
  if (isFilled(meta.search_start_date) || isFilled(meta.search_end_date)) {
    overview.push({ icon: <CalendarDays size={13} />, label: 'Search Period', value: `${fmt(meta.search_start_date)} — ${fmt(meta.search_end_date)}` });
  }

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
  const hasStat = Object.values(stat).some(isFilled);

  return (
    <div className="ds">
      <div className="ds-head">
        <div className="ds-title">
          <div className="ds-title-icon"><FileText size={20} /></div>
          <div>
            <div className="ds-filename">{res.filename || 'Document'}</div>
            <div className="ds-sub">
              {docType && <span className="badge badge-blue">{docType}</span>}
              <span className="ds-status"><Check size={12} /> Complete</span>
            </div>
          </div>
        </div>
      </div>

      {overview.length > 0 && (
        <div className="ds-grid">
          {overview.map((t, i) => <FactTile key={i} icon={t.icon} label={t.label} value={t.value} />)}
        </div>
      )}

      <SearchCriteriaSection crit={s.search_criteria} />
      <LedgerSection ledger={Array.isArray(s.historical_ledger) ? s.historical_ledger : []} />

      {hasParties && (
        <Section icon={<Users size={15} />} title="Parties">
          <div className="ds-parties">
            <PartyCol title="Vendors" icon={<Building2 size={13} />} people={vendors} />
            <PartyCol title="Purchasers" icon={<Users size={13} />} people={purchasers} />
          </div>
        </Section>
      )}

      {hasProperty && !isEC && (
        <Section icon={<Ruler size={15} />} title="Property Schedule">
          <div className="ds-grid">
            {propFields.map(([label, value], i) => <FactTile key={i} label={label} value={fmt(value)} />)}
          </div>
          <BoundaryPlot bounds={bounds} />
          {hasFullDesc && (
            <div className="ds-description">
              <div className="ds-description-label">Full Description</div>
              <p className="ds-description-text">{fmt(prop.full_schedule_description)}</p>
            </div>
          )}
        </Section>
      )}

      {hasFin && (
        <Section icon={<Wallet size={15} />} title="Financials">
          <div className="ds-grid">
            {isFilled(fin.declared_consideration_amount) && <FactTile label="Declared Consideration" value={money(fin.declared_consideration_amount)} />}
            {isFilled(fin.stamp_duty_paid_amount) && <FactTile label="Stamp Duty Paid" value={money(fin.stamp_duty_paid_amount)} />}
            {isFilled(fin.total_registration_fees) && <FactTile label="Registration Fees" value={money(fin.total_registration_fees)} />}
            {isFilled(fin.payment_dd_reference) && <FactTile label="DD Reference" value={fmt(fin.payment_dd_reference)} />}
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
        </Section>
      )}

      {hasStat && (
        <Section icon={<ShieldCheck size={15} />} title="Statutory Valuation">
          <div className="ds-grid">
            {isFilled(stat.estimated_market_value) && <FactTile label="Estimated Market Value" value={money(stat.estimated_market_value)} />}
            {isFilled(stat.prevent_of_undervaluation_referred) && <FactTile label="Undervaluation Referred" value={fmt(stat.prevent_of_undervaluation_referred)} />}
            {isFilled(stat.form_1a_communication_date) && <FactTile label="Form 1A Date" value={fmt(stat.form_1a_communication_date)} />}
          </div>
        </Section>
      )}

      <FallbackSections structured={s} />
    </div>
  );
}
