# Backend Production-Readiness Plan

Ordered steps to take the backend from "working prototype" to production-safe.
Each step is an issue found in `docs/ARCHITECTURE_OVERVIEW.md` (§11–§13) or
verified in the current source, with a concrete fix and an acceptance check.

Dependency rule: do steps **1–3 first** (error taxonomy + fail-fast) before
**4–8** (retry/fallback correctness) before **9–13** (cleanup). Steps 1–3
change how errors are raised/classified; everything downstream consumes them.

---

## Step 1 — One `PipelineError` taxonomy (foundation)

**Issue (ARCHITECTURE §13.1):** Error classification is coarse. Retry-vs-
fallback-vs-give-up is decided by string matching and `except Exception`,
scattered across files. There is no single place that says "this is transient,
this is terminal."

**Evidence:**
- `backend/services/extract.py:29` `is_transient_error(e)` and `:38`
  `is_rate_limit_error(e)` match on `str(e)` substrings — fragile, provider-agnostic.
- `backend/workers/tasks.py:28-36` `TASK_RETRY_CONFIG` autoretrys on
  `(Exception,)` — every exception class retried 5× unless excluded.
- Retry numbers live in 4 places: `tasks.py` (5/120s), `extract.py`
  (`OCR_MAX_RETRIES=3`, `STRUCTURE_MAX_RETRIES=3`, `MAX_RATE_LIMIT_RETRIES=5`),
  Sarvam inner+outer retries, title/verify tasks (`max_retries=2`).

**Fix:**
1. Add `backend/domain/pipeline_errors.py` with a base `PipelineError` and
   subclasses:
   - `TransientProviderError` (429/5xx/timeout/RESOURCE_EXHAUSTED → retry, then fallback)
   - `RateLimitError` (per-provider, with `shrinkable: bool`)
   - `InsufficientCreditsError` (terminal, excluded from retry)
   - `ModelOutputError` (empty response / unparseable JSON / schema mismatch → re-prompt once, then fallback)
   - `SafetyBlockError` (terminal for that content — no retry of same input)
   - `ClassificationFailedError` (terminal, already exists as `ClassificationFailed`)
2. Replace the string matching in `extract.py` with `isinstance` checks on
   these classes.
3. Remove the two string-matchers from `extract.py` (`is_transient_error`,
   `is_rate_limit_error`).
4. Keep `max_retries`/backoff knobs in `config.py` as one
   `RETRY_POLICY` dict (see Step 4), not in 4 modules.

**Accept:** `grep -rn "str(e)" backend/services backend/workers` shows no
classification logic left; `ClassificationFailed` and
`InsufficientCreditsError` are excluded from autoretry.

---

## Step 2 — Sarvam credits: detect and fail fast (bulk of production failures)

**Issue (ARCHITECTURE §12.2):** 9/10 production failures were Sarvam
`Insufficient credits for N pages` — a permanent condition. `run_ocr_with_retry`
retried 3×+3× anyway, burning time and masking the real cause.

**Evidence:** `backend/integrations/ocr/sarvam_client.py` `run_ocr_with_retry`
inner+outer `OCR_MAX_RETRIES` loops (referenced from `extract.py:14,46-55`).

