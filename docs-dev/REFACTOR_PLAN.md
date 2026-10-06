# clearTitle — Pipeline Simplification & Refactor Plan

> Status: Approved plan (v1)
> Scope: Extraction-only pipeline, Title Chain, Cross-Document Verification, User Auth
> Target: Simpler backend, leaner DB, minimal UI. No pipeline-logic regression.

---

## 0. Executive Summary

The current system is feature-heavy: it runs a 6-stage per-document extraction chain,
then per-document verification, a RAG/statute store, human-feedback learning, a
self-critique pass, risk scoring, and an LLM "legal opinion" report. Most of this is
no longer wanted.

After this refactor the product does exactly four things:

1. **Data Extraction** — structured JSON from each uploaded document (no per-doc verification).
2. **Title Chain Establishment** — LLM matches the Sale Deed property schedule to the right EC ledger entries; entries are sorted chronologically into a title chain.
3. **Cross-Document Verification** — LLM verifies each Sale Deed field (source of truth) against the EC (primary); field-by-field VERIFIED / NOT_VERIFIED / N/A.
4. **User Authentication** — Email + Password (hashed), scan history, gated full report.

Both title-chain matching and cross-document verification are **LLM-driven** (single
semantic pass each), because the hard part — comparing property schedules and verifying
fields across Kannada/English documents — needs semantic understanding, not string
matching. The LLM returns only structured, minimal output (matched EC entry numbers /
field-level statuses) and deterministic code does the rest (sorting, chain construction,
persistence). This keeps LLM usage small, focused, and easy to make correct.

---

## 1. What Is Being Removed

### 1.1 Backend modules (delete entirely)

| Feature | Files / symbols |
|---|---|
| RAG / statute store | `backend/ai/rag/` (statute_rag.py, vector_store.py), `initialize_statute_store()` in `main.py`, `vs.search` usage, `retrieve_corrections()` / `format_few_shot_examples()` in `classifier.py`, `qdrant-client` dep |
| Per-document verification | `VERIFICATION_NOTES_SCHEMA` + `verification_notes` in every schema in `ai/prompts/schemas/static.py`, `ai/prompts/verification.py`, "PART 2 — VERIFY" in `ai/prompts/extraction.py`, `verification_notes` handling in `workers/stages.py` |
| Human feedback module | `application/verification/feedback.py`, `store_feedback()`, `POST /api/verify/{id}/feedback`, `GET /api/verify/learnings/stats`, `human_feedback` table |
| Deterministic rule-based checks | `ai/verification/deterministic/`, `ai/verification/base.py`, `ai/scoring/risk_scorer.py`, `ai/critique/self_critique.py`, the deterministic + legal-opinion logic in `ai/verification/cross_doc.py` |
| Observability extras | `observability/` (tracing/metrics/traced_stage/logging) → collapsed to `logger.py`; remove `traced_stage` decorators; drop prometheus/otel |
| Duplicate / dead code | `backend/locking/` (dup of `infrastructure/locking/`), `backend/shared/`, `backend/utils/file_utils.py` (dup), `ai/prompts/schemas/cross_doc.py`, `analytics_repo.py`, `application/verification/reporting.py` + `runner.py` (replaced) |

### 1.2 Database objects to drop

- Tables: `human_feedback`, `llm_calls`, `cross_doc_verifications` (replaced by `verification_results`), view `daily_cost_summary`.
- Columns: `cases.pipeline_logs`, `cases.verdict`, `cases.verification_status`; `documents.verification_notes`, `documents.raw_ocr_path`, `documents.input_tokens/output_tokens/cost_usd/latency_ms/model_used`, `documents.trace_id`, `documents.stage_started_at/stage_completed_at`.

### 1.3 UI outputs removed

The user should only ever see: **Uploaded Documents (extracted details), Title Chain, Verification Results, Case History.**

Removed from UI:
- OCR Raw Output (History "OCR" tab)
- Files View (History "Files" tab)
- Processing Logs (dashboard log box + History "Logs" tab)
- Bundles (History "Bundle" tab, API `bundle`)
- Human Feedback Data (report "Human Review" tab, learnings counter)
- Old report tabs: Per Document, Missing Documents, Final Report (legal opinion), risk score, findings drawer
- Token/cost metrics on the results page
- `pdfReport.ts` + `jspdf`/`jspdf-autotable` (old-format PDF)

