# ClearTitle — System Architecture and Design

This document describes the implementation currently in this repository. It covers the high-level architecture, runtime flows, verification-agent behavior, persistence model, and operational status semantics. It is not a legal opinion or a claim that the product determines legal title.

## 1. System purpose and boundaries

ClearTitle accepts property-document PDFs, extracts searchable text and structured fields, then runs a case-level investigation over a saved title chain. The agent assesses each chain transaction against selected uploaded evidence and creates a consolidated report.

The system has two distinct workflows:

1. **Document processing:** upload, preprocess, OCR, merge, classify, structure, persist.
2. **Title investigation:** establish/reuse the property identity and chain, verify transactions, and save the report.

Document extraction success is not title verification. Likewise, an agent run marked `done` means its work loop ended; it does not mean every transaction was verified or that title is legally clear.

## 2. High-level architecture

```text
Browser (React SPA)
       │ HTTP / JSON
       ▼
FastAPI API ───────────── MySQL (durable application state)
       │                         │
       ├── Redis (cache, locks)  └── title/documents/results
       │
       └── enqueue Celery task ──► Redis broker ──► Celery worker
                                                       │
                         ┌─────────────────────────────┼─────────────────────┐
                         ▼                             ▼                     ▼
                  Shared outputs/                 Sarvam OCR           LLM provider(s)
                  PDFs and artifacts              for OCR              classification,
                                                                       extraction, agent
```

In Docker Compose, the API and worker use the same application image and share the `uploads/` and `outputs/` bind mounts. The API serves the built React SPA from `frontend/dist`. MySQL and Redis use Docker named volumes. phpMyAdmin is an optional local database browser.

| Component | Main responsibility | Code location |
|---|---|---|
| React SPA | Upload, processing status, OCR/document results, title chain, verification, case history | `frontend/src/` |
| FastAPI | HTTP API, auth/access checks, queue requests, result assembly, static SPA serving | `backend/main.py`, `backend/routers/` |
| Celery | Long-running document and verification tasks | `backend/celery_app.py`, `backend/workers/` |
| Workflow services | Document pipeline orchestration and ClearTitle agent orchestration | `backend/services/` |
| Integrations | OCR, LLM, Redis, filesystem adapters | `backend/integrations/` |
| Repositories | MySQL reads/writes | `backend/database/repositories/` |
| MySQL | Durable users, cases, document data, title chain, agent memory and results | `backend/database/` |
| Redis | Celery broker/result backend, transient cache/logs, distributed locks | `backend/integrations/redis/` |
| Filesystem | Uploaded PDFs and intermediate/final processing artifacts | `outputs/<case_id>/` |

## 3. Runtime and deployment

`docker-compose.yml` defines five services:

| Service | Purpose | Host access |
|---|---|---|
| `api` | FastAPI plus built React SPA | `http://localhost:8000` |
| `worker` | Celery background jobs; concurrency is configured in Compose | Internal Docker network |
| `mysql` | Durable relational storage | Host port `3307` → container `3306` |
| `redis` | Broker, result backend, cache and locks | Internal Docker network |
| `phpmyadmin` | Local MySQL browser | `http://localhost:8080` |

FastAPI initializes tables on startup through `backend/database/migrations.py`. The worker consumes tasks from Redis and accesses the same MySQL and mounted files as the API. In Docker, frontend changes require rebuilding the image because the SPA bundle is baked into it. The standalone Vite/Express frontend development server is a separate development mode.

Configuration is loaded by `backend/config.py` from environment variables / `.env`. Important settings include MySQL and Redis connection values, `SARVAM_API_KEY`, `OPENAI_API_KEY`, `CLEARTITLE_AGENT_PROVIDER`, `CLEARTITLE_AGENT_MODEL`, optional Gemini settings, JWT/OAuth settings, upload limits, and pipeline-lock configuration. Secrets must be supplied through environment configuration, not committed to source.

## 4. End-to-end flows

### 4.1 Upload and document processing

