# Backend Audit — Issues, Dead Code & Improvements

Full audit of `C:\Users\Asus\OneDrive\Desktop\clearTitle\backend`.
Each issue is explained with context, evidence (file:line), why it matters,
and a concrete fix. Grouped by priority — critical first, then high, medium, low.

---

## Issue 1 — JWT secret has a known default (CRITICAL)

**What's wrong:** When the server starts, it reads `JWT_SECRET_KEY` from
the environment. If the env var is missing, it falls back to the string
`"cleartitle-secret-key-production-change-me-12345"`. This default is
written in the source code, which is public (GitHub).

**Why it matters:** Anyone who reads the source can forge a valid JWT token
and impersonate any user — admin or guest. A deployment without `.env` is
completely compromised. This is the most severe security issue in the codebase.

**Evidence:** `config.py:64`
```python
JWT_SECRET_KEY: str = "cleartitle-secret-key-production-change-me-12345"
```

**Fix:**
1. Remove the hardcoded default entirely — set default to `""`.
2. Add a startup check: if `JWT_SECRET_KEY` is empty or equals the old
   default, raise `ValueError` and refuse to start.
3. In local dev, the `.env` already sets it. In production, it must be
   set via secrets manager.

**Accept:** Server refuses to start without an explicit `JWT_SECRET_KEY`.

---

## Issue 2 — `/api/clear` endpoint has no authentication (CRITICAL)

**What's wrong:** The `/api/clear` endpoint flushes all Redis data, revokes
every running Celery task, and purges the entire task queue. It requires
zero authentication — any HTTP client can call it.

**Why it matters:** An attacker (or a curious browser tab) can destroy all
in-flight processing with a single GET request. Even in dev, a stray
`curl localhost:8000/api/clear` kills every running pipeline.

**Evidence:** `routers/cases.py:453-483`
```python
@router.get("/clear")
async def clear_all_data():
    # flushes Redis, revokes all tasks, purges queue
```
No `Depends(get_current_user)` or any auth middleware.

**Fix:**
1. Add `Depends(get_current_user)` to the endpoint.
2. Add an admin-role check (or at minimum, require authentication).
3. Better yet: remove it from the router entirely and make it a CLI
   management command that runs locally.

**Accept:** `curl localhost:8000/api/clear` returns 401 without a valid token.

---

## Issue 3 — No startup validation for required API keys (HIGH)

**What's wrong:** The server starts happily even if `SARVAM_API_KEY`,
`GROQ_API_KEY`, `GEMINI_API_KEY` are all empty. The first time a user
uploads a document, the pipeline runs all the way to the OCR stage and
then fails with a cryptic error from the Sarvam client.

**Why it matters:** A fresh deployment looks healthy (the server responds
to `/health`, the UI loads) but every document processing attempt fails.
The error messages are deep in worker logs, not visible to the user or
the deployer. It wastes time debugging what is actually a missing env var.

**Evidence:** `config.py` — all API key fields default to `""`. No
validation function exists. `main.py` startup only checks truthiness of
keys in `/health` but doesn't block startup.

**Fix:**
1. Add `_validate_config()` called in `main.py` at startup.
2. Check that every key listed in `REQUIRED_API_KEYS` is non-empty.
3. Raise `ValueError` with a clear message listing which keys are missing.

**Accept:** Server refuses to start if any required API key is missing.

---

## Issue 4 — Lock leaks in upload and retry (HIGH)

**What's wrong:** The pipeline uses a Redis distributed lock to prevent
two pipelines from running on the same case simultaneously. The lock is
acquired at the start, but if an error happens between acquisition and
the actual pipeline start, the lock is never released. The case becomes
permanently locked — no retry, no upload, nothing works until the Redis
key expires (which it doesn't, because there's no TTL).

**Why it matters:** A user uploads a document, something fails (e.g. the
Redis log write fails), and now their case is stuck forever. The only fix
is manually deleting the Redis key.

**Evidence — Upload path:** `routers/cases.py:191-223`
```python
lock = acquire_case_lock(case_id)  # line 198
# ... if set_case_status() or append_log() fail here ...
# the lock is never released
case = start_case_pipeline(...)  # line 213
```

