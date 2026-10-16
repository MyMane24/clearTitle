# ClearTitle Architecture

This document describes the current implementation in this repository. It is intended for both maintainers and users who want to understand what happens to a document from upload through the final report.

## 1. At a glance

ClearTitle has two processing phases:

1. **Document pipeline:** prepare each PDF, run OCR, classify it, structure its contents, and persist the extraction.
2. **Title investigation:** after all documents are structured, the ClearTitle agent establishes property identity, builds a chronological title chain, verifies each transaction, and produces a case report.

The browser talks to FastAPI. FastAPI stores durable state in MySQL, uses Redis for Celery and a best-effort case cache, and queues long-running work to Celery workers. Original files and intermediate OCR/structured output are stored in the `outputs/` directory.

```text
                         +-----------------------+
                         | User / React browser  |
                         +-----------+-----------+
                                     | HTTP
                                     v
                         +-----------+-----------+
                         |      FastAPI API      |
                         +--+--------+--------+--+
                            |        |        |
                     durable data   cache   case files
                            |        |        |
                            v        v        v
                         MySQL     Redis   outputs/<case_id>
                                      |
                                      | Celery queue
                                      v
                              +-------+--------+
                              | Celery workers |
                              +--+----------+--+
                                 |          |
                      Sarvam OCR   OpenAI-compatible extraction
                                 |          |
                                 +----+-----+
                                      |
                               structured data
                                      |
                                      v
                              ClearTitle agent
                                /         \
                         configured LLM   MySQL + OCR files
```

### Runtime components

| Component | Responsibility |
|---|---|
| `frontend/src/` | React user interface: upload, case history, processing status, OCR viewer, transaction findings, and report controls. |
| `backend/main.py` | FastAPI app, router registration, startup database initialization, health endpoint, and production SPA serving. |
| `backend/routers/` | HTTP endpoints, authentication dependencies, case ownership checks, upload/status/result actions. |
| `backend/services/` | Application workflows: OCR/extraction routing, agent orchestration, result assembly, PDF report creation, and authentication. |
| `backend/workers/` | Celery tasks for document stages, case finalization, agent execution, and transaction skip/resume. |
| `backend/integrations/` | Adapters to Sarvam OCR, OpenAI-compatible document processing, optional Gemini agent calls, Redis, and filesystem storage. |
| `backend/database/repositories/` | Parameterized MySQL reads/writes for cases, documents, users, and agent state. |
| `backend/database/migrations.py` | Creates the current application tables and applies best-effort changes to older schemas. |

In Docker, the frontend is built with Vite and served as static files by FastAPI. `frontend/server.ts` is a separate Node/Express development server; it is not the Docker production API.

## 2. End-to-end user flow

### Step 1 — Upload documents

The user opens `/app`, selects PDFs, and submits them through `POST /api/upload`.

- The API checks the upload is a PDF and enforces the configured file-size limit.
- It creates a short case ID and sequential document IDs such as `DOC_001`.
- Files are saved under `outputs/<case_id>/raw/`.
- A `cases` row and one `documents` row per PDF are written to MySQL.
- Redis is warmed with case metadata and file paths for the pipeline. It is a cache; MySQL is the durable source of truth.
- Upload slots can identify a file as the expected sale deed or encumbrance certificate. The expected type is a classification fallback, not OCR evidence.

The UI currently requires a sale deed and EC slot before enabling its main “Verify Title” action. The upload endpoint itself accepts a list of PDF files.

### Step 2 — Start background processing

The browser calls `POST /api/process/{case_id}`. The API checks case access, optionally acquires a Redis pipeline lock, sets the case to `processing`, and asks `services/orchestrator.py` to queue work.

The orchestrator creates one **sequential Celery chain per document** and combines those chains in a chord. Different documents may therefore process concurrently; stages for a single document run in order. Idempotency wrappers skip stages whose persisted status is already beyond the target stage.

### Step 3 — Extract each document

Every PDF passes through these six stages:

| Order | Stage | What it does | Main artifacts/state |
|---:|---|---|---|
| 1 | Preprocess | Tries to improve the scan (deskew/contrast/denoise). If preprocessing fails, it logs a warning and uses the original PDF. | `outputs/<case_id>/preprocessed/`; `documents.file_paths.preprocessed` |
| 2 | OCR | Sends the PDF through Sarvam OCR with retry handling and page/chunk support. | OCR chunk artifacts under `outputs/<case_id>/ocr_raw/`; `documents.file_paths.ocr_chunks` |
| 3 | Merge | Combines OCR chunks, including overlap handling, into one document text record. | `outputs/<case_id>/ocr_raw/<doc_id>_merged.json`; `documents.file_paths.merged_ocr` |
| 4 | Classify | Uses a bounded OCR prefix with an LLM, plus deterministic rules for recognized document formats. Unrelated documents are flagged for user action. | `documents.document_type` and `documents.status` |
| 5 | Structure | Sends the full merged OCR and matching schema to the configured OpenAI-compatible document processor. | Structured data and summary in MySQL; structured JSON artifact |
| 6 | Persist | Normalizes EC ledger structure where applicable, writes the final structured JSON, and persists it to MySQL. | `documents.structured_data`, `documents.file_paths.structured`, page/token/model/cost fields |

### Step 4 — Finalize the document pipeline

After the document chains finish, `workers/finalize.py` recalculates case/document counts and sets the document-pipeline status:

- `complete`: every document is structured (or otherwise counted as resolved by the repository status calculation).
- `partial`: at least one document failed while others completed.
- `failed`: no document completed and failures occurred.

When the case is `complete`, the finalizer queues the ClearTitle agent. A user can replace or skip a classification-failed document; when all unresolved documents are addressed, that route also queues the agent. Failed OCR/structuring documents can be retried using `POST /api/retry/{case_id}`.

The document-pipeline status and agent status are separate concepts. A case can have all PDFs processed while agent verification is paused for missing evidence.

### Step 5 — ClearTitle agent investigates the case

`workers/title_chain_tasks.py` invokes `services/cleartitle_agent.py::run_agent`. The agent is a tool-calling workflow; the model interprets evidence, while Python tools validate and persist results.

#### 5.1 Document summaries

`ensure_summaries` creates a short navigation summary only when a document has no saved summary. It reads merged OCR text and supplies up to 6,000 characters to `agent_summary.txt`. The summary helps the agent find documents; it is not a substitute for reading source evidence.

#### 5.2 Property identity and title chain

If a saved chain with transactions already exists, the agent reuses it on resume. Otherwise, it starts the `chain` tool phase:

1. The prompt receives document IDs, types, filenames, and summaries.
2. The agent can call `list_documents`, `get_document_metadata`, and `get_document_text` to inspect specific documents. Metadata includes structured extraction; text is read from merged OCR. The text tool defaults to 40,000 characters per call and caps a requested read at 200,000 characters.
3. The agent determines property identity and chronological transfers, preserving explicit uncertainty and document references.
4. It calls `save_title_chain`. The tool validates the Pydantic `TitleChain`, assigns stable IDs such as `TX001` where missing, saves the chain, and creates one TODO per transaction.

The chain is a document-supported ownership history. It is not itself a conclusion that every transfer has been verified.

**Contract caveat in the current source:** `agent_chain_task.txt` illustrates transactions with `sequence` but no `tx_id`, while the Pydantic `TransactionEntry` requires `tx_id`. The tool assigns a missing ID only after Pydantic validation. This prompt/schema ordering should be reconciled before relying on the model to omit IDs.

#### 5.3 Transaction-by-transaction verification

For each TODO that is not complete or skipped:

1. The agent receives the transaction and the cross-document plus transaction-type rules from `backend/services/agent_rules.py`.
2. It can retrieve transaction details, applicable rules, document metadata, and full OCR text through tools.
3. It records supporting/contradictory evidence, limitations, missing documents, and a permitted verification status.
4. `save_transaction_result` validates the result and persists it to `findings`; the TODO is marked complete only after persistence succeeds.

If a required document is missing, `request_missing_documents` saves `PENDING_NOT_VERIFIED`, leaves the TODO pending, and pauses the run. The user can upload/process additional evidence and resume with `POST /api/results/{case_id}/analyze`, or explicitly skip the paused transaction using `POST /api/results/{case_id}/agent/skip/{tx_ref}`. A skipped transaction remains incomplete and is not represented as verified.

#### 5.4 Consolidated report

When the transaction loop finishes without pausing, the final phase receives the saved chain and transaction results. It calls `save_report`; the application assembles the final response and persists the report to `reports` plus the latest-result copy in `cases.agent_result`.