---

## 2. New End-to-End Flow

```
Home Page → Run Scan
  → Upload PDFs (anonymous allowed)
  → Pipeline (Celery):
       per doc: preprocess → OCR → merge → classify → structure → persist
                (NO per-doc verification)
       chord callback (finalize):
          recompute case status
          build_title_chain(case_id)   ← LLM matches SD schedule → EC entry numbers
          run_verification(case_id)    ← LLM: SD = source of truth, EC primary
  → Result Generation
  → Results page:
       [1] Uploaded Documents + Extracted Details
       [2] Title Chain
       [3] Verification Results
  → Not logged in  : gated preview (limited SD + EC details, verification status summary)
  → Sign in / up   : case linked to account → full report + case history unlock
```

Title-chain + verification now run **automatically** on finalize. The manual "Agentic
Verification" button is removed; the verify endpoint becomes an optional re-run.

---

## 3. New Backend Structure (~45 files → ~23)

```
backend/
├── main.py                # FastAPI app, lifespan (init DB only), routers, SPA mount
├── config.py              # all env config (moved from app/config.py)
├── constants.py           # statuses + doc-type constants
├── logger.py
├── celery_app.py
├── database/
│   ├── connection.py      # MySQL pool (unchanged)
│   ├── migrations.py      # new DDL (users, cases, documents, title_chains, verification_results)
│   └── repos.py           # merged: cases / documents / users / title_chain / verification
├── routers/
│   ├── __init__.py
│   ├── auth.py            # register / login / me / link-case
│   ├── cases.py           # upload / process / status / history / upload-more / delete / replace-skip
│   └── results.py         # documents / preview / title-chain / verification (gated)
├── services/
│   ├── auth.py            # bcrypt hashing + JWT issue/verify + ownership guard
│   ├── extract.py         # 6-stage logic moved from workers/stages.py + pipeline/helpers.py
│   ├── classifier.py      # classify_document only (few-shot/RAG removed)
│   ├── schemas.py         # lazy schema registry (§7)
│   ├── title_chain.py     # LLM: SD schedule vs EC entries → matched entry numbers → chain (§5)
│   ├── verify.py          # LLM: field-level cross-doc verification (§6)
│   └── results.py         # preview + full-result payload builders
├── integrations/
│   ├── sarvam_ocr.py      # OCR client + chunking + retry
│   ├── ocr_merger.py      # merge_chunked_outputs
│   ├── preprocessor.py    # preprocess_pdf
│   ├── llm.py             # gemini + groq executors, model_router, rate limiter (no DB writes)
│   └── redis_lock.py      # RedisLock + state-store helpers (file registry, status)
├── workers/
│   ├── stages.py          # 6 stage classes (verification_notes removed)
│   ├── tasks.py           # celery task wrappers (retry/idempotency folded in)
│   └── finalize.py        # recompute status → chain(title_chain_task → verify_case_task)
└── __init__.py
```

Removed folders: `ai/`, `application/`, `app/`, `domain/`, `infrastructure/`,
`locking/`, `observability/`, `pipeline/`, `shared/`, `utils/`.

**Kept identical (no pipeline-logic impact):** 6-stage chain, model routing/fallback,
retry/idempotency, OCR/integration clients, MySQL pool, storage helpers,
upload/process/status endpoints, Celery/Redis infra.

---

## 4. Database Redesign

New DDL (added to `ensure_tables()`):