**Evidence — Retry path:** `routers/cases.py:270-333`
Same pattern: lock acquired at line 280, multiple early-return paths at
lines 293-309 that don't release the lock.

**Fix:**
Wrap the entire lock lifetime in `try/finally`:
```python
lock = acquire_case_lock(case_id)
try:
    # all the logic that can fail
    ...
finally:
    lock.release()
```
Or better: use a context manager `with acquire_case_lock(case_id):`.

**Accept:** No path through upload or retry can leave a lock held after
the function returns.

---

## Issue 5 — Gemini 503 retries not enough (HIGH — root cause of EC failure)

**What's wrong:** When Gemini returns `503 UNAVAILABLE` (model experiencing
high demand), the system retries 3 times with increasing backoff. During
demand spikes, 3 retries is not enough — the Sale Deed doc succeeded on
its 3rd try, but the EC doc exhausted all 3 retries and failed permanently.

**Why it matters:** This is the actual reason the A0FD0A1C EC document
failed. Both documents hit Gemini simultaneously. The Sale Deed got lucky
on its 3rd retry (26s, 96s, then success on 68s). The EC exhausted all 3
(26s, 96s, 68s) and fell back to Groq, which also failed (wrong model
names). The user saw "All Groq models failed" when the real problem was
Gemini demand.

**Evidence:** Worker logs show:
```
16:26:59  DOC_002 Gemini attempt 1: 503 UNAVAILABLE (high demand)
16:27:25  DOC_002 Gemini attempt 2: 503 UNAVAILABLE
16:29:01  DOC_002 Gemini attempt 3: 503 UNAVAILABLE
16:30:19  DOC_002 Fallback to Groq → model 404
```

**Fix:**
1. Increase Gemini retries for 503 errors to 5 (not 3).
2. Use consistent exponential backoff: 10s, 20s, 40s, 80s, 160s.
3. Log the primary provider error alongside the fallback error (see Issue 6).

**Accept:** A Gemini 503 during demand spike retries up to 5 times with
proper backoff before falling back.

---

## Issue 6 — Error message hides the real provider (HIGH)

**What's wrong:** When a document fails after trying multiple LLM providers,
the error message stored in the database is "All Groq models failed" — even
when the primary provider was Gemini. The fallback chain overwrites the
error message at each step, so only the last provider's error survives.

**Why it matters:** A user sees "All Groq models failed" and thinks Groq
is the problem. The actual issue (Gemini 503) is invisible. This directly
misleads debugging.

**Evidence:** `services/extract.py:58-110`
```python
for model_name in chain:
    ...
    except Exception as e:
        last_error = f"All {model_name} models failed: {str(e)}"  # overwrites
```
Each failed provider replaces `last_error` with its own message.

**Fix:**
1. Collect errors across the chain as a list, not a single overwritten variable.
2. Store the full chain: `"Gemini gemini-2.5-flash: 503 UNAVAILABLE; Groq llama-3.3-70b: 404 Not Found"`.
3. Log the decision at each fallback step (see Issue 14).

**Accept:** Error message for a multi-provider failure lists every provider
tried and the reason each failed, in order.

---

## Issue 7 — Groq fallback chain is dead (HIGH)

**What's wrong:** The fallback chain after Gemini is Groq. But both Groq
models in the config (`llama-3.3-70b-versatile` and `llama-3.1-8b-instant`)
return 404 on the user's Groq account. The fallback chain is useless — it
always fails, adding ~60 seconds of wasted time before the document is
marked as permanently failed.

**Why it matters:** Every Gemini failure results in a guaranteed Groq failure
too, wasting time and producing misleading error messages. The fallback
should either work or not exist.

**Evidence:**
- `integrations/llm/model_router.py:58-62` — `FALLBACK_CHAIN` lists Groq models.
- `integrations/llm/groq_executor.py:23-26` — `GROQ_MODELS` list has both
  models that 404.
- Worker logs: `All Groq models failed: 404 Not Found`

**Fix:**
1. Check the user's Groq account for available models and update the list.
2. Or: replace Groq with another provider (e.g. another Gemini model variant,
   or OpenAI if available).
3. Or: if no working fallback exists, remove the fallback chain and fail
   immediately with the Gemini error.

**Accept:** The fallback chain either works end-to-end or is removed. No
guaranteed-failure fallback.

---

