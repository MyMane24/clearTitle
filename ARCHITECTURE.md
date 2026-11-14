# ClearTitle — System Architecture & Runtime Flow

ClearTitle verifies Karnataka property titles. The user uploads scanned PDFs; a six-stage
Celery pipeline turns each PDF into structured data; then a tool-calling LLM agent builds the
title chain (Phase A) and verifies each transaction against its own documents (Phase B),
pausing to ask for missing evidence instead of guessing. A final verification report can be
generated and downloaded as a PDF.

---

## 1. Runtime components

| Component | Runs as | Job |
|---|---|---|
| **API** | FastAPI + uvicorn, port `8000` | HTTP endpoints, saves uploads, fires Celery tasks, serves the built SPA |
| **Worker** | Celery worker (`--concurrency=2`) | Runs the 6 document stages, finalize, and the agent |
| **Redis** | `redis:7-alpine` | Celery broker + result backend, case live state, pipeline locks, logs |
| **MySQL 8** | `mysql:8.0`, host port `3307` | Source of truth: cases, documents, chain, results, memory, evidence ledger |
| **phpMyAdmin** | `phpmyadmin`, port `8080` (localhost only) | DB inspection |

`docker-compose.yml` starts all of these. The frontend (`React 19 + Vite`) is built into the
image and served by FastAPI; use the Vite dev server (port `3000`) while iterating.

```
Browser / SPA
   │  REST /api/*
   ▼
FastAPI (routers/) ── writes ──▶ MySQL (repositories/)  ◀── reads ── Celery worker (workers/)
   │                                        ▲                          │
   └──── enqueues tasks ──▶ Redis (broker) ──┴──── stage + agent state ─┘
```

---

## 2. Where data lives

### MySQL tables (`backend/database/migrations.py`)

| Table | Holds |
|---|---|
| `users` | Accounts (email + password hash, or Google) |
| `cases` | One row per case: `status`, doc counts, `verification_status`, `verdict`, `agent_status`, log JSON |
| `documents` | One row per PDF: `doc_id`, `status`, `document_type`, `merged_ocr_text`, `structured_data`, `summary`, `file_paths` JSON, token/cost fields, `error`, `retry_count` |
| `title_chains` | Phase A output: `property_identity`, `title_chain_graph`, `detailed_chain`, `chain`, `phase_a_hash` |
| `case_results` | Per case: `case_result` = JSON array of transaction verification results, `final_report` = report document |
| `case_memory` | Agent checkpoint (`case_memory` LONGTEXT): stage, paused tx, missing docs, completed/pending tx ids |

### Redis keys

| Key | Holds |
|---|---|
| `case:{id}:meta` | Live status + total docs |
| `case:{id}:files` | Uploaded file manifest (doc_id → path, name) |
| `case:{id}:log` | Last ~200 user-visible pipeline log lines |
| `case:{id}:pipeline_lock`, `case:{id}:agent_lock`, `case:{id}:final_report_lock` | Mutual exclusion |
| Celery keys | Task queue and chord results |

### Filesystem (`outputs/<case_id>/`)

```
raw/            original PDFs (uploaded)
preprocessed/   <doc_id>_prep.pdf        (cleaned pages)
ocr_raw/        <doc_id>_chunks.json     (raw Sarvam chunks)
                <doc_id>_merged.json     (merged full text + page count)
structured/     <doc_type> JSON per document (copy; MySQL is canonical)
final_report/   title-verification-report.pdf
```

`uploads/` is legacy and not written by current code.

---

## 3. Full flow at a glance

```
POST /api/upload ──▶ cases + documents rows, outputs/<case>/raw/
POST /api/process/{id} ──▶ Celery chord
      └─ per document: preprocess → OCR → merge → classify → structure → persist
                              (all docs done)
                                    ▼
                          finalize_case_task
                                    ▼
                          run_case_analysis_task (the agent)
             Phase A: build title chain ──▶ title_chains
             Phase B: verify each transaction ──▶ case_results
                    ├─ all settled ──▶ done
                    └─ evidence missing ──▶ paused (user uploads more)
GET /api/results/{id} ──▶ stored chain + per-transaction results
POST /api/results/{id}/verification-report/generate ──▶ report JSON + PDF
```

---

## 4. Step-by-step

### Step 1 — Upload

`POST /api/upload` (multipart: `files`, optional `slots`)

- **Input:** one or more PDFs (≤ `MAX_UPLOAD_SIZE_MB`, default 100 MB each).
- **Does:** rejects non-PDFs and oversized files, creates `case_id` (8-char UUID prefix,
  e.g. `8A14D132`), saves each file as `outputs/<case_id>/raw/<name>`, assigns
  `DOC_001`, `DOC_002`…
- **Output:** `{ case_id, files: [{ doc_id, original_name, saved_path, size_kb, slot }] }`
- **Database:** inserts `cases` (status `uploaded`, owner = current user or NULL) and one
  `documents` row per file (status `uploaded`); Redis `case:{id}:meta`, `:files`, `:log`.

### Step 2 — Start processing

`POST /api/process/{case_id}`