```sql
CREATE TABLE users (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,      -- bcrypt
  full_name VARCHAR(128) NOT NULL DEFAULT '',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE cases (
  id VARCHAR(32) NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,             -- NULL = anonymous pre-login scan
  status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
  total_docs INT NOT NULL DEFAULT 0,
  completed_docs INT NOT NULL DEFAULT 0,
  failed_docs INT NOT NULL DEFAULT 0,
  title_chain_status VARCHAR(32) DEFAULT NULL,    -- pending/running/complete/skipped
  verification_status VARCHAR(32) DEFAULT NULL,   -- pending/running/complete
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_user (user_id),
  CONSTRAINT fk_cases_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE documents (    -- Uploaded Documents + Extracted Structured JSON
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(32) NOT NULL,
  doc_id VARCHAR(32) NOT NULL,
  doc_index INT NOT NULL DEFAULT 0,
  filename VARCHAR(512) NOT NULL,
  document_type VARCHAR(128) NOT NULL DEFAULT '',
  page_count INT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
  structured_data JSON NULL,                -- ← the core extraction output
  file_paths JSON NULL,                     -- raw PDF path (re-processing only)
  error TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_case_doc (case_id, doc_id)
);

CREATE TABLE title_chains (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(32) NOT NULL,
  sale_deed_doc_id VARCHAR(32) NULL,
  ec_doc_id VARCHAR(32) NULL,
  source_schedule JSON NULL,                -- SD property schedule used for matching
  matched_transactions JSON NULL,           -- EC entries matched by LLM, chronologically sorted
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_case (case_id)
);

CREATE TABLE verification_results (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(32) NOT NULL,
  source_doc_id VARCHAR(32) NULL,           -- Sale Deed doc
  fields JSON NULL,     -- [{field,status,sd_value,primary_evidence,supporting_evidence[]}]
  summary JSON NULL,    -- {verified_count, not_verified_count, na_count, overall}
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_case (case_id)
);
```

Data mapping: `documents.structured_data` already holds the JSON; old
`cross_doc_verifications.findings` → structured `verification_results.fields`.

---

## 5. Title Chain Establishment (`services/title_chain.py`)

**LLM does the semantic matching; deterministic code does sorting + chain construction.**

1. Load structured docs (`documents` where `status='structured'`).
2. Find **Sale Deed** and **EC**. If either is missing → `title_chain_status='skipped'`
   with a neutral reason ("Sale Deed required" / "EC required"); no error noise in UI.
3. **Inputs built from structured JSON (no raw OCR):**
   - **SD property schedule** (from Sale Deed `structured_data`): survey number,
     CTS number, plot/site/apartment number, extent/measurements, village/hobli/taluk/
     district, boundaries (N/E/W/S), full schedule description.
   - **EC ledger entries** (from EC `structured_data.historical_ledger`): each entry is
     flattened into a compact record carrying its **entry number (`transaction_index`)**,
     `transaction_type`, `execution_date`, `registration_reference`, and its
     `property_details` (survey/CTS/plot numbers, description, measurements, boundaries,
     location).
4. **LLM call — entry selection:**
   - Prompt: *"Here is the correct property schedule from the Sale Deed. Here are all EC
     ledger entries with their entry numbers and property details. Semantically compare
     each entry's property details against the Sale Deed property schedule."*
   - Rules given to the LLM: subdivision/Paiki/Hissa/CTS relationships are **not**
     automatically mismatches; allow Kannada↔English transliteration and spelling/
     formatting variation; treat missing data as unknown, not as a conflict.
   - LLM returns **ONLY the entry numbers** whose property matches the Sale Deed
     schedule (JSON array, e.g. `{"matched_entry_numbers": [3, 7, 12]}`). No prose.
5. **Deterministic chain construction (code):**
   - Take the matched entry numbers → pull the full records from the EC `historical_ledger`.
   - Sort them **chronologically** by `execution_date` / registration date.
   - Build the chain records from those entries (transaction type, parties, consideration,
     registration reference) with the Sale Deed appended as the terminal node.
6. Persist to `title_chains` (`matched_transactions` = sorted matched ledger entries);
   return a timeline for the UI.

Why this design: the LLM solves the only hard part (semantic identity across
transliteration/subdivision variation) with a tiny structured output, and the code keeps
sorting/construction deterministic and correct.

---

## 6. Cross-Document Verification (`services/verify.py`)

**Sale Deed = source of truth. EC = primary verification document. LLM does the
verification reasoning; code shapes + persists the result.**

1. Load structured docs; identify the Sale Deed and every other uploaded doc.
2. **Inputs built from structured JSON:** compact field projection per doc (Sale Deed
   fields, EC ledger + search criteria, and the matching fields from RTC / Mutation /
   PRC / Conversion / Allotment when present).