## Issue 8 — Race condition in upload: Redis before MySQL (HIGH)

**What's wrong:** When a user uploads a document, the system first creates
the case in Redis (`redis_init_case`), then creates it in MySQL (`init_case`).
If the process crashes between these two calls, Redis has a case record that
MySQL doesn't. Subsequent operations find the case in Redis but not in MySQL,
leading to inconsistent state.

**Why it matters:** A crash during upload (OOM, network blip) leaves an
orphaned Redis case. The user sees their case in the list (from Redis) but
processing fails because MySQL has no case record.

**Evidence:** `routers/cases.py:143-188`
```python
redis_init_case(case_id, meta)  # line ~160 — Redis first
try:
    init_case(case_id, meta)    # line ~170 — MySQL second
except Exception:
    log("non-fatal")            # line 185 — but Redis is now orphaned
```

**Fix:**
1. Create MySQL record first (the source of truth).
2. Then warm the Redis cache from the MySQL data.
3. If Redis warm fails, the case still works (MySQL is truth).
4. If MySQL fails, don't create Redis at all.

**Accept:** A crash between MySQL and Redis init leaves no orphaned state.

---

## Issue 9 — Zero-value fields never written to database (MEDIUM)

**What's wrong:** After structuring, the system writes token counts, latency,
and cost to the `documents` table. But the code checks `if input_tokens:`
instead of `if input_tokens is not None:`. When the value is `0` (which is
a valid value — a cached response costs $0), the condition is falsy and the
field is never written. The document retains stale values from a previous
attempt.

**Why it matters:** A document that was processed via a cached Gemini response
(cost $0, 0 tokens) shows the cost and tokens from a previous failed attempt.
Reporting and billing data is wrong.

**Evidence:** `database/document_repo.py:56-68`
```python
if input_tokens:    # 0 is falsy — skipped
    sets.append("input_tokens = %s")
if latency_ms:      # 0 is falsy — skipped
    sets.append("latency_ms = %s")
if cost_usd:        # 0 is falsy — skipped
    sets.append("cost_usd = %s")
```

**Fix:** Change all three to `is not None` checks:
```python
if input_tokens is not None:
if latency_ms is not None:
if cost_usd is not None:
```

**Accept:** A document with $0 cost and 0 tokens has those values written
correctly to the database.

---

## Issue 10 — String interpolation bug in error message (MEDIUM)

**What's wrong:** When a document replacement fails, the error message
shown to the user contains literal `{case_id}` and `{doc_id}` instead of
the actual values. The string uses `.format()` syntax but is not formatted.

**Why it matters:** The user sees a useless error message like
`"POST /api/case/{case_id}/doc/{doc_id}/replace"` instead of the actual
endpoint URL they should use.

**Evidence:** `workers/stages.py:225-226`
```python
"hint": "POST /api/case/{case_id}/doc/{doc_id}/replace"  # not an f-string
```

**Fix:** Change to an f-string:
```python
"hint": f"POST /api/case/{case_id}/doc/{doc_id}/replace"
```

**Accept:** The error message shows the actual case and document IDs.

---

## Issue 11 — `state_store.py` uses `print()` instead of logger (MEDIUM)

**What's wrong:** Error messages in the Redis state store use `print()`
instead of the project's standard `get_logger()`. These messages go to
stdout without timestamps, log levels, or any structure. In production
(log aggregation, Docker logs), they're invisible or mixed with other output.

**Why it matters:** When Redis operations fail, the error is printed but
not logged. A production operator searching logs for Redis errors will
find nothing. The failure is silent.

**Evidence:** `integrations/redis/state_store.py:64, 86, 109, 122`
```python
print(f"[state_store] Failed to init case {case_id}: {e}")  # not a real log
```

**Fix:** Replace all `print()` calls with `logger.error()` or `logger.warning()`.
```python
logger = get_logger(__name__)
# ...
logger.error("Failed to init case %s: %s", case_id, e)
```

**Accept:** `grep -n "print(" integrations/redis/state_store.py` returns 0 hits.

---

## Issue 12 — Duplicate helper functions across files (MEDIUM)

**What's wrong:** Several utility functions are copy-pasted across multiple
files instead of living in one shared location. When one copy is updated,
the others fall out of sync.