The report status is based on saved transaction outcomes and remaining work. “No issue identified in supplied documents” is not equivalent to “fully investigated” or a legal determination that title is marketable.

### Step 6 — View results and report

The browser polls case status while document processing is active. It then calls `GET /api/results/{case_id}` for case status, extracted documents, action-required documents, and the `agent` result containing property identity, title chain, transaction results, findings, missing documents, and report text.

Other result actions:

- `GET /api/results/{case_id}/ocr` returns merged raw OCR text by document.
- `GET /api/case/{case_id}/doc/{doc_id}/pdf` serves an uploaded PDF.
- `GET /api/results/{case_id}/report/pdf` builds and downloads a PDF report.
- `POST /api/results/{case_id}/analyze` queues an agent run/resume.
- `POST /api/results/{case_id}/agent/skip/{tx_ref}` queues a transaction skip/resume.

Owned cases require the authenticated owner. Cases with a null `user_id` are treated as anonymous cases and are accessible by case ID; the UI can link such a case to a signed-in account.

## 3. Main sequence diagram

```text
USER / BROWSER
    |
    | 1. Select PDFs and upload slots
    v
FASTAPI
    |-- save PDFs ------------------------------> outputs/<case_id>/raw/
    |-- create case and document rows ----------> MySQL
    |-- warm case cache ------------------------> Redis
    |<-- return case_id and document IDs --------|
    |
    | 2. POST /api/process/<case_id>
    |-- set processing status ------------------> MySQL / Redis
    |-- queue one task chain per document ------> Celery
    v
CELERY WORKER (document chains run concurrently)
    |-- preprocess PDF
    |-- OCR ------------------------------------> Sarvam
    |<-- OCR chunks -----------------------------|
    |-- merge chunks; save merged OCR ----------> outputs/<case_id>/ocr_raw/
    |-- classify document
    |-- classify prefix + extract full OCR ----> OpenAI-compatible processor
    |<-- structured fields and usage metrics ---|
    |-- persist document status and fields ------> MySQL
    |-- save structured JSON --------------------> outputs/<case_id>/structured/
    |
    | 3. Finalize case counts/status -----------> MySQL
    |-- release pipeline lock ------------------> Redis
    |
    +-- if all documents are complete:
    |       queue ClearTitle agent
    |       agent reads merged OCR on demand ----> outputs/<case_id>/ocr_raw/
    |       agent reads/saves chain, findings,
    |       TODOs, memory, and report -----------> MySQL
    |
    +-- if a document needs attention:
            show replace/skip action in UI
            user resolves it, then retries/resumes

USER / BROWSER
    | 4. Request results
    v
FASTAPI -- read case, documents, and agent data --> MySQL
    |
    +-- return results --------------------------> React UI
    +-- optionally generate PDF report ----------> Browser download
```

## 4. API surface map

The main application router prefixes are registered in `backend/main.py`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/register` | Create an email/password account. |
| `POST` | `/api/auth/login` | Authenticate and return a bearer token. |
| `GET` | `/api/auth/me` | Return the authenticated user. |
| `GET` | `/auth/google/login` | Start Google OAuth. |
| `GET` | `/auth/google/callback` | Complete OAuth and redirect to the frontend. |
| `GET` | `/api/cases` | List the signed-in user's cases. |
| `POST` | `/api/upload` | Create a case and upload its initial PDFs. |
| `POST` | `/api/process/{case_id}` | Start document extraction. |
| `GET` | `/api/status/{case_id}` | Read document pipeline progress, logs, and action requirements. |
| `POST` | `/api/retry/{case_id}` | Retry failed documents. |
| `POST` | `/api/case/{case_id}/upload` | Add documents to an existing case. The frontend follows with processing. |
| `POST` | `/api/case/{case_id}/doc/{doc_id}/replace` | Replace a failed/unrecognized document. |
| `POST` | `/api/case/{case_id}/doc/{doc_id}/skip` | Skip an unrecognized document. |
| `POST` | `/api/case/{case_id}/link` | Link an anonymous case to the signed-in user. |
| `DELETE` | `/api/case/{case_id}` | Delete a case's DB/cache/files data. |
| `GET` | `/api/case/{case_id}/doc/{doc_id}/pdf` | Download the original uploaded PDF. |
| `GET` | `/api/results/{case_id}` | Read extraction and agent results. |
| `GET` | `/api/results/{case_id}/ocr` | Read merged OCR text for the case. |
| `GET` | `/api/results/{case_id}/report/pdf` | Generate/download the PDF report. |
| `POST` | `/api/results/{case_id}/analyze` | Queue or resume the ClearTitle agent. |
| `POST` | `/api/results/{case_id}/agent/skip/{tx_ref}` | Skip a paused transaction and resume. |
| `GET` | `/health` | Basic service and configured-provider-key presence check. |

## 5. Data and file storage

### MySQL

MySQL is the durable source of truth for account, case, document, and agent records. `backend/database/migrations.py` defines the tables and also applies additive columns to older schemas. The repository code uses parameterized SQL for values.

### Redis

Redis has two roles:

1. Celery broker and result backend.
2. Best-effort hot cache for case metadata, file lists, logs, and lock keys.

Case/document records and logs are persisted to MySQL; Redis misses fall back to MySQL. Redis can be restarted without making it the durable owner of case data.

### Filesystem

The API and worker share `outputs/` through the Docker bind mount. Typical files are:

```text
outputs/<case_id>/
├── raw/                     # uploaded PDFs
├── preprocessed/            # optional preprocessed PDFs
├── ocr_raw/
│   ├── <doc_id>_chunks.json
│   └── <doc_id>_merged.json # full_text used by the agent
└── structured/
    ├── <doc_id>_<TYPE>.json # final structured extraction
    └── <doc_id>_temp.json    # temporary between structure and persist stages