3. **LLM call — field verification:**
   - Prompt: *"Sale Deed is the source of truth. Compare each Sale Deed field against the
     EC (primary). If a supporting document also matches, list it as supporting evidence."*
   - Rules given to the LLM (exact spec):
     - SD field matches EC → **VERIFIED** (primary evidence = EC).
     - EC available and contradicts SD → **NOT_VERIFIED** (only then is it a failure).
     - EC missing / field not present in SD → **N/A** (neutral, no failure).
     - A supporting doc that matches → `supporting_evidence`. A supporting doc that does
       **not** match → ignore (no failure, no warning).
     - Missing values in secondary documents → no warnings.
     - Tolerate name prefixes (Shri./Smt./M.), Kannada↔English transliteration, and
       formatting variations; a subdivision/Paiki relationship is not a mismatch.
   - LLM returns ONLY a JSON array of field results (no prose):
     ```json
     [
       {"field":"seller_name","status":"VERIFIED","sd_value":"...","primary_evidence":"EC","supporting_evidence":["RTC_PAHANI"]},
       {"field":"survey_number","status":"NOT_VERIFIED","sd_value":"663/1","ec_value":"663/2"},
       {"field":"extent","status":"N/A","reason":"EC does not record extent"}
     ]
     ```
4. **Deterministic code** validates the statuses, computes the summary
   (`{verified_count, not_verified_count, na_count, overall}`), and persists to
   `verification_results.fields` + `summary`.

Field table (each field is projected into the LLM prompt per doc type):

| Field | Sale Deed (source) | EC (primary) | Supporting docs (evidence only, no failure) |
|---|---|---|---|
| Seller Name | `parties.vendors[].entity_name` | ledger `parties.vendors` | RTC owners_col9, Mutation |
| Buyer Name | `parties.purchasers[].entity_name` | ledger `parties.purchasers` | RTC owners_col9, Mutation |
| Property Schedule | `property_schedule` | ledger `property_details` | PRC, RTC land_details |
| Survey Number | `property_schedule.survey_number` | ledger `survey_no` | RTC, Mutation, Conversion, Building License |
| Site Number | apartment/shop/plot no | ledger `plot_no` | Allotment, RERA, PRC |
| Extent / Area | `measurements.*` | ledger `measurements` | RTC extent_details, Conversion |
| Village / Hobli / Taluk / District | `property_schedule.village` + schedule text | `search_criteria.target_*` | RTC `land_details`, Mutation |
| Registration Details | `file_metadata.registration_number/date/office` | ledger `registration_reference` + search period | — |

---

## 7. Schema Loading Optimization (`services/schemas.py`)

Since title-chain and verification now **use the LLM**, only the schemas/fields for the
actually-uploaded document types must be loaded — never the full set.

- Static per-type schema dicts live in one place (moved from `ai/prompts/schemas/static.py`),
  with `verification_notes` blocks **stripped** → smaller schemas → fewer output tokens.
- Expose **lazy loaders**: `load_schema(doc_type)` (used per-document during structuring)
  and `load_schemas_for(doc_types)`.
- Detect uploaded types once from `documents.document_type`
  (`detect_doc_types(case_id)`), then load **only** those schemas.
- Title-chain and verification prompts are built from **compact field projections** of the
  uploaded docs only (never the full schema set, never every supported doc type).
- Extraction prompts embed only the single schema for the document being structured
  (already the case today; keep + formalize).

---

## 8. User Authentication (`services/auth.py`, `routers/auth.py`)

- New deps: `bcrypt`, `PyJWT` (two additions to `requirements.txt`).
- `POST /api/auth/register` `{email, password, full_name}` → creates user (bcrypt hash),
  returns `{token, user}`.
- `POST /api/auth/login` → verifies, returns JWT (exp ~7d).
- `GET /api/auth/me` → current user.
- `POST /api/case/{case_id}/link` → attaches an anonymous case to the logged-in user
  (only if `case.user_id IS NULL`); full report unlocks.
- Ownership guard on all full-result endpoints: `case.user_id == current_user.id` else 403.
- Frontend stores token in `localStorage`; `AuthContext` provides login/register/logout/me.

