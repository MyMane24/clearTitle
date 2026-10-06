# Pipeline Issues — Analysis (Discussion Only, No Implementation Yet)

Case under review: **998A8755** (DOC_001 EC, DOC_002 Sale Deed, DOC_003 Mutation)

Status: this document is a root-cause analysis backed by actual runtime evidence
(docker worker logs, Redis `llm_call_log`, MySQL `documents` table, merged-OCR files
on disk). Nothing has been changed in the code.

---

## 0. TL;DR

| # | Issue | Root cause |
|---|-------|------------|
| 1 | No progress shown after "Structured JSON saved to DB" | (a) Title-chain + verification services never append intermediate logs; (b) for this case the follow-on analysis was never queued because the Sale Deed failed (status = `partial`); (c) the UI only shows doc-count progress, not the current stage. |
| 2 | "Structuring with gemini" but error says "All Groq models failed"; Sale Deed JSON never produced | Gemini was tried first and returned **empty responses (3× HTTP 200, no content)** → JSON decode error, silently fell back to Groq → Groq **free-tier TPM limit** rejected the request (413 `rate_limit_exceeded`). The log line is only the routing pre-announcement; the error shown is the last fallback's error. |

---

## 1. TPM / Rate-limit logic — still present

The logic you remember is **not missing**. It survived the refactor **byte-for-byte**:

| Current file | Backup (clr_backup) file | Verdict |
|--------------|--------------------------|---------|
| `backend/integrations/llm/rate_limiter.py` | `backend/services/rate_limiter.py` | Identical |
| `backend/integrations/llm/model_router.py` | `backend/services/model_router.py` | Identical |
| `backend/services/extract.py` (`structure_document`, `is_transient_error`, `is_rate_limit_error`) | `backend/pipeline/helpers.py` | Identical |

So the failure is **not** caused by the refactor dropping the rate limiter.

However, the rate limiter is configured with **paid-tier values** (see §3.4), so it
never protects against the **free-tier** limits that the actual Groq account has.

---

## 2. Issue 2 — Sale Deed missing + "gemini vs groq" confusion

### 2.1 Evidence from the worker logs (cleartitle-worker-1)

```
[13:41:06] Routing SALE_DEED → gemini/gemini-2.5-flash
[13:41:06] WARNING backend.integrations.llm.gemini_client:
           Failed to create/refresh context cache for SALE_DEED:
           400 INVALID_ARGUMENT ... 'Cached content is too small.
           total_token_count=823, min_total_token_count=1024'
[13:41:08] HTTP POST .../gemini-2.5-flash:generateContent "HTTP/1.1 200 OK"
[13:41:08] WARNING backend.services.extract:
           gemini/gemini-2.5-flash attempt 1 failed for SALE_DEED:
           Expecting value: line 1 column 1 (char 0)     <-- json.JSONDecodeError
[13:41:15] ... attempt 2 failed ... Expecting value: line 1 column 1 (char 0)
[13:41:28] ... attempt 3 failed ... Expecting value: line 1 column 1 (char 0)
[13:41:28] HTTP POST https://api.groq.com/openai/v1/chat/completions "HTTP/1.1 413 Payload Too Large"
           'Request too large for model `llama-3.3-70b-versatile` ...
           on tokens per minute (TPM): Limit 12000, Requested 50531 ...
           type: 'tokens', code: 'rate_limit_exceeded'
           ... llama-3.1-8b-instant ... Limit 6000, Requested 50531 ...
[13:41:29] ERROR LLM structuring failed for case 998A8755, doc DOC_002:
           All Groq models failed. llama-3.3-70b-versatile: 413 ... | llama-3.1-8b-instant: 413 ...
```

### 2.2 The actual Gemini error — it was NOT a quota / 429

