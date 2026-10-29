# ClearTitle — Full Low-Level Architecture

This document describes the implementation currently in this repository, verified
against the source. It covers the low-level architecture, every runtime flow step
(input → processing → retrieval → output → persistence), the OCR subsystem, the
verification agent and its tool loop, the result contract, memory/checkpoint
design, the database, prompts and skills, Redis internals, Docker topology, and
the tech stack. It is not a legal opinion and does not claim the product
determines legal title.

---

## Table of contents

1. [System purpose and boundaries](#1-system-purpose-and-boundaries)
2. [Tech stack](#2-tech-stack)
3. [System architecture (low-level diagram)](#3-system-architecture-low-level-diagram)
4. [Docker topology](#4-docker-topology)
5. [Configuration surface](#5-configuration-surface)
6. [Runtime flow — every step](#6-runtime-flow--every-step)
7. [OCR subsystem in depth](#7-ocr-subsystem-in-depth)
8. [Verification agent in depth](#8-verification-agent-in-depth)
9. [Result contract (schema 3.0)](#9-result-contract-schema-30)
10. [Memory architecture — how state is stored correctly](#10-memory-architecture--how-state-is-stored-correctly)
11. [Database design](#11-database-design)
12. [Prompts and skills](#12-prompts-and-skills)
13. [Redis internals](#13-redis-internals)
14. [Retrieval paths — what the LLM can see and how](#14-retrieval-paths--what-the-llm-can-see-and-how)
15. [API map](#15-api-map)
16. [PDF report generation](#16-pdf-report-generation)
17. [Frontend architecture](#17-frontend-architecture)
18. [Observability](#18-observability)
19. [Failure handling matrix](#19-failure-handling-matrix)
20. [Tests](#20-tests)
21. [Security and reliability notes](#21-security-and-reliability-notes)
22. [Source map](#22-source-map)

---

## 1. System purpose and boundaries

ClearTitle accepts property-document PDFs (Karnataka, India documents),
extracts text and structured fields, then runs an investigation agent over a
saved title chain. The agent assesses each chain transaction against selected
uploaded evidence. There are two distinct workflows:

1. **Document processing** — upload, preprocess, OCR, merge, classify,
   structure, persist.
2. **Title investigation** — establish/reuse the property identity and chain
   (Phase A), verify transactions one at a time (Phase B), expose results.

Hard boundaries:

- Document extraction success is **not** title verification.
- Agent status `done` means the run loop ended — it does not mean every
  transaction passed or that title is legally clear.
- The LLM interprets documents; the application owns procedure, IDs,
  persistence, and workflow state. The application never decides a
  transaction's legal status itself, and the model cannot bypass the gates.
- OCR/LLM artifacts are evidence-analysis outputs, not authenticity verdicts.

---

## 2. Tech stack

### Backend (Python 3.11 in Docker; 3.12 in local venv)

| Concern | Library | Where used |
|---|---|---|
| HTTP API | FastAPI 0.115 + uvicorn 0.30 | `backend/main.py` |
| Background jobs | Celery 5.4 (prefork, Redis broker/backend) | `backend/celery_app.py`, `backend/workers/` |
| Durable storage | MySQL 8 via mysql-connector-python 9.1 (pooled) | `backend/database/` |
| Cache/locks/broker | redis-py 4.6 | `backend/integrations/redis/` |
| OCR | sarvamai SDK 0.1.28 — Document Intelligence | `backend/integrations/ocr/sarvam_client.py` |
| Image processing | PyMuPDF (fitz) 1.24, OpenCV-headless 4.10, numpy, Pillow | `preprocessor.py`, OCR chunking |
| Verification LLM | OpenAI-compatible tool calling (default model `GPT-6 Luna`, base URL override supported) **or** Gemini (`google-genai` 1.45) | `backend/integrations/llm/agent_llm.py` |
| Document classify/structure LLM | OpenAI-compatible JSON mode (`DOCUMENT_PROCESSOR_MODEL`, defaults to the agent model) | `backend/services/document_processor.py` |
| Validation | Pydantic 2.8 (schemas 2.x) | `backend/services/agent_schemas.py` |
| Auth | PyJWT (HS256), bcrypt, Google OAuth 2.0 code flow | `backend/services/auth.py`, `routers/auth.py` |
| PDF report | ReportLab 4.2 | `backend/services/report.py` |
| HTTP client | httpx 0.28 (Google token/userinfo exchange) | `routers/auth.py` |

### Frontend

| Concern | Library |
|---|---|
| UI | React 19 + react-router-dom 7 |
| Build | Vite 6 + TypeScript 5.8, Tailwind CSS 4 |
| Visuals | three.js (hero background), lucide-react icons |
| Dev server | Express (`frontend/server.ts`) via `tsx`; SPA bundle served by FastAPI in Docker |

### Infra

| Concern | Choice |
|---|---|
| Containers | Docker compose: `redis:7-alpine`, `mysql:8.0`, `phpmyadmin:latest`, one application image built from the repo Dockerfile (frontend build stage `node:20-alpine` + runtime `python:3.11-slim`) |
| Task transport | Redis broker + result backend; JSON serialization; visibility timeout 7500 s |

---

## 3. System architecture (low-level diagram)

```text
                        ┌──────────────────────────────────────────────────┐
                        │                     Browser                      │
                        │  React 19 SPA (Upload, Status, OCR viewer,       │
                        │  Phase A graph, Transaction results, Cases)      │
                        └───────┬───────────────────────▲──────────────────┘
                                │ HTTP/JSON (JWT bearer  │ build_case_results()
                                │ or guest access)       │
        ┌───────────────────────▼────────────────────────┴─────────────────┐
        │  FastAPI API process (uvicorn backend.main:app)                  │
        │  ├─ routers/auth.py      register/login/me + Google OAuth        │
        │  ├─ routers/cases.py     upload/process/retry/status/delete/     │
        │  │                       replace/skip/add-files                  │
        │  ├─ routers/results.py   results/ocr/analyze/skip/report pdf     │
        │  ├─ services/results.py  payload assembly + legacy adaptation    │
        │  └─ services/orchestrator.py  builds chain+chord, resume points  │
        └───────┬──────────────────┬───────────────────┬───────────────────┘
                │ SQL (pooled)     │ cache/log/lock    │ celery delay / chord
                ▼                  ▼                   ▼
        ┌───────────────┐   ┌─────────────┐   ┌────────────────────────────┐
        │  MySQL 8      │   │ Redis 7     │   │ Celery worker (conc. 2)    │
        │  (source of   │   │  broker +   │◄──┤ ├─ preprocess_document_task│
        │  truth)       │   │  result     │   │ ├─ ocr_document_task       │
        │  users        │   │  backend +  │   │ ├─ merge_ocr_task          │
        │  cases        │   │  case cache │   │ ├─ classify_document_task  │
        │  documents    │   │  + logs +   │   │ ├─ structure_document_task │
        │  title_chains │   │  locks +    │   │ ├─ persist_document_task   │
        │  case_results │   │  rate limit │   │ ├─ finalize_case_task      │
        │  case_memory  │   └─────────────┘   │ ├─ run_case_analysis_task  │
        └───────────────┘                     │ └─ skip_cleartitle_        │
                ▲                             │    transaction_task        │
                │ SQL reads/writes            └──────┬────────────┬────────┘
        ┌───────┴────────────────────────────────────┘            │
        │  Repositories (document_repo, case_repo, agent_repo,    │
        │  user_repo, verification_repo, results accessors)       │
        │                                                         ▼
        │  ┌────────────────────────────┐          ┌──────────────────────────┐
        │  │ Integrations               │          │ Integrations used by AI  │
        │  │ ├─ sarvam_client (OCR)     │          │ ├─ agent_llm (tool loop, │
        │  │ ├─ preprocessor (OpenCV)   │          │ │  JSON mode, retries)   │
        │  │ ├─ ocr_merger              │          │ ├─ rate_limiter (Lua     │
        │  │ └─ file_utils / storage    │          │ │  token bucket)         │
        │  └────────────────────────────┘          │ └─ lock (RedisLock)      │
        └──────────────────────────────────────────┴──────────────────────────┘
                │
                ▼
        Shared filesystem (bind-mounted: identical view for API + worker)
        outputs/<case_id>/raw/            uploaded PDFs
        outputs/<case_id>/preprocessed/   enhanced PDFs
        outputs/<case_id>/ocr_raw/        per-chunk request/response zips + merged json
        outputs/<case_id>/structured/     per-doc structured JSON artifacts

  External services: Sarvam Document Intelligence (OCR) · OpenAI-compatible
  chat-completions endpoint (classify/structure/agent) · or Gemini generateContent.
```

Data ownership rule used throughout: **MySQL is the durable source of truth;
Redis is a read-cache/broker/lock; file artifacts support processing and
as a legacy fallback; conversation transcripts are never persisted.**

---

## 4. Docker topology

`docker-compose.yml` defines five services:

| Service | Image | Ports | Volumes | Notes |
|---|---|---|---|---|
| `redis` | redis:7-alpine | internal | `redis_data:/data` | broker + result backend + cache/locks; `redis-cli ping` healthcheck |
| `mysql` | mysql:8.0 | host **3307** → 3306 | `mysql_data:/var/lib/mysql` | env creates DB on first boot; healthcheck via mysqladmin ping |
| `phpmyadmin` | phpmyadmin:latest | host 8080 (localhost only) | — | local DB browser |
| `api` | built from repo Dockerfile | host 8000 | `./uploads:/app/uploads`, `./outputs:/app/outputs` | env file `.env` with overrides `MYSQL_HOST=mysql`, `REDIS_URL=redis://redis:6379/0`, `TZ=Asia/Kolkata`; healthcheck `curl /health` |
| `worker` | same application image, command overridden | internal | same bind mounts | `celery -A backend.celery_app worker --loglevel=info --concurrency=2` |

### Dockerfile build stages

```text
Stage 1 (frontend)      node:20-alpine
  ├─ npm ci (package-lock pinned)
  └─ npm run build  →  dist/                       # Vite production bundle

Stage 2 (runtime)       python:3.11-slim
  ├─ apt: gcc, build-essential (C extensions), libgomp1 + libglib2.0-0
  │        (OpenCV-headless runtime deps), curl (healthchecks)
  ├─ WORKDIR /app
  ├─ COPY requirements.txt → pip install           # cached dependency layer
  ├─ COPY backend/ frontend/
  ├─ COPY --from=build /ui/dist ./frontend/dist    # SPA baked into image
  └─ mkdir uploads outputs/structured outputs/raw_ocr
  CMD  uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Operational consequences:

- Both `api` and `worker` share one image → identical Python deps and
  identical mounted filesystem, so file paths written by stages resolve on
  the other process.
- Frontend changes require an image rebuild (bundle is baked in).
- MySQL exposure on **3307** avoids colliding with a local MySQL on 3306.
- `docker compose down -v` wipes `redis_data` + `mysql_data`.

---

## 5. Configuration surface

`backend/config.py` is the single place any `os.getenv` is read (loads `.env`
once, scrubs injected dead-proxy `127.0.0.1:9` variables). Key settings:

| Env var | Default | Used by |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | broker, backend, cache, locks |
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | `127.0.0.1/3306/root/password/property_ocr_v2` | pooled connections |
| `SARVAM_API_KEY` | — | OCR |
| `OPENAI_API_KEY`, `OPENAI_API_BASE`, `OPENAI_API_VERSION` | — | classify/structure/agent (Azure-compatible base URL optional) |
| `GEMINI_API_KEY` | — | agent provider `gemini` |
| `CLEARTITLE_AGENT_PROVIDER` | `openai` (`gemini`\|`openai`\|`luna`) | provider registry lookup |
| `CLEARTITLE_AGENT_MODEL` | `GPT-6 Luna` | agent + summarize + structure |
| `CLEARTITLE_VERIFY_MODEL_CALL_BUDGET` | `16` (clamped 3…`CLEARTITLE_VERIFY_MODEL_CALL_MAX=24`) | per-transaction model-call budget |
| `CLEARTITLE_AGENT_MAX_ATTEMPTS` | `5` | per-provider-call retries |
| `CLEARTITLE_AGENT_MAX_RAW_CHARS` | `60000` | config surface (legacy char cap) |
| `DOCUMENT_PROCESSOR_MODEL` | falls back to `CLEARTITLE_AGENT_MODEL` | classify/structure |
| `DOCUMENT_CLASSIFICATION_TOKEN_BUDGET` | `3000` | classification prefix = budget × 4 chars |
| `GEMINI_RPM` / `GEMINI_TPM` / `GEMINI_BURST` | `30` / `4000000` / `5` | Lua token bucket |
| `MAX_UPLOAD_SIZE_MB` | `100` | upload guard |
| `JWT_SECRET_KEY/ALGORITHM/EXPIRE_MINUTES` | dev default / HS256 / 7 days | auth |
| `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI/…` | localhost defaults | OAuth |
| `CORS_ORIGINS` | localhost 8000/3000 | SPA |
| `PIPELINE_LOCK_ENABLED` | `true` | Redis locks around pipeline/agent |

Secrets must be supplied via `.env`; none are committed.

---

## 6. Runtime flow — every step

### 6.1 Authentication

| Step | Component | Behavior |
|---|---|---|
| Register | `POST /api/auth/register` → `user_repo.create_user` | bcrypt hash, `users.id` = `uuid4().hex`, unique email enforced (409 on duplicate); returns HS256 JWT |
| Login | `POST /api/auth/login` | bcrypt verify → JWT (`access_token`, 7-day default expiry) |
| Session | `GET /api/auth/me` via `Depends(get_current_user)` | decodes `Authorization: Bearer` |
| Google OAuth | `/auth/google/callback` (site-root router) | state cookie (`ct_oauth_state`) → code exchange → userinfo → `get_or_create_user_by_email` → JWT → redirect to frontend login page with token |
| Guest models | `Depends(get_optional_user)` on case routes | `cases.user_id IS NULL` cases are open to anyone holding the case id; owned cases require the matching JWT (`_enforce_access`) |

### 6.2 Upload (initial and additional)

`POST /api/upload` / `POST /api/case/{case_id}/upload` in `routers/cases.py`:

1. Validate: every file `.pdf`, size ≤ `MAX_UPLOAD_SIZE_MB` (per-file).
2. Generate `case_id` (8-char hex style ids such as `0C3695AD`), assign doc ids
   `DOC_001…DOC_NNN` sequentially (`start_idx + i + 1` so added files continue
   numbering).
3. Save bytes under `outputs/<case_id>/raw/` (original filenames preserved
   into `documents.filename`).
4. Persist: `case_repo.init_case` (or `upload_docs_reset` for added files;
   `total_docs` updated) + `document_repo.init_document` per doc
   (`files_paths = {"raw": …}`).
5. Warm Redis (`init_case` / `add_files_to_case`): `case:<id>:meta`,
   `case:<id>:files`, fresh log.
6. Additional-upload extras: optional `transaction_id` form field marks
   `evidence_retry_tx_id` in `case_memory` (validated: tx must be in the
   skip list, in the saved chain, and pending); clears stale marker when
   absent; acquires `case:<id>:pipeline_lock`; rejects while a pipeline run
   is active (409).
7. Respond `{case_id, files[]}` — pipeline is *not* auto-started for the
   initial upload until `POST /api/process/{case_id}`.

### 6.3 Pipeline orchestration (`services/orchestrator.py`)

```text
start_case_pipeline(case_id)
  files ← Redis case:<id>:files (fallback MySQL)
  todo ← files whose documents.status ∉ {structured, skipped}
  if todo empty → finalize_case_task.delay([], case_id)
  else:
    chord( per-doc chain( preprocess.si → ocr.si → merge.si
                          → classify.si → structure.si → persist.si )
          )  →  finalize_case_task.s(case_id)
```

- Documents run **concurrently** (chord over per-doc chains); stages within a
  document run **sequentially** (Celery `chain` of `.si` immutable signatures).
- `start_retry_pipeline` (used by `POST /api/retry/{case_id}` after a failure)
  rebuilds the chain **suffix** from the last durable checkpoint:

```text
_resume_stage(checkpoint):
  has structured_data + document_type        → resume at "persist"
  has document_type + merged OCR             → resume at "structure"
  has merged OCR                             → resume at "classify"
  otherwise                                  → resume at "preprocess"
```

- `POST /api/case/{case_id}/doc/{doc_id}/replace` or `/skip` resolve a
  classification-failed document: replace swaps the file and queues a
  transaction-scoped retry; skip marks `SKIPPED` and (via a fresh finalize)
  allows verification to proceed without it.

### 6.4 Celery task layer (reliability contract)

`workers/tasks.py` + `workers/idempotency.py` + `domain/state_machine.py`:

- Every stage task is wrapped by `idempotent_stage(entry_stage, complete_stage)`:
  1. Read `documents.status` from MySQL.
  2. If status is terminal-failed (`classification_failed`, or `failed` with
     zero retries consumed) → return `{skipped}` so the rest of the chain
     short-circuits.
  3. If the current stage is already past `complete` (IntEnum comparison,
     `Stage 0…12`; `complete`/`processing`/`pending_retry` map to reliable
     equivalents) → skip (idempotent re-delivery).
  4. Mark `entry` stage in MySQL **before** running; mark `complete` after.
  5. On exception: if retries exhausted or exception class is in the task's
     `exclude_from_autoretry` (`ClassificationFailed`, `OcrInsufficientCredits`)
     → write `failed`/`classification_failed` + error, log to the pipeline
     log, and return `{status: failed}` instead of raising further.
  6. Otherwise re-raise for Celery autoretry.

- Task autoretry: any `Exception`, exponential backoff capped at 120 s with
  jitter, `max_retries=5`, `acks_late=True`.
- Celery app-wide (`backend/celery_app.py`): JSON serialization,
  `task_track_started`, `task_acks_late`, `task_reject_on_worker_lost`,
  `worker_prefetch_multiplier=1`, `visibility_timeout=7500` (> the 7200 s hard
  time limit so a killed task reappears), soft limit 3600 s, hard limit 7200 s,
  `result_expires=86400`, chord join timeout 7200 s.
  Tasks registered via `include=` list: `agent_tasks`, `finalize`, `tasks`,
  `title_chain_tasks`.
- Stage threading: `workers/stage_adapter.py` builds a `StageContext`
  (ports: `llm`, `cache`, `storage`, `state`) and calls
  `stage.invoke(ctx, input)`; `workers/stages.py` contains all stage logic;
  nothing else touches stage-level code.

### 6.5 The six document stages (exact inputs/outputs)

All stages persist through `document_repo.update_document_status`, which can
write status, document_type, page_count, structured_data, merged_ocr_text,
summary, file_paths, error, retry_count, and usage analytics
(input_tokens/output_tokens/latency_ms/cost_usd/model_used). Every stage
emits human-readable pipeline-log lines through `append_log` (MySQL-first,
Redis replica).

**Stage 1 — `PreprocessStage`** (`PreprocessStage.invoke`)
- Reads: `documents.file_paths["raw"]` from MySQL.
- Opens the PDF with PyMuPDF, renders every page at **200 DPI**
  (`fitz.Matrix(200/72)`), then per page, in a `ThreadPoolExecutor` (OpenCV
  releases the GIL):
  1. grayscale →
  2. **deskew**: Canny(50,150) edges → HoughLines, collect θ within ±15°,
     median angle, `warpAffine` with `BORDER_REPLICATE` (skip if |angle| < 0.3°) →
  3. **denoise** only when the page is actually noisy (`std(gray) > 15.0`,
     clean digital renders sit < 8): `fastNlMeansDenoisingColored(h=10,
     hColor=10, template=7, search=21)` — skipping avoids O(N²) search cost
     and text blur →
  4. **CLAHE** clip 2.5 on the L channel of LAB (faded stamps) →
  5. **unsharp** mask (Gaussian σ=3, addWeighted 1.5 / −0.5).
- Writes: `outputs/<case_id>/preprocessed/<doc>_prep.pdf` (pages embedded as
  quality-92 JPEG), `file_paths["preprocessed"]`, status `preprocessed`.
- Failure policy: **non-fatal** — logs a warning and records the *original*
  PDF as the preprocessed path so OCR can proceed.

**Stage 2 — `OcrStage`** (deep dive in §7)
- Reads: preprocessed-or-raw path.
- Calls `extract.run_ocr_with_retry` → `sarvam_client.run_sarvam_ocr` →
  list of `ChunkResult` dataclasses (chunk_index, page_start, page_end,
  status, md_text, json_data, error).
- Writes: `ocr_raw/<doc>_chunks.json` (asdict list), `file_paths["ocr_chunks"]`,
  status `ocr_done`.
- Failures: any "insufficient credits" chunk → `OcrInsufficientCredits`
  (non-retryable, message tells the user to top up credits); zero complete
  chunks → `RuntimeError` listing per-chunk errors; `increment_retry`
  recorded; re-raised for autoretry. Partial chunk failures only log warnings
  and are merged later (deduplication tolerates them by page).

**Stage 3 — `MergeStage`**
- Reads: `ocr_raw/<doc>_chunks.json`.
- `ocr_merger.merge_chunked_outputs` (§7.3) builds the unified document dict.
- Page count is **overridden with the physical PDF page count** via
  `fitz.open(source_pdf).page_count` — OCR-emitted page labels/numbers may be
  wrong or hallucinated, so displayed totals come from the source file.
- Writes: `ocr_raw/<doc>_merged.json`; and to MySQL:
  `merged_ocr_text` (**canonical evidence text** for the entire system),
  `page_count`, status `merged`, `file_paths["merged_ocr"]`.
- Failure: `increment_retry` + raise (autoretry from the last checkpoint).

**Stage 4 — `ClassifyStage`**
- Reads: canonical OCR **from MySQL** (`get_document_ocr_text`) with the
  merged JSON artifact as legacy fallback (`_read_merged_ocr`).
- `document_processor.classify_document`:
  - First a deterministic rule: Karnataka RDPR **Form 9 / e-Swattu** detector
    (`_is_e_swattu_form9`) matches ನಮೂನೆ 9/`form no. 9` plus the RDPR
    department heading or "e-swattu" — matches are classified `E_SWATTU`
    without an LLM call (analytics flagged `model: "rule-based"`).
  - Otherwise one JSON-mode completion over a **bounded prefix** of the OCR
    (first `3000 × 4 = 12000` chars), system prompt instructs:
    property-related records (including adverse facts, mortgages, disputes)
    are always useful (`is_property_related=true`),
    `needs_user_action=true` **only** for property-unrelated documents; Form
    9 classification even when a receipt form coexists; completion
    certificates subclassified by issuer → `…_BY_ARCHITECT` vs
    `…_BY_GRAM_PANCHAYAT` (post-verified by header regex
    `_completion_certificate_subtype`).
- Non-property document → `UnsupportedDocumentError` → status
  `classification_failed` with the user-facing message →
  `ClassificationFailed` (excluded from autoretry) → surface in
  `GET /api/results/{case_id}` `needs_action` with replace/skip URLs.
- Writes: `document_type`, analytics, status `classified`.
- `classify → type retrieval`: `retrieve_schema()` normalizes the model label
  and resolves it against `SCHEMA_MAP` (22 document types, see §12.4) via
  exact match, alias table (`MODT`→`MEMORANDUM_OF_DEPOSIT`, `PAHANI`→
  `RTC_PAHANI`, `EC`→`ENCUMBRANCE_CERTIFICATE`, …) and word-subset matching.
  A completely novel type is allowed through with `schema=None`.

**Stage 5 — `StructureStage`**
- Reads: document_type from MySQL, canonical OCR again from MySQL.
- `document_processor.extract_document`: **second, separate LLM turn** (full
  OCR, `max_tokens=16000`, JSON mode):
  - With a schema: "use ONLY the retrieved schema; fill unknowns with
    null/empty lists; no extra keys" + strict-fidelity preamble (extract only
    explicitly present information; never repair OCR errors / infer digits or
    parties; preserve spellings verbatim).
  - Without a schema: exhaustive `all_information` capture — sections,
    fields, records, and uncategorized text in source order, no dedup.
  - Type-specific overlays appended to the system prompt: **EC ledger
    rules** (date-starts-transaction; blank-date rows append to the previous
    dated transaction even across page boundaries; never split a dated
    transaction; never treat header numbers/page labels as serials; map
    parties only from indicated columns; only labeled consideration/market
    value as financials); **E_SWATTU** rules (preserve all Form 9 sections
    and conflicting spellings; ignore an embedded Receipt Form 3 section
    entirely; keep duplicate certificates separate); **completion
    certificates** (issuer identity from the heading, reference-number vs
    date disambiguation, full certificate_description paragraphs, referenced
    earlier certificate kept separate).
  - A separate top-level `summary` (2–3 sentences ≤75 words) is mandatory —
    the response is rejected if absent; this pre-warms `documents.summary`
    so the agent's `ensure_summaries` usually needs no extra LLM call.
- Writes: `structured_data`, `summary`, analytics, status `structuring` →
  (persist stage completes it). On anything else: status `failed` + raise.

**Stage 6 — `PersistStage`**
- Reads: document_type + structured_data from MySQL, merged json page count.
- If `document_type == ENCUMBRANCE_CERTIFICATE`:
  `shared/ec_ledger.normalize_ec_structured` runs deterministic **post-OCR
  table repair**: rows missing both an execution date **and** a registration
  reference are page-split continuation rows — their filled cells are merged
  into the preceding dated transaction (boundaries keyed per direction,
  longer strings kept); a genuine EC record always carries both fields.
- Writes: `outputs/<case_id>/structured/<doc>_<TYPE>.json` **best-effort**
  (an `OSError`/full disk must not discard a valid DB extraction — logged and
  skipped); `file_paths["structured"]`; status `structured` (terminal) with
  final page_count.

### 6.6 Finalization (`workers/finalize.py::finalize_case_task`)

The chord callback runs once after **all** documents of the case finish:

1. `case_repo.recompute_case_status` (counts completed/failed docs).
2. Computes overall case status: `failed` (all failed), `complete` (no
   failures), `partial` (mixed) → `set_case_status` (MySQL-first + Redis cache)
   and appends `-- Pipeline done: X complete, Y failed --`.
3. Releases the pipeline lock (`force_release`).
4. Auto-agent trigger `_should_start_agent(docs, memory)`: true when any doc
   is `structured`, or memory holds `paused_transaction` / `pending_tx_ids` /
   `evidence_retry_tx_id` / a pending `current_tx_id`. It then queues
   `run_case_analysis_task(case_id, resume_paused, retry_skipped_tx_id)`
   with:
   - `retry_skipped_tx_id` = `memory["evidence_retry_tx_id"]` (explicit
     user-selected skipped transaction being retried with new evidence), or
   - `resume_paused = True` when a paused transaction checkpoint exists, or
   - neither → fresh full analysis (first processing of the case).
5. Verification never runs concurrently with the pipeline because finalize is
   the chord callback — it fires exactly when processing concluded.

> Initial chain/verification analysis is otherwise queued explicitly by
> `POST /api/results/{case_id}/analyze` (dashboard action). Document
> finalization alone only re-queues when a resume checkpoint exists or the
> case has just become processable for the first time through this path.

### 6.7 Agent task queueing semantics

`workers/title_chain_tasks.run_case_analysis_task(case_id, resume_paused,
retry_skipped_tx_id)` dispatches to the service layer and appends a
user-visible pipeline-log line for each outcome:

| Ended as | Log line |
|---|---|
| `done` | `✓ Transaction verification pass complete` |
| `paused` | `⚠ Verification paused — a document is required to continue.` |
| `error` | `✗ Verification failed: <reason>` |

`workers/agent_tasks.skip_cleartitle_transaction_task(case_id, tx_id)` wraps
`services.cleartitle_agent.skip_transaction` — `tx_ref` may be a stable tx id
**or** a 1-based sequence, so step 4 is fully reversible from the UI.

---

## 7. OCR subsystem in depth

```text
raw PDF ──► Preprocess (OpenCV enhance, 200 DPI) ──► Sarvam Document Intelligence
                                                        │
        ≤ 10 pages ► single .pdf upload job             │ async job: create_job
        > 10 pages ► render 200 DPI PNGs →              │ → upload_file → start →
                     zip per 10-page chunk (overlap 1)  │   wait_until_complete
                     up to 8 chunks in parallel         │ → download_output(zip)
                                                        ▼
                                       per-chunk response zip: .md + .json
                                                        ▼
                          merge_chunked_outputs → unified doc dict
                          {total_pages (physical), full_text "--- Page N ---"
                           per page, pages[] with absolute_page_number,
                           tables[] tagged source_page}
                                                        ▼
                          MySQL documents.merged_ocr_text  (canonical)
                          + artifacts under outputs/<case_id>/ocr_raw/
```

Key numbers and mechanics (`sarvam_client.py`):

| Parameter | Value | Purpose |
|---|---|---|
| `CHUNK_SIZE` | 10 pages | Sarvam hard limit |
| `CHUNK_OVERLAP` | 1 page | continuity across chunk boundaries |
| `MAX_WORKERS` | 8 | parallel chunk jobs |
| `MAX_RETRIES`, delays | 3 attempts, sleep [5,15] s between | transient OCR failures |
| language / format | `kn-IN` (Kannada+English), markdown | regional documents |
| Long-doc rendering | 200 DPI PNGs, page re-indexed from `0001` **inside each zip** | Sarvam orders pages within a chunk by zip name |
| Job statuses | success = `Completed`/`PartiallyCompleted` | partial completion recorded as chunk error text |
| Quota errors | "insufficient credits" → abort immediately (non-retryable), surfaced as `OcrInsufficientCredits` | actionable user message |

`ChunkResult` (dataclass): `chunk_index, page_start, page_end, status, md_text,
json_data, error`.

**Merger** (`ocr_merger.py`):

1. `_extract_pages` — normalize each chunk to absolute page numbers
   (`page_start + local - 1`); clean content (below). Fallback chain: no
   `pages[]` JSON → split markdown on `Page N Of M` footer markers → last
   resort one synthetic page from the whole chunk.
2. `_deduplicate_pages` — overlap pages dedupe by absolute number; **the
   earlier chunk wins**.
3. `_detect_merge_split_tables` — a page ending with an open table row and a
   next page beginning with a row but *no* header separator (`|---|` line)
   is a split table: the continuation is appended into the earlier page and
   the continuation page body emptied (marshal-safe, `_merged_into` marker).
4. `_clean_content` — replaces Sarvam-embedded base64 stamp/seal images with
   the placeholders `[OFFICIAL STAMP / SEAL]` / `[IMAGE REMOVED]`, collapses
   excess blank lines.
5. `_build_output` — full text assembled with `\n\n--- Page N ---` markers
   (these markers are exactly what page citations in the agent's provably-read
   OCR follow), tables copied with `source_page`.

Receipts: `documents.merged_ocr_text` becomes the single canonical evidence
text the verification agent later reads in chunks; the merged JSON remains a
processing artifact and legacy fallback.

---

## 8. Verification agent in depth

Module map:

| File | Role |
|---|---|
| `services/cleartitle_agent.py` | orchestration: lock, phase A, ordered transaction loop, pause/skip/resume/retry, memory updates, outcome sync |
| `services/agent_runtime.py` | one generic bounded model⇄tool loop |
| `services/agent_tools.py` | tool schemas + handlers + all validation gates + canonicalization |
| `services/agent_schemas.py` | Pydantic contracts, status enum, legacy read-adapter |
| `database/repositories/agent_repo.py` | durable persistence for chain/results/memory/documents access |
| `integrations/llm/agent_llm.py` | provider-agnostic `complete_json` / `complete_with_tools` |
| `prompts/*`, `skills/*` | instructions (§12) |

### 8.1 Entry and run-id discipline

`POST /api/results/{case_id}/analyze` → Celery task → `run_agent(case_id)` →
`_run_with_lock`. All entry modes (fresh/resume/retry/reverify) funnel here.

`_run_with_lock` acquires `case:<id>:agent_lock` (Redis `SET NX PX` with
token + Lua-guarded release + running refresh timer, TTL 30 min) when
`PIPELINE_LOCK_ENABLED`. Non-acquired → `{status: busy}`. Lock failure
degrades to lockless (logged) rather than blocking verification.

A `run_id` (`uuid4`) is stamped on every log line (`agent_run_start`,
`agent_model_call`, `agent_tool_call`, `agent_tool_rejected`,
`agent_result_persist_attempted/persisted`, `agent_loop_stop`,
`agent_transaction_*`), and `ctx.run_id` flows through the whole pass.

### 8.2 Phase A (chain creation/reuse)

`_run` reads the persisted chain from `title_chains` (`agent_repo.get_agent_result`).
If it exists with a `title_chain`, it is **reused** — a resume never rebuilds
the chain. Only then:

1. `ensure_summaries` — for any document lacking a summary, generate one
   (`agent_summary.txt` over the first 6000 chars of canonical OCR,
   `complete_json`) and persist to `documents.summary`. A summary failure is
   non-fatal (placeholder "(summary unavailable)"). The structuring stage
   already writes `documents.summary` from its own extracted `summary` field,
   so usually nothing extra needs to be generated.
2. Build the Phase A conversation:
   ```text
   system: title_chain_system.txt
   user:   MANDATORY SKILL (skills/title_chain/skill.md — read from disk)
         + title_chain_task.txt
         + manifest lines: "<doc_id> | citation filename | summary"
   ```
3. `run_tool_loop(phase="phase_a")` with tools `[list_documents,
   get_document_text, save_phase_a_result, finish]` and a **80-step budget**.
   Note this Phase A `list_documents` variant filters nothing by phase; the
   model is expected to inspect summaries and read OCR of relevant docs.
4. `save_phase_a_result` validates heavily before persisting
   through `agent_repo.save_phase_a_result` into the three dedicated
   `title_chains` columns (`property_identity` JSON, `title_chain_graph`
   LONGTEXT, `detailed_chain` JSON) via `INSERT … ON DUPLICATE KEY UPDATE`.
   → `ctx.saved_phase_a_result`; loop terminates (`finished=True`).
5. Resilience: `AgentLLMError` after a successful durable save is *not*
   treated as failure ("Phase A saved but final model turn failed" warning).
   Phase A ending without a saved result raises and the whole run is recorded
   as an error — there is no silent half-built chain.

### 8.3 Transaction flattening (`_phase_a_transactions`)

Each `detailed_chain` entry becomes exactly one verification transaction:

```python
transaction = documented_transaction (dict)
 + tx_id        = entry.tx_id or PA-TC-{position:04d}   # stable internal id
 + sequence     = position							   # 1-based chain order
 + is_current_owner_transaction = (position == len(chain))
 + related_events = entry.related_events or []
 + chain_position = entry.chain_position
 - for succession/inheritance/death types: executed_date forced None
   (a death date is never an instrument execution date)
```

Legacy chains (stored under the old `chain` JSON) are adapted in load
(`get_agent_result'): legacy transaction dicts are wrapped as
`{tx_id, chain_position, documented_transaction, related_events: []}`
without rewriting rows.

### 8.4 Ordered transaction loop (`_run` core)

```text
docs ← get_agent_documents (doc_id, filename, type, status, summary — never OCR)
memory ← get_agent_memory
set agent_status=running; memory.stage=verifying …
verified_tx_ids ← []
for transaction in transactions:                # chronological order (root → current owner)
    if run scoped to explicit transaction_ids and tx not in it → skip
    if tx in skipped_this_run (set)             → skip
    previous ← get_transaction_result(case_id, tx_id)
    if previous is terminal (not fresh)          → skip  # never re-verify
    memory: current_tx_id=tx, stage=verifying_transaction → _save_state(running)
    upstream_context ← _build_upstream_context(  # saved state of earlier links
        case_id, phase_a, sequence)              # (tx_id, sequence, status,
                                                 #  report_excerpt,
                                                 #  outstanding_required_documents)
    ctx ← _verify_transaction(...)               # one tool loop per tx; the
                                                 # instruction embeds an
                                                 # --- UPSTREAM CHAIN CONTEXT --- block
    if result_error → raise (agent error state)
    if nothing saved and no missing request → raise
    verified_tx_ids.append(tx_id)
    re-read saved result for truth
    log saved status + stop reason + call counts
    if missing requests or status == PENDING_NOT_VERIFIED:
        if run was scoped (resume/retry/re-verify):
            _refresh_downstream_results(changed=verified_tx_ids)
        pause checkpoint (§10.4) → return {"status": paused, missing_documents}
    else:
        memory.last_transaction_{id,status,summary} (report excerpt),
        last_evidence_requirements, last_reviewed_document_ids,
        recompute completed_tx_ids (terminal results) and
        pending_tx_ids (PENDING_NOT_VERIFIED) from the DB,
        clear current_tx_id → _save_state(running)
end
if run was scoped (transaction_ids is not None):
    _refresh_downstream_results(changed=verified_tx_ids)
    # textual only: per downstream result, refresh transaction_metadata.chain_context
    # from DB truth + the report's '## Upstream dependency' section (one small LLM
    # section rewrite while an upstream link is unverified; deterministic section
    # removal once every upstream link is verified).
    # No OCR reads, no verification passes, statements/citations/status untouched.
memory.stage=done; completed/pending+missing recomputed from DB
overall ← _overall_transaction_status(all results)
_save_state(done); _sync_case_verdict("complete", overall)
return {"status": done, "overall_status": …}
```

**Dependency semantics.** Chain verification is sequential and dependency-aware:
`c→d` is verified knowing whether `c` holds the property — a fact established by
the `b→c` result. Each verifier receives the saved state of earlier links as
read-only prompt context (`_build_upstream_context`: status of every upstream
link, a short excerpt of the previous link's saved report, and the outstanding
document requests of any unresolved upstream link). It must not re-verify how
its transferor acquired the property, must never request an upstream link's
documents, and — when an upstream link is unverified — states that dependency
once in its own report's `## Upstream dependency` section while still being
judged on its own evidence. A downstream transaction whose own
documents verify fine keeps `VERIFIED_WITH_AVAILABLE_EVIDENCE` (or
`ISSUES_IDENTIFIED`) plus the dependency note; because
`_overall_transaction_status` requires every link terminal-verified for a
verified case, the case can never report `CLEAR_TITLE` while an upstream link is
pending. Every save also persists `transaction_metadata.chain_context =
{upstream_unverified: [{tx_id, status, missing}]}` computed from DB truth by
`_upstream_chain_context` (agent_tools).

Terminality (`_is_terminal_transaction_result`) rules:

| Status | Terminal? |
|---|---|
| `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED` | yes |
| `INCONCLUSIVE` with unchanged `_document_manifest` | yes |
| `INCONCLUSIVE` with a changed manifest (new/removed/reprocessed docs) | **no** → re-verified on the next run |
| any result carrying `_verification_checkpoint` (`bounded_stop`, `repeated_tool_call`) | **no** → retried |
| `PENDING`, `IN_PROGRESS`, `PENDING_NOT_VERIFIED`, missing | no |

Overall status: `ISSUES_IDENTIFIED` dominates; else all-terminal-verified →
`VERIFIED_WITH_AVAILABLE_EVIDENCE`; else `INCONCLUSIVE`. Verdict mirror:
`CLEAR_TITLE` only if overall verified; `ATTENTION_REQUIRED` otherwise;
`N/A` for pending-through-error states. Any unexpected exception →
`stage=error + error text` in memory, `agent_status=error`, verdict `N/A`.

### 8.5 The tool-calling loop (`agent_runtime.run_tool_loop`)

```python
while step < max_steps:
    if ctx.finished: break
    resp = complete_with_tools(messages, tools=tools_for(phase),
                               system=system, task="phase:run=<id>:tx=<id>")
    log agent_model_call (provider, model, call #, budget, attempts, latency, usage)
    if no tool_calls: break                      # model finished talking
    messages.append assistant{content, tool_calls}
    for call in resp.tool_calls:                 # execute each in order
        if ctx.finished: break
        result = dispatch(ctx, call.name, call.args)      # never raises
        _grant_recovery_budget(...)                       # +8 on recoverable errors
        if fingerprint-duplicate: inject
           {"duplicate_call": true,
            "next_step": "This exact action already ran …"}
        if extension reserved: max_steps = min(max_steps+8, 24)
        log agent_tool_call (+ agent_tool_rejected with diagnostics)
        messages.append tool{tool_call_id, name, content=json.dumps(result)}
    if ctx.finished: stop_reason="persisted_result"; break
else:
    stop_reason = "model_call_budget_exhausted"
```

Loop-level guarantees:

- **Bounded**: verify budget `16` model calls by default (env-tunable, floor 3,
  ceiling 24); Phase A fixed 80. The `while/else` ensures every exit records a
  `stop_reason` (`model_stopped_without_result`, `persisted_result`,
  `finished`, `model_call_budget_exhausted`, plus `existing_result_preserved`,
  `existing_pending_checkpoint_preserved`, `bounded_stop_inconclusive_saved`
  set by the orchestrator).
- **Recovery budget**: exactly once per transaction, when a tool rejects with
  one of the known recoverable evidence errors ("whose complete OCR was not
  reviewed", "must be read for every selected supporting document") the runtime
  reserves 8 extra steps instead of
  letting the model fail (also granted explicitly via
  `request_additional_verification_calls`).
- **Duplicate defense**: `(name,args)` pairs fingerprinted (sorted-JSON);
  repeats return the cached result plus a `next_step` instruction, and
  `repeated_tool_calls` are counted; cache survives only inside the current
  transaction. A stop reason `repeated_tool_call_limit` upstream keeps the
  checkpoint safe.
- **Error traffic is JSON**, never exceptions: `dispatch` catches
  `SchemaValidationError` (with its issue list) and any other exception into
  `{"error": …, "issues": [...]}` tool messages.

### 8.6 Verify-phase tool catalog and gates

Tool schemas for `save_transaction_result` are generated from the canonical
Pydantic schema (`TransactionVerification.model_json_schema()` with `$defs`
inlined) — the model writes directly against the contract.

**Phase navigation tools**

| Tool | Gate that must hold first | Behavior |
|---|---|---|
| `list_transactions` | — | compact chain listing from active chain (ids, sequence, type, dates; parties when legacy shape) |
| `get_transaction` | only the **active** tx may load (`tx_id != ctx.current_tx_id` → error) | returns transaction JSON **with `source_refs` removed** so Phase B re-derives evidence from OCR + prior persisted result (hidden entirely on fresh re-verification) |
| `record_evidence_requirements` | active tx; non-empty typed list | locks after listing: post-list changes rejected — "start a controlled new transaction review" |
| `list_documents` | recorded requirements (verify phase) | returns doc_id, filename, type, status, summary for every non-EC document plus a `scope` narrative; the agent alone decides from the summaries what to select — the system adds no candidate suggestions; ECs filtered out by type **or** filename stem (`_is_phase_a_only_document`) |
| `get_document_metadata` | listed docs only | metadata only — `structured_data` is **stripped** (structured extraction is never offered as evidence) |
| `select_documents` | requirements + listing complete | only ids returned by `list_documents`; selections **accumulate**; logs `agent_documents_selected` |
| `get_document_text` | selected; doc status ∈ {`structured`,`complete`,`completed`} | chunk read from canonical `merged_ocr_text` (from MySQL through `agent_repo.get_document_raw_text`), cache per doc; pagination `start_char`/`max_chars` (default 40 000, cap 200 000); **rejects overlapping re-reads** with `next_start_char`; records read ranges; returns `{total_chars, start_char, next_start_char, has_more, text}` |

**Budget**

| `request_additional_verification_calls` | one-time | requires honest 12–400-char `next_step`; grants +8 calls (hard cap 24) |

**Persistence (transaction-terminal) tools**

| Tool | Gates that must hold | Behavior |
|---|---|---|
| `save_transaction_result` | see below | validate → canonicalize → upsert into `case_results`; sets `finished=True` |
| `request_missing_documents` | requirements + listing done | forces `status=PENDING_NOT_VERIFIED`, same validation, persists, returns `{paused: true, required_documents}`, `finished=True` |
| `finish` | a result already saved or a missing request exists | sets `finished=True` only; used in Phase A after save |

The complete verification-save gate chain (in `_h_save_transaction_result`
→ `_canonical_verification` → validators):

1. **Full-OCR gate** — a terminal status requires ≥1 selected document and
   every selected document read to 100 % of its length
   (`_has_read_full_text` unions recorded ranges); otherwise error and
   `ctx.result_error` set.
2. **tx_id/sequence binding** — tx_id must equal the active tx; sequence must
   equal the chain-derived expectation (PA-TC number fallback).
3. **Canonicalization** (`_canonical_verification`):
   - merges prior `transaction_metadata` and appends fresh app-side snapshot
     (`_current_transaction_metadata`: type/dates/registration/parties/…
     with regex fallback for parties from summary points, removal of
     "(EC entry; instrument not supplied)" phrasing, `related_events`
     without source refs, `_document_manifest` snapshot);
   - strips any `_verification_checkpoint` the model might set;
   - `reviewed_document_ids` = union(prior persisted, this run selected)
     minus EC-only docs; unknown ids rejected;
   - `verified_at` = now only for terminal statuses, else null;
   - `schema_version="3.0"`;
   - **citation validation**: every `cited_documents` entry must exist in the
     case, must not be an EC, and (unless that exact `(doc_id, pages)` citation
     is already retained in the prior result's `cited_documents`) must be
     selected AND fully OCR-read in this run;
   - **upstream anchor gate**: while `chain_context.upstream_unverified` is
     non-empty, the report must contain the exact `## Upstream dependency`
     heading;
   - required_documents dedupe; `for_transaction` must belong to the active tx;
   - partial-call inheritance: missing `cited_documents`/`required_documents`
     inherit prior arrays; explicit empty arrays are deliberate updates.
4. **Schema validation** (Pydantic) then compactness gate: the report is capped
   at 20 000 characters; `required_documents[i].reason` must not repeat a
   report sentence. (Report length targets are advisory — only duplication and
   runaway length fail.)
5. **Missing/`PENDING_NOT_VERIFIED` sanity** — a pending result must contain
   ≥1 `required_documents` entry (otherwise rejected in favor of
   `INCONCLUSIVE`).
6. **Persistence re-validation** at the repo boundary — `agent_repo.save_
   transaction_result` validates again, locks (`SELECT … FOR UPDATE`),
   removes the matching `tx_id` item, appends, sorts by sequence, then
   upserts the one per-case row.

Response after a save: `{saved, tx_id, status}` — or
`{saved, paused: true, tx_id, required_documents}` when pending. Persistence
is the transaction's terminal action on purpose: the model cannot reopen the
investigation after saving.

**Safe checkpoints** (`_verify_transaction` in cleartitle_agent): a bounded
run that ends without any saved result/missing request either preserves the
previously persisted outcome (pending → new missing request,
`existing_pending_checkpoint_preserved`; other → `existing_result_preserved`,
error nulled) or persists an honest fallback result:

```json
{ "status": "INCONCLUSIVE",
  "report": "## Conclusion\n\nThe verification could not complete its evidence
             checks within this run; no verification claim is made.",
  "transaction_metadata": {"_verification_checkpoint": "bounded_stop"}, … }
```

Checkpointed results are deliberately **non-terminal** and re-run later; it
is never promoted to verified and never silently dropped.

### 8.7 Pause / skip / resume / retry semantics

| Action | Mechanism | Effect on verification results |
|---|---|---|
| Pause | `PENDING_NOT_VERIFIED` saved at the moment the tool ran; memory records `paused_transaction`, `missing_documents`, `pending_tx_ids`, `next_action`; `agent_status=paused` | run returns early; downstream transactions untouched |
| Skip (`…/agent/skip/{tx_ref}`) | `_skip_transaction_locked`: only the currently paused & pending tx; adds to `skipped_tx_ids`; writes memory narrative | **never rewrites the result** (skip is navigation state only); then `_run(skip_tx_ids=…)` continues to later transactions |
| Resume (after upload finalize or explicit) | resume from memory: paused tx must exist in saved chain; `transaction_ids = {paused}` **only**, `skipped = skip set − paused` | paused tx re-verified alone with prior result preserved as context; then `_refresh_downstream_results` textually updates every later result (chain_context + the report's `## Upstream dependency` section) — downstream transactions are **never re-verified** and their OCR is never re-read |
| Retry skipped with evidence | upload endpoint validates (`skipped_tx_ids`, chain membership, pending status) and sets `evidence_retry_tx_id`; finalize re-queues `retry_skipped_tx_id`; validated again, un-skipped, single-tx run | same single-tx upsert path + downstream textual refresh |
| Fresh re-verification | `_run_with_lock(fresh_reverification=True, transaction_ids=…)` | prior results hidden from the model and durable rows replaced on save (upsert); scoped selections also trigger the downstream textual refresh |
| Full analysis (normal) | idle→running; clears `skipped_tx_ids` saved in memory so pending links can be retried; skips terminal results | pending/`INCONCLUSIVE`-with-changed-manifest/checkpointed links retried in order; no downstream refresh needed (every run link gets fresh upstream context) |

---

## 9. Result contract (schema 3.0)

Single source of truth: `backend/services/agent_schemas.py`
(`TransactionVerification`, "Output B"; Phase A's "Output A" shape v2.0 is
validated inside `save_phase_a_result` and persisted to `title_chains`).

The narrative layer is one free-form markdown `report`; the machine layer is
the small rigid set of fields around it. There are no `summary`/`findings`
fields anymore.

```json
{
  "tx_id": "PA-TC-0003",
  "sequence": 3,
  "transaction_metadata": {
    "transaction_type": "Sale", "executed_date": "2012-04-18",
    "registration_number": "…", "registration_date": "…",
    "transaction_number": "TN-…", "vendors": ["…"], "purchasers": ["…"],
    "survey_number": "…", "plot_number": "…", "site_flat_number": "…",
    "property_location": "…", "schedule_property": "…", "conveyed_portion": "…",
    "chain_position": 3, "is_current_owner_transaction": false,
    "related_events": [ { "type": "…", "summary_points": ["…"] } ],
    "_document_manifest": { "DOC_001": "structured", … },
    "chain_context": { "upstream_unverified": [
      { "tx_id": "PA-TC-0002", "status": "PENDING_NOT_VERIFIED",
        "missing": [ { "document_type": "…", "reason": "…" } ] } ]
    }
  },
  "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
  "report": "## What this transaction is\n\n… [DOC_004 p.2-3] …\n\n## Upstream dependency\n\n…",
  "cited_documents": [ { "doc_id": "DOC_004", "pages": "2-3" } ],
  "required_documents": [
    { "document_type": "Registered sale deed dated … between … (complete, specific)",
      "reason": "What question this document must resolve",
      "for_transaction": "PA-TC-0003" }
  ],
  "reviewed_document_ids": ["DOC_004"],
  "verified_at": "2026-10-28T…",
  "schema_version": "3.0"
}
```

**Report writing rules** (enforced by `agent_verify_task.txt`, gated in code
where cheap): short `## ` sections adapted to the transaction ("What this
transaction is", "What the documents show", "Problems and gaps", "What is
needed next"); ~100–200 words typical, never omit a material fact, never pad;
inline citations `[doc_id]` or `[doc_id p.X-Y]` with only observed page
references; every cited document must appear in `cited_documents`; no
chain-of-thought; no other transaction's issues. While any upstream link is
unverified the report must contain the exact heading `## Upstream dependency`;
when every upstream link is verified the section is omitted.

| Field | Who supplies | Notes |
|---|---|---|
| `tx_id`, `sequence` | application | must match active tx (validated) |
| `transaction_metadata` | application (model may echo it) | merge of chain snapshot + `_document_manifest`; non-root results also carry `chain_context` — `{upstream_unverified: [{tx_id, status, missing}]}` computed by `_upstream_chain_context` from DB truth at save time (root results stay clean); downstream refresh adds `refreshed_at` |
| `status` | model | `normalize_status` coerces aliases; unknown → `PENDING` (fail-safe) |
| `report`, `cited_documents`, `required_documents` | model | report length-capped and duplication-gated; citations must be traceable (see §8.6) |
| `reviewed_document_ids` | application | union of persisted prior + this run's selections (EC excluded) |
| `verified_at` | application | now() only for terminal statuses, else null |
| `schema_version` | application | stamped during canonicalization |

Schema validators (always enforced, incl. at the repo boundary):
- `report` must be non-empty;
- `cited_documents` dedupe (doc_id+pages) and duplicates rejected;
- `required_documents` dedupe (type+reason casefolded) and duplicates rejected;
- pending/`IN_PROGRESS` results must **not** carry `verified_at`;
- `ISSUES_IDENTIFIED` requires ≥1 cited document;
- extra fields are forbidden (`extra="forbid"`).

Status enum (§8 of the original spec): `PENDING`, `IN_PROGRESS`,
`VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `INCONCLUSIVE`,
`PENDING_NOT_VERIFIED`.

**Legacy read-adapter** (`normalize_transaction_verification`): converts older
result shapes (`conclusion`, `missing_documents`, `impact`, `unresolved`,
`limitations`, `findings[{description,significance,explanation,source_refs}]`,
`supporting_evidence`, `contradictory_evidence`) into one markdown `report`
with `## Conclusion` / `## Findings` / `## Material qualifications` sections and
a flat `cited_documents` list **at the read/update boundary, without rewriting
stored rows**. Rows already carrying a `report` pass through unchanged. Legacy
prose is deduplicated (cover overlaps), a `LEGACY-<hash>` tx_id is synthesized
when missing, contradictory evidence becomes a "Contradictory evidence" bullet,
and an old `ISSUES_IDENTIFIED` without retained citations is downgraded to
`INCONCLUSIVE` with a stated qualification. This adapter is also the API
serialization step (`services/results._transaction_for_api`), so the UI always
consumes 3.0.

---

## 10. Memory architecture — how state is stored correctly

### 10.1 Ephemeral vs durable

| Layer | Lifetime | Content |
|---|---|---|
| `ToolContext` | one phase/transaction pass (in-process) | run_id; `evidence_requirements`; `listed_document_ids`; `selected_document_ids`; `read_text_ranges` (per-doc read windows incl. total length); `document_text_cache`; fingerprint/result caches; call counters; saved turn outputs |
| Conversation messages | one phase pass only | never persisted — every resume reconstructs fresh messages from durable stored state |
| `title_chains` row | durable | Phase A artifact |
| `case_results` row | durable | all transaction results |
| `case_memory` row | durable | resume checkpoint (JSON in a LONGTEXT column) |
| `cases` mirrors | durable | `agent_status`, `verification_status`, `verdict` |

### 10.2 The three durable stores (exactly)

1. **`title_chains`** — three dedicated columns per case (unique case_id):
   `property_identity` (JSON), `title_chain_graph` (LONGTEXT readable
   graph), `detailed_chain` (JSON, list of
   `{tx_id, chain_position, documented_transaction, related_events}`). A
   legacy `chain` JSON from older versions is adapted in memory on read. A
   Phase A save is an upsert — one current chain per case; the previous
   chain is replaced as a whole, never partially patched.

2. **`case_results`** (`case_result` JSON column, exactly one row per case):
   - **Value** = an ordered array of canonical transaction results.
   - **Writer** (`agent_repo.save_transaction_result`) = validate →
     `SELECT case_result … FOR UPDATE` (row lock protecting read-modify-write
     against the other worker) → remove any item with the same `tx_id` →
     append updated item → keep sorted by sequence → `INSERT … ON DUPLICATE
     KEY UPDATE`. Read side tolerates legacy dict payloads
     (`{"transactions": []}` form).
   - This gives idempotent per-transaction upserts: re-verification replaces
     the same item rather than adding a row, and pause/resume inherits the
     prior items.
   - No consolidated report object is persisted any more; overall status is
     derived from these items at response time.

3. **`case_memory`** (`case_memory` LONGTEXT, one row per case): the compact
   checkpoint. **Writer** (`save_agent_memory`) projects any given memory dict
   into a fixed schema (missing fields dropped):

   ```json
   { "case_id": "…",
     "current_tx_id": null | "PA-TC-0003",
     "current_stage": "phase_a|verifying|verifying_transaction|paused|skipped|done|error",
     "status": "IN_PROGRESS" | "PENDING_NOT_VERIFIED" | <last tx status>,
     "paused_transaction": "PA-TC-0003" | null,
     "result_ref": "PA-TC-0003",
     "next_action": "Upload the requested document(s) for … or skip …",
     "updated_at": "…",
     "evidence_retry_tx_id": "…" (only during a targeted retry),
     "skipped_tx_ids": ["PA-TC-0008", …] }
   ```

   **Reader** (`get_agent_memory`) parses the JSON, falls back to pre-json
   labeled-line text ("Progress:", "Paused transaction:", …) for legacy rows,
   and reconstructs `paused_transaction` from `current_tx_id` when
   stage=paused with pending status.

### 10.3 Correctness mechanics (summary)

- **Single-writer per case**: the `agent_lock` ensures only one agent
  instance; the pipeline/agent never run simultaneously (finalize is the
  last pipeline callback).
- **Row-lock RMW** for the results JSON prevents lost updates even if two
  workers somehow overlap.
- **Validation at two boundaries**: tool canonicalization + repo save-time
  schema revalidation mean persisted data is always schema-valid, sorted by
  sequence, and keyed consistently.
- **Checkpoints written before every await point**: each loop iteration
  rewrites memory (`_save_state`) before analysis (`verifying_transaction`),
  after each saved transaction, at pause, at done, and at error. A worker
  crash loses nothing but resumes exactly at the checkpoint because each
  write happens synchronously inside the run loop before the next LLM call.
- **`_save_state` always bumps `updated_at` and mirrors `current_stage`** to
  avoid stage/status drift; the API also exposes `stage` from memory to the UI.
- **Legacy migration**: old stores (`findings`, `reports`,
  `verification_results`, `agent_todos`, in-table agent columns) were
  consolidated into the two per-case tables once on startup, then dropped
  (see migrations flow §11.2); the labeled-text format is still readable.

### 10.4 Resume checkpoints — data flow

```text
pause: save PENDING result  ─┐
                             ├─► case_memory {paused_transaction, missing…,
next run                     │   pending_tx_ids, next_action}, agent_status=paused
  (upload finalize auto-queue or POST /analyze)          │
                             ├─ resume_paused: [paused..end] run, continues
                             └─ retry_skipped: single tx re-run
                             skip: add skipped_tx_ids; do NOT touch result
```

---

## 11. Database design

### 11.1 Current tables (defined in `backend/database/migrations.py`)

```text
users            (id PK, email UNIQUE, password_hash, full_name, timestamps)

cases            (id PK, user_id NULL→guest, status, total_docs,
                  completed_docs, failed_docs, verification_status, verdict,
                  pipeline_logs JSON, created_at, updated_at;
                  KEY idx_status, KEY idx_user_id)

documents        (id PK, case_id, doc_id UNIQUE per case (uq_case_doc),
                  doc_index, filename, expected_type, document_type,
                  page_count, status, structured_data JSON,
                  merged_ocr_text LONGTEXT, summary TEXT, file_paths JSON,
                  input_tokens, output_tokens, latency_ms, cost_usd,
                  model_used, error, retry_count, timestamps;
                  KEYs: case_id, status, document_type)

title_chains     (id PK, case_id UNIQUE, status, property_identity JSON,
                  title_chain_graph LONGTEXT, detailed_chain JSON,
                  legacy chain JSON / source JSON columns retained)

case_results     (case_id PK, case_result JSON, updated_at)
                  # one row; case_result is an array of canonical tx results

case_memory      (case_id PK, case_memory LONGTEXT, updated_at)
                  # one row; JSON checkpoint text
```

No SQL foreign keys exist — ownership and lifecycle are enforced in
application code (routers/services). All repository SQL is parameterized.

### 11.2 Startup migration and consolidation

`ensure_tables()` runs once at API startup (`migrations._tables_initialized`
guard) and:

1. Drops obsolete objects (`daily_cost_summary` view, `llm_calls`,
   `human_feedback`, `cross_doc_verifications`).
2. Creates the six tables (IF NOT EXISTS).
3. Best-effort `ADD COLUMN` for pre-existing DBs (`user_id`, `expected_type`,
   `merged_ocr_text`, `summary`, `agent_status`, the three Phase A columns…).
4. One-time consolidation of legacy stores before dropping them:
   `case_memory.memory` column → `case_memory`; `cases.agent_memory` rows →
   labeled lines; `agent_todos` rows → memory notes; `findings` +
   `reports` + `cases.agent_result` transaction payloads → merged into
   `case_results`; then `DROP TABLE findings/reports/verification_results/
   agent_todos/agent_verification_plans` and `DROP COLUMN
   cases.agent_result/agent_memory`.
5. Splits Phase A results that used to live entirely in `chain` JSON into
   `property_identity`/`title_chain_graph`/`detailed_chain`, and nulls the
   legacy `chain` payload once split.

Legacy transaction shapes inside `case_results` are handled by the read
adapter (§9), never rewritten.

---

## 12. Prompts and skills

`backend/prompts/loader.py` loads plain-text prompts by filename at runtime.

### 12.1 Prompt files

| File | Role |
|---|---|
| `title_chain_system.txt` | Phase A role: untrusted-evidence framing, input restrictions (summaries + merged OCR only, never structured extraction), phase boundary ("save exactly once then finish"; no verification/reporting) |
| `title_chain_task.txt` | Phase A task — single home for the task script and output contract: latest-sale-deed anchoring, backward tracing with the 30-year expectation (earliest supported root recorded as the chain limit), `"CRITICAL CHAIN COMPLETENESS RULE"` (recital-only links become their own chain items with `evidence_status`), EC representation rules, chronological graph + list with the ASCII layout, exact result JSON shape, summary_points/source_refs style rules, no unresolved fields |
| `agent_system.txt` | Phase B system prompt: buyer-side objective, 10 core reasoning principles (incl. untrusted-data rule), tool invariant, property identity/evolution, dependency-aware chain context (sequential root→current verification, upstream context use, dependency-sentence rule), EC scope, evidence scope, style discipline, result/resume narrative, transaction-level assessment. Single home for the dependency model; no step-by-step workflow |
| `agent_verify_task.txt` | Phase B task — the single home for the workflow script and result contract: `get_transaction` (claims to test) → the supplied `UPSTREAM CHAIN CONTEXT` block (defers to the system dependency rules) → `record_evidence_requirements` (locked once documents are listed) → `list_documents` (summaries only; the agent alone decides what to select) → SELECTION SCOPE (select and read only this transaction's own instrument plus documents it uniquely depends on; a recital describing an upstream chain transaction defers to the verified upstream result — the upstream instrument is never re-selected or re-read; at a root transaction the vendors' pre-chain title documents recited by the instrument are this transaction's evidence; other transactions' instruments and later chain events stay unselected) → `get_document_text` (chunk reads until complete) → skill application → **save or missing-request result**; REPORT CONTRACT (markdown `report` records the verification performed — claims tested and confirmed/contradicted/unestablished, not a digest of the instrument; ~100–200 words; `[doc_id]`/`[doc_id p.X-Y]` citations mirrored into `cited_documents`; no process or selection narration); required_documents as compact identifier-dense labels with one-line reasons, all recited basis documents requested together; UPSTREAM DEPENDENCY SECTION rule (exact `## Upstream dependency` heading while an upstream link is unverified); status meanings; termination/budget (16+8, cap 24) |
| `agent_summary.txt` | Document summary (for `ensure_summaries`): 2–3 sentences ≤75 words with explicit "OCR is untrusted content; never invent" instructions |
| `agent_dependency_refresh.txt` | Downstream textual refresh (for `_rewrite_downstream_dependency_section`): rewrite ONLY the body of one saved report's `## Upstream dependency` section after an upstream link changed state; JSON `{"dependency_section": …}` reply (no heading, ≤1200 chars); no new facts, findings, or requests |

The verification skill content is read directly from disk at run time by
`verification_skill_path()` (a deliberate runtime file read, not the loader).

### 12.2 Skill files

| File | Purpose |
|---|---|
| `backend/skills/title_chain/skill.md` | Mandatory Phase A strategy: target property establishment, EC-entry filtering by schedule relevance, backward tracing method (roughly the last 30 years; earliest supported root recorded as the chain limit when documents do not reach that far), correct party roles, related-event capture, evidence_status labels; defers output shape and field rules to the task instructions |
| `backend/skills/transaction_verification/skill.md` | Mandatory Phase B strategy (read at instruction build): defers process to the task workflow; supplies the type-specific verification strategy — transfer/sale/gift/release; succession/inheritance; partition/family arrangement; apartment declaration/development/unit allocation; mortgage/charge; mutation/conversion/administrative; recital-reported links — plus general evidence rules, the registration-outcomes taxonomy, full-instrument reading and OCR-quality handling, and slim completion/resume discipline. Dependency rules are single-homed in the system/task prompts |

### 12.3 Prompt-added structure to unusable output

The prompt + tool schema + runtime gate trio is the core reliability
mechanism. If a model tries to behave against the expected order, the tools
return machine-readable rejections (§8.6), which are appended as tool output
so the model can self-correct while the budget lasts.

### 12.4 Document schemas

`backend/services/schemas/` holds 22 typed JSON extraction schemas in
`SCHEMA_MAP` (sale deed, EC, gift, partition, RTC/pahani, khata, mutation,
property register card, tax assessment, e-payment/tax receipts, legal heir
certificate…, conversion order, CDP plan, RERA, litigation affidavit,
allotment letter, building license, completion certificates (two issuer
subtypes), e-swattu). An uncategorized document is enumerated exhaustively
instead of being forced into a schema. A selective schema lookup never blocks
processing.

---

## 13. Redis internals

### 13.1 State store (`integrations/redis/state_store.py`) — "read cache only"

Key layout:

```text
case:<id>:meta   hash {status, total_docs}
case:<id>:files  string JSON [{doc_id, original_name, saved_path}]
case:<id>:log    list (append full pipeline log lines, trimmed ±200)
case:<id>:docs   string JSON per-doc status cache (retry resets)
```

Philosophy: **MySQL first on every write** (status changes, results, logs) and
Redis updated best-effort; **reads go to Redis first and fall back to MySQL**
on miss/error; all Redis calls are guarded so a Redis outage never breaks the
pipeline and stale-Redis-wins cannot happen. Snapshot endpoint
`get_case_job` reproduces the legacy JOBS dict shape for the status cards.

### 13.2 Distributed lock (`integrations/redis/lock.py::RedisLock`)

```text
acquire:    SET key "<uuid4-token>" NX PX 1800000     (30-min TTL)
refresh:    Lua: compare token → PEXPIRE             (timer every 300 s)
release:    Lua: GET==token → DEL                    (token check prevents
                                                     releasing some other holder)
force_release: DEL                                   (used by finalize)
```

Used as `case:<id>:pipeline_lock` (document processing) and
`case:<id>:agent_lock` (agent runs).

### 13.3 Rate limiter (`integrations/llm/rate_limiter.py`)

Redis Lua atomic token bucket shared across all workers for Gemini calls
(configurable `GEMINI_RPM/TPM/BURST`; one script handles TIME + read-state +
write-state atomically; sorted set holds the 60 s request window,
`ZREMRANGEBYSCORE` prunes it; token bucket refills at TPM/60 per second).
`wait_and_acquire` backs off exponentially (max ~105 s) so a rate-limited
worker fails fast rather than stalling a task slot.

---

## 14. Retrieval paths — what the LLM can see and how

| Audience | Data | Path | Explicitly excluded |
|---|---|---|---|
| Phase A model | doc summaries (manifest) | prompt assembly | structured_data |
| Phase A model | full OCR of relevant docs | `get_document_text` (no selection gate in Phase A) | — |
| Phase B model | doc summaries + filenames | `list_documents` (EC filtered) | structured_data |
| Phase B model | selected docs' OCR chunks | `get_document_text` (gated by selection + status; the prompt's SELECTION SCOPE keeps other transactions' instruments and later chain events unselected) | unselected docs' OCR |
| Phase B model | transaction details | prompt (from Phase A chain entry, `source_refs` stripped) | source provenance |
| Phase B model | upstream links' saved state | `--- UPSTREAM CHAIN CONTEXT ---` block in the instruction (`_build_upstream_context`: statuses, previous-link report excerpt, unresolved links' outstanding requests) | upstream OCR, upstream reports as evidence |
| Phase B model | own prior result | `get_transaction` (unless fresh re-verification or bounded lockout rules) — recovered via `_prior_result_for_agent` | other transactions' results via tools — enforced in prompt + tool reply shape |
| Downstream refresh | each later result's own saved report + new upstream state | `_refresh_downstream_results` → `agent_dependency_refresh` prompt (section-only `complete_json`) or deterministic section removal | any OCR read, any verification pass |
| Report PDF | persisted results only | `services/report.py` builds from `build_case_results` | no new LLM calls |

Invariants: structured extraction JSON is **not** documentary evidence
(metadata handler strips it); every Phase B citation requires full OCR read
in this run; no cross-transaction result loading is possible via tools (the
only tool that accesses saved results takes the active tx only) — upstream
dependency context reaches the model only through the application-compiled
instruction block, never as readable evidence.

Retrieval failures (metadata missing, OCR empty, wide-range overlap) return
`{"error": …}` tool messages — the model is required to treat them as
failures, never to claim a tool action succeeded without confirmation.

---

## 15. API map

Registered in `backend/main.py` under `/api` (plus `/health` and SPA routes):

| Method & path | Handler | Purpose / responses |
|---|---|---|
| `POST /api/auth/register`, `POST /api/auth/login` | `routers/auth` | 201/200 JWT + user |
| `GET /api/auth/me` | `routers/auth` | current user |
| `/auth/google/*` | site-root OAuth router | login + callback (redirect with token) |
| `GET /api/cases` | `cases.get_all_cases` (JWT) | case list |
| `POST /api/upload` | `cases.upload` | creates case + files; returns case_id + files; 413 over limit |
| `POST /api/process/{case_id}` | `cases.process` | acquires pipeline lock → `start_case_pipeline` (chord queued; 409 when already running) |
| `GET /api/status/{case_id}` | `cases.status` | `get_case_job` snapshot (files/results/errors/log/progress) |
| `POST /api/retry/{case_id}` | `cases.retry_failed` | resets failed docs and re-fires pipelines from their checkpoints |
| `POST /api/case/{case_id}/upload` | `cases.add_case_files` | additional evidence; optional `transaction_id` → retry-a-skippedTx flow |
| `POST /api/case/{case_id}/doc/{doc_id}/replace` / `/skip` | classification action | replace (processes new file later, continues) / mark skipped and re-finalize |
| `GET /api/results/{case_id}` | `results.get_results` | assembled case/document/agent payload (§10-adjacent) |
| `GET /api/results/{case_id}/ocr` | `results.get_case_ocr` | per-doc canonical OCR text (DB-first, merged-file fallback) for the OCR viewer |
| `POST /api/results/{case_id}/analyze` | `results.trigger_analysis` | queue `run_case_analysis_task(case_id)` |
| `POST /api/results/{case_id}/agent/skip/{tx_ref}` | `skip_agent_transaction` | queue skip by tx id or sequence number |
| `GET /api/results/{case_id}/report/pdf` | report PDF | ReportLab render of saved state (404/500 cases) |
| `GET /api/results/{case_id}/required-documents/pdf` | required-doc checklist PDF | outstanding docs digest |
| `GET /api/case/{case_id}/doc/{doc_id}/pdf` | document download | renders saved original copy |
| `DELETE /api/case/{case_id}` | `cases.delete_case` | revokes Redis keys, DB rows, files |
| `GET /health` | `main.health` | provider-key presence report |

Case endpoints enforce ownership using `get_case_owner`:
`None` owner = open guest case (case id acts as the secret), otherwise a valid
JWT of the owner is required; 403 otherwise; 404 on unknown cases.

Response shapes the dashboard relies on (`services/results.py`):

```jsonc
{ "case": {case_id, status, counts, verification_status, verdict, timestamps},
  "documents": [ {doc_id, doc_index, filename, document_type, status,
                  page_count, structured, error, model_used, cost_usd} ],
  "needs_action": [ {doc_id, filename, document_type, message,
                     choices:[{action,method,url,label}]} ],
  "agent": {
      "property_identity": …, "title_chain_graph": …, "title_chain": […],
      "transactions": [ <canonical v3.0 results…> ],
      "overall_status": "ISSUES_IDENTIFIED" | "VERIFIED_WITH_AVAILABLE_EVIDENCE"
                        | "INCONCLUSIVE" | null,
      "status": "<agent_status>", "updated_at", "stage",
      "paused_transaction", "next_action", "skipped_tx_ids" } }
```

---

## 16. PDF report generation

`backend/services/report.py`:

- `render_report_pdf(case_id)` (and `render_required_documents_pdf`) call
  `build_case_results` and render with ReportLab; **no LLM calls** — the PDF
  is a deterministic formatting of persisted data.
- Layout: cover block with generation date, verdict, case status, counts and
  model metadata; title-chain graph in monospace (preserving the ASCII graph)
  plus Phase A property identity; per-transaction sections printing status and
  outstanding required-document entries (type + reason, by transaction); a
  case-level conclusion from the Phase A/consolidated `headline`/`report`
  fields with an overall-status fallback.
- Served with `Content-Disposition` attachment.

---

## 17. Frontend architecture

```text
frontend/
  server.ts        dev-entrypoint (tsx): serves dev SSR-less static + API proxy
  vite.config.ts   build; dev proxy for /api + /health; assets
  src/
    App.tsx            Router: / (landing pages) /login /app /status /results /ocr /pricing …
    api/backend.ts     auth-aware fetch client (localStorage token), typed payloads
    dashboard/
      VerificationDashboard.tsx   main case view (upload & processing status,
        classification actions, and the verification flow with:
        pause banner + required documents, skip button, per-transaction cards)
      PhaseAResult.tsx            Phase A graph (mono) + identity + chain cards
      TransactionResultCard.tsx   one canonical result card (status pill,
        metadata chips, markdown report sections with inline citation chips,
        "Documents cited" list, pending docs, retry upload for skipped links)
      transactionResults.ts       typed accessors: report section parser,
        cited documents per tx (dedupe), required documents per tx (dedupe),
        status labels incl. skipped variants, metadata chip builder
      AuthScreen.tsx              login/register + Google OAuth start
      dashboard.css
    pages/             marketing + about pages (+ OCR viewer page endpoint-linked)
    components/        landing page sections (hero, pipeline explainer, FAQ, …)
```

Data flow: dashboard polls `GET /api/results/{case_id}` (and
`/api/status/{case_id}` during processing). The results payload shown to the
user is exactly what the API assembles; the UI never infers party roles or
chain links itself (it renders the saved Phase A result). Started runs are
user-triggered (`Analyze` button → `/analyze`); the pause state and
`next_action` come from the same payload. Flows are synchronized with the
JWT stored by `api/backend.ts` (login/register/OAuth callback).

Production serving: the SPA bundle is baked into the image at
`frontend/dist` and FastAPI mounts `/assets` + a catch-all
`GET /{path}` SPA fallback (index.html for client-side routes;
`FileResponse` for real files). Dev mode: `npm run dev` uses the Express
`server.ts` with Vite middleware proxied to a local backend.

---

## 18. Observability

- `backend/logger.py` — stdlib logging used per module with structured
  messages, e.g.:
  - provider: `agent_provider_request_failed`, `agent_provider_retry`
  - loop: `agent_model_call` (provider, model, call #, budget, attempts,
    latency, usage), `agent_tool_call`, `agent_loop_stop`
  - gates: `agent_tool_rejected`, `agent_documents_selected`, `agent_ocr_range`
  - persistence: `agent_result_persist_attempt`,
    `agent_result_persisted`, `agent_missing_request_persisted`,
    `agent_duplicate_tool_call`,
    `agent_validation_recovery_budget_granted`,
    `agent_verification_budget_extended`, `agent_safe_checkpoint_saved`
  - run: `agent_run_start`, `agent_transaction_start`,
    `agent_transaction_saved`, per-phase summaries
- Pipeline log lines in the DB (`append_pipeline_log`) + Redis cache (user
  visible) with per-stage steps (`Step 1: Preprocessing …`,
  chunk success counts, and a finalization line).
- Usage counters stored per document row (input/output tokens, latency,
  cost, model) for classify/structure; agent usage is logged per model call.

---

## 19. Failure handling matrix

| Failure | Detection | Handling |
|---|---|---|
| Preprocess failure | exception in CV chain | fallback to original PDF (non-fatal), status still advances |
| OCR insufficient credits | error text contains "insufficient credits" | `OcrInsufficientCredits` (no autoretry), document failed with actionable message |
| Some OCR chunks failed | chunk statuses | merge proceeds with successful chunks; failures logged + visible |
| All OCR chunks failed | zero complete chunks | `RuntimeError` with per-chunk detail; autoretry up to 5 |
| Physical pages > merged label | mismatch detected in merge | final page_count from `fitz` physical count |
| Classification not property related | `UnsupportedDocumentError` | `classification_failed` status + needs_action UI with replace/skip |
| Structuring invalid JSON / missing summary | parse/shape errors | `DocumentProcessingError`; failed status; retryable (`max_retries=5`) |
| Disk full while writing structured artifact | `OSError` | warn + keep DB data; disk artifact skipped |
| Stage task killed mid-run | `acks_late` + `reject_on_worker_lost` + visibility timeout | redelivered; idempotency decorator re-checks checkpoint |
| Agent lock contention | lock not acquired | immediate `{status: busy}` |
| Agent LLM transient errors | 429/503/timeout/quota markers | exponential-backoff retries per provider attempt (≤5) |
| Agent budget exhausted without result | loop else-branch | safe `INCONCLUSIVE` checkpoint persisted or existing result preserved; marked checkpointed (non-terminal) |
| Duplicate identical tool call | fingerprint + prior result cached | returns cached output + `"duplicate_call"` hint |
| Model tries out-of-order tool calls | gate errors returned as JSON | model self-corrects within budget |
| Model fabricates citations / cites unread docs | canonicalization citation gate | save blocked + issues returned |
| Model repeats a report sentence in a requirement rationale | compactness gate | save blocked with targeted edit instruction |
| Model asks for already-uploaded document | anti-duplicate-request gate | blocked with candidate list |
| Persist failure (DB) | repo exception | `result_error → persist failure`; surfaced and re-raised as agent error (safe checkpoint when applicable) |
| Agent crash mid-transaction | exception in `_run` | `stage=error` + memory error text + `agent_status=error`; resumable from the saved checkpoints |
| Two-agent race | Redis lock | `{status: busy}` |

---

## 20. Tests

`backend/tests/` (pytest):

| File | Covers |
|---|---|
| `test_agent_schemas.py` | schema validators (report/citation invariants), normalize_status, legacy adapter → markdown report |
| `test_agent_repo.py` | memory writer/reader, tx-result upsert semantics |
| `test_agent_runtime.py` | loop stop reasons, duplicate calls, budgets |
| `test_cleartitle_agent.py` | agent orchestration, phase A, skip/retry paths |
| `test_direct_transaction_verification.py` | the largest suite: per-transaction verification flows, gates (unread-OCR rejection, citation traceability + retention, upstream anchor heading, duplicate requests, checkpoint preservation), dependency-aware chain flows (upstream-context compilation, `chain_context` injection, downstream textual refresh without re-verification — deterministic section removal vs LLM section rewrite, scoped-run refresh wiring, prompt dependency phrases) |
| `test_document_processor.py` | classification prefix rule, e-Swattu rule, schema retrieval, extraction contract |
| `test_ec_ledger_merge.py` | EC ledger row-continuation merge |
| `test_title_chain_phase_a.py` | Phase A chain validation |
| `test_finalize.py` | finalize auto-queue decisions (start/resume/retry) |
| `test_results.py`, `test_report_parties.py` | payload assembly & PDF content |
| `test_sarvam_client.py` (new) | OCR integration |

Frontend: `npm test` runs `transactionResults.test.ts` +
`TransactionResultCard.test.tsx` (node:test + tsx) covering the typed
accessors and card rendering.

---

## 21. Security and reliability notes

- Repository SQL is parameterized always; case access is checked at route
  boundaries (owner check; guest cases rely on case id secrecy).
- `.env` never committed; secrets via environment configuration only.
- LLM-visible OCR/summaries are treated as **untrusted data** — the system
  prompt instructs to ignore embedded instructions, and the verification skill
  repeats this. Tool outputs are the only path to persist anything.
- The application never relies on the model's claim of success: saving is
  validated by schema + gates and is the sole signal that advances state.
- Erroneous hidden-token billings are guarded by rate limiter + one-extension
  budget + hard cap.
- Encryption of data at rest is delegated to the DB/disk configuration
  (documented deployment concern, not dedicated code).
- `cases.verdict` is a compact UI mirror, never a legal determination; a
  `done` agent state is not "title is clear".

---

## 22. Source map

| Concern | Main files |
|---|---|
| App startup / routing / SPA hosting | `backend/main.py`, `backend/routers/*` |
| Auth | `backend/services/auth.py`, `backend/routers/auth.py`, `backend/database/repositories/user_repo.py` |
| Upload/processing APIs | `backend/routers/cases.py` |
| Pipeline orchestration | `backend/services/orchestrator.py` |
| Document stages | `backend/workers/{tasks,stages,stage_adapter,stage_base,context,idempotency}.py` |
| Document AI stages | `backend/services/document_processor.py`, `backend/services/schemas/*` |
| OCR | `backend/integrations/ocr/{preprocessor,sarvam_client,ocr_merger}.py`, `backend/services/extract.py` |
| EC post-processing | `backend/shared/ec_ledger.py` |
| Finalize + agent queueing | `backend/workers/finalize.py`, `backend/workers/title_chain_tasks.py`, `backend/workers/agent_tasks.py` |
| ClearTitle agent | `backend/services/{cleartitle_agent,agent_runtime,agent_tools,agent_schemas}.py` |
| Persistence | `backend/database/{connection,migrations}.py`, `backend/database/repositories/*` |
| Integrations | `backend/integrations/llm/*`, `backend/integrations/redis/*`, `backend/integrations/storage/file_utils.py` |
| Results + PDF | `backend/services/results.py`, `backend/services/report.py`, `backend/routers/results.py` |
| Prompts / skills | `backend/prompts/*`, `backend/skills/title_chain/skill.md`, `backend/skills/transaction_verification/skill.md` |
| React SPA | `frontend/src/**`, `frontend/server.ts` |
| Deployment | `Dockerfile`, `docker-compose.yml`, `backend/config.py` |
