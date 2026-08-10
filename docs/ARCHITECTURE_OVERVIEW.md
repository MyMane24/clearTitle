# ClearTitle — Architecture & Codebase Guide (Simplified)

> A plain-English, ground-up walkthrough of the **ClearTitle property title
> verification app** — what it does, how the pieces fit together, how data
> flows through the pipeline, what is stored where (and what is wasted), and
> how to build correct retry / fallback / error handling on top of it.

---

## Table of Contents

1. [What This App Does (30-second version)](#1-what-this-app-does)
2. [Technology Stack — short list](#2-technology-stack)
3. [High-Level Architecture (HLD)](#3-high-level-architecture-hld)
4. [Low-Level Architecture (LLD) — components & their jobs](#4-low-level-architecture-lld)
5. [The Document Pipeline — one document, end to end](#5-the-document-pipeline)
6. [Request Flow — what happens when you click "Verify Title"](#6-request-flow)
7. [How Redis & Celery work here](#7-how-redis--celery-work-here)
8. [Preprocessing & Sarvam OCR — inputs and outputs in detail](#8-preprocessing--sarvam-ocr-in-detail)
9. [Structuring & the LLM routing / fallback chain](#9-structuring--llm-routing)
10. [Title Chain & Verification (case-level analysis)](#10-title-chain--verification)
11. [Database — schema, and what we store unnecessarily](#11-database)
12. [Tradeoffs & Known Issues](#12-tradeoffs--known-issues)
13. [How to build correct retry / fallback / error handling](#13-retry-fallback-error-handling)

---

## 1. What This App Does

ClearTitle answers one question about a **Karnataka property**:

> **"Does the buyer of this property have a clean title?"**

It does this in three stages:

1. **Read the paperwork.** The user uploads scanned PDFs (usually a **Sale
   Deed** and an **Encumbrance Certificate / EC**, plus optional extras like
   RTC, Khata, Mutation). The app converts each scan into searchable text with
   **Sarvam OCR** (it understands Kannada + English mixed documents).
2. **Extract structured data.** An LLM (Gemini first, Groq as fallback) reads
   the OCR text and fills a strict JSON schema — parties, property survey
   numbers, consideration amount, EC historical ledger, etc.
3. **Analyze the title.** A second LLM pass builds a **title chain** (a
   timeline of every registered transaction on the property) and **verifies**
   that the Sale Deed's claims (survey number, parties, dates, encumbrances)
   match what the EC ledger says. Result: a `VERIFIED` / `NOT_VERIFIED`
   verdict.

Everything runs in the background (Celery), and the frontend polls the status
and shows a live log, the extracted fields, the title-chain timeline, and the
verification table.

---

## 2. Technology Stack

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | React 19, Vite 6, TypeScript, Tailwind CSS, lucide-react | SPA: landing page + dashboard (upload → processing → results) |
| **Backend API** | FastAPI + Uvicorn (Python 3.11) | REST endpoints: auth, upload, process, status, retry, results |
| **Async jobs** | Celery | Background workers that run the 6-stage per-document pipeline |
| **Broker / queue** | Redis 7 | Celery message broker + result backend |
| **State cache** | Redis | Hot-path cache of case status/logs; **MySQL is the source of truth** |
| **Relational DB** | MySQL 8 | Persistent storage: `cases`, `documents`, `title_chains`, `verification_results`, `users` |
| **OCR** | Sarvam AI Vision (`sarvamai` SDK) | Scan → text for Kannada+English docs; chunks >10 pages |
| **Image preprocess** | OpenCV (cv2) + PyMuPDF (fitz) + Pillow + numpy | Contrast/denoise/deskew the scan before OCR |
| **LLM structuring** | Google Gemini 2.5 Flash (primary), Groq llama-3.3-70b / 3.1-8b (fallback) | OCR text → strict JSON |
| **LLM analysis** | Gemini 2.5 Flash | Title chain + verification passes |
| **Infra** | Docker Compose | 5 services: api, worker, mysql, redis, phpmyadmin |

---

## 3. High-Level Architecture (HLD)

```
                          ┌─────────────────────────────┐
                          │        BROWSER (React SPA)   │
                          │  Upload / Poll / Results     │
                          └──────────────┬──────────────┘
                                         │  HTTP (JSON)  port 8000
                                         ▼
                          ┌─────────────────────────────┐
                          │     FastAPI (api service)    │
                          │  /api/upload /process/status │
                          │  /api/retry /results ...     │
                          └───────┬───────────────┬──────┘
                                  │ start pipeline │ enqueue
                                  ▼               ▼
                          ┌─────────────────────────────┐
                          │     CELERY WORKER(s)         │  ──┐
                          │  (celery -A backend.celery)  │    │ async
                          └───────┬───────────────┬──────┘    │
                                  │              │           ▼
                                  ▼              ▼        ┌──────────────┐
                          ┌───────────────┐  ┌───────────▼──┐   REDIS      │
                          │    MYSQL      │  │   REDIS       │ broker+state │
                          │ (source of    │  │ (broker,      │ cache        │
                          │  truth)       │  │  locks, cache)│              │
                          └───────────────┘  └───────────┬──┘              │
                                  ▲                      │                 │
                                  │ files on disk        │                 │
                          ┌───────┴────────┐    ┌────────▼─────────┐       │
                          │ uploads/ +      │    │  EXTERNAL APIs:  │       │
                          │ outputs/{case}/ │    │  Sarvam OCR      │       │
                          │ (PDFs, JSONs)   │    │  Gemini          │       │
                          └────────────────┘    │  Groq            │       │
                                                └──────────────────┘       │
```

**The two most important architectural facts:**

- **MySQL is the single source of truth.** Redis is only a cache in front of it
  (see §7). If Redis dies, the pipeline still works; if MySQL dies, it doesn't.
- **The pipeline is asynchronous.** The API never runs OCR/LLM inline — it
  enqueues Celery tasks and returns immediately. The frontend polls
  `/api/status/{case_id}` every 2 seconds to watch progress.

---

## 4. Low-Level Architecture (LLD)

The backend is split into clean layers (this is the *new* layout after the
refactor — the README still describes the old one):

```
backend/
├── main.py                  # FastAPI app: routers + static SPA serving
├── celery_app.py            # Celery config (broker, acks_late, timeouts)
├── config.py                # ALL env vars in one place (single loader)
│
├── routers/                 # HTTP layer (thin: validate → call service)
│   ├── auth.py              #   register / login / me
│   ├── cases.py             #   upload, process, status, retry, delete, clear
│   └── results.py           #   results/{id}, results/{id}/analyze
│
├── services/                # Business logic (no HTTP, no Celery)
│   ├── orchestrator.py      #   builds Celery chains + chords
│   ├── classifier.py        #   keyword-based doc-type detection
│   ├── extract.py           #   OCR retry + LLM fallback-chain driver
│   ├── title_chain.py       #   build title tree from SD + EC ledger
│   ├── verify.py            #   cross-document verification pass
│   ├── results.py           #   assemble /api/results payload
│   ├── extraction_prompts.py#   Gemini prompt builders
│   ├── auth.py              #   JWT + bcrypt helpers
│   └── schemas/             #   per-doc-type JSON extraction schemas
│
├── workers/                 # Celery layer (thin task wrappers)
│   ├── tasks.py             #   6 idempotent stage tasks
│   ├── stages.py            #   the actual stage logic (preprocess→persist)
│   ├── stage_base.py        #   ExtractionStage contract
│   ├── stage_adapter.py     #   task → stage.invoke adapter
│   ├── idempotency.py       #   skip-already-done guard
│   ├── finalize.py          #   chord callback: recompute status + queue analysis
│   ├── title_chain_tasks.py #   build_title_chain_task + verify_case_task
│   └── context.py           #   StageContext (dependencies handed to stages)
│
├── domain/state_machine.py  # Stage enum + status→stage mapping (pure logic)
│
├── integrations/            # Adapters to external/plumbing systems
│   ├── llm/                 #   gemini_executor, groq_executor,
│   │                        #   model_router, rate_limiter, analysis_executor
│   ├── ocr/                 #   sarvam_client, ocr_merger, preprocessor
│   ├── redis/               #   client, state_store, lock
│   ├── storage/             #   file_utils (paths, save, delete)
│   └── (database in database/)
│
├── database/
│   ├── connection.py        #  MySQL connection helper
│   ├── migrations.py        #  DDL bootstrap (runs at startup)
│   └── repositories/        #  SQL access (case_repo, document_repo, ...)
│
└── shared/constants.py      # doc-type + status string constants
```

**Design pattern that matters:** stages get everything through a
`StageContext` (`workers/context.py`) — never globals. Each stage exposes
`invoke(ctx, input_data) -> dict`. Celery tasks are thin wrappers that add
retry + idempotency and call the stage through `stage_adapter.run_stage()`.
This is what makes stages unit-testable and swap-able.

---

## 5. The Document Pipeline

Every uploaded PDF goes through **6 stages**, each its own Celery task, chained
with `chain(...)` so they run strictly in order. A Celery **chord** runs one
chain per document in parallel and then calls `finalize_case_task`.

```
DOC_001 ──► preprocess ──► ocr ──► merge ──► classify ──► structure ──► persist ──┐
DOC_002 ──► preprocess ──► ocr ──► merge ──► classify ──► structure ──► persist ──┼──► finalize
DOC_003 ──► preprocess ──► ocr ──► merge ──► classify ──► structure ──► persist ──┘
```

### Stage-by-stage (with inputs → outputs)

| # | Stage | Input | Work | Output | Writes status |
|---|---|---|---|---|---|
| 1 | **Preprocess** (`stages.py:64`) | raw PDF path (`file_paths.raw`) | contrast (CLAHE), denoise, deskew, sharpen via OpenCV → new PDF | `outputs/{case}/preprocessed/{doc}_prep.pdf`; path saved to `file_paths.preprocessed` | `preprocessed` |
| 2 | **OCR** (`stages.py:102`) | preprocessed (or raw) PDF | call Sarvam: ≤10 pages → 1 call; >10 pages → overlapping 10-page chunks in parallel | chunk response zips + `ocr_raw/{doc}_chunks.json` (list of `ChunkResult`); path `file_paths.ocr_chunks` | `ocr_done` |
| 3 | **Merge** (`stages.py:151`) | `{doc}_chunks.json` | de-duplicate overlapping pages, re-join split tables, strip base64 blobs | `ocr_raw/{doc}_merged.json` = `{total_pages, full_text, pages[], tables[]}`; path `file_paths.merged_ocr` | `merged` |
| 4 | **Classify** (`stages.py:188`) | filename + first 2000 chars of `full_text` | keyword match (filename first, then content, English + Kannada) | `document_type` (e.g. `SALE_DEED`, `UNKNOWN`) | `classified`, or `classification_failed` |
| 5 | **Structure** (`stages.py:247`) | `merged.json` + `document_type` from DB | LLM fills the JSON schema (Gemini primary, Groq fallback — see §9) | temp file `structured/{doc}_temp.json` holding `{structured_data, _analytics}` | `structuring_done` |
| 6 | **Persist** (`stages.py:295`) | `{doc}_temp.json` | read temp, write final `structured/{doc}_{TYPE}.json`, save JSON + tokens/cost/model to MySQL, delete temp | MySQL `documents` row: `status=structured`, `structured_data`, `page_count`, `input/output_tokens`, `cost_usd`, `model_used` | `structured` |

### The three files-on-disk contracts (what stages hand to each other)

The pipeline deliberately uses **JSON files on disk** as the hand-off between
stages (not Celery task return values). This makes a stage crash safe — the
next stage can always re-read the file.

1. `ocr_raw/{doc}_chunks.json` — Sarvam's raw output per chunk.
2. `ocr_raw/{doc}_merged.json` — merged, deduplicated, clean text + pages + tables.
3. `structured/{doc}_temp.json` — the LLM's JSON + analytics (deleted after persist).

---

## 6. Request Flow

What actually happens from button-click to final verdict:

```
User clicks "Verify Title"
        │
        ▼
(1) POST /api/upload  {files[], slots[]}
        │   saves PDFs → outputs/{case}/raw/
        │   creates case in MySQL + Redis meta
        ▼
(2) POST /api/process/{case_id}
        │   acquires Redis lock (case:{id}:pipeline_lock)
        │   sets case status = "processing"
        │   builds Celery CHORD:
        │     for each unprocessed doc → chain(preprocess, ocr, merge,
        │                                 classify, structure, persist)
        │     chord → finalize_case_task
        ▼
(3) Celery worker picks up tasks, runs the 6-stage chains in parallel
        │   each stage updates MySQL doc status + Redis cache + appends a
        │   log line to the case log (seen live in the UI)
        ▼
(4) finalize_case_task (runs once after ALL docs finish)
        │   recompute_case_status() → case status = complete / partial / failed
        │   IF all docs structured (status == "complete"):
        │       build_title_chain_task → (linked) verify_case_task
        ▼
(5) build_title_chain_task  : one Gemini call → title tree, saved to title_chains
(6) verify_case_task        : one Gemini call → field-by-field verification
                              → verdict (VERIFIED / NOT_VERIFIED / N/A)
        │                     saved to verification_results + cases.verdict
        ▼
(7) Frontend (polling /api/status every 2 s) flips to "results"
        │   shows extracted fields, title-chain timeline, verification table
        ▼
    GET /api/results/{case_id} → assembled by services/results.py
```

**Special user-action flows:**

- **Retry** (`POST /api/retry/{case_id}`): finds docs with status `failed` /
  `pending_retry`, resets them, re-fires the chord for just those docs.
- **Replace** (`POST /api/case/{id}/doc/{doc}/replace`): uploads a new PDF,
  resets that doc to `failed` with `retry_count=0`, then you call retry.
- **Skip** (`.../doc/{doc}/skip`): marks doc `skipped` so the case can
  finalize without it.
- **Re-run analysis** (`POST /api/results/{case_id}/analyze`): manually
  re-triggers title chain + verification for a completed case.

---

## 7. How Redis & Celery Work Here

### Redis does 3 separate jobs (don't confuse them)

1. **Celery broker + result backend.** The queue. The API *publishes* task
   messages; the worker *consumes* them. Result backend is used for the chord
   join. Configured in `celery_app.py`.
2. **Pipeline state cache.** Keys under `case:{case_id}:*`:
   - `case:{id}:meta` — hash `{status, total_docs}`
   - `case:{id}:files` — list of uploaded files
   - `case:{id}:log` — last 200 log lines (a Redis list)
   - `case:{id}:docs` — per-doc status hash (merged via a Lua script)
   - `case:{id}:results` / `case:{id}:errors` / `case:{id}:done_count`
   - `ratelimit:{gemini|groq}:*` — token buckets
   - `llm_call_log` — capped (10,000) list of per-call LLM metrics
   - `case:{id}:pipeline_lock` — the pipeline lock
3. **Distributed lock + rate limiter.**
   - **Lock** (`integrations/redis/lock.py`): `SET key token NX PX` with a
     background refresh timer (TTL 30 min, refresh every 5 min), atomic Lua
     release/refresh. Prevents two "process" calls running the same case.
   - **Rate limiter** (`integrations/llm/rate_limiter.py`): a Redis **token
     bucket** implemented as one atomic Lua script per provider, shared by all
     workers, so N workers can't together exceed Gemini/Groq TPM/RPM. Acquires
     with exponential backoff (`wait_and_acquire`).

> **Key rule in `state_store.py`:** every write goes **MySQL first**, then
> updates Redis best-effort; every read tries **Redis first**, falls back to
> MySQL. All Redis calls are wrapped in try/except so a Redis outage degrades
> to MySQL-only instead of crashing the pipeline.

### Celery configuration highlights (`celery_app.py`)

- `task_acks_late=True` + `worker_prefetch_multiplier=1` — a task is only
  acked after it completes; a crashed worker's task gets redelivered. This is
  the "at-least-once" guarantee that makes idempotency necessary.
- `task_time_limit=7200`, `task_soft_time_limit=3600` — hard kill after 2h.
- `visibility_timeout=7500` — a redelivered task reappears ~2h+ after a hard
  kill (must exceed the time limit).
- Per-task `autoretry_for=(Exception,)`, `max_retries=5`, exponential backoff
  with jitter (see `workers/tasks.py`).
- `include=[...finalize, tasks, title_chain_tasks]` — these modules are
  imported so their tasks are registered.

### Idempotency (why stages can safely run twice)

Because `acks_late` means a task can run twice, every stage task is wrapped in
`idempotent_stage(entry, complete)` (`workers/idempotency.py`):

- Reads the doc's current status from MySQL.
- If status is already `failed`/`classification_failed` → skip the chain.
- If status is already at/past the stage's *complete* state → skip.
- Otherwise sets the *entry* stage, runs the stage, then sets the *complete*
  stage. On exception, it lets Celery retry up to `max_retries`, then marks
  the doc `failed` permanently.

### The state machine (`domain/state_machine.py`)

A simple `IntEnum` ordering stages 0→12 plus negative terminal states
(`FAILED = -1`, `CLASSIFICATION_FAILED = -2`, `SKIPPED = -3`).
`stage_from_status(status)` maps a DB status string → enum;
`already_past(status, target)` decides "have we already done this?".
This ordering is exactly what idempotency relies on.

---

## 8. Preprocessing & Sarvam OCR (in detail)

### 8a. Preprocess (`integrations/ocr/preprocessor.py`)

Input: raw PDF path. Output: enhanced PDF.

Per page (rendered at 200 DPI via PyMuPDF):
1. **Deskew** — Hough line transform, corrects tilt up to ±15° (only if the
   median angle is meaningful; skips clean pages).
2. **Denoise** — `fastNlMeansDenoisingColored` *only when* the page's pixel
   std-dev > 15 (skipped on clean digital PDFs to save CPU and avoid blur).
3. **CLAHE contrast** on the LAB L-channel.
4. **Unsharp mask sharpen**.
5. Re-embeds images as JPEG (quality 92) into a new PDF.

Fault tolerance: if preprocessing throws, the OCR stage **uses the original
PDF** — preprocessing is non-fatal (`stages.py:91-98`).

### 8b. Sarvam OCR (`integrations/ocr/sarvam_client.py`)

Input: preprocessed (or raw) PDF. Output: `ChunkResult` list.

- `SarvamAI.document_intelligence.create_job(language="kn-IN", output_format="md")`
  → upload file → start → `wait_until_complete()` → download a zip.
- **Page count first** (PyMuPDF). `<= 10` pages → send the PDF in one job.
  `> 10` pages → chunk into overlapping 10-page windows (1-page overlap so a
  table split across a boundary isn't lost), render pages to PNGs at 200 DPI,
  zip each chunk, and process up to 8 chunks in parallel.
- Each chunk retried 3× (`RETRY_DELAYS = [5, 15, 30]`), and `run_ocr_with_retry`
  in `services/extract.py` wraps the whole thing with 3 more outer retries.
- Zip extraction pulls the `.md` text and `.json` pages/tables into a
  `ChunkResult{chunk_index, page_start, page_end, status, md_text, json_data, error}`.

`ChunkResult.status` can be `complete`, `failed`, or `complete` with an error
note for `PartiallyCompleted`. If **all** chunks fail, the OCR stage raises
`RuntimeError("All Sarvam OCR chunks failed. ...")` and the doc is marked
`failed` (`stages.py:130-133`).

### 8c. Merge (`integrations/ocr/ocr_merger.py`)

Input: list of `ChunkResult`. Output: `{total_pages, full_text, pages[], tables[]}`.

- Single chunk → trivially rebuilt.
- Multi-chunk → de-duplicate pages by absolute page number (keep first),
  detect a markdown table split across a page boundary and re-join it,
  strip embedded base64 image blobs and replace with `[OFFICIAL STAMP / SEAL]`
  or `[IMAGE REMOVED]`.
- `full_text` is assembled with `--- Page N ---` separators — this is exactly
  the text the LLM later reads.

---

## 9. Structuring & LLM Routing

### The fallback chain (`services/extract.py` + `integrations/llm/model_router.py`)

The router decides the **primary** provider per doc-type (`model_router.py`):

- **Gemini 2.5 Flash** (reasoning-heavy): `SALE_DEED`, `ENCUMBRANCE_CERTIFICATE`,
  `GIFT_DEED`, `PARTITION_DEED`, `COURT_ORDER`, `BUILDING_LICENSE`,
  `COMPLETION_CERTIFICATE`.
- **Groq llama-3.1-8b-instant** (cheap/deterministic): receipts, tax
  assessments, khata, mutation, RTC, etc.
- **Groq llama-3.3-70b**: `KHATA`, `LEGAL_HEIR_CERTIFICATE`.

`structure_document()` then builds a **fallback chain** (primary first):
`get_fallback_chain()` = primary + `[groq-70b, groq-8b, gemini]` (dedup).
For each (provider, model), it tries up to 3 attempts:

- Acquires a rate-limiter token (`wait_and_acquire(tokens=1)`).
- Calls the provider's executor.
- On error: if `is_transient_error` (503/429/500/413/rate-limit/JSON-parse) →
  backoff and retry same model; if `is_rate_limit_error` (429/413/quota/…) →
  fall through to the **next** model; otherwise → stop and raise.

### Gemini executor (`integrations/llm/gemini_executor.py`)

- Truncates OCR to `GEMINI_MAX_CONTEXT_CHARS` (800k chars).
- Uses the static prompt + schema as `system_instruction` with a per-doc-type
  **context cache** (billed cheaper). `max_output_tokens=65536`.
- Parses JSON from `response.text`, with a fenced-json fallback.
- Records tokens/cost to `LLMCallTracker` (→ Redis `llm_call_log`).

### Groq executor (`integrations/llm/groq_executor.py`)

- Tries `[model_override or llama-3.3-70b, llama-3.1-8b]`.
- `max_tokens=5000` (recently reduced from 32000 — see §12).
- On rate-limit it logs and moves to the next model; if all fail it raises
  `RuntimeError("All Groq models failed. ...")`.

### What the LLM is asked to produce

`services/schemas/static.py` defines a strict schema per doc type (e.g. for
`SALE_DEED`: `file_metadata`, `financial_summary`, `parties`, `property_schedule`,
`statutory_valuation_endorsement`; for EC: `file_metadata`, `search_criteria`,
`historical_ledger[]`). The prompt contract (`extraction_prompts.py`) demands:
valid JSON only, `null` for missing, `YYYY-MM-DD` dates, numbers as numbers,
extract ALL ledger transactions, prefer English over Kannada, never hallucinate.

---

## 10. Title Chain & Verification

Both are **one LLM call per case** on Gemini, driven by
`integrations/llm/analysis_executor.py::run_analysis()`.

### Title chain (`services/title_chain.py`)

- Reads the case bundle (structured docs) from MySQL: needs a `SALE_DEED` and
  an `ENCUMBRANCE_CERTIFICATE` with a non-empty `historical_ledger`. Missing
  either → saves a `no_transactions` / `error` status chain.
- Sends Gemini the SD's property schedule + the full EC ledger and asks it to
  classify every matched entry: `THE_SD | PREDECESSOR_TITLE |
  SUBSEQUENT_TRANSFER | DIVERGENT_BRANCH | ENCUMBRANCE | UNRELATED`, plus
  portion / share fraction / explanation.
- Merges the LLM enrichment onto the ledger, sorts chronologically, fills in
  deterministic defaults for anything the LLM missed (`_fallback_role`,
  `_default_identity`, etc.), and persists to `title_chains` (one row per case).

### Verification (`services/verify.py`)

- Same bundle; if no SD or no EC → saves `skipped`.
- Asks Gemini to compare material fields (survey/CTS numbers, locality, dates,
  parties, consideration) between the SD and EC ledger, returning
  `{items: [{field, sd_value, ec_value, status, notes}], overall_comment}`.
- Validates enums, computes a verdict deterministically
  (`_summarize`): `VERIFIED` iff zero `NOT_VERIFIED` and at least one
  `VERIFIED`; otherwise `NOT_VERIFIED` / `N/A`.
- Persists to `verification_results` and sets `cases.verification_status` +
  `cases.verdict`.

> Both are only auto-queued when **every** document structured successfully
> (`finalize.py:61`). A partial case must use the manual
> `/api/results/{case_id}/analyze` endpoint.

---

## 11. Database

### Tables & what each row means

| Table | Key fields | Purpose |
|---|---|---|
| `users` | id, email, password_hash | auth accounts (bcrypt, JWT) |
| `cases` | id, user_id, status, total/completed/failed_docs, verification_status, verdict, pipeline_logs(JSON) | one row per upload batch |
| `documents` | case_id, doc_id, document_type, status, structured_data(JSON), file_paths(JSON), input/output_tokens, cost_usd, model_used, page_count, error, retry_count, expected_type, stage_started/completed_at | one row per uploaded PDF + all extraction results |
| `title_chains` | case_id, status, chain(JSON), source(JSON), model_used, tokens/cost | one row per case |
| `verification_results` | case_id, status, verdict, summary(JSON), items(JSON), model_used | one row per case |

`structured_data` (documents) stores the full extracted JSON; `pipeline_logs`
(cases) stores the last 200 log lines; `file_paths` (documents) accumulates
`raw → preprocessed → ocr_chunks → merged_ocr → structured` paths.

### What we store unnecessarily (candidates to remove)

1. **`documents.raw_ocr_path`** — column exists (migrations + repo support it)
   but **no stage ever writes it**. The OCR path is already tracked inside
   `file_paths.ocr_chunks`. Dead column.
2. **`documents.trace_id` + `set_trace_id()`** — column and repo function
   exist but **nothing calls `set_trace_id`**. Dead (no OpenTelemetry in use).
3. **`cases.pipeline_status`** — column exists, **never written**. Dead.
4. **Redis helpers that nothing calls anymore** (`state_store.py`):
   `add_result`, `add_error`, `remove_error_for_doc`, `increment_done_count`,
   `set_doc_status` — all dead after the "MySQL is source of truth" refactor.
   The status endpoint now reads `get_case_status_payload` from MySQL. Keeping
   them is harmless but misleading.
5. **`_analytics` bloat in the persist hand-off** — the temp JSON carries
   `input_tokens/output_tokens/cached_tokens/charged_input_tokens/cost_usd`
   etc.; only a subset lands in MySQL (`input_tokens`, `output_tokens`,
   `latency_ms`, `cost_usd`, `model_used`). Not a big deal, but the payload
   could be trimmed.
6. **`structured_data` duplicates the on-disk JSON.** It's stored in MySQL
   *and* as `outputs/{case}/structured/{doc}_{TYPE}.json`. Needed as long as
   results are served from the DB, but worth noting as duplication.
7. **`cases.pipeline_logs` duplicates Redis `case:{id}:log`** — by design
   (MySQL is truth, Redis is cache), so this is fine — just keep the parity.

---

## 12. Tradeoffs & Known Issues

Ranked roughly by severity. The first two are the ones we already diagnosed in
the field.

### 12.1 Groq free-tier TPM mismatch (the "413 Request too large" errors)

- **Problem:** `groq_executor.py` sent `max_tokens=32000`, and
  `config.py` defaulted `GROQ_TPM=15000000` (a dev-tier number). On Groq's
  **free tier** the per-minute TPM limits are **12,000 (llama-3.3-70b)** and
  **6,000 (llama-3.1-8b)**. Groq's 413 `rate_limit_exceeded` counts
  `prompt_tokens + max_tokens` as "Requested" tokens, so *any* request
  reserving 32k was rejected before a single prompt token — e.g. a Kannada
  Sale Deed requested 50,531 tokens (18.5k prompt + 32k max).
- **Impact:** every doc routed to Groq (or any doc that fell back to Groq)
  failed with 413. In production data this hit the 998A8755 Sale Deed; the
  other 9 failures were a *different* cause (OCR credits, below).
- **Fix already applied:** `max_tokens=32000 → 5000` and
  `GROQ_TPM default 15000000 → 6000` (the safe shared value for both models).
- **Remaining risk:** 5k + a Kannada-heavy prompt can still exceed 6k TPM. The
  real durable fixes are (a) rely on Gemini for long docs (already primary for
  SD/EC), (b) trim OCR junk before prompt-building, (c) upgrade Groq tier, or
  (d) make max_tokens configurable per model and lower it.

### 12.2 Sarvam OCR "insufficient credits" (bulk of the failures)

- 9 of the 10 failed documents failed **before** any LLM call: Sarvam returned
  `Insufficient credits for N pages. Please add more credits or reduce the
  document size.` — the OCR account simply ran out of credits.
- **Impact:** 6 cases blocked. `run_ocr_with_retry` retries 3×+3× but the
  credit error is not transient, so retries just burn time.
- **Fix direction:** detect credit/quota errors explicitly and fail fast with
  a clear message (no pointless retries); top up or gate uploads by remaining
  credits; consider page-count-based credit pre-checks before starting a case.

### 12.3 Gemini empty-response / safety block is not logged

- The 998A8755 Sale Deed returned HTTP 200 with **empty text** from Gemini 3×
  (`json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`), then
  fell back to Groq → 413 → fail. The likely cause is a safety block
  (suspicious injected text about a "20,000 Rupee banknote" stamp in the OCR),
  but **the code never reads or logs `finish_reason` / `block_reason`**, so we
  can't confirm.
- **Fix direction:** log `response.candidates[0].finish_reason`,
  `response.prompt_feedback.block_reason`, and `safety_ratings` on empty
  responses before parsing; treat empty-response as its own error class with
  its own retry/fallback policy.

### 12.4 Progress is only doc-count based, and caps at 90%

- `get_case_job` / `get_case_status_payload` compute
  `progress = (completed+failed)/total * 90` while `processing`, and the
  frontend shows only `X/Y docs` plus the log. There is no per-stage progress
  ("stuck on OCR", "structuring 2/3", etc.). "Structured JSON saved to DB"
  appears as the *last* log line with no indication of what's next (title
  chain / verification), which is exactly the confusion seen in the UI.
- **Fix direction:** include the current stage (or doc status) per document in
  the status payload (`statusData`), and derive a stage-aware label/progress.
  After persist, emit an explicit log like "All documents structured — running
  title analysis" so the user knows the pipeline isn't idle.

### 12.5 Retry replays the entire 6-stage chain from scratch

- `start_retry_pipeline` re-runs preprocess → OCR → … for the failed doc even
  when only the LLM stage failed. Idempotency makes it *correct*, but it
  wastes Sarvam credits and time.
- **Fix direction:** let retry resume from the failed stage (persist a
  `last_completed_stage` and start the chain there), or at least skip
  re-uploading/re-merging when `merged_ocr` exists.

### 12.6 Misleading "All Groq models failed" for Gemini-primary docs

- For a doc whose primary is Gemini (SD/EC), the log first says
  "Structuring with gemini" (from `resolve_model` in `stages.py:271`), but if
  Gemini fails and Groq is hit as fallback, the surfaced error becomes
  "All Groq models failed." — which reads as if Groq was the intended
  provider. Confusing to debug.

### 12.7 Dead config / stale docs

- `.env` sets `PRIMARY_STRUCTURER=groq` but **no code reads it** (dead config).
- `README.md` still describes the pre-refactor structure (old `ai/`,
  `infrastructure/`, `routers/documents.py`, `routers/verification.py`, etc.)
  that no longer exists — it will mislead newcomers.

### 12.8 Context-cache edge case

- `gemini_client._ensure_context_cache` logs "Cached content is too small …
  min_total_token_count=1024" for short static prompts; harmless (caching just
  disables) but noisy and confusing next to real errors.

### 12.9 Cost estimation is approximate

- Cost formulas are hard-coded (Gemini $0.15/$0.60 per 1M, Groq $0.59/$0.79)
  in three places. They drift from actual billing and aren't centralized.

### 12.10 No checkpointing / no per-stage observability

- Only `documents.stage_started_at / stage_completed_at` and a monotonic
  status string exist. There's no structured per-stage timing log, no
  `finish_reason` capture, no global request-id correlation beyond
  `trace_id` (which is never populated).

---

## 13. Retry / Fallback / Error Handling — how to build it correctly

The current system already has a decent skeleton: idempotent stages, Celery
autoretry with backoff, a provider fallback chain, and MySQL as truth. The
problems are that **error classification is coarse** and **recovery is
all-or-nothing**. Here is the model to move to.

### 13.1 Classify every error first — then decide retry vs fallback vs give up

Make one `PipelineError` taxonomy and route everything through it:

| Class | Examples | Policy |
|---|---|---|
| **Transient provider error** | 429, 503, 500, socket timeout, `RESOURCE_EXHAUSTED` | Retry same provider with backoff (up to N); then fallback provider |
| **Rate-limit/quota (request-level)** | 413 `rate_limit_exceeded`, "insufficient credits" | **Do NOT burn retries.** Classify per-provider: for Groq 413, shrink the request (lower max_tokens / truncate text) or skip provider; for Sarvam credits, fail the stage with a clear user-facing message |
| **Model output error** | empty response, unparseable JSON, schema mismatch | Re-prompt once (maybe with stricter instructions), then fallback provider. Log `finish_reason`/`block_reason` to learn why |
| **Deterministic/business error** | UNKNOWN document, missing SD/EC | No retry — terminal state, require user action (already the pattern with `classification_failed`) |

Concretely:
- **Sarvam:** catch credit/quota errors and raise a distinct
  `InsufficientCreditsError` that is **excluded from autoretry** — retrying
  can't conjure credits. Show it in the UI errors list immediately.
- **Groq:** before calling, compute `estimated_prompt_tokens` (chars/1.5, or a
  tokenizer) and compare against `max_tokens + prompt_tokens` vs the model's
  real TPM; if it can't fit, **skip Groq and go straight to Gemini** instead
  of failing. Keep `max_tokens` small and per-model.
- **Gemini:** on empty `response.text`, read `finish_reason` and
  `prompt_feedback.block_reason`; if it's a safety block, don't retry the same
  content 3× — trim/rewrite the offending chunk or mark the doc for human
  review.

### 13.2 Centralize the retry policy (stop scattering it)

Today retries live in several places with different numbers: Celery task
`max_retries=5` + backoff; `extract.py` `STRUCTURE_MAX_RETRIES=3`; Sarvam
`MAX_RETRIES=3` twice (inner + outer); title/verify tasks `max_retries=2`.
Unify into one config object (per stage/provider: `max_retries`,
`backoff_base`, `backoff_max`, `jitter`, `exclude_classes`, `fallback_chain`).
One knob to tune = one place to edit.

### 13.3 Make retry resumable (skip completed work)

Store `last_completed_stage` on the document (we already persist
`stage_completed_at` and status). On retry, rebuild the chain starting at the
stage *after* the last completed one. Combined with idempotency this gives
checkpointing for free, saves Sarvam credits, and speeds recovery.

### 13.4 Never mask the real provider

When a Gemini-primary doc falls back to Groq and fails, the surfaced error
should be: `Gemini failed (<reason>); Groq fallback failed (<reason>)` — not
just the last model's error. Collect `errors[]` across the whole chain and
raise one combined message (the Groq executor already accumulates per-model
errors; `structure_document` should do the same across providers).

### 13.5 Fail fast on permanent errors, retry only on transient ones

Use a whitelist/blacklist:
- Transient set: `429, 5xx, timeout, connection errors, rate_limit,
  RESOURCE_EXHAUSTED, unparseable JSON (retry once)`.
- Permanent set (fail immediately, mark doc `failed`, log clearly):
  `4xx not in {429}`, `insufficient credits`, `invalid API key`,
  `safety block`, `UNKNOWN document`, `missing file`.

### 13.6 Log the reason for every fallback/retry

Every retry/fallback should emit a structured line: `doc_id, stage, provider,
model, attempt, error_class, decision(backoff|fallback|terminal), next_action`.
This turns the opaque "Structuring with gemini … All Groq models failed" flow
into a readable trail and gives you the data to tune limits.

### 13.7 Surface status honestly in the UI

Add the current doc stage to the status payload and derive:
- progress label: "OCR 1/2 · Structuring Sale Deed · 2/3 docs done"
- explicit post-persist message: "All documents structured — running title
  analysis"
- a per-doc stage chip (preprocessing / ocr / merging / classifying /
  structuring / persisting / failed-with-reason) so a stuck stage is visible
  instead of a silent 90% bar.

---

## Appendix A — Quick file map (read these first)

| If you want to understand… | Read |
|---|---|
| The whole pipeline entry point | `backend/services/orchestrator.py` |
| Stage logic | `backend/workers/stages.py` |
| Task wrappers + retry config | `backend/workers/tasks.py`, `workers/idempotency.py` |
| LLM fallback chain | `backend/services/extract.py`, `integrations/llm/model_router.py` |
| Gemini / Groq call sites | `integrations/llm/gemini_executor.py`, `groq_executor.py` |
| Rate limiting across workers | `integrations/llm/rate_limiter.py` |
| Redis as cache + truth rule | `integrations/redis/state_store.py` |
| Redis locks | `integrations/redis/lock.py` |
| OCR + merge | `integrations/ocr/sarvam_client.py`, `ocr_merger.py` |
| Preprocessing | `integrations/ocr/preprocessor.py` |
| Title chain + verify | `services/title_chain.py`, `services/verify.py` |
| DB schema + truth repos | `database/migrations.py`, `database/repositories/*` |
| API endpoints | `routers/cases.py`, `routers/results.py` |
| Frontend flow | `frontend/src/dashboard/VerificationDashboard.tsx`, `api/backend.ts` |
| Live evidence for issues §12.1–12.3 | `docs/PIPELINE_ISSUES_ANALYSIS.md` |

---

*Generated from the current source tree. Where this doc and the README
disagree, this doc reflects the actual code.*