- Gemini `generateContent` returned **HTTP 200 OK on all 3 attempts**.
- The real failure: `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
  — `response.text` was **empty** (nothing to parse).
- Source: `backend/integrations/llm/gemini_executor.py:79-86` (`json.loads(raw_response)`).
- Most likely cause: **Gemini returned no content** (safety-block / refusal → empty
  candidates). Supporting signal: the Sale Deed OCR contains an injected-looking line —
  `"This image is a high-resolution scan of a 20,000 Indian Rupee banknote ..."`
  (Sarvam's vision model described a stamp/seal image as text). The two other docs
  (EC, Mutation) succeeded on Gemini in the same run; only the Sale Deed came back empty.
- We cannot confirm the exact block reason — the code never logs `finishReason` /
  `blockReason`. Adding that logging is part of the fix.
- Secondary non-fatal issue: Gemini **context-cache creation always fails** for this doc
  (`Cached content is too small, 823 < 1024 min`) — so `cached_content` is never actually
  used, and a failing cache call runs on every attempt.

### 2.3 Why the log says "gemini" but the error says "All Groq models failed"

1. `[DOC_002] Step 5: Structuring with gemini/gemini-2.5-flash` is a **pre-announcement**
   printed before the call from `resolve_model("SALE_DEED")` (`workers/stages.py:270-271`).
2. `structure_document()` tries the chain **gemini → groq-70b → groq-8b**
   (`services/extract.py:58`).
3. Gemini failed silently from the user's view (only `logger.warning` to the server log;
   nothing appended to the case log).
4. Both Groq models 413'd. `groq_executor` raised
   `RuntimeError("All Groq models failed. ...")` (`groq_executor.py:160`).
5. That final Groq error is what reached the user. **Not contradictory** — the log line
   = routing target, the error = last fallback's failure, Gemini's failure was invisible.

### 2.4 Why Groq reported "Requested 50531 tokens" for an 18k-char document

The 413 is **NOT a context-length limit**. Groq's error says it clearly:

```
type: 'tokens', code: 'rate_limit_exceeded'
on tokens per minute (TPM): Limit 12000, Requested 50531
```

Meaning:

- Your Groq account is on the **free "on_demand" tier**, whose TPM limits are:
  - `llama-3.3-70b-versatile` → **12,000 TPM**
  - `llama-3.1-8b-instant` → **6,000 TPM**
- The merged Sale Deed OCR is **18,094 chars**, **~59% Kannada/non-ASCII**.
  Indic script tokenizes at ~1 token per char, so the prompt alone is **~18.5k tokens**.
- The code sends **`max_tokens=32000`** (`groq_executor.py:102`). Groq's TPM
  reservation = **prompt tokens + max_tokens**:
  `18,531 + 32,000 = 50,531`. That is the "Requested 50531" figure.
- 50,531 > 12,000 (70b) and > 6,000 (8b) → rejected as "Request too large ... on TPM".

Confirmed by DOC_003 (Mutation, only 7,372 chars): same error, **Requested 39726**
(= ~7,726 prompt + 32,000 max_tokens), still > the free-tier limits. **The Mutation doc
only survived because it fell back to Gemini**, which has no such TPM wall here.

So in this run:
- **MUTATION** → Groq (primary) 413 → **fell back to Gemini → succeeded**.
- **SALE_DEED** → Gemini (primary) returned empty → fell to Groq (always 413) → **failed**.
- The fallback chain only rescued MUTATION because Gemini happened to be next.

### 2.5 The three real bugs behind Issue 2

1. **413 is misclassified as a transient / rate-limit error** in the retry/fallback logic
   (`services/extract.py:29-40`). Here it IS a rate-limit (TPM), but the code treats it
   as retryable and cascades across models instead of recognizing the real constraint.
2. **Per-attempt provider failures never reach the case log** — users can't see what
   actually failed. Only `logger.warning` (server log) is used.
3. **The rate-limiter config doesn't match the account.**
   `config.py` defaults to `GROQ_TPM = 15,000,000` (paid tier); `.env` does not override
   it, and the limiter reserves only `1` token per call (`extract.py:77`).
   So the app never self-throttles and Groq enforces the real 6k/12k TPM server-side.

### 2.6 Dead config worth noting

- `.env` sets `PRIMARY_STRUCTURER=groq`, but **nothing in `backend/` reads it**
  (`grep` → no matches). Routing is driven entirely by `MODEL_ROUTING_MAP`/the default map
  in `model_router.py`. `PRIMARY_STRUCTURER` is a leftover from the pre-refactor design.

---

## 3. Issue 1 — No progress after "Structured JSON saved to DB"

### 3.1 Root cause (a): case-level services log nothing

- `grep append_log` across the backend shows it is called from the per-doc stage workers
  (`workers/stages.py`), routers, idempotency, finalize, and the two case-level task wrappers.
- **`backend/services/title_chain.py` and `backend/services/verify.py` never call `append_log`.**
- The wrappers (`workers/title_chain_tasks.py`) append **one line only after the whole
  title-chain build / verification finishes** (or on failure).
- During the long Gemini calls for title chain + verification, the case log is frozen.

### 3.2 Root cause (b): follow-on analysis is skipped entirely on partial failure

- `finalize_case_task` only queues title-chain + verification when `new_status == "complete"`
  (`workers/finalize.py:61-68`).
- For 998A8755, DOC_002 failed → `new_status = "partial"` → **nothing ran after the docs**.
- Worker log confirms the later manual run: `Title chain skipped: no SALE_DEED in bundle`
  and `Verification skipped: need both SALE_DEED and ENCUMBRANCE_CERTIFICATE`.
- So the pipeline did not stall — it legitimately stopped, but the UI gave no reason.

### 3.3 Root cause (c): the UI only shows doc-count progress

- Frontend `pollStatus` sets the label to `"{status} – {completed_docs}/{total_docs} docs"`
  and caps the bar at 90% while processing (`VerificationDashboard.tsx:567-582`).
- There is no `stage` / `phase` field in the status payload, so the UI can't say what is
  currently running.

### 3.4 Side note: the rate limiter is not protecting the real account

- `structure_document` acquires `tokens=1` per call; the executors acquire
  `max(1, len(ocr_text)//100000)` (≈1 for these docs).
- `GROQ_TPM` defaults to `15,000,000` and `GEMINI_TPM` to `4,000,000` in `config.py`;
  neither is overridden in `.env`.
- The real Groq free-tier TPM is 6k/12k — **~2,000× smaller than what the code assumes**.
- So the Redis rate limiter never paces Groq, and the provider enforces the limit via 413.

---

## 4. Proposed solution directions (for discussion — nothing implemented)

### For Issue 1 (progress visibility)

1. Add intermediate progress logs inside `build_title_chain` and `verify_case`
   (e.g. `─ Establishing title chain ─`, `─ Running cross-document verification ─`,
   `─ Generating verification report ─`).
2. Add a `stage` / `phase` field to the status payload
   (`get_case_status_payload` / `get_case_job`) and render it in the UI.
3. Decide behaviour for `partial` cases:
   - Option A: keep the gate, but clearly report
     "Blocked — Sale Deed failed, title chain and verification cannot run."
   - Option B: attempt title-chain + verification for the docs that *did* structure.
4. Move the progress bar to reflect phases (docs → title chain → verification),
   not just doc count.

### For Issue 2 (fallback + transparency)

1. Append every provider attempt + error to the case log so failures are visible:
   `[DOC_002] ⚠ gemini-2.5-flash returned empty response, falling back to groq/...`.
2. Log Gemini response metadata on empty results (`finishReason`, `blockReason`,
   `safetyRatings`) to confirm the block reason.
3. Fix 413 handling:
   - Recognize Groq 413 `type: 'tokens'` / `code: 'rate_limit_exceeded'` as a
     **hard TPM limit** — stop cascading across models and surface a clear message.
4. Align the rate limiter with the real account:
   - Set `GROQ_TPM`/`GROQ_RPM` in `.env` to the actual tier values (6k/12k).
   - Reserve the estimated real token cost (`max(1, est_prompt_tokens + max_tokens)`)
     instead of `1`.
5. Reduce request size:
   - Cap `max_tokens` at a realistic value (e.g. 8k–16k) instead of 32k/65536.
   - Truncate/clean OCR (the "scan of a 20,000 Rupee banknote..." image-description junk
     adds tokens and may be what triggers Gemini's safety filter).
   - Consider routing large Kannada-heavy documents to Gemini by default
     (Gemini handled all 3 docs here; Groq free tier handled none).
6. Clean up dead config: remove/ignore `PRIMARY_STRUCTURER`.

---

## 5. Confirmed evidence vs open items

| Item | Status |
|------|--------|
| Actual Gemini error for DOC_002 | **Confirmed** — HTTP 200 OK ×3, empty `response.text` → `json.JSONDecodeError`. Block reason not logged. |
| Why 50,531 tokens | **Confirmed** — ~18.5k prompt tokens (18,094-char Kannada-heavy OCR) + `max_tokens=32000` = 50,531; Groq free-tier TPM is 12k/6k. |
| Whether DOC_003 hit Groq too | **Confirmed** — yes (Requested 39,726), rescued by Gemini fallback. |
| Why no title chain / verification | **Confirmed** — partial case (Sale Deed failed) gated the follow-on. |
| Exact Gemini block reason (safety?) | **Open** — requires adding `finishReason`/`blockReason` logging and re-running. |

---

## 6. The two highest-impact questions to decide together

1. **Groq tier:** are we upgrading the Groq account (Dev tier), or treating Groq as
   unsuitable for these documents and routing more to Gemini? This decides whether the
   fix is "raise limits in `.env` + throttle correctly" or "change routing + reduce
   request size".
2. **Partial cases:** when one document fails, should the app still run title chain /
   verification on what succeeded (Option B), or stop and clearly explain (Option A)?