**What's duplicated:**

1. `_enforce_access()` — identical in `routers/cases.py:74-86` and
   `routers/results.py:16-19`. Checks if a user owns a case.

2. `_is_ec()` and `_is_sale_deed()` — identical in
   `services/title_chain.py:66-71` and `services/verify.py:37-42`. Checks
   document type.

3. JSON parsing with markdown code-block extraction — nearly identical in
   `gemini_executor.py:80-104`, `groq_executor.py:108-115`, and
   `analysis_executor.py:71-93`.

**Why it matters:** If the access check logic changes (e.g. adding shared
cases), you have to remember to update it in two places. If you forget,
one endpoint has the old logic. This is a classic source of security bugs.

**Fix:**
1. Move `_enforce_access()` to `services/auth.py` or `utils/access.py`.
2. Move `_is_ec()` / `_is_sale_deed()` to `services/schemas/__init__.py`.
3. Extract JSON parsing to `integrations/llm/utils.py` and import from all
   three executors.

**Accept:** Each helper exists in exactly one file; other files import it.

---

## Issue 13 — Duplicate `_case_row()` query (MEDIUM)

**What's wrong:** There are two different code paths to read the same
`cases` table row. `services/results.py` has its own `_case_row()` that
runs raw SQL, while `database/repositories/case_repo.py` has
`get_case_status_payload()`. They query the same table with slightly
different column sets.

**Why it matters:** If a column is added to the `cases` table, you have to
update both queries. If one is updated and the other isn't, the status
endpoint and the results endpoint return different data.

**Evidence:**
- `services/results.py` — `_case_row()` runs `SELECT id, case_name, ...`
- `database/repositories/case_repo.py` — `get_case_status_payload()` runs
  the same query with different columns.

**Fix:** Remove `_case_row()` from `results.py` and use
`case_repo.get_case_status_payload()` everywhere.

**Accept:** One query reads the `cases` table; `results.py` imports from
`case_repo`.

---

## Issue 14 — No structured logging or trace IDs (MEDIUM)

**What's wrong:** All log output is free-text to stdout. There are no JSON
structured logs, no request IDs, no trace IDs that correlate log lines
across a pipeline run. The `documents` table has a `trace_id` column and
`set_trace_id()` function, but nothing ever writes to it — the field is
always `NULL`.

**Why it matters:** When a pipeline fails, you have to grep through
thousands of lines of free-text logs to find the relevant entries for one
document. There's no way to say "show me all logs for document X" because
nothing tags log lines with the document ID.

**Evidence:**
- `database/document_repo.py:275` — `set_trace_id()` exists, never called.
- `workers/stage_adapter.py` — runs stages but doesn't set trace_id.
- All logger calls are `logger.info("message")` without structured fields.

**Fix:**
1. Set `documents.trace_id` to the Celery task ID at stage start.
2. Use structured logging: `logger.info("OCR completed", extra={"doc_id": doc_id, "stage": "ocr", "trace_id": trace_id})`.
3. Or adopt `structlog` for automatic context propagation.

**Accept:** Every log line from a pipeline run carries the document ID and
trace ID as structured fields.

---

## Issue 15 — No tests (MEDIUM)

**What's wrong:** The backend has exactly 1 test file with 8 unit tests,
all covering title-chain enrichment logic. There are no tests for:
- API endpoints (upload, status, retry)
- Pipeline stages (OCR, classify, structure)
- LLM routing and fallback chain
- Redis state management
- Authentication and access control
- Error handling paths

**Why it matters:** Every change risks breaking something invisible. The
Gemini retry issue (Issue 5), the lock leak (Issue 4), the zero-value
bug (Issue 9) — all would have been caught by basic tests. Without tests,
refactoring is dangerous and debugging is the only quality gate.

**Fix (priority order):**
1. API integration tests: upload → status → process → verify.
2. Unit tests for `extract.py` fallback chain logic.
3. Unit tests for `model_router.py` routing decisions.
4. Unit tests for `state_store.py` Redis operations (mock Redis).

**Accept:** `pytest --cov=backend` shows >50% line coverage.

---

## Issue 16 — `update_file_in_case()` is not atomic (MEDIUM)