- **Input:** case id.
- **Does:** checks ownership, takes `pipeline_lock`, sets status `processing`, then builds a
  Celery **chord**: one chain of 6 tasks per not-yet-structured document, with
  `finalize_case_task` as the callback.
- **Output:** `{ case_id, status: "processing", mode: "celery" }` (immediate; work is async).
- **Database:** `cases.status = processing`; Redis status + log.

Poll `GET /api/status/{case_id}` for live status, per-document state, `needs_action`
(replace/skip requests), and the log. MySQL is the source of truth for this payload.

### Steps 3–8 — Per-document pipeline

Each document runs these six Celery tasks in order. They are idempotent (each is skipped if
its completion state is already stored) and auto-retry up to 5 times with backoff.

| # | Stage | Input | Does | Output | Database write |
|---|---|---|---|---|---|
| 3 | **preprocess** | raw PDF | OpenCV: deskew, denoise, CLAHE contrast, sharpen; re-render PDF | `preprocessed/<doc_id>_prep.pdf` (falls back to the raw PDF on failure) | `documents.status = preprocessed`, `file_paths.preprocessed` |
| 4 | **OCR** | preprocessed PDF | Sarvam OCR; documents >10 pages are split into 10-page overlapping chunks, 8 parallel workers, 3 retries. All-chunks-failed → error; “insufficient credits” → non-retryable error | `ocr_raw/<doc_id>_chunks.json` (per-chunk text/status) | `documents.status = ocr_done`, `file_paths.ocr_chunks` |
| 5 | **merge** | chunk JSON | Merge chunks, de-duplicate overlap, take page count from the physical PDF | `ocr_raw/<doc_id>_merged.json` (`full_text`, `total_pages`) | `status = merged`, `merged_ocr_text`, `page_count` |
| 6 | **classify** | merged OCR text (bounded prefix) | One LLM call → document type (SALE_DEED, EC, RTC_PAHANI, …). Unsupported/irrelevant type → `classification_failed` and a user action request | document type + analytics | `status = classified`, `document_type`, token/cost fields |
| 7 | **structure** | full OCR + the one schema matching the type | One LLM call extracts **all** fields into that schema (no schema → open extraction, nothing dropped) | `structured_data` + short `summary` | `status = structuring`, `structured_data`, `summary`, analytics |
| 8 | **persist** | `structured_data` from MySQL | Normalizes encumbrance certificates, writes a JSON artifact | `structured/…json` | `status = structured` (+ `file_paths.structured`), `page_count` |

**User-in-the-loop:** a `classification_failed` or `failed` document appears in `needs_action`.
`POST /api/case/{id}/doc/{doc_id}/replace` (new PDF) or `/skip` resolves it, then
`POST /api/retry/{case_id}` re-runs only the failed documents from their last checkpoint.

### Step 9 — Finalize (chord callback)

`finalize_case_task`

- **Input:** chord results + case id.
- **Does:** recomputes case status (`complete` / `partial` / `failed`), writes a completion log,
  releases `pipeline_lock`, and decides whether to run the agent — only if some document is
  `structured` or the case has pending/paused verification.
- **Output:** agent task queued (`run_case_analysis_task`).
- **Database:** `cases.status`, `completed_docs`, `failed_docs`.

### Step 10 — Agent, Phase A: build the title chain

- **Input:** all `structured` documents (id, filename, summary; summaries are LLM-generated once
  and stored in `documents.summary` if missing).
- **Does:** a bounded tool loop (`list_documents`, `get_document_text`, `save_phase_a_result`,
  `finish`) reads documents and produces: property identity, the ordered chain of transactions,
  the property graph, and a detailed chain. The application assigns the transaction ids
  (`PA-TC-0001`, …) — never the model.
- **Output:** saved Phase A result.
- **Database:** `title_chains` upsert (`property_identity`, `title_chain_graph`,
  `detailed_chain`, `chain`, `phase_a_hash`); `case_memory` stage progress.

Phase A is reused on every later run and is only rebuilt for a case with no saved transaction
results (a silent rebuild would orphan persisted history).

### Step 11 — Agent, Phase B: verify each transaction

Transactions are verified sequentially, earliest link first. For each one the agent runs a
fresh bounded tool loop (`CLEARTITLE_VERIFY_MODEL_CALL_BUDGET`, default 16 model calls) with:

- **Input:** the current transaction, the saved state/report excerpt of every earlier link
  (upstream context, never used as evidence), and its own evidence scope.
- **Tool order enforced by the application:** `record_evidence_requirements` →
  `select_documents` (only its own instrument plus documents it uniquely depends on) →
  `get_document_text` (must read each selected document end to end) → optionally
  `record_observation` → `save_transaction_result` (or `request_missing_documents`).
- **Enforced invariants:** no citation may point at a document that was not fully read;
  a “pending” result must name at least one concrete document; encumbrance certificates are
  chain context only, never verification evidence.