1. The UI uploads PDF files to `POST /api/upload` or adds files through the existing-case upload endpoint.
2. The API creates a case ID, assigns document IDs such as `DOC_001`, saves the PDFs under `outputs/<case_id>/raw/`, and creates `cases` and `documents` rows. The `documents.filename` column is intended to contain the uploaded filename; older cases may contain generated placeholder filenames.
3. `POST /api/process/{case_id}` starts `services/orchestrator.py`.
4. The orchestrator creates a sequential Celery chain for each document and runs document chains concurrently in a Celery chord. Resume logic starts from the last durable document checkpoint.
5. Each document runs these stages:

   | Order | Stage | Main behavior / persisted output |
   |---:|---|---|
   | 1 | Preprocess | Improve scan when possible; retain original on non-fatal preprocessing failure. |
   | 2 | OCR | Call Sarvam OCR; write OCR chunk artifacts. |
   | 3 | Merge | Merge OCR chunks; store canonical merged OCR text in `documents.merged_ocr_text` and an artifact/path. |
   | 4 | Classify | Determine document type; mark unrelated/uncertain items for user action. |
   | 5 | Structure | Extract typed fields using the configured document-processing model and matching schema. |
   | 6 | Persist | Store structured JSON, document status, usage metadata, and artifact paths. |

6. `finalize_case_task` recomputes document counts/status, releases the pipeline lock, and, when a verification transaction is already paused/pending after an additional upload, queues the agent to resume after OCR processing.
7. Failed document extraction can be retried. Classification-failed documents can be replaced or skipped through the case API.