---

## 9. Result Display (Frontend)

New dashboard results page = **exactly 3 sections, in this order** (user-confirmed):

1. **Section 1 — Uploaded Documents & Extracted Details**
   - Card per uploaded doc: filename, doc type badge, page count.
   - Extracted details table (doc-type-aware): parties, property schedule, survey/CTS
     numbers, area, registration details, dates — rendered from `structured_data` via the
     per-type schema key order.
   - *Pre-login:* only selected Sale Deed + EC cards (limited fields).

2. **Section 2 — Title Chain**
   - Chronological timeline of the EC entries the LLM matched to the Sale Deed schedule:
     entry number, date, transaction type (Sale/Gift/Partition/Mortgage/Release…),
     parties, consideration, registration reference.
   - Sale Deed is highlighted as the terminal node.

3. **Section 3 — Verification Results**
   - Field-by-field status table: `Seller Name ✅ Verified`, `Buyer Name ✅ Verified`,
     `Property Schedule ✅ Verified`, `Survey Number ✅ Verified`, `Extent ✅ Verified`,
     `Registration Details ✅ Verified` (or `⚠ Not Verified` / `N/A (EC required)`).
   - Supporting-evidence chips per verified field.
   - *Pre-login:* only a status summary (e.g., `9/11 fields verified`); the full table is
     locked behind login with a CTA.

- **Case History:** sidebar lists the user's cases (or session cases when anonymous);
  clicking opens the same 3-section view. Upload-more-PDFs is kept.

Frontend file changes:
- New: `auth/AuthContext.tsx`, `auth/AuthPage.tsx`, `dashboard/ResultsView.tsx`,
  `TitleChainView.tsx`, `VerificationResultsView.tsx`, `DocExtractView.tsx`.
- Delete: `VerificationReportView.tsx`, `pdfReport.ts` (+ jspdf deps) unless a simple
  3-section PDF export is requested.
- Slim: `VerificationDashboard.tsx` (remove log box, token/cost metrics, needs-action
  flow, verify button), `HistoryDetail.tsx` (remove bundle/ocr/files/logs tabs),
  `api/backend.ts` (remove `ocrRaw`, `bundle`, `caseFiles`, `verifyPerDoc`,
  `submitFeedback`, `getLearningStats`, `tokenUsage`; add auth + `documents`, `preview`,
  `titleChain`, `verification`, `link` calls).

---

## 10. Phased Execution Order

1. **Remove features** — delete RAG, critique, scoring, deterministic checks, feedback,
   verification_notes (schemas + prompts + stages + executor contracts), old verification
   router endpoints, observability extras, duplicate folders; drop `qdrant-client`.
2. **Database redesign** — new migrations (users, cases.user_id, title_chains,
   verification_results; drop obsolete tables/columns); update `repos.py`.
3. **Backend restructure** — move code into `database/`, `services/`, `integrations/`
   layout; fix imports; keep pipeline logic identical; update `finalize.py` to chain
   title-chain → verification.
4. **Auth service + endpoints + frontend auth.**
5. **Title chain (LLM) builder + endpoint + UI section.**
6. **Cross-doc verification (LLM) engine + endpoint + UI section.**
7. **Schema lazy loading** + extraction output trimmed (no verification_notes).
8. **Frontend rewrite** — 3-section results, gating, slimmed history.
9. **Cleanup + verify** — `ruff check backend` + `npm run lint` (`tsc --noEmit`);
   manual smoke: upload Sale Deed + EC → extraction → title chain → verification → login link.

---

## 11. Open Points (defaults assumed — flag if different)

- Title-chain and verification use **two separate focused LLM calls** (entry selection /
  field verification), each with small structured output. Deterministic code only sorts,
  validates, and persists. No LLM call runs per-field or per-entry.
- LLM prompts must be validated against real docs (Kannada/transliteration/subdivision
  cases) before rollout — same model routing/fallback/rate-limiter as extraction.
- New Python deps added: `bcrypt`, `PyJWT`.
- `observability/` (OpenTelemetry + Prometheus) is dropped to a single `logger.py`.
  If `/metrics` is needed for ops, a thin Prometheus module can be kept.
