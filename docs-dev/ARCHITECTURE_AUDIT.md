# clearTitle — Architecture & Working-Flow Audit

One doc that explains the whole system in plain language, then goes deep on every
mechanism (retries, fallbacks, idempotency, locks, rate limits, error handling).
All file references are `repo/relative/path:line`.

---

## 1. What it does (30 seconds)

clearTitle turns two scanned Karnataka property PDFs — a **Sale Deed (SD)** and an
**Encumbrance Certificate (EC)** — into a verified title report:

1. **OCR** the PDFs (Sarvam Vision, Kannada).
2. **Classify** each doc (SD / EC / 20+ other types).
3. **Extract** structured JSON from each (LLM).
4. **Build a title chain**: map every EC ledger entry onto the ownership timeline
   of the SD's property.
5. **Verify**: cross-check SD fields against the EC ledger and produce a verdict
   (`CLEAR_TITLE` / `ATTENTION_REQUIRED`).
6. Render results + a PDF report in the dashboard.

Everything after "upload" runs asynchronously in Celery. MySQL is the system of
record; Redis is a broker + read cache; PDFs/JSON live on disk under `outputs/`.

---

## 2. Architecture diagram

```txt
                         +-------------------------------+
                         |   FRONTEND  (React 19 + Vite) |
                         |  VerificationDashboard        |
                         |  upload -> process -> poll -> |
                         |  results                     |
                         +---------------+---------------+
                                         |
                                         |  HTTP + Bearer JWT
                                         v
  +-------------------------------------------------------------------+
  |                    API  (FastAPI,  prefix /api)                   |
  |   auth.py     register | login | me | link                        |
  |   cases.py    upload | process | status | retry | replace | skip  |
  |   results.py  GET results | analyze | report.pdf                  |
  +--+----------------------------------------------------------------+
     |                                  |
     |  MySQL-first writes              |  POST /process
     |  Redis read-cache                |  (RedisLock; 409 if running)
     v                                  v
  +------------------+    +------------------------------------------+
  |  MySQL           |    |  CELERY  (broker: Redis)                 |
  |  cases           |    |  chord of 6-stage chains,                |
  |  documents       |    |  one chain per document:                 |
  |  title_chains    |    |                                          |
  |  verification_   |    |  preprocess -> ocr -> merge ->           |
  |   results        |    |  classify -> structure -> persist        |
  |  users           |    |  (Sarvam OCR)  (Gemini / Groq LLM)       |
  |                  |    |                                          |
  |                  |    |  chord callback: finalize_case_task       |
  |                  |    |    recompute status, release lock,        |
  |                  |    |    if complete -> run_case_analysis_task  |
  +------------------+    +-------------------+----------------------+
  (source of truth)                           |
                                              |  two independent LLM passes
                                              v
                                  +-----------+-----------+
                                  |                       |
                                  v                       v
                            +-------------+          +-------------+
                            | build_title |          |  verify_case |
                            | chain       |          |              |
                            +------+------+          +------+-------+
                                   |                       |
                                   |  Gemini call          |  Gemini call
                                   v                       v
  +-------------------------------------------------------------------+
  |                     PERSISTENCE  (results tables)                 |
  |  MySQL  : title_chains (chain/source)                             |
  |           verification_results (verdict/summary/items)            |
  |  Disk   : outputs/{case_id}/ raw/ preprocessed/ ocr_raw/          |
  |           structured/                                             |
  |  Redis  : case state, pipeline log, job meta                      |
  +-------------------------------------------------------------------+
```

Legend: `->` = flow  · side labels on the line = the trigger/transport.

Flow in words: **upload** (FastAPI) writes Redis + MySQL + disk → **process**
acquires a Redis lock and fires a *chord* = one 6-stage *chain* per document →
**finalize** (chord callback) recomputes case status, releases the lock, and — if
all docs structured — queues **analysis** → **title chain** and **verification**
each run an LLM pass and persist their own tables → dashboard polls until it can
render results.

---

## 3. Technology stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Vite + TypeScript (`frontend/`) |
| API | FastAPI + uvicorn (`backend/main.py`) |
| Jobs | Celery (Redis broker), `acks_late`, prefetch 1 (`backend/celery_app.py`) |
| SQL | MySQL 8 (`backend/database/`) — migrations auto-run at startup |
| Cache/state | Redis (`backend/integrations/redis/`) |
| OCR | Sarvam Vision (`document_intelligence`, Kannada) |
| LLM | Gemini (primary analysis/extraction) + Groq (fallback models) |
| Storage | Disk under `outputs/{case_id}/` |
| Auth | JWT (HS256, bcrypt) |

