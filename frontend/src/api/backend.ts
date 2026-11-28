const TOKEN_KEY = "cleartitle_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export interface HealthStatus {
  status: string;
  sarvam_key: boolean;
  openai_key: boolean;
  gemini_key: boolean;
  agent_provider: string;
  agent_provider_key: boolean;
  max_upload_size_mb?: number;
}

export interface AuthUser {
  id: string;
  email: string;
  full_name?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface UploadResponse {
  case_id: string;
  files: { doc_id: string; original_name: string; saved_path: string; size_kb: number }[];
}

export interface ProcessResponse {
  status: string;
  mode?: string;
}

export interface StatusResponse {
  status: string;
  progress?: number;
  completed_docs?: number;
  total_docs?: number;
  failed_docs?: number;
  verification_status?: string | null;
  verdict?: string | null;
  log?: string[];
  errors?: any[];
  needs_action?: any[];
  files?: { doc_id: string; original_name: string; status: string; document_type: string; error?: string }[];
}

export interface CaseListItem {
  id: string;
  status: string;
  completed_docs: number;
  total_docs: number;
  failed_docs?: number;
  verification_status?: string | null;
  verdict?: string | null;
  created_at?: string;
}

export interface CasesResponse {
  cases: CaseListItem[];
  total: number;
}

export interface OcrDocText {
  doc_id: string;
  doc_index: number | null;
  filename: string | null;
  document_type: string | null;
  status: string | null;
  total_pages: number | null;
  full_text: string;
  available: boolean;
}

export interface OcrTextResponse {
  case_id: string;
  documents: OcrDocText[];
}

export interface AgentMissingDoc {
  document_type: string;
  reason?: string;
  for_transaction?: string;
}

export interface AgentReport {
  status: string;
  next_action?: string | null;
  property_identity?: unknown;
  title_chain_graph?: string;
  title_chain?: unknown;
  missing_documents?: AgentMissingDoc[];
}

export interface CaseResults {
  case: {
    case_id: string;
    status: string;
    total_docs: number;
    completed_docs: number;
    failed_docs: number;
    created_at?: string;
    updated_at?: string;
  };
  documents: any[];
  needs_action?: any[];
  agent: AgentReport;
}

// -- Title verification --------------------------------------------------------

export type VerificationRunStatus = "running" | "done" | "incomplete" | "error";
export type ReportOpinion = "CLEAR" | "CLEAR_SUBJECT_TO" | "NOT_CLEAR";

export interface VerificationRun {
  id: string;
  kind: "full" | "incremental";
  status: VerificationRunStatus;
  error?: string | null;
  usage?: Record<string, number> | null;
  started_at: string;
  finished_at?: string | null;
}

export interface ChainTransaction {
  transaction_type: string;
  transaction_number?: string | null;
  survey_number?: string | null;
  executed_date?: string | null;
  registration_date?: string | null;
  transferors: string[];
  transferees: string[];
  evidence_status?: string | null;
  summary_points?: string[];
  source_refs?: { doc_id: string; filename: string }[];
}

export type TransferResult = "verified" | "verified_with_concerns" | "documents_missing" | "defective";
export type Severity = "high" | "medium" | "low";

/** A document that proves part of a transfer (or of the property today). */
export interface ProofDocument {
  name: string;
  proves: string;
  status: "found" | "missing";
  request_id?: string | null;
}
export interface Concern { severity: Severity; text: string }

/** One transfer and, once verified, its whole record. ``result`` is worked out by the backend. */
export interface VerificationTransfer {
  id: string;
  origin: "phase_a" | "verification";
  transaction: ChainTransaction;
  added_because?: { note: string } | null;
  property?: { survey?: string | null; extent?: string | null; type: string } | null;
  connects?: { ok: boolean; note: string } | null;
  documents: ProofDocument[];
  concerns: Concern[];
  summary?: string | null;
  result: TransferResult | null;
  before_root: boolean;
}

export type SectionName = "encumbrances" | "revenue_records" | "tax_and_approvals";
export interface PropertySection { note: string; documents: ProofDocument[]; concerns: Concern[]; ok: boolean }

/** A document asked of the buyer; filed and closed by the backend. */
export interface VerificationRequest {
  id: string;
  document: string;
  reason: string;
  needed_for: string[];
  status: "open" | "received" | "settled";
  doc_id?: string | null;
}
export interface VerificationDocument {
  doc_id: string;
  filename: string;
  document_type: string;
  examined: boolean;
  examination_error?: string | null;
  examined_summary?: string | null;
}

export interface VerificationCaseFile {
  transfers: VerificationTransfer[];
  property_today: Record<SectionName, PropertySection | null>;
  requests: VerificationRequest[];
  documents: Record<string, VerificationDocument>;
}

/** The advocate-style Report of Investigation of Title. Reports saved before 2026-11-24
 * carry only the opinion and reasons; their other fields are empty. */
export interface DueDiligenceReport {
  version: number;
  opinion: ReportOpinion;
  reasons: string[];
  title_holders?: string[];
  property_description?: string | null;
  boundaries?: { east?: string | null; west?: string | null; north?: string | null; south?: string | null };
  documents?: { doc_id: string; date: string; nature: string }[];
  document_details?: { doc_id: string; text: string }[];
  history?: string[];
  certificate?: string | null;
  documents_required?: { document: string; reason: string }[];
  prepared_on?: string | null;
  changes: string[];
}

export interface VerificationState {
  case_id: string;
  run: VerificationRun | null;
  case_file: VerificationCaseFile | null;
  report: DueDiligenceReport | null;
}

export interface VerificationEvent {
  id: number;
  run_id: string;
  kind: string;
  text: string;
  ref?: string | null;
  created_at: string;
}

async function apiError(response: Response, fallback = "Request failed"): Promise<string> {
  const text = await response.text();
  if (!text) return fallback;
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ");
    return data.message || data.detail || fallback;
  } catch {
    return text;
  }
}