**Fix:**
1. In `sarvam_client.py`, detect the credit/quota error from the Sarvam error
   body (match on "insufficient credits", Sarvam's quota error codes) and
   raise `InsufficientCreditsError` (Step 1).
2. Add `InsufficientCreditsError` to `exclude_from_autoretry` in
   `backend/workers/tasks.py` (alongside `ClassificationFailed`).
3. On `InsufficientCreditsError`, write a user-facing error in the case
   errors list immediately (via `document_repo.update_document_status` +
   Redis `append_log`) instead of waiting for retries to exhaust.
4. Pre-check: when a case is created, estimate total pages × Sarvam price and
   surface a "not enough credits" warning before kicking off OCR.

**Accept:** With credits exhausted, one OCR attempt runs, the doc is marked
`failed` with the credit message, no 3×/3× retry storm, UI shows the reason.

---

## Step 3 — Groq request-size guard (finish §12.1)

**Issue (ARCHITECTURE §12.1 remaining risk):** 5k `max_tokens` + a
Kannada-heavy prompt can still exceed Groq free-tier TPM (6k llama-3.1-8b,
12k llama-3.3-70b). Groq's 413 counts `prompt_tokens + max_tokens`, so an
oversized prompt is rejected before a token is generated.

**Evidence:** `backend/integrations/llm/groq_executor.py` hard-codes
`max_tokens`; `backend/config.py:54` `GROQ_TPM = 6000`.

**Fix:**
1. Make `max_tokens` per-model configurable in `config.py`
   (`GROQ_MAX_TOKENS` map keyed by model).
2. In `groq_executor.py`, before calling: estimate prompt tokens
   (`len(text)/1.5`, or a tokenizer) and compute `estimated_prompt +
   max_tokens` vs the model's real TPM.
3. If it cannot fit, **skip Groq and go straight to Gemini** (raise a
   `RateLimitError` with `shrinkable=True` so the caller falls through the
   chain) instead of attempting and failing.
4. Keep `GROQ_TPM=6000` default (already fixed from 15M).

**Accept:** An oversized Groq-bound doc never issues a doomed 413 call — it
routes to Gemini with a logged reason.

---

## Step 4 — Centralize retry policy (stop scattering it)

**Issue (ARCHITECTURE §13.2):** Retry behavior lives in 4 places with
different numbers and no single tuning point.

**Fix:**
1. Add one `RETRY_POLICY` dict in `backend/config.py`:
   `{stage: {max_retries, backoff_base, backoff_max, jitter, exclude_classes, fallback_chain}}`
   (e.g. `ocr`, `structure`, `title`, `verify`, `groq`, `sarvam`).
2. `backend/workers/tasks.py` builds `TASK_RETRY_CONFIG` from it per task.
3. `extract.py` and `sarvam_client.py` read their retry counts from it.

**Accept:** `grep -rn "MAX_RETRIES\|max_retries" backend` shows the only
definitions in `config.py` and `tasks.py` (derived).

---

## Step 5 — Gemini empty-response: log finish/block reason (ARCHITECTURE §12.3)

**Issue:** The 998A8755 Sale Deed returned HTTP 200 with empty text 3×,
likely a safety block, but `finish_reason`/`block_reason` are never read or
logged, so it's unconfirmable.

**Evidence:** `backend/integrations/llm/gemini_executor.py` parses
`response.text` without inspecting candidates.

**Fix:**
1. In `gemini_executor.py`, before parsing, read
   `response.candidates[0].finish_reason`, `response.prompt_feedback.block_reason`,
   and `safety_ratings`; log them as a structured line (`doc_id, stage, provider,
   finish_reason, block_reason`).
2. Empty text → raise `ModelOutputError` (Step 1) carrying the reasons.
3. `SafetyBlockError` (block_reason set) → do **not** retry the same content;
   trim/rewrite the offending chunk or mark the doc for human review.

**Accept:** Every empty/blocked Gemini response produces a log line showing
`finish_reason` and `block_reason`; a safety block fails without pointless retries.

---

## Step 6 — Combined error surfacing across the provider chain (ARCHITECTURE §12.6, §13.4)

**Issue:** For a Gemini-primary doc, the surfaced error is "All Groq models
failed" — as if Groq was the intended provider. The real provider is masked.

**Fix:**
1. In the structure stage (`backend/workers/stages.py` `StructureStage` /
   `backend/services/extract.py`), collect `errors[]` across the full chain:
   `Gemini failed (<reason>); Groq fallback failed (<reason>)`.
2. Raise one combined `PipelineError` listing every provider/model attempted.
3. Log a structured decision line per fallback (see Step 8).

**Accept:** For a Gemini-primary doc, the error message names both providers
and the reason per provider, in order.

---

## Step 7 — Resumable retry (skip completed work) (ARCHITECTURE §12.5, §13.3)

**Issue:** `start_retry_pipeline` replays preprocess → OCR → … from scratch
even when only the LLM stage failed. Correct but wasteful (burns Sarvam
credits and time).

**Evidence:** `backend/integrations/redis/state_store.py:462`
`reset_for_retry`; chain built in `backend/services/orchestrator.py`.

**Fix:**
1. Persist `last_completed_stage` on the document row (new column, or reuse
   the status string which is already monotonic).
2. On retry, rebuild the chain starting at the stage *after* the last
   completed one (skip re-uploading/re-merging when `merged_ocr` exists).
3. Update `reset_for_retry` to honor it instead of resetting to stage 1.

**Accept:** A doc that failed at structuring retries from the structuring
stage; OCR credits are not re-consumed.

---

## Step 8 — Structured per-stage observability (ARCHITECTURE §12.10)

**Issue:** No per-stage timing log, no global request-id correlation
(`trace_id` column + `set_trace_id` exist but are never populated), no
decision log for retries/fallbacks.

**Fix:**
1. Populate `documents.trace_id` with a request id at case creation and
   thread it through every log line (or adopt `celery` task id as the
   correlation id — lowest effort).
2. Emit one structured line per retry/fallback (ARCHITECTURE §13.6):
   `doc_id, stage, provider, model, attempt, error_class,
   decision(backoff|fallback|terminal), next_action`.
3. Persist per-stage timing (`stage_started_at` → `stage_completed_at`) into
   a per-stage field (or a JSON column) so a stuck stage is visible in data,
   not just logs.

**Accept:** Every log line carries a correlation id; every retry/fallback has
a decision record with attempt + error class.

---

## Step 9 — Stage-aware progress in the status payload (ARCHITECTURE §12.4, §13.7)

**Issue:** Progress caps at 90%, doc-count only. "Structured JSON saved to DB"
is the last log line with no "title analysis running" indicator — the UI looks
idle/stuck.

**Fix:**
1. Add the current stage per document to the `statusData` payload
   (`backend/integrations/redis/state_store.py:483` `get_case_job` reads
   `get_document_status` from MySQL — include it).
2. Derive a stage-aware label: `OCR 1/2 · Structuring Sale Deed · 2/3 docs`.
3. After persist, emit an explicit log: "All documents structured — running
   title analysis".

**Accept:** UI shows a per-doc stage chip (preprocessing/ocr/merging/
classifying/structuring/persisting/failed-with-reason) and a label instead of
a silent 90% bar.

---

## Step 10 — Fix pipeline-log write contention (extra, found in review)

**Issue:** `append_pipeline_log` (called per stage, per log line) does a
`SELECT … FOR UPDATE` on `cases.pipeline_logs`, re-reads, re-appends, and
re-writes the full 200-line JSON **per call**. Under concurrent doc stages
this serializes all workers on one row and can lose updates.

**Evidence:** `backend/database/repositories/verification_repo.py:16-35`.

**Fix:**
1. Append to Redis `case:{id}:log` (already the fast path) and flush to MySQL
   periodically/on completion, **or**
2. Batch: replace per-line writes with one final flush of the 200-cap list, **or**
3. If per-line MySQL must stay, use `JSON_SET`/`JSON_ARRAY_APPEND` instead of
   read-modify-write under `FOR UPDATE`.

**Accept:** N concurrent stages append logs without blocking each other;
stress test with 5 parallel docs shows no lost log lines.

---

## Step 11 — Remove dead DB columns, repo functions, config (ARCHITECTURE §11, §12.7)

**Verified dead (no callers in `backend/`):**

| Item | Location | Status |
|---|---|---|
| `cases.pipeline_status` | `migrations.py:40` | never written |
| `documents.raw_ocr_path` | `migrations.py:69`, `document_repo.py:45,68-69,94` | no stage writes it; OCR path is in `file_paths.ocr_chunks` |
| `documents.trace_id` + `set_trace_id` | `migrations.py:74,162`, `document_repo.py:275` | nothing calls `set_trace_id` |
| `state_store` dead helpers | `add_result:323, add_error:331, remove_error_for_doc:339, increment_done_count:356, set_doc_status:407` | only defined, never called (MySQL is truth) |
| `PRIMARY_STRUCTURER` | `.env` | zero references in `backend/` |
| stale docstrings | `groq_executor.py` "primary LLM" | contradicts `model_router` (Gemini primary for SD/EC) |

**Fix (in this order):**
1. Delete the dead `state_store` helper functions first (pure dead code).
2. Drop the 3 DB columns via one migration.
3. Remove `raw_ocr_path` from `document_repo.py` (param, field-set, SELECT).
4. Remove `set_trace_id` from `document_repo.py`.
5. Remove `PRIMARY_STRUCTURER` from `.env`/docs.
6. Fix the `groq_executor.py` docstring to reflect the routing reality.

**Accept:** `grep -rn "pipeline_status\|raw_ocr_path\|set_trace_id\|PRIMARY_STRUCTURER" backend` → 0 hits (after migration); app boots and a case passes end-to-end.

---

## Step 12 — Centralize cost formulas (ARCHITECTURE §12.9)

**Issue:** Gemini ($0.15/$0.60 per 1M) and Groq ($0.59/$0.79) prices are
hard-coded in 3 places and drift from billing.

**Fix:**
1. One `MODEL_PRICING` map in `backend/config.py` (per model:
   input/output per-1M-token price).
2. All cost computations import from it.

**Accept:** `grep -rn "0.15\|0.59\|0.60\|0.79" backend` shows prices only in
`config.py`.

---

## Step 13 — Quiet the context-cache noise (ARCHITECTURE §12.8)

**Issue:** `gemini_client._ensure_context_cache` logs
"Cached content is too small … min_total_token_count=1024" for short static
prompts — noisy, confusing next to real errors.

**Fix:** Log at `debug` level (or skip logging entirely) when caching
disables for small content; keep a real error log only for actual cache
failures.

**Accept:** A short-prompt case produces no "cache too small" lines at
default log level.

---

## Step 14 — Docs reconciliation (ARCHITECTURE §12.7)

**Issue:** `README.md` describes the pre-refactor structure (`ai/`,
`infrastructure/`, `routers/documents.py`, `routers/verification.py`) that no
longer exists.

**Fix:** Rewrite README's structure map to match the current tree (see
ARCHITECTURE Appendix A for the accurate file map).

**Accept:** README paths all exist in the repo.