---

## 4. The document pipeline (6 stages per PDF)

A chain of immutable tasks, no result passed between stages — each re-reads state
from MySQL/disk (`services/orchestrator.py:21-30`).

| # | Stage | What it does | On failure |
|---|---|---|---|
| 1 | `preprocess` | 200-DPI render + deskew/denoise/CLAHE/unsharp | **Non-fatal** — falls back to original PDF (`workers/stages.py:91-98`) |
| 2 | `ocr` | Sarvam OCR (≤10 pages = single job; >10 = chunks of 10 w/ 1 page overlap) | Retry, then `increment_retry` → `failed` (`stages.py:143-147`) |
| 3 | `merge` | dedupe overlap pages, stitch split tables, clean base64 images | `increment_retry` → `failed` (`stages.py:180-184`) |
| 4 | `classify` | filename keywords → content keywords → declared upload slot (SD/EC) | `UNKNOWN` → `classification_failed` (permanent) (`stages.py:220-233`) |
| 5 | `structure` | one LLM call per doc → typed JSON | doc marked `failed` + Celery retry (`stages.py:287-291`) |
| 6 | `persist` | write JSON to disk + structured_data, tokens, cost to MySQL | propagates; wrapper marks `failed` |

### Retry stack around each document — **3 nested layers**

```
Sarvam chunk retries          stage wrappers            Celery autoretry
per chunk: 3 attempts          run_ocr_with_retry        TASK_RETRY_CONFIG
sleep  5s, 15s (30s unused)    3 attempts, 5s linear     autoretry_for=Exception
(sarvam_client.py:24-25)       (extract.py:43-55)        max_retries=5, backoff
                                                          cap 120s + jitter
>--------------->-------------->-------------->--------->MAX(5 attempts)
```

**Important gotcha:** the Celery `max_retries=5` layer is effectively dead for the
OCR/merge/classify/structure stages. Those stages call `increment_retry`
(`document_repo.py:128-137`) or set `failed` (`stages.py:290`) *before* the
decorator re-raises, so the next autoretry attempt sees `status=failed` and
short-circuits to "skipped" without re-running (`workers/idempotency.py:35-40`).
The *real* recovery path is the API-level **`POST /retry/{case}`** (`routers/cases.py:270`),
which resets failed docs to `pending_retry` and re-fires a chord over just those files.

### Idempotency (per-document only)

`@idempotent_stage(entry, complete)` (`workers/idempotency.py:22-108`) guards each
of the 6 stage tasks (`workers/tasks.py:40-70`):

1. Read doc `status` in MySQL. 2. `failed`/`classification_failed` → skip.
3. Already past the current stage → skip. 4. Write the *entry* stage.
5. Run. 6. Write the *complete* stage (or mark permanently failed).

MySQL is the sole dedup authority — check-then-act is **not atomic**, so double
invocation (worker redelivery, concurrent run) can double-run a stage.

### Pipeline lock

`RedisLock(case:{id}:pipeline_lock)` — `SET NX PX`, TTL 30 min, auto-refreshed
every 5 min by a timer in the **API** process (`integrations/redis/lock.py`).
Acquired by `POST /process` and `POST /retry` (409 when held), released by
`finalize_case_task` via **token-less** `force_release` (`finalize.py:55-56`).

---

## 5. Case finalization

`finalize_case_task` is the chord callback, runs once after **all** docs finish
(`workers/finalize.py:17-67`):

1. `recompute_case_status` in MySQL: `partial` if any failed/classification_failed,
   `complete` if structured == total_docs, else `processing` (`case_repo.py:26-46`).
2. Re-derives status in Python (ignores skipped/total_docs) and writes Redis.
3. `force_release`s the lock.
4. If `complete` → queues `run_case_analysis_task` (title chain + verification).

---

## 6. Case analysis (title chain + verification)

One task, two independent phases — failure in one never blocks the other
(`workers/title_chain_tasks.py:25-45`). Both persist `error` rows instead of
raising. **No Celery retry and no idempotency on this task.**

### Title chain (`services/title_chain.py`)
- Requires SD + EC with a non-empty `historical_ledger`, else persists
  `no_transactions`.
- One Gemini call (`analysis_executor.run_analysis`, `max_output_tokens=32768`)
  classifies each ledger entry (role, edge type, graph_from, portion…).