- **Output per transaction:** `status` (`VERIFIED_WITH_AVAILABLE_EVIDENCE` /
  `ISSUES_IDENTIFIED` / `PENDING_NOT_VERIFIED` / `INCONCLUSIVE`), a markdown report with a
  Conclusion, cited documents, reviewed document ids, and the requested documents.
- **Database:** appended/updated in `case_results.case_result` (JSON array keyed by `tx_id`);
  `case_memory` updated after every link; `cases.verification_status` + `verdict` mirrored.

Already-terminal transactions are skipped on resume. When an upstream link changes state,
downstream reports are textually refreshed — not re-verified.

### Step 12 — Pause, evidence upload, resume

- A transaction that lacks evidence saves a `PENDING_NOT_VERIFIED` result, records
  `paused_transaction`, the missing documents and the open requirements in `case_memory`, then
  the agent stops with status `paused`. It never fabricates a success.
- The dashboard shows the request. The user uploads more PDFs with
  `POST /api/case/{id}/upload` (optional `transaction_id` for a skipped transaction) or skips
  the transaction with `POST /api/results/{id}/agent/skip/{tx_ref}`.
- New uploads go through the same six stages; finalize matches them to open requirements
  (`MATCHED` / `PARTIALLY_MATCHED` / `AMBIGUOUS` / `NOT_MATCHED`), then the agent resumes:
  paused transaction → `resume_paused_transaction`, selected skipped transaction →
  `retry_skipped_transaction`, otherwise a normal run.

### Step 13 — Results

`GET /api/results/{case_id}`

- **Input:** case id.
- **Output:** `{ case, documents, needs_action, agent }` where `agent` contains the Phase A
  chain, the list of per-transaction results, overall status, current stage, paused
  transaction, next action and skipped tx ids.
- **Database:** reads `cases`, `documents`, `title_chains`, `case_results`, `case_memory`
  (Redis is not used for results).

Other reads: `GET /api/status/{id}` (progress), `GET /api/results/{id}/ocr` (raw text),
`GET /api/case/{id}/doc/{doc_id}/pdf` (original PDF).

### Step 14 — Verification report

`GET /api/results/{case_id}/verification-report`
→ readiness gate (`final_ready`, blockers) plus the stored report and whether it is stale.

`POST /api/results/{case_id}/verification-report/generate` (`report_type`: `FINAL` or `PRELIMINARY`)

- **Input:** case id + report type.
- **Gate:** `FINAL` is blocked while any chain transaction is missing, pending, awaiting
  documents, inconclusive, or skipped (`409` with blockers). `PRELIMINARY` is always allowed and
  states what is unverified.
- **Does:** takes `final_report_lock`, assembles facts from the chain and results, has the LLM
  write the narrative (validated against a fixed schema), raises the verdict if the evidence
  floor is worse, renders the PDF.
- **Output:** report document + `title-verification-report.pdf`.
- **Database:** `case_results.final_report` (with `source_case_result_hash` for staleness);
  file at `outputs/<case_id>/final_report/title-verification-report.pdf`.
  Download: `GET /api/results/{case_id}/verification-report/pdf`.

---

## 5. Status reference

| Field | Values |
|---|---|
| `documents.status` | `uploaded` → `preprocessed` → `ocr_done` → `merged` → `classified` → `structuring` → `structured`; or `failed`, `classification_failed`, `skipped`, `pending_retry` |
| `cases.status` | `uploaded`, `processing`, `complete`, `partial`, `failed` |
| `cases.agent_status` / `case_memory.status` | `running`, `paused`, `done`, `error` |
| Transaction result `status` | `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `PENDING_NOT_VERIFIED`, `INCONCLUSIVE` |
| `cases.verification_status` / `verdict` | `complete` / `paused` / `error`; verdict `CLEAR_TITLE`, `ATTENTION_REQUIRED`, `N/A` |

---

## 6. Non-negotiable guarantees (enforced in code, tested)

1. A result is rejected unless every selected document was read end to end in that session.
2. A transaction may only select its own instrument and documents it uniquely depends on;
   upstream recitals defer to the verified upstream result.
3. Workflow order is fixed: requirements → list → select → read → save.
4. Every citation points at a fully read case document.
5. `PENDING_NOT_VERIFIED` requires at least one concrete requested document; failures surface as
   `error`, never as fabricated success.
6. The application never keyword-matches or suggests documents — the agent decides from
   summaries and document text alone.
7. Encumbrance certificates take part in the chain but are never verification evidence.

---

## 7. Where to change what

| Change | File |
|---|---|
| HTTP endpoint | `backend/routers/` |
| Business logic | `backend/services/` |
| Stage behaviour / Celery wrappers | `backend/workers/stages.py`, `workers/tasks.py` |
| Agent tools, gates, schemas | `backend/services/agent_tools.py`, `agent_schemas.py`, `agent_runtime.py` |
| Prompts / agent playbooks | `backend/prompts/*.txt`, `backend/skills/*/skill.md` |
| SQL | `backend/database/repositories/` |
| Schema | `backend/database/migrations.py` (additive, idempotent) |
| Env vars | `backend/config.py` + `.env.example` |
| Dashboard UI | `frontend/src/dashboard/` |
