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
  title_chain_status?: string | null;
  log?: string[];
  results?: any[];
  errors?: any[];
  needs_action?: any[];
  files?: { doc_id: string; original_name: string; status: string; document_type: string }[];
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

export interface AgentCheck {
  rule?: string;
  result?: string;
  note?: string;
}

export interface AgentMissingDoc {
  document_type: string;
  reason?: string;
  required_for_transaction?: number;
  for_transaction?: number;
}

export interface AgentTransaction {
  index: number;
  date?: string | null;
  type?: string | null;
  parties?: string | null;
  property?: string | null;
  registration_reference?: string | null;
  explanation?: string | null;
  status?: string | null;
  finding?: string | null;
  checks?: AgentCheck[];
  evidence_used?: string[];
  missing_documents?: AgentMissingDoc[];
}

export interface AgentIdentity {
  identity?: Record<string, unknown>;
  evidence?: { field?: string; value?: string; doc_id?: string }[];
  summary?: string;
  unresolved?: string[];
}

export interface AgentResult {
  case_id?: string;
  overall_status?: string;
  headline?: string;
  report?: string;
  findings?: string[];
  property_identity?: AgentIdentity | null;
  title_chain?: { transactions?: AgentTransaction[]; title_story?: string; unresolved?: string[] } | null;
  transactions?: AgentTransaction[];
  missing_documents?: AgentMissingDoc[];
  recommendation?: string;
  updated_at?: string;
}

export interface AgentState {
  case_id: string;
  status: string;
  stage?: string | null;
  paused_transaction?: number | null;
  next_action?: string | null;
  missing_documents?: AgentMissingDoc[];
  memory?: Record<string, unknown> | null;
  result?: AgentResult | null;
}

export interface TitleChainEntry {
  tx_id?: string;
  sequence?: number;
  document_type?: string | null;
  transaction_type?: string | null;
  executed_date?: string | null;
  registration_number?: string | null;
  registration_date?: string | null;
  vendors?: any[];
  purchasers?: any[];
  survey_number?: string | null;
  plot_number?: string | null;
  site_flat_number?: string | null;
  property_location?: string | null;
  market_value?: string | null;
  consideration?: string | null;
  schedule_property?: string | null;
  conveyed_portion?: string | null;
  source_doc_ids?: string[];
  inferred?: boolean;
  uncertainty?: string[];
  transaction_index?: number | null;
  execution_date?: string | null;
  registration_reference?: string | null;
  parties?: any;
  financials?: any;
  property_details?: any;
  source?: string;
  chain_role?: string;
  is_sale_deed_entry?: boolean;
  is_title_transfer?: boolean;
  is_agreement_to_sell?: boolean;
  portion?: string | null;
  share_fraction?: string | null;
  property_identity?: string | null;
  explanation?: string | null;
}

export interface VerificationItem {
  field?: string;
  sd_value?: unknown;
  ec_value?: unknown;
  khata_value?: unknown;
  status: "VERIFIED" | "NOT_VERIFIED" | "N/A" | string;
  notes?: string;
}

export interface AgentReport {
  status: string;
  stage?: string | null;
  property_identity?: unknown;
  title_chain_graph?: string;
  title_chain?: unknown;
  paused_transaction?: number | null;
  next_action?: string | null;
  missing_documents?: AgentMissingDoc[];
  overall_status?: string | null;
  headline?: string;
  report?: string;
  findings?: string[];
  transactions?: AgentTransaction[];
  updated_at?: string | null;
  recommendation?: string;
}

export interface CaseResults {
  case: {
    case_id: string;
    status: string;
    total_docs: number;
    completed_docs: number;
    failed_docs: number;
    verification_status?: string | null;
    verdict?: string | null;
    created_at?: string;
    updated_at?: string;
  };
  documents: any[];
  needs_action?: any[];
  agent: AgentReport;
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

  async skipAgentTransaction(caseId: string, txRef: string): Promise<{ case_id: string; status: string }> {
    return request(`/api/results/${caseId}/agent/skip/${txRef}`, { method: "POST" });
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

  async analyze(caseId: string): Promise<{ case_id: string; status: string }> {
    return request(`/api/results/${caseId}/analyze`, { method: "POST" });
  },
};