async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const body = opts.body;
  if (body && !(body instanceof FormData) && typeof body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

export const API = {
  async health(): Promise<HealthStatus> {
    try {
      const r = await fetch("/health");
      if (!r.ok) return { status: "error", sarvam_key: false, openai_key: false, gemini_key: false, agent_provider: "openai", agent_provider_key: false };
      return r.json();
    } catch {
      return { status: "error", sarvam_key: false, openai_key: false, gemini_key: false, agent_provider: "openai", agent_provider_key: false };
    }
  },

  async register(email: string, password: string, fullName?: string): Promise<AuthResponse> {
    return request<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName || null }),
    });
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    return request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async me(): Promise<AuthResponse> {
    return request<AuthResponse>("/api/auth/me");
  },

  async upload(files: File[], slots?: string[]): Promise<UploadResponse> {
    const fd = new FormData();
    files.forEach((f, i) => {
      fd.append("files", f);
      if (slots) fd.append("slots", slots[i] ?? "");
    });
    return request<UploadResponse>("/api/upload", { method: "POST", body: fd });
  },

  async uploadMore(caseId: string, files: File[]): Promise<UploadResponse> {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    return request<UploadResponse>(`/api/case/${caseId}/upload`, { method: "POST", body: fd });
  },

  async process(caseId: string): Promise<ProcessResponse> {
    return request<ProcessResponse>(`/api/process/${caseId}`, { method: "POST" });
  },

  async status(caseId: string): Promise<StatusResponse> {
    try {
      return await request<StatusResponse>(`/api/status/${caseId}`);
    } catch {
      return { status: "unknown" };
    }
  },

  async retry(caseId: string) {
    return request(`/api/retry/${caseId}`, { method: "POST" });
  },

  async skipDoc(caseId: string, docId: string) {
    return request(`/api/case/${caseId}/doc/${docId}/skip`, { method: "POST" });
  },

  async replaceDoc(caseId: string, docId: string, file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/api/case/${caseId}/doc/${docId}/replace`, { method: "POST", body: fd });
  },

  async deleteCase(caseId: string) {
    return request(`/api/case/${caseId}`, { method: "DELETE" });
  },

  async link(caseId: string): Promise<{ case_id: string; linked: boolean; already?: boolean }> {
    return request(`/api/case/${caseId}/link`, { method: "POST" });
  },

  async listCases(): Promise<CasesResponse> {
    try {
      return await request<CasesResponse>("/api/cases");
    } catch {
      return { cases: [], total: 0 };
    }
  },

  async getResults(caseId: string): Promise<CaseResults> {
    return request<CaseResults>(`/api/results/${caseId}`);
  },

  async getOcr(caseId: string): Promise<OcrTextResponse> {
    return request<OcrTextResponse>(`/api/results/${caseId}/ocr`);
  },

  async buildChain(caseId: string): Promise<{ case_id: string; status: string }> {
    return request(`/api/results/${caseId}/chain`, { method: "POST" });
  },

  async startVerification(caseId: string, fresh = false): Promise<{ case_id: string; status: string }> {
    return request(`/api/verify/${caseId}?fresh=${fresh}`, { method: "POST" });
  },

  async getVerification(caseId: string): Promise<VerificationState> {
    return request<VerificationState>(`/api/verify/${caseId}`);
  },

  async getVerificationEvents(caseId: string, after: number): Promise<{ events: VerificationEvent[] }> {
    return request(`/api/verify/${caseId}/events?after=${after}`);
  },

  /** Downloads the latest report as a PDF file. */
  async downloadReport(caseId: string): Promise<void> {
    const headers = new Headers();
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const r = await fetch(`/api/verify/${caseId}/report.pdf`, { headers });
    if (!r.ok) throw new Error(await apiError(r, "Could not download the report"));
    const url = URL.createObjectURL(await r.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `ClearTitle-report-${caseId}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  },

  async uploadForRequisitions(caseId: string, uploads: { requisitionId: string; file: File }[]) {
    const fd = new FormData();
    uploads.forEach(({ requisitionId, file }) => {
      fd.append("files", file);
      fd.append("requisition_ids", requisitionId);
    });
    return request(`/api/verify/${caseId}/requisitions/batch-upload`, { method: "POST", body: fd });
  },
};
