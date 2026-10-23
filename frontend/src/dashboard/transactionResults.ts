export type RequiredDocument = {
  document_type: string;
  reason?: string | null;
  for_transaction?: string | null;
};

export type TransactionEvidence = {
  doc_id: string;
  pages?: string | null;
};

export type TransactionFinding = {
  title: string;
  details: string;
  evidence: TransactionEvidence[];
};

export type TransactionVerificationResult = {
  tx_id: string;
  sequence: number;
  status: string;
  summary: string;
  findings: TransactionFinding[];
  required_documents: RequiredDocument[];
  reviewed_document_ids: string[];
  transaction_metadata?: Record<string, unknown>;
  verified_at: string | null;
  schema_version: string;
};

export function requiredDocumentsForTransaction(transaction: unknown): RequiredDocument[] {
  if (!transaction || typeof transaction !== 'object') return [];
  const items = (transaction as { required_documents?: unknown }).required_documents;
  if (!Array.isArray(items)) return [];
  const seen = new Set<string>();
  return items.filter((item): item is RequiredDocument => {
    if (!item || typeof item !== 'object') return false;
    const value = item as RequiredDocument;
    if (typeof value.document_type !== 'string' || !value.document_type.trim()) return false;
    const key = `${value.document_type.trim().toLocaleLowerCase()}|${String(value.reason || '').trim().toLocaleLowerCase()}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function requirementsForPausedTransaction(transactions: unknown, txId: unknown): RequiredDocument[] {
  if (!Array.isArray(transactions) || typeof txId !== 'string' || !txId) return [];
  const transaction = transactions.find((item: any) => item?.tx_id === txId);
  return requiredDocumentsForTransaction(transaction);
}

export function transactionStatusLabel(status: unknown): string {
  const normalized = String(status || 'PENDING').toUpperCase();
  const labels: Record<string, string> = {
    PENDING: 'Pending',
    IN_PROGRESS: 'In progress',
    PENDING_NOT_VERIFIED: 'Pending verification',
    VERIFIED_WITH_AVAILABLE_EVIDENCE: 'Verified with available evidence',
    ISSUES_IDENTIFIED: 'Issues identified',
    INCONCLUSIVE: 'Inconclusive',
    SKIPPED: 'Skipped · not verified',
    SKIPPED_BY_USER: 'Skipped · not verified',
  };
  return labels[normalized] || 'Pending verification';
}

export function transactionTitle(result: Pick<TransactionVerificationResult, 'sequence' | 'transaction_metadata'>): string {
  const metadata = result.transaction_metadata || {};
  const rawType = String(metadata.transaction_type || metadata.document_type || 'Transaction').trim();
  const type = rawType
    .replace(/[_-]+/g, ' ')
    .toLocaleLowerCase()
    .replace(/(^|\s)\p{L}/gu, letter => letter.toLocaleUpperCase());
  const sequence = Number.isFinite(result.sequence) && result.sequence > 0 ? result.sequence : '—';
  return `Transaction ${sequence} — ${type}`;
}

export function transactionMetadataItems(metadata: Record<string, unknown> | undefined): Array<{ label: string; value: string }> {
  if (!metadata) return [];
  const items: Array<{ label: string; value: string }> = [];
  const registrationNumber = textValue(metadata.registration_number);
  const transactionNumber = textValue(metadata.transaction_number);
  if (registrationNumber) items.push({ label: 'Registration no.', value: registrationNumber });
  else if (transactionNumber) items.push({ label: 'Transaction no.', value: transactionNumber });

  const executionDate = textValue(metadata.executed_date);
  const registrationDate = textValue(metadata.registration_date);
  if (executionDate) items.push({ label: 'Execution date', value: executionDate });
  else if (registrationDate) items.push({ label: 'Registration date', value: registrationDate });

  const identifiers = [
    ['Survey', metadata.survey_number],
    ['Plot', metadata.plot_number],
    ['Site/flat', metadata.site_flat_number],
  ].flatMap(([label, value]) => {
    const text = textValue(value);
    return text ? [`${label} ${text}`] : [];
  });
  if (identifiers.length) items.push({ label: 'Property', value: identifiers.join(' · ') });

  const vendors = partyNames(metadata.vendors);
  const purchasers = partyNames(metadata.purchasers);
  if (vendors.length || purchasers.length) {
    const value = vendors.length && purchasers.length
      ? `${vendors.join(', ')} → ${purchasers.join(', ')}`
      : [...vendors, ...purchasers].join(', ');
    items.push({ label: 'Parties', value });
  }
  return items;
}

function textValue(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value).trim()
    : '';
}

function partyNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(party => typeof party === 'string'
    ? party.trim()
    : String((party as any)?.entity_name || (party as any)?.name || '').trim()).filter(Boolean);
}