- **Deterministic fallbacks** fill anything the LLM missed:
  - `_fallback_role` (`:103-113`): entry == SD registration/date → `THE_SD`;
    encumbrance keywords → `ENCUMBRANCE`; date after SD → `SUBSEQUENT_TRANSFER`;
    else `PREDECESSOR_TITLE`.
  - `_fallback_edge_type` (`:132-140`), `_normalize_graph_from` (`:143-156`),
    `_default_portion/_identity/_explanation` (`:159-198`).
- `UNRELATED` entries dropped; no matches → persists `complete` with empty chain
  + a "no matching property" message (`:311-328`).
- LLM call fails → persists `status='error'`, `chain=NULL` (`:262-270`).

### Verification (`services/verify.py`)
- Requires SD + EC, else persists `skipped`.
- One Gemini call returns per-field items + a case verdict.
- Item `status` coerced to `N/A` when invalid (`:100-102`); **invalid verdict →
  the whole verification is persisted `status='error'`** (`:111-117`) — no
  re-call, no deterministic verdict.

### The DB row you hit earlier (why `chain` was live-NULL but verification worked)

Case `BE3A0C14`, rerun log: the title-chain Gemini call hit a transient **503
"model experiencing high demand"** (`analysis_executor.py:40-53` raises, no retry);
`build_title_chain` caught it and persisted `status='error'` with `chain` unset →
`title_chain_repo.save_title_chain` writes **NULL** (`title_chain_repo.py:24`).
24 s later the verification call succeeded (200). Then `results.py:34-35` masks
the NULL chain to `[]`, so the UI showed "no title chain" with no error surfaced.

---

## 7. LLM subsystem

### Model routing (`integrations/llm/model_router.py`)
- `ROUTING_MAP` built from `MODEL_ROUTING_MAP` env (JSON) or defaults — per
  doc-type: cheap Groq for receipts/registers/khata, Gemini for SD/EC/gift/
  partition/court/license, Groq-120b for KHATA/LEGAL_HEIR.
- `resolve_analysis_task()` → **Gemini only** for title chain + verification.
- Fallback chain: primary → `groq/gpt-oss-20b` → `gemini/gemini-3.6-flash`
  (`:58-62`).
- `model_router.py` hardcodes `gemini-3.6-flash` while actual calls use the
  `GEMINI_MODEL` env — logs and reality can disagree.

### Extraction retry/fallback (`services/extract.py:58-110`)

```
for model in provider+fallback-chain (≤4):        # structure_document
  for attempt in 1..3:
    wait rate limiter (tokens = max(1, chars/100k))
    call executor
    on exception:
      transient & attempt<3  -> sleep 5.5s/11s, retry SAME model
      rate-limit token miss  -> break to NEXT model immediately
      429/413/503/500        -> transient branch first, else break
      quota/billing          -> break (never retried)
    exhausted                -> raise; doc marked failed
```

`is_transient_error` (`:29-35`) counts JSON-decode errors as transient too, so a
consistently malformed response burns up to 3 retries × 4 models = 12 calls.

### Executors
- **Gemini** (`gemini_executor.py`): no own retry; JSON parse → fenced-code-block
  re-parse → raise; context caching per doc-type (md5 of static prompt, silent
  degradation on cache failure).
- **Groq** (`groq_executor.py`): tries `gpt-oss-120b` then `gpt-oss-20b` (no
  backoff), aggregates failures into one `RuntimeError`.
- **Analysis** (`analysis_executor.py`): single call, parse → `RuntimeError` on
  unparseable/non-object JSON. **No retry — this is why an overload 503 persisted
  an error row.**

### Rate limiting (`integrations/llm/rate_limiter.py`)
Redis token bucket + 60 s request window in one atomic Lua script. Limits:
Gemini 30 RPM / 4M TPM / burst 5; Groq 60 RPM / **6,000 TPM** (very tight) / burst 10.
- `wait_and_acquire` backs off exponentially (cap 15 s, default 10 tries).
- **Advisory only**: executors log-and-proceed on missing tokens; only
  `extract.structure_document` hard-breaks to the next model.
- Extraction is **double-charged**: it acquires a 1-token slot then the executor
  acquires another for the same call.
- Redis outage in the limiter surfaces as a model failure → may trigger fallback.

### Schema validation
`response_schema` is only serialized into the prompt ("EXPECTED OUTPUT SHAPE") —
never validated programmatically. Services do their own coercions
(title_chain is the most robust; verify fails closed on bad verdicts). Prompt/schema
files are loaded at import → missing files fail fast at boot (`prompts/loader.py`).