**What's wrong:** The function reads the entire files list from Redis,
modifies it in Python, then writes it back. If two concurrent operations
(e.g. two uploads to the same case, or a replacement during upload) do
this simultaneously, the second write overwrites the first.

**Why it matters:** A document replacement during processing can silently
lose the new document from the case's file list.

**Evidence:** `integrations/redis/state_store.py:189-200`
```python
files = get_case_files(case_id)   # read
files[idx] = updated_file         # modify in Python
redis.hset(...)                   # write back — lost if another thread wrote in between
```

**Fix:** Use a Redis Lua script for atomic read-modify-write, or use
Redis hashes with per-file keys instead of a single list.

**Accept:** Two concurrent file updates to the same case don't lose data.

---

## Issue 17 — No rate limiting on upload and process (MEDIUM)

**What's wrong:** The `/api/upload` and `/api/process` endpoints have no
rate limiting. A user (or script) can upload thousands of documents and
trigger thousands of pipelines, exhausting Sarvam OCR credits and Gemini
API quotas.

**Why it matters:** A single malicious or buggy client can burn through
the entire team's API budget in minutes.

**Fix:**
1. Add per-user rate limiting (e.g. 10 uploads/hour, 5 process triggers/hour).
2. Add a maximum document size and page count at upload time.
3. Add a global concurrency limit on active pipelines.

**Accept:** Rate-limited user gets 429 after exceeding the limit.

---

## Issue 18 — No TTL on Redis keys (MEDIUM)

**What's wrong:** When a case is processed, Redis stores metadata, files,
results, and log entries under `case:{id}:*` keys. These keys have no TTL.
Old completed cases leave Redis keys forever.