```

The `documents.file_paths` JSON column records paths such as `raw`, `preprocessed`, `ocr_chunks`, `merged_ocr`, and `structured`. The agent reads merged OCR using the saved `merged_ocr` path, falling back to `outputs/<case_id>/ocr_raw/<doc_id>_merged.json`.

## 6. Database schema

The table/column list below is derived from the checked-in migration source; it describes the schema this code initializes, not a live database inspection. The ER diagram shows logical relationships only: there are no declared SQL foreign-key constraints in this DDL; case ownership and delete behavior are handled in application repositories.

### Entity relationship diagram

```text
USERS (1) -------- owns -------- (many) CASES
                                      |
                                      +-- (many) DOCUMENTS
                                      +-- (0..1) TITLE_CHAINS
                                      +-- (0..1) CASE_MEMORY
                                      +-- (many) FINDINGS, one per transaction
                                      +-- (many) AGENT_TODOS, one per transaction
                                      +-- (many) REPORTS, report history
                                      +-- (0..1) VERIFICATION_RESULTS (legacy)

These are logical links by case_id. The migration does not declare SQL foreign keys.
```

### Table purpose and persistence path

| Table | Purpose | Main writer/reader |
|---|---|---|
| `users` | Password/OAuth accounts. | `user_repo.py`; auth routes/services. |
| `cases` | Case ownership, document counts/status, logs, agent status, a fallback agent-memory column, and a latest-result copy. | `case_repo.py`, `agent_repo.py`; status/results endpoints. |
| `documents` | Per-document metadata, extraction status, structured fields, file paths, summary and extraction usage metrics. | `document_repo.py`; workers, OCR viewer, reports, agent. |
| `title_chains` | Current agent's authoritative property identity and chronological chain in `chain`. | `agent_repo.py`; result assembly and status endpoint. `source` is retained for the older seeder/repository path. |
| `case_memory` | Authoritative agent resume state such as current phase, paused transaction, skipped IDs and next action. | `agent_repo.py`; agent resume. |
| `findings` | One current verification payload per case/transaction ID. Includes canonical status, conclusion, evidence, limitations, and rule versions. | `agent_repo.py`; agent and result/report assembly. |
| `agent_todos` | Durable verification checklist, one row per case/transaction. | `agent_repo.py`; chain save, verification, resume. |
| `reports` | Append-only report versions; the latest row supplies the current report. | `agent_repo.py`; results/PDF report paths. |
| `verification_results` | Older case-level field-check result shape. It is retained in the migration for legacy code/demo compatibility; the current ClearTitle agent writes transaction data to `findings`. | Older `verify.py`/repository and demo seeder, not the current post-OCR agent workflow. |

### Indexes and uniqueness

- `users`: primary key `id`; unique email.
- `cases`: primary key `id`; indexes on status and user ID.
- `documents`: primary key `id`; unique `(case_id, doc_id)`; indexes on case, status, and document type.
- `title_chains`: primary key `id`; unique `case_id`.
- `verification_results`: primary key `id`; unique `case_id`.
- `case_memory`: primary key `case_id`.
- `findings`: primary key `id`; indexes on `case_id` and `(case_id, tx_id)`.
- `agent_todos`: primary key `id`; unique `(case_id, tx_id)`.
- `reports`: primary key `id`; index on `case_id`.

### Important status distinction

- `cases.status` describes **document processing** (`uploaded`, `processing`, `complete`, `partial`, `failed`).
- `documents.status` describes **one document's extraction stage** or a terminal document outcome.
- `cases.agent_status` describes the **agent run** (`idle`, `running`, `paused`, `done`, `error`).
- `findings.status` describes **one transaction's verification result**. Allowed statuses are `PENDING`, `IN_PROGRESS`, `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `INCONCLUSIVE`, and `PENDING_NOT_VERIFIED`.
- `cases.verdict` is a compact UI summary (`CLEAR_TITLE`, `ATTENTION_REQUIRED`, or `N/A`); it is not an official legal determination.