---

## 8. OCR subsystem (`integrations/ocr/`)

- **≤10 pages**: one Sarvam job on the PDF directly. **>10 pages**: every page
  rendered to 200-DPI PNG, zipped in chunks of 10 with 1-page overlap, submitted
  in parallel (≤8 workers) (`sarvam_client.py:82-187`).
- Per-chunk retries: 3 attempts, sleeps 5 s/15 s (the 30 s slot is dead code),
  each retry = a fresh job (`:110-136`, `:197-223`).
- `PartiallyCompleted` counts as success; failed chunks are dropped silently —
  their pages just vanish, so pages 6-10 might be missing but `total_pages` still
  reads high (`ocr_merger.py:27`, `:215`).
- Preprocessing is always non-fatal; OCR around a missing API key is the only
  hard failure — caught by `run_ocr_with_retry`.

---

## 9. Storage & database

**Disk** `outputs/{case_id}/`: raw uploads, `preprocessed/{doc}_prep.pdf`,
`ocr_raw/{doc}/` (chunk + response zips), `ocr_raw/{doc}_chunks.json`,
`ocr_raw/{doc}_merged.json`, `structured/DOC_1_SALE_DEED.json`.

**MySQL** (5 tables, no FK constraints): `cases` (status, verification_status,
verdict, pipeline_logs), `documents` (status, structured_data, file_paths, costs),
`title_chains` (chain JSON, source JSON), `verification_results` (summary, items),
`users`.

Write discipline: **MySQL first, Redis best-effort** everywhere; reads are
Redis-first with MySQL fallback. `documents.file_paths` is merged atomically via
`JSON_SET` (no read-modify-write race). `save_title_chain` / `save_verification_results`
are full row-replace upserts — omitting a payload column writes NULL.

---

## 10. API & auth (surface summary)

- **Auth**: optional (`get_optional_user`) on all case CRUD → anonymous "guest"
  cases are open to anyone with the case ID; required (`get_current_user`) on
  login/register/me/cases list/link. JWT 7-day expiry, bcrypt.
- **Anonymity → account**: `/api/case/{id}/link` (rowcount-guarded against
  TOCTOU) + dashboard auto-link on login.
- **Endpoints**: upload, process, status (polls), retry, replace, skip, add-docs,
  delete, serve-pdf, link; results GET, report PDF, analyze POST; health.
- **Error statuses**: 400 (bad upload/no-failed), 401/403 (auth/ownership), 404
  (missing case/doc), 409 (lock held / duplicate email / active pipeline), 500
  (pipeline start / report render).
- **Deliberate soft failures**: DB write during upload, Redis blips, status-payload
  JSON corruption — all log-and-continue. Report PDF **hard 500s** when
  verification is `error` (report.py:303-306 → masked by the UI + "Please retry").

---

## 11. Frontend flow (60 seconds)

1. **Upload step** (dashboard): SD + EC are mandatory slots, extras optional
   (`VerificationDashboard.tsx:269-273`). Gates on ≥1 SD + ≥1 EC → `/upload` →
   `/process` → poll.
2. **Processing step**: polls `/status` every 2 s (`:1264-1304`); 6 per-doc stage
   bars, then "Building title chain / Verifying title" phases from
   `title_chain_status` + `verification_status`. If status is `complete` but
   verification hasn't landed yet, it keeps pollin up to **8 minutes** (`:1287-1294`).
3. **Results step**: guest sees a locked preview ("Sign in to Unlock"); authed
   user sees verdict banner, per-field verification checklist, title-chain
   timeline, doc extractions, replace/skip actions for failed docs.
4. **Re-run analysis**: `POST /analyze` (fire-and-forget) then polls results
   every 3 s until `verification.updated_at` changes or 8 min elapse (`:1357-1406`).
5. Missing title chain rendered as `title_story` else the placeholder
   "No title chain entries yet…" (`:397`, `:1484`).

The three API helpers `API.health / status / listCases` never throw (degrade to
placeholders); everything else throws and callers log it (`frontend/src/api/backend.ts:162-245`).

---

## 12. Retry & fallback matrix (everything in one table)