Initial chain/verification analysis is explicitly queued through `POST /api/results/{case_id}/analyze` (the dashboard's analysis action). Document finalization alone does not automatically start the initial title-chain investigation.

The document pipeline status (`cases.status`) is independent of the agent status. A case may have all PDFs processed while verification is paused or incomplete.

### 4.2 Title-chain and transaction verification

The main agent task is `run_case_analysis_task` → `services/cleartitle_agent.py::run_agent`. A Redis lock (`case:<case_id>:agent_lock`) prevents concurrent analysis when locks are enabled.

#### Phase A — chain creation or reuse

- The agent loads the persisted Phase A result from `title_chains`.
- If a usable chain exists, it is reused; analysis does not rebuild it merely because verification is resumed.
- If absent, summaries are generated as needed and the Phase A prompt/skill builds the property identity and chronological chain. The result is saved into the dedicated `title_chains` columns.
- Each saved chain entry becomes a verification transaction with an internal stable ID (`PA-TC-0001`, etc.), sequence, related events, and a marker for the last/current-owner endpoint.

#### Phase B — one transaction at a time

For each eligible chain transaction, the agent receives `agent_system.txt`, `agent_verify_task.txt`, the transaction-verification skill, and the transaction details. The current verifier uses the prompt and skill; the former hardcoded `agent_rules.py` rule catalogue and `load_rules` tool have been removed.

The tool workflow is:

1. `get_transaction` loads the chain entry and any prior saved result.
2. `record_evidence_requirements` records transaction-specific evidence needed.
3. `list_documents` returns uploaded filenames, document types, statuses, and saved summaries. Summaries are navigation aids, not evidence.
4. `select_documents` chooses candidate documents. The tool only permits OCR reads for selected candidate IDs.
5. `get_document_text` reads selected documents' canonical merged OCR text from MySQL. The model compares it to the transaction, adjacent chain links, and relevant events.
6. `save_transaction_result` validates and saves a structured result. If essential evidence is missing, the result can instead be saved as `PENDING_NOT_VERIFIED` and the run pauses on that transaction.
7. The user may upload evidence and resume, or skip the paused transaction. A skip remains pending/not verified; it does not become a completed verification.

The verifier is scoped to one transaction per pass. It does not scan every OCR document by default. Its selected evidence references are persisted as internal document IDs; the UI resolves these to filenames/document labels for display.

#### Completion and consolidated report

After processing all eligible transactions without pausing, the overall status is derived from the saved transaction statuses. No consolidated report object is generated or persisted.

Statuses describe different layers:

| Field/status | Meaning |
|---|---|
| `cases.status` | Document-processing state, e.g. uploaded/processing/complete/partial/failed. |
| `cases.agent_status` | Agent workflow state: idle/running/paused/done/error. `done` means the run ended, not that all title links passed verification. |
| `case_memory.stage` | Resume checkpoint such as `phase_a`, `verifying`, `verifying_transaction`, `paused`, `done`, or `error`. |
| Transaction `status` | One transaction's assessment: `PENDING`, `IN_PROGRESS`, `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `INCONCLUSIVE`, or `PENDING_NOT_VERIFIED`. |
| `cases.verdict` | Compact UI mirror; not a legal determination. |

Only transaction statuses actually classified as verified count toward a verified-transaction count. `ISSUES_IDENTIFIED` and skipped/pending results do not count as verified. Overall `INCONCLUSIVE`/`ISSUES_IDENTIFIED` can coexist with agent status `done`.

### 4.3 Result retrieval and UI

`GET /api/results/{case_id}` calls `services/results.py::build_case_results`. It combines case/document extraction data with the Phase A title chain, saved transaction results, and selected workflow-state fields. The React dashboard renders the title chain and transaction verification as separate views. OCR and PDF endpoints are separately available; PDF generation uses `services/report.py` to render the saved transaction entries on demand, not from a persisted report object.

## 5. Low-level application design

### 5.1 Backend layering

```text
HTTP router
  ├─ validates request and case ownership
  ├─ calls service or queues Celery task
  └─ serializes response

Service / orchestrator
  ├─ applies workflow decisions and status transitions
  ├─ invokes provider adapters / tool loop
  └─ reads/writes through repository functions

Worker task
  ├─ owns retry/idempotency boundary for long-running work
  └─ invokes stage/agent service

Repository
  └─ performs parameterized MySQL reads/writes
```

The agent loop in `agent_runtime.py` maintains an in-process sequence of model/tool messages for one phase. `agent_tools.py` supplies phase-specific tool schemas, validates arguments/results, and delegates persistence to repositories. The in-process tool context and model conversation are not the durable resume memory.

### 5.2 Document processing modules

- `backend/services/orchestrator.py`: builds document task chains/chords and determines a resume stage from durable checkpoints.
- `backend/workers/tasks.py`: thin Celery wrappers with retry and idempotency configuration.
- `backend/workers/stages.py` and `stage_adapter.py`: execute individual document stages and persist stage state.
- `backend/workers/finalize.py`: recomputes case status, releases locks, and may queue verification resume after evidence upload.
- `backend/services/document_processor.py`, `extract.py`, and `integrations/`: provider and extraction logic.

### 5.3 Verification modules

- `backend/workers/title_chain_tasks.py`: starts case-level agent execution.
- `backend/workers/agent_tasks.py`: queues skip/resume operations.
- `backend/services/cleartitle_agent.py`: owns lock, chain reuse/build, ordered transaction loop, pause/resume, and final report invocation.
- `backend/services/agent_runtime.py`: generic bounded model/tool-call loop.
- `backend/services/agent_tools.py`: tool schemas/handlers for document navigation, requirements, evidence selection, result persistence, missing evidence, and report persistence.
- `backend/services/agent_schemas.py`: Pydantic validation for chain, transaction, evidence, and final-result structures.
- `backend/prompts/` and `backend/skills/`: system/task prompts and mandatory chain/verification procedures.
- `backend/database/repositories/agent_repo.py`: persistence and retrieval of title chain, readable agent memory/status, and the single case result document.

### 5.4 Failure, pause, retry, and skip behavior

- Document tasks use retries and idempotency guards; retries can start from a durable checkpoint.
- If a transaction requests essential missing evidence, the transaction result is saved as pending and `case_memory` records the paused transaction, missing documents, and next action. Agent status becomes `paused`.
- Uploads are run through document processing before a paused verification is retried.
- Skipping the currently paused transaction writes a pending/not-verified result, preserves prior verification points and missing evidence, records the skip in readable memory, and advances to the next independent transaction.
- A later fresh analysis clears the per-pass skip list and retries pending transactions. Terminal transaction statuses (`VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `INCONCLUSIVE`) are not re-run automatically by the transaction loop.
- Unexpected agent errors set stage/status to `error`; they do not imply a negative legal finding.

## 6. Database design

The schema is initialized in `backend/database/migrations.py`. The logical relationships below are keyed by `case_id`; the DDL does not declare SQL foreign-key constraints. Repositories and routers enforce ownership and lifecycle behavior in application code.

```text
users (1) ──────── (many) cases
                         ├── (many) documents
                         ├── (0..1) title_chains
                         ├── (0..1) case_memory
                         ├── (0..1) case_results [all transaction results + latest report]
                         └── (0..1) case_memory [human-readable progress/checkpoint text]
```

| Table | Main columns/data | Role and write behavior |
|---|---|---|
| `users` | ID, email, password hash, name, timestamps | Login/ownership records. Email is unique. |
| `cases` | ID, owner ID, document status/counts, verification status/verdict, pipeline logs, `agent_status` | Case-level status only; verification content and memory are stored in their dedicated per-case tables. |
| `documents` | Case/document IDs, index, filename, expected/actual type, status, `structured_data` JSON, `merged_ocr_text`, `file_paths` JSON, error and extraction metrics | One row per uploaded PDF; stores canonical merged OCR and extraction output. Unique `(case_id, doc_id)`. |
| `title_chains` | Case ID, status, `property_identity` JSON, `title_chain_graph` text, `detailed_chain` JSON; legacy `chain`/`source` columns may remain | Current Phase A chain. Repository reads/writes the three dedicated columns (`property_identity`, graph, detailed chain). Unique case ID. |
| `case_results` | `case_id` primary key, `case_result` JSON, update timestamp | Exactly one row per case. `case_result` is an ordered array of transaction metadata, point-wise verification results, and missing-document names/reasons. Each completed transaction is appended/updated immediately. No final report object or per-transaction/report-history tables are stored. |
| `case_memory` | `case_id` primary key, `case_memory` LONGTEXT, update timestamp | Exactly one row per case. Concise readable progress/outcome/reason text; the repository parses labeled lines needed to resume workflow. |

The startup migration safely copies legacy `findings`, transaction entries from `reports`/case-level report copies, `verification_results`, and case-level memory into the two per-case tables before dropping those redundant stores/columns. Only the transaction entries are retained; report summaries are intentionally discarded. Phase A title-chain data remains in `title_chains`.

### 6.1 Case result JSON

The `case_results.case_result` value is an array. Representative transaction result shape (optional lists/values may be empty):

```json
{
  "tx_id": "PA-TC-0001",
  "sequence": 1,
  "status": "PENDING_NOT_VERIFIED",
  "conclusion": "The reported transfer is not verified because its source deed is missing.",
  "reasoning": "Evidence basis and assessment limitations.",
  "findings": [
    {
      "description": "A later deed recites the earlier transfer.",
      "significance": "The recital does not independently establish the transfer.",
      "explanation": "Short supporting explanation.",
      "source_refs": [{"doc_id": "DOC_017", "page": "2"}]
    }
  ],
  "supporting_evidence": [],
  "contradictory_evidence": [],
  "missing_documents": [
    {"document_type": "Registered source deed", "reason": "Confirm parties and property conveyed."}
  ],
  "evidence_requirements": [],
  "reviewed_document_ids": ["DOC_017"],
  "impact": "The root ownership link remains unconfirmed.",
  "unresolved": [],
  "limitations": [],
  "verified_at": "...",
  "schema_version": "1.0"
}
```

The UI combines this payload with the corresponding Phase A chain transaction. Document IDs are internal join keys; source display should resolve them through the case's document metadata.

### 6.2 Agent memory JSON

`case_memory.case_memory` is concise plain text, not JSON or a versioned conversation transcript. Example:

```text
Progress: paused
Paused transaction: PA-TC-0003
Pending transactions: PA-TC-0001, PA-TC-0003
Missing document: Registered source deed — Confirm parties and property conveyed.
Next action: Upload requested evidence or skip this transaction.
```

The text explains progress and reasons for pending/skipped/verified outcomes. `cases.agent_status` remains a high-level status column; the memory text is the readable case-level narrative/checkpoint.

Transactions are stored in `case_results.case_result.transactions`, keyed by `tx_id`, and a re-verification replaces that transaction's existing item instead of creating another row. The final report is stored alongside them under `report` in that same case row.

### 6.3 Keys and indexes

The migration declares no foreign keys. Uniqueness/index behavior is:

- `users`: primary key on `id`; unique `email`.
- `cases`: primary key on `id`; indexes on case `status` and `user_id`.
- `documents`: primary key on row `id`; unique `(case_id, doc_id)`; indexes on case, extraction status, and document type.
- `title_chains`: primary key on row `id`; unique `case_id` (one current chain row per case).
- `case_results`: primary key `case_id` (one result row per case).
- `case_memory`: primary key `case_id` (one memory row per case).

### 6.4 Consolidated report JSON

There is no persisted consolidated report. Overall status is derived from the transaction statuses when the API responds.

## 7. State ownership and source of truth

| Data | Durable source of truth | Cache/artifact role |
|---|---|---|
| Case/document status and extracted data | MySQL `cases` / `documents` | Redis can accelerate status/log access. |
| Original PDFs and intermediate extraction files | Shared `outputs/<case_id>/` filesystem | `documents.file_paths` points to artifacts. |
| Canonical OCR text | `documents.merged_ocr_text` | Merged OCR JSON artifact supports processing/legacy fallback. |
| Property identity and chain | `title_chains` dedicated columns | Result endpoint assembles it with verification data. |
| Agent progress/resume | `case_memory.case_memory` readable text | No duplicate memory copy. |
| Transaction verification and latest report | `case_results.case_result` | One case row; transactions are appended as they complete. |
| Current workflow status | `cases.agent_status` and `case_memory.stage` | Redis task state/log cache is not authoritative for verification. |

## 8. API map

Main routers are registered in `backend/main.py`.

| Method | Path | Function |
|---|---|---|
| `POST` | `/api/auth/register`, `/api/auth/login` | Create account / authenticate. |
| `GET` | `/api/auth/me`, `/api/cases` | Current user / owned cases. |
| `POST` | `/api/upload` | Create a case and upload initial PDFs. |
| `POST` | `/api/process/{case_id}` | Queue document processing. |
| `GET` | `/api/status/{case_id}` | Document progress and action state. |
| `POST` | `/api/retry/{case_id}` | Retry failed document processing. |
| `POST` | `/api/case/{case_id}/upload` | Add evidence/documents to an existing case. |
| `POST` | `/api/case/{case_id}/doc/{doc_id}/replace` or `/skip` | Resolve classification action. |
| `GET` | `/api/results/{case_id}` | Read case, document, chain, transaction, and report data. |
| `GET` | `/api/results/{case_id}/ocr` | Read available merged OCR by document. |
| `POST` | `/api/results/{case_id}/analyze` | Queue or resume agent verification. |
| `POST` | `/api/results/{case_id}/agent/skip/{tx_ref}` | Skip the currently paused transaction and continue. |
| `GET` | `/api/results/{case_id}/report/pdf` | Generate/download a PDF report. |
| `GET` | `/api/case/{case_id}/doc/{doc_id}/pdf` | Download an uploaded PDF. |
| `GET` | `/health` | Service/provider-key presence health response. |

Case endpoints enforce ownership when `cases.user_id` is set. Guest cases with no owner use the current anonymous-case access behavior and can be linked to an account.

## 9. Security and reliability notes

- Repository SQL parameterizes data values; case access is checked at route boundaries.
- Celery document stages have retry and idempotency guards. Redis locks protect processing/agent runs where enabled.
- Redis is not the durable owner of MySQL records or mounted PDFs.
- OCR and LLM outputs are document-analysis artifacts; they do not establish authenticity or legal validity.
- Errors should not be interpreted as negative title findings, and a completed workflow should not be rendered as verified title unless transaction statuses support that.
- Do not log or expose secrets; configure provider keys and auth secrets via environment variables.

## 10. Source map

| Concern | Main files |
|---|---|
| App startup / routing | `backend/main.py`, `backend/routers/` |
| Case/document APIs | `backend/routers/cases.py`, `backend/services/orchestrator.py` |
| Document pipeline | `backend/workers/tasks.py`, `stages.py`, `stage_adapter.py`, `finalize.py` |
| ClearTitle agent | `backend/services/cleartitle_agent.py`, `agent_runtime.py`, `agent_tools.py`, `agent_schemas.py` |
| Agent prompt/skills | `backend/prompts/`, `backend/skills/title_chain/`, `backend/skills/transaction_verification/` |
| Persistence | `backend/database/migrations.py`, `backend/database/repositories/` |
| Result composition/PDF | `backend/services/results.py`, `backend/services/report.py`, `backend/routers/results.py` |
| React dashboard | `frontend/src/dashboard/VerificationDashboard.tsx`, `PhaseAResult.tsx`, `frontend/src/api/backend.ts` |
| Deployment | `Dockerfile`, `docker-compose.yml`, `backend/config.py` |