### Agent data path

```text
title_chains.chain  <- property identity + chain transactions
findings.payload    <- verification result for each tx_id
agent_todos         <- pending/completed transaction checklist
case_memory.memory  <- pause/resume state
reports.result      <- append-only final report versions
cases.agent_result  <- latest-result fallback/cache copy
documents.summary   <- brief navigation label for each document
documents.file_paths.merged_ocr -> filesystem OCR JSON -> full_text
```

## 7. Authentication and ownership

- Email/password uses bcrypt hashes and signed bearer tokens.
- Google sign-in uses the OAuth authorization-code flow.
- Authenticated users list their own cases; case endpoints check `cases.user_id` when it is set.
- Anonymous cases have `user_id = NULL`; the current access helper permits access by case ID and supports later linking to a signed-in user.
- The frontend stores its bearer token in browser local storage and attaches it to API requests.

## 8. Deployment and configuration

Docker Compose runs:

| Service | Role |
|---|---|
| `api` | FastAPI API and built React SPA on host port 8000. |
| `worker` | Celery tasks for OCR, extraction, finalization, and agent analysis. |
| `mysql` | MySQL on the internal service network; host port 3307. |
| `redis` | Celery broker/result backend and cache. |
| `phpmyadmin` | Local database browser on host port 8080. |

The API and worker share the same image and mounted `outputs/` files. The `mysql_data` and `redis_data` named volumes survive normal container restarts. Removing volumes destroys their contents.

Important environment setting names are read in `backend/config.py`:

- Database and tasking: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `REDIS_URL`.
- OCR and document extraction: `SARVAM_API_KEY`, `OPENAI_API_KEY`, `DOCUMENT_PROCESSOR_MODEL`.
- Verification agent: `CLEARTITLE_AGENT_PROVIDER`, `CLEARTITLE_AGENT_MODEL`, `OPENAI_API_KEY`; optional Gemini provider uses `GEMINI_API_KEY` and Gemini rate-limit settings.
- Auth: `JWT_SECRET_KEY`, Google OAuth client and redirect settings.
- Processing: `MAX_UPLOAD_SIZE_MB`, `PIPELINE_LOCK_ENABLED`.

Never commit populated secrets. `.env.example` documents names/placeholders only.

## 9. Source map

| Concern | Main files |
|---|---|
| App startup and API | `backend/main.py`, `backend/routers/*.py` |
| Case/document processing | `backend/services/orchestrator.py`, `backend/workers/tasks.py`, `backend/workers/stages.py`, `backend/workers/finalize.py` |
| Agent workflow | `backend/services/cleartitle_agent.py`, `agent_runtime.py`, `agent_tools.py`, `agent_schemas.py`, `agent_rules.py` |
| LLM provider access | `backend/integrations/llm/agent_llm.py`; optional Gemini rate limiting in `rate_limiter.py` |
| OCR | `backend/integrations/ocr/` |
| Persistence | `backend/database/migrations.py`, `connection.py`, `repositories/` |
| Results/PDF | `backend/services/results.py`, `backend/services/report.py` |
| Browser app | `frontend/src/App.tsx`, `frontend/src/api/backend.ts`, `frontend/src/dashboard/`, `frontend/src/pages/` |