| Layer | Mechanism | Attempts | Backoff | Exhausted behavior |
|---|---|---|---|---|
| Sarvam OCR chunk | fresh job per retry | 3 | 5s, 15s | chunk stored `failed`, dropped from merge |
| OCR stage wrapper | `run_ocr_with_retry` | 3 | 5s linear | re-raise → doc `failed` |
| LLM extraction/model | per-model loop → fallback chain | 3 × ≤4 models | 5.5s/11s | raise → doc `failed` |
| Celery stages | autoretry (dead for 4/6) | 5 | exp ≤120s + jitter | marked `failed`/`classification_failed` |
| API retry | `POST /retry` resets → rerun failed docs | manual | — | returns 400 if none |
| Title chain / verify | **none** | 1 | — | persists `status='error'` row (chain → NULL) |
| Schema/model | `title_chain` deterministic fallbacks | every run | — | missing LLM fields filled from ledger |
| Model chain | primary → groq-20b → gemini | per doc type | — | raise after all |
| Classification | keywords → declared slot → fail | 1 | — | `classification_failed` (user replaces/skips) |
| Preprocess | return original PDF | 1 | — | non-fatal, continue |
| Rate limiter | token bucket + RPM window | waits (≤10 tries) | exp ≤15s | advisory → call anyway (extraction: hard break) |

---

## 13. Known gaps & footguns (worth fixing)

1. **Analysis has no retry** (the bug you hit): one transient Gemini 503 → permanent
   `error`/NULL row that nothing re-drives. Fix: retry with backoff in
   `run_analysis` for 5xx.
2. **Celery autoretry is dead for 4 of 6 stages** — `increment_retry` marks `failed`
   before re-raise; make the wrapper's burnout path the only `failed` writer.
3. **Token-less `force_release`** can delete a newer run's lock after a crash.
4. **Lock refresher lives in the API process**, not workers — web restart mid-run
   forfeits the lock at 30 min while tasks run up to 2 h.
5. **Finalize overwrites the SQL status** with Python logic that ignores
   skipped/total docs; an all-skipped case reports `complete` and triggers analysis.
6. **`chain` NULL on error** + results-masking hides failures from the UI.
7. `analysis_executor`, `gemini_client`, routing map disagree on the Gemini model
   name (env vs hardcoded).
8. Groq TPM default (6,000) is an order of magnitude tighter than RPM — likely a
   config bug.
9. Duplicate `headline` key in `verification_schema.json`; `verification_schema`
   is a shape description, not a schema.
10. Dead code: `_require_owner` (cases.py:74), `DETERMINISTIC_DOC_TYPES` +
    `is_deterministic_doc` (model_router.py:107), Redis keys `:results`/`:errors`/
    `:docs`/`:done_count` never populated, `RETRY_DELAYS[2]=30` never used.
11. Default JWT secret in `config.py:64` must be changed for any deployment.
12. Idempotency check is non-atomic (double-run possible on redelivery), and
    `retry_count` isn't reset by the retry endpoint (compounds across cycles).

---

## 14. Dead code & unused inventory (full-repo sweep)

Method: `ruff check backend --select F` (clean — no unused imports/locals), AST
cross-reference scan, import greps on every module, and a MySQL
`information_schema.columns` pass compared against every read/write in the code.
"Dead" = defined/created but nothing consumes it.

### 14.1 Backend — entirely dead module

| File | Why dead |
|---|---|
| `backend/integrations/storage/file_service.py` (whole module: `list_output_cases`:32, `get_case_bundle_from_filesystem`:73, …) | never imported anywhere; only self-references |

### 14.2 Backend — dead symbols

| Symbol | Location | Notes |
|---|---|---|
| `_ensure_tables` | `database/migrations.py:184` | dead alias of live `ensure_tables` |
| `get_recent` | `integrations/llm/rate_limiter.py:220` | no callers |
| `is_deterministic_doc` + `DETERMINISTIC_DOC_TYPES` | `integrations/llm/model_router.py:15-25`, `:107` | no callers; `REASONING_DOC_TYPES`/`resolve_model` are the live path |
| `EMAIL_RE` | `routers/auth.py:21` | unused — Pydantic `EmailStr` does validation |
| `RETRY_DELAYS[2] = 30` | `integrations/ocr/sarvam_client.py:25` | 3rd sleep never reached (see §13.10) |
| Redis keys `:results` / `:errors` / `:docs` / `:done_count` | `integrations/redis/state_store.py` | never populated (see §13.10) |

### 14.3 Backend — dead constants (`shared/constants.py`)

Defined but referenced nowhere:

- `STATUS_PREPROCESSING`, `STATUS_OCR_IN_PROGRESS`, `STATUS_MERGING`,
  `STATUS_COMPLETE`, `STATUS_PARTIAL`
- Entire `STEP_*` family: `STEP_PIPELINE`, `STEP_PREPROCESSING`, `STEP_OCR`,
  `STEP_MERGE`, `STEP_CLASSIFY`, `STEP_STRUCTURE`, `STEP_DONE` (no callers)

Still used (keep): `STATUS_PROCESSING`, `STATUS_PENDING_RETRY`,
`STATUS_NO_TRANSACTIONS` (title_chain.py), `STATUS_PREPROCESSED`,
`STATUS_OCR_DONE`, `STATUS_MERGED`, `STATUS_CLASSIFYING`,
`STATUS_CLASSIFICATION_FAILED`, `STATUS_STRUCTURING`, `STATUS_STRUCTURED`,
`STATUS_FAILED`. All `DOC_TYPE_*` constants are used by `services/classifier.py`.
All `Stage` members in `domain/state_machine.py` are used for valid-state
comparisons — none dead.

### 14.4 Database — dead / vestigial columns

Checked all 5 tables (`cases`, `documents`, `title_chains`, `users`,
`verification_results`) against every SQL statement and repo call:

| Column | Verdict |
|---|---|
| `documents.raw_ocr_path` | **never written** — `update_document_status` accepts it (`document_repo.py:45`) but no stage passes it; `get_case_documents`:94 selects it → always NULL. Either drop or start persisting the raw-OCR PDF path here. |
| `users.full_name` | written on register, read by repos, returned by `/auth/register|login` — but never displayed in the frontend dashboard. Used, not dead; note for cleanup decision. |

No dead tables; every other column is written and/or read by a live path.

### 14.5 Frontend — dead / orphan files

| File | Verdict |
|---|---|
| `src/types.ts` | **orphan** — no imports anywhere (6 interfaces) |
| `src/metadata.json` | **orphan** — Chrome-extension-style manifest; not referenced by `index.html`, vite, or build |
| `src/dashboard/utils.tsx` | `flattenObj`, `buildSummaryGroups`, `SummaryTable`, `FlatRow` are exported but only chain to each other internally; only `DocSummary` is imported by `VerificationDashboard`. Make them module-private or delete. |

NOT dead (verified used): `three`/`DuneFieldBackground`, all `components/*`,
`server.ts` (+ express/dotenv), `@google/genai` (used by `server.ts:5`),
`landingData.ts`, `AuthScreen`. Note: `vite` is listed in both `dependencies`
and `devDependencies` in `frontend/package.json` (cosmetic duplicate).

### 14.6 Dependencies

- `requirements.txt` — all 22 direct packages are imported/used (incl. `aiofiles`,
  pymupdf, reportlab, `email-validator` via `EmailStr`). No unused deps.
- `frontend/package.json` — no unused deps (duplicate `vite` entry above is the
  only blemish).

### 14.7 Config / env

- Every `backend/config.py` var has a consumer (incl. the `MODEL_ROUTING_MAP`
  env → `model_router._load_routing_map`, `MAX_UPLOAD_SIZE_MB` →
  `file_utils`). No dead config.

### 14.8 Stale planning docs (informational, not code)

`docs/*.md` includes older planning/scratch docs that may contradict current
behavior — review before relying on or deleting them: `BACKEND_AUDIT.md`,
`PIPELINE_ISSUES_ANALYSIS.md`, `REFACTOR_PLAN.md`, `TITLE_CHAIN_GRAPH_PLAN.md`,
`PRODUCTION_READINESS_PLAN.md`, `LLM_PROMPTS.md`, `LEGAL_OPINION_REPORT_FORMAT.md`,
`langfuse-observability-plan.md`, `opencode-architecture.md`.

### 14.9 Suggested first-pass cleanup (lowest risk → highest)

1. Delete `frontend/src/types.ts`, `frontend/src/metadata.json`.
2. Delete `_ensure_tables`, `get_recent`, `input EMAIL_RE`, `is_deterministic_doc`
   + `DETERMINISTIC_DOC_TYPES`.
3. Delete dead `STATUS_*`/`STEP_*` constants.
4. Delete `backend/integrations/storage/file_service.py` (after confirming no
   import remains — it is self-contained).
5. Drop `documents.raw_ocr_path` (or wire OCR stage to populate it).
6. Strip `flattenObj`/`buildSummaryGroups`/`SummaryTable`/`FlatRow` to module-private.