**Why it matters:** Redis memory grows unbounded. Over weeks/months of
production use, Redis fills up and starts evicting keys (if maxmemory is
set) or crashes (if it's not).

**Fix:** Set a TTL (e.g. 7 days) on case keys when the case reaches a
terminal state (`completed` or `failed`). The MySQL record is permanent;
the Redis cache is disposable.

**Accept:** Redis keys for completed cases auto-expire after the TTL.

---

## Issue 19 — `list_cases()` pagination returns wrong total (MEDIUM)

**What's wrong:** The `list_cases()` endpoint returns `total: len(results)`
where `results` is the current page. The client sees `total: 10` (the page
size) and doesn't know if there are 10 more pages or zero.

**Why it matters:** The frontend can't implement "load more" or pagination
correctly because it doesn't know the real total count.

**Evidence:** `database/repositories/case_repo.py:79-96`
```python
return {"cases": cases, "total": len(cases)}  # wrong: this is page count
```

**Fix:** Add `SELECT COUNT(*) FROM cases WHERE user_id = %s` and return
the real total.

**Accept:** `GET /api/cases?page=1&page_size=10` with 25 cases returns
`total: 25`, not `total: 10`.

---

## Issue 20 — `/health` endpoint leaks API key presence (MEDIUM)

**What's wrong:** The `/health` endpoint returns which API keys are
configured: `{"sarvam_key": true, "groq_key": false, "gemini_key": true}`.
This tells an attacker which services are available and which aren't.

**Why it matters:** Information leakage. An attacker knows Groq isn't
configured, so they can target that provider knowing there's no fallback.

**Evidence:** `main.py:62-67`
```python
return {
    "sarvam_key": bool(config.SARVAM_API_KEY),
    "groq_key": bool(config.GROQ_API_KEY),
    ...
}
```

**Fix:** Return only `{"status": "ok"}`. Log the detailed key status at
startup instead.

**Accept:** `/health` returns `{"status": "ok"}` with no key details.

---

## Issue 21 — No PDF MIME type validation (MEDIUM)

**What's wrong:** The upload endpoint checks that the filename ends with
`.pdf` but doesn't validate the actual file content. A user can rename
a `.exe` or `.jpg` to `.pdf` and upload it.

**Why it matters:** A malicious or buggy upload could send non-PDF content
to the preprocessing pipeline, causing crashes or unexpected behavior in
the PDF renderer.

**Evidence:** `routers/cases.py:159`
```python
if not file.filename.lower().endswith('.pdf'):
    raise HTTPException(400, "Only PDF files are accepted")
```

**Fix:** Check the MIME type or magic bytes (PDF starts with `%PDF-`).

**Accept:** A non-PDF file renamed to `.pdf` is rejected.

---

## Issue 22 — Preprocessing failure silently swallowed (MEDIUM)

**What's wrong:** When PDF preprocessing fails (e.g. corrupted file), the
error is logged as WARNING and the original (unprocessed) PDF is used as
the "preprocessed" input for OCR. The document proceeds through the
entire pipeline with a potentially corrupt input.

**Why it matters:** A corrupted PDF that should fail immediately instead
consumes Sarvam OCR credits, then fails at structuring with a confusing
error. The user wastes credits and gets an unhelpful error message.

**Evidence:** `workers/stages.py:82-98`
```python
try:
    preprocessed = preprocess_pdf(path, doc_id)
except Exception as e:
    logger.warning(f"Preprocessing failed: {e}")  # WARNING, not ERROR
    preprocessed = path  # use original — silently proceeds
```

**Fix:** Bump to `logger.error()` and add a warning flag to the document
record so the user sees "Preprocessing failed, using original file" in
the UI.

**Accept:** A preprocessing failure is visible to the user and logged at
ERROR level.

---

## Issue 23 — Sarvam client not thread-safe (LOW)

**What's wrong:** The `SarvamAI` client is a global singleton created
without a `threading.Lock`. If two Celery worker threads try to create
the client simultaneously, both may see `_sarvam_client is None` and
create duplicate clients.

**Why it matters:** Minor — duplicate clients work, but waste memory and
may cause confusion if the client holds state (tokens, connections).

**Evidence:** `integrations/ocr/sarvam_client.py:41-55`
```python
_sarvam_client = None

def get_client():
    global _sarvam_client
    if _sarvam_client is None:  # not atomic
        _sarvam_client = SarvamAI(...)
```
Compare to `database/connection.py` which uses `threading.Lock`.

**Fix:** Add a `threading.Lock` around the singleton creation, same
pattern as `database/connection.py`.

**Accept:** Two concurrent `get_client()` calls create exactly one client.

---

## Issue 24 — No timeout on Sarvam `job.wait_until_complete()` (LOW)

**What's wrong:** After submitting OCR to Sarvam, the code calls
`job.wait_until_complete()` which blocks until the job finishes. There's
no timeout — if Sarvam hangs, the Celery task blocks until the 7200s
(2 hour) hard limit.

**Why it matters:** A hung Sarvam job ties up a Celery worker for 2 hours.
With limited concurrency, this can block all other pipeline work.

**Evidence:** `integrations/ocr/sarvam_client.py:116, 203`
```python
job.wait_until_complete()  # no timeout parameter
```

**Fix:** Add a polling loop with a max-wait of ~300s (5 minutes). If the
job hasn't completed, cancel it and raise a timeout error.

**Accept:** A hung Sarvam job is detected within 5 minutes and the worker
is freed.

---

## Issue 25 — Dead code: `file_service.py` (entire module) (LOW)

**What's wrong:** `integrations/storage/file_service.py` contains 160 lines
and 5 public functions (`get_case_ocr_raw`, `list_output_cases`,
`get_case_bundle_from_filesystem`, `list_case_ocr_raw`,
`list_case_outputs`). None of these functions are called from anywhere
in the codebase.

**Why it matters:** Dead code confuses developers ("should I use this?")
and inflates the codebase. It may have been used in a previous architecture
and was never cleaned up.

**Fix:** Delete the entire file.

**Accept:** `grep -rn "file_service" backend/` returns 0 hits.

---

## Issue 26 — Dead code: unused constants and functions (LOW)

**What's wrong:** Several constants and functions are defined but never
imported or called:

1. `StageResult` dataclass (`workers/stage_base.py:17-21`) — exported
   in `__all__` but never instantiated. Stages return plain dicts.

2. `is_deterministic_doc()` (`integrations/llm/model_router.py:107-108`)
   — defined but never called.

3. `get_schema()` (`services/schemas/__init__.py:19-21`) — exported but
   all callers use `SCHEMA_MAP` directly.

4. `GENERIC_SCHEMA_TEMPLATE` (`services/schemas/__init__.py:8`) — exported
   but never imported.

5. 20+ `STATUS_*` constants (`shared/constants.py`) — workers use the
   `Stage` enum instead.

6. 7 `STEP_*` constants (`shared/constants.py:52-58`) — never imported.

7. `_ensure_tables()` (`database/migrations.py:186-188`) — deprecated
   wrapper never called.

8. `persist()` function (`workers/stage_adapter.py:41-47`) — called but
   does nothing (pass-through).

**Fix:** Delete all of the above.

**Accept:** `grep -rn "StageResult\|is_deterministic_doc\|get_schema\|GENERIC_SCHEMA_TEMPLATE\|STEP_PIPELINE\|_ensure_tables" backend/` returns 0 hits.

---

## Issue 27 — Duplicate cost/token calculation logic (LOW)

**What's wrong:** Token counting, cost calculation, and
`LLMCallTracker.record()` logic is nearly identical in three files:
- `gemini_executor.py:80-104`
- `groq_executor.py:108-115`
- `analysis_executor.py:71-93`

**Why it matters:** If the cost formula changes (new pricing), you have to
update three places. The current prices ($0.15/$0.60 per 1M for Gemini)
are already hard-coded in multiple locations.

**Fix:** Extract to a shared function `record_llm_call(provider, model,
input_tokens, output_tokens, latency_ms)` in a new
`integrations/llm/tracking.py`.

**Accept:** Cost calculation exists in one place; three executors call it.

---

## Issue 28 — `llm_call_log` scan is O(N) per call (LOW)

**What's wrong:** `LLMCallTracker.get_recent()` scans the entire
`llm_call_log` list (up to 10,000 entries) and deserializes every JSON
object to filter by timestamp. This runs on every rate-limit check.

**Why it matters:** With 10,000 entries, this is ~10,000 JSON deserializations
per call. Not critical now but will slow down as usage grows.

**Evidence:** `integrations/llm/rate_limiter.py:220-236`

**Fix:** Use Redis sorted sets with timestamp scores instead of a list.
Range queries are O(log N) instead of O(N).

**Accept:** Rate-limit check time is constant regardless of call history size.

---

## Issue 29 — `update_case_status()` executes 4 subqueries (LOW)

**What's wrong:** A single `UPDATE cases SET ...` statement runs 4
subqueries in the SET clause to count structured/failed documents. On
large tables, this is expensive.

**Evidence:** `database/repositories/case_repo.py:26-46`

**Fix:** Use conditional aggregation:
```sql
UPDATE cases SET structured_count = (
    SELECT COUNT(*) FROM documents WHERE case_id = %s AND status = 'structured'
), ...
```
Or: maintain counters incrementally instead of recalculating.

**Accept:** Status update is a single query with no subqueries.

---

## Issue 30 — Dead directory creation at import (LOW)

**What's wrong:** `main.py` creates directories `uploads/`,
`outputs/structured/`, `outputs/raw_ocr/` relative to the current
working directory at import time. These directories are never used —
actual storage uses `outputs/{case_id}/` via `file_utils.py`.

**Why it matters:** Creates confusing empty directories. New developers
see them and think they're important.

**Evidence:** `main.py:23-24`
```python
for d in ["uploads", "outputs/structured", "outputs/raw_ocr"]:
    Path(d).mkdir(parents=True, exist_ok=True)
```

**Fix:** Remove the dead directory creation.

**Accept:** No empty directories created at startup.

---

## Summary

| Severity | Count | Issues |
|----------|-------|--------|
| Critical | 2 | JWT secret, /clear no auth |
| High | 6 | Config validation, lock leaks, Gemini retries, error masking, Groq dead, Redis-before-MySQL |
| Medium | 12 | Zero-value bug, string interpolation, print vs logger, duplicates, no tests, race conditions, no rate limiting, no TTL, wrong pagination total, health leakage, MIME validation, silent preprocessing failure |
| Low | 10 | Thread safety, no timeout, dead code (×3), duplicate logic, O(N) scan, 4 subqueries, dead directories |

## Recommended Priority Order

1. **This session:** JWT secret + /clear auth + config validation (Issues 1-3)
2. **Next session:** Lock lifecycle + Gemini retries + error chain (Issues 4-6)
3. **Then:** Dead code cleanup + duplicate extraction (Issues 25-27)
4. **Backlog:** Tests + Redis TTL + pagination + logging (Issues 14-15, 18-19)
