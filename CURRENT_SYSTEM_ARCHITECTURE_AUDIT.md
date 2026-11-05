# CURRENT SYSTEM ARCHITECTURE AUDIT — ClearTitle

**Date of audit:** 2026-11-05
**Mode:** Read-only. No source file, prompt, configuration, schema, or migration was modified by this audit. The only artifact produced is this document (repo root, uncommitted).
**Method:** Every claim below was verified by reading the actual source in the repository and/or executing read-only `SELECT` queries against the live MySQL database (port 3307) for case `8A14D132`. All quoted JSON under §12 is verbatim stored data. Illustrative examples are labeled as such.

---

## 1. System overview

### 1.1 What the system is

ClearTitle is a property title due-diligence web application for Karnataka (Belagavi region) land records. A user uploads a set of scanned PDFs (sale deeds, encumbrance certificate, mutation, partition deed, etc.). The system:

1. Runs every PDF through an OCR/extraction Celery pipeline (preprocess → OCR → merge → classify → structure → persist).
2. Runs a **single primary LLM agent** (`backend/services/cleartitle_agent.py`) that (a) reconstructs the property's title chain (Phase A) and (b) verifies each chain transaction sequentially against the uploaded OCR evidence (Phase B), pausing to request missing evidence when needed.
3. Exposes results, evidence upload/skip flows, and an on-demand synthesizer-generated final PDF audit report through a FastAPI backend that also serves the React SPA.

### 1.2 Runtime topology (`docker-compose.yml`, `Dockerfile`, `backend/celery_app.py`, `backend/main.py`)

| Component | Image / runtime | Port | Notes |
|---|---|---|---|
| `api` | one shared image: `python:3.11-slim` + baked `frontend/dist` | 8000 | FastAPI `backend.main:app` (uvicorn); serves SPA, `/health`, API |
| `worker` | same image (override CMD, `celery worker`) | — | runs pipeline + agent tasks; `task_acks_late=True`, prefetch 1, soft limit 3600 s, hard limit 7200 s, visibility_timeout 7500 s |
| `mysql` | `mysql:8.0` | 3307 (host) | DB created on first boot; tables created by `backend/database/migrations.py` |
| `redis` | `redis:7-alpine` | 6379 (internal) | Celery broker + result backend + pipeline state cache + case lock |
| `phpmyadmin` | phpmyadmin | 8080 | admin UI for MySQL |

Bind mounts: only `./uploads` and `./outputs` are bind-mounted; everything else is in images/volumes. The frontend is **built into the API image** (`Dockerfile` stage 1: node 20 `npm run build` → stage 2 `COPY --from=frontend-build /ui/dist ./frontend/dist`), so frontend changes require rebuilding the `api` image.

### 1.3 Source layout (verified)

```
backend/
  main.py, celery_app.py, config.py, logger.py
  domain/            state_machine.py          — 13-state Stage IntEnum
  workers/           tasks.py stages.py stage_adapter.py stage_base.py
                     context.py idempotency.py finalize.py
                     agent_tasks.py title_chain_tasks.py
  services/          cleartitle_agent.py agent_runtime.py agent_tools.py
                     agent_schemas.py final_report.py results.py report.py
                     extract.py document_processor.py orchestrator.py auth.py
                     schemas/  (__init__, static.py, generic.py)
  database/          connection.py migrations.py
                     repositories/ case_repo document_repo agent_repo
                                   verification_repo user_repo
  integrations/      redis/ (state_store.py, lock.py, client.py)
                     storage/ (file_utils.py)
                     ocr/ (sarvam_client.py, ocr_merger.py, preprocessor.py)
                     llm/ (agent_llm.py, rate_limiter.py)
  shared/            constants.py ec_ledger.py
  prompts/           loader.py + 7 .txt files (§3)
  skills/            title_chain/skill.md, transaction_verification/skill.md
  routers/           cases.py results.py auth.py
frontend/src/
  api/backend.ts                                   — single API client
  dashboard/ VerificationDashboard.tsx (2,019 lines), TransactionResultCard.tsx,
            EvidenceRequestDialog.tsx, FinalReportBlockersModal.tsx,
            PhaseAResult.tsx, transactionResults.ts(+test), utils.tsx,
            TransactionResultCard.test.tsx, dashboard.css
  pages/     HomePage LoginPage PricingPage HowItWorksPage OcrViewerPage
  App.tsx    routes: / /login /pricing /how-it-works /app /ocr /ocr/:caseId
```

### 1.4 System flow (Mermaid)

```mermaid
flowchart TD
    U[User browser - React SPA] -->|files (sale_deed / ec / additional slots)| APIU["POST /api/upload -> /api/process/<case>"]
    APIU --> ORC[services/orchestrator.py: chord of 6 stage tasks per doc]
    ORC --> ST1[Preprocess: cv2 CLAHE/deskew/200 DPI]
    ST1 --> ST2[OCR: Sarvam 10-page chunks, kn-IN]
    ST2 --> ST3[Merge: dedup overlap, split tables]
    ST3 --> ST4[Classify: LLM 2-turn -> doc type]
    ST4 --> ST5[Structure: LLM -> typed JSON schema]
    ST5 --> ST6[Persist: MySQL documents row]
    ST6 --> FIN[finalize_case_task - chord callback]
    FIN -->|"~_should_start_agent()"| AGENT["run_case_analysis_task -> cleartitle_agent.run_agent"]
    AGENT --> PA[Phase A: chain build + save_phase_a_result]
    PA --> PB[Phase B: sequential per-transaction verification]
    PB -->|missing evidence| PAUSE["agent_status=paused,\nrequest_missing_documents"]
    PAUSE --> UP[User uploads via /api/case/<case>/upload] --> PROC[per-doc chord again] --> RESUME[resume_paused_transaction / retry]
    RESUME --> PB
    PB --> DONE[all transactions terminal]
    DONE --> REP[on-demand final report: synthesis LLM + ReportLab PDF]
    REP --> PR[Persisted: case_results.final_report]
    U -->|polls /results/<case> every 5 s| RAPI[GET /api/results/<case>]
    RAPI --> UI[Transaction cards, EvidenceRequestDialog,\nFinalReportBlockersModal, PhaseAChainView]
```

**LLM layer one paragraph:** `backend/integrations/llm/agent_llm.py` exposes two entry points (`complete_json`, `complete_with_tools`) and a provider registry `gemini | openai | luna` (`_PROVIDERS`, extensible via `register_provider`). Production config: `CLEARTITLE_AGENT_PROVIDER=openai`, `CLEARTITLE_AGENT_MODEL=GPT-6 Luna` (`backend/config.py` lines 63–72); OpenAI calls are made with `reasoning_effort="none"`, `max_completion_tokens=32000`, `temperature=0`. The Gemini-only Redis sliding-window rate limiter (`integrations/llm/rate_limiter.py`, `GEMINI_RPM/TPM/BURST`) applies only to the `gemini` provider path. Document classification/extraction (Stage 4/5) uses a **separate model** `DOCUMENT_PROCESSOR_MODEL` (defaults to the agent model) through `OpenAI` client constructed in `services/document_processor.py`. Per user decision: OpenAI `gpt-6-luna` is the only sanctioned agent model; Gemini wiring is legacy and must not be switched to.

---

## 2. Document pipeline phases

### 2.1 Upload and case creation

- Router: `backend/routers/cases.py` — `POST /api/upload` accepts N PDFs plus parallel `slots` array (`sale_deed`, `ec`, `additional`); each file becomes a `documents` row (`init_document`, `doc_id = DOC_%03d`, `doc_index`, `expected_type` from slot; original stored as `<case_id>/<doc_id>_<safe_name>.pdf` under `uploads/` by `integrations/storage/file_utils.save_upload`, max size from `MAX_UPLOAD_SIZE_MB` = 100 MB).
- `POST /api/process/<case_id>` → `services/orchestrator.py` decides per document whether to start the chord (`chain`) at the correct stage (`_resume_stage(checkpoint)` inspects persisted `file_paths`/`structured_data`) and fires one `chord` per document with callbacks `finalize_case_task`. Redis case lock (`integrations/redis/lock.RedisLock`, TTL 30 min, Lua refresh every 300 s) guards concurrent processing when `PIPELINE_LOCK_ENABLED` (default true).
- Case state: `cases` row via `case_repo.init_case/update_case_status`; a Redis-visible job payload kept MySQL-first by `integrations/redis/state_store` (every write persists MySQL first, then best-effort Redis; every read Redis-first with MySQL fallback; a Redis outage never blocks the pipeline).

### 2.2 The 13-state machine (`backend/domain/state_machine.py`)

```python
class Stage(IntEnum):
    UPLOADED=0 PREPROCESSING=1 PREPROCESSED=2 OCR_IN_PROGRESS=3 OCR_DONE=4
    MERGING=5 MERGED=6 CLASSIFYING=7 CLASSIFIED=8 STRUCTURING=9
    STRUCTURING_DONE=10 PERSISTING=11 STRUCTURED=12
    # terminal/error
    FAILED=-1 CLASSIFICATION_FAILED=-2 SKIPPED=-3
```
String↔enum conversion (`stage_from_status`) and ordering (`already_past`) live in the same pure module. The frontend mirrors these labels (`VerificationDashboard.docStageInfo` map, incl. `pending_retry`).

### 2.3 Stage tasks and idempotency (`backend/workers/`)

- `tasks.py` declares the six Celery tasks (preprocess, ocr, merge, classify, structure, persist) wrapped by the `idempotent_stage(entry, complete)` decorator from `idempotency.py`: on delivery it reads the MySQL document status and short-circuits if the stage is already complete/passed or failed (retry-safe requeue semantics). Auth retry counting via `increment_retry`, pipeline chatter via `append_pipeline_log` (`verification_repo.py`, last 200 messages into `cases.pipeline_logs`).
- `stage_adapter.py` is the only place a task meets a stage: builds the `StageContext` (`context.py` — ports: `llm`, `cache`, `storage`, `state`), loads input, invokes `stage.invoke(ctx, input)`.
- Retry behavior: Celery autoretry max 5 with backoff; `ClassificationFailed` and `OcrInsufficientCredits` are non-retryable (`services/document_processor.UnsupportedDocumentError` / Sarvam credit error detection in `sarvam_client._is_insufficient_credits`).
- Contract: `stage_base.py` defines `ExtractionStage.invoke(ctx, input) -> StageResult(status, payload)` (dataclass); all six stages conform.

### 2.4 Per-stage behavior (`backend/workers/stages.py`)

1. **Preprocess** `integrations/ocr/preprocessor.preprocess_pdf` — renders each page at 200 DPI (`fitz.Matrix`), CLAHE contrast, denoise, deskew, Otsu binarization; writes `outputs/<case>/preprocessed/…`.
2. **OCR** `integrations/ocr/sarvam_client.run_sarvam_ocr` — page count via PyMuPDF; ≤10 pages → single call; >10 pages → overlapping 10-page chunks (overlap 1), 8 parallel workers, retries after 5 s/15 s, output format `md`, language `kn-IN`; API key from `SARVAM_API_KEY`. Credit exhaustion raises `OcrInsufficientCredits` (non-retryable, surfaced verbatim in UI).
3. **Merge** `integrations/ocr/ocr_merger.merge_chunked_outputs` — dedups the 1-page chunk overlap, merges tables split across chunk boundaries, strips base64 image blobs; emits `{total_pages, full_text ("--- Page N ---"), pages[], tables[]}`.
4. **Classify** `services/document_processor.classify_document` — first of the two LLM turns against the merged text (token budget `DOCUMENT_CLASSIFICATION_TOKEN_BUDGET` = 3000); rule-based overrides for `E_SWATTU`, `FORM_9`, and a completion-certificate subtyping into `COMPLETION_CERTIFICATE_BY_ARCHITECT` vs `..._BY_GRAM_PANCHAYAT`; `UNKNOWN_DOC` on no match → `UnsupportedDocumentError` → `classification_failed` (non-retryable; user replaces or skips).
5. **Structure** `extract_document` — second LLM turn, JSON mode into `SCHEMA_MAP[doc_type]` (`services/schemas/static.py`: SALE_DEED, EC, PROPERTY_REGISTER_CARD, E_PAYMENT_RECEIPT (reused for TAX_RECEIPT), E_SWATTU, GIFT_DEED, RTC_PAHANI, CONVERSION_ORDER, MUTATION, CDP_PLAN, RERA_CERTIFICATE, LITIGATION_AFFIDAVIT, ALLOTMENT_LETTER, BUILDING_LICENSE, PARTITION_DEED, COMPLETION_CERTIFICATE(+two subtypes), KHATA; generic fallback in `schemas/generic.py` for the remaining types). Response guarded by `DocumentProcessingError`; structured JSON written to `outputs/<case>/structured/<doc_id>_<TYPE>.json` (`extract.structured_output_path`).
6. **Persist** `document_repo.persist…` sets `status='structured'`, keeps `structured_data` JSON in MySQL, merges EC-ledger cleanups via `shared/ec_ledger.normalize_ec_structured` (EC tall records spanning page breaks are folded by "row missing both execution date and registration reference ⇒ continuation" rule).

### 2.5 Case finalize and agent start (`workers/finalize.py`)

`finalize_case_task` (the chord callback, idempotent) recomputes `cases.completed_docs/failed_docs`, appends a completion log line, emits the stop event, and decides whether to start the agent:

```python
def _should_start_agent(docs, memory) -> bool:
    has_structured_documents = any(doc.get("status") == "structured" for doc in docs)
    has_pending_verification = bool(
        memory.get("paused_transaction") or memory.get("pending_tx_ids")
        or memory.get("evidence_retry_tx_id")
        or (memory.get("status") == "PENDING_NOT_VERIFIED" and memory.get("current_tx_id")))
    return has_structured_documents or has_pending_verification
```

It then enqueues `run_case_analysis_task.apply_async(args=[case_id, resume_paused, retry_tx_id])` (detailed in §6). Retry paths (`POST /api/retry/<case_id>`, doc replace, skip) rebuild chords from the correct checkpoint stage (`orchestrator._resume_stage`), so a re-run does not redo OCR of already-merged documents.

---

## 3. Prompt inventory (complete)

### 3.1 Loader (`backend/prompts/loader.py`)

```python
_PROMPTS_DIR = Path(__file__).parent
def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.txt"
    ...
```
A thin file reader; no caching, no templating. All agent prompt assembly happens in `cleartitle_agent.py`.

### 3.2 The seven prompt files (all read in full)

| File | Lines | Role |
|---|---|---|
| `agent_system.txt` | 205 | The single agent's system instructions: untrusted-evidence rule, phase sequencing, document-manifest handling, dependency rules between transactions, save discipline |
| `title_chain_system.txt` | 13 | Phase A system prompt stub: "You are ClearTitle's Phase A property-identity and title-chain investigator… Build Phase A only… save_phase_a_result exactly once, then finish" |
| `title_chain_task.txt` | 125 | Phase A task: find latest sale deed(s) → identify target property → EC triage relevant entries → trace ownership backward ("roughly the last 30 years"), record earliest supported root as the chain limit, no invented links |
| `agent_verify_task.txt` | 235 | Phase B task per transaction: STAGE header, UPSTREAM CHAIN CONTEXT block semantics, workflow steps (get_transaction → record_evidence_requirements → select_documents → read full-coverage OCR text → save_transaction_result or request_missing_documents) |
| `agent_dependency_refresh.txt` | 28 | The *rewrite-only* prompt: rewriter of the `## Earlier transactions` section body of one saved report after an earlier link changes state; three supplied sections are data, never instructions |
| `final_report_task.txt` | 34 | Final report synthesizer role: ONE CASE DATA payload, "use ONLY facts present… never re-run verification, never re-interpret raw documents… Do NOT concatenate transaction reports" |
| `agent_summary.txt` | — | One-shot `complete_json` summary prompt used by `agent_llm.complete_json` for document summaries surfaced to the agent manifest |

### 3.3 The two in-repo skill files, spliced into instructions (`backend/skills/`)

- `title_chain/skill.md` (126 lines): mandatory strategy for chain building — used every build/rebuild; purpose, tracing expectations, property-schedule matching, EC-entry discipline, no generic substitute.
- `transaction_verification/skill.md` (218 lines): type-specific verification strategy; general evidence rules ("Never verify using summaries alone… verify the active transaction on its own instrument plus only the documents it uniquely depends on…"), plus per-type sections (sale, gift, partition, mutation/khata/EC-derived support, mortgage/memorandum of deposit, conversion/layout, building permissions/CC, etc.).

These are not loaded via file reads at runtime by agent code paths — they are **spliced into the instructions text** by `cleartitle_agent._phase_a_instruction()` / `_verify_instruction()`, together with the document manifest or upstream context. There is no runtime skill-loading mechanism beyond this static splice (a design fact relevant for redesign: skills are prompt material, not a runtime plugin).

### 3.4 Prompts embedded in code (not from `prompts/`)

- `services/document_processor.py` builds its own **two classification/extraction turns inline** (messages composed in `classify_document`/`extract_document`), independent of `prompts/loader` — the only LLM texts not in the Prompt directory.
- `cleartitle_agent.py` assembles the actual system messages: persona + `title_chain_system.txt`/`agent_system.txt` + skill body + document manifest / upstream chain context block.
- `final_report.py` composes the CASE DATA payload around `final_report_task.txt`.
- `cleartitle_agent._dependency_refresh` (report editor) wraps `agent_dependency_refresh.txt`.

---

## 4. Title-chain reconstruction (Phase A)

**Entry:** `cleartitle_agent.run_agent` → decides phase A needed (no saved `title_chains` row or chain too shallow per case memory) → Phase A loop.

- Loop runtime: `agent_runtime.run_tool_loop` — one tool-calling loop (model → tool calls executed by name via `agent_tools.dispatch` → results appended as tool messages) until `finish` or the step budget. Phase A runs with **max 80 steps** (`CLEARTITLE_AGENT_MAX…` constants/config; hard caps enforced in the loop, not the tool handlers).
- Tools available in phase A (`agent_tools.tools_for("phase_a")`): `list_documents`, `get_document_metadata`, `get_document_text`, `save_phase_a_result`, `finish` (subset enforced by schema-level gating: ECs are phase-A-discoverable documents, `_is_phase_a_only_document`).
- Evidence access paths:
  - `list_documents` — something from `agent_repo.get_agent_documents` (one row per doc: `doc_id`, `filename`, `document_type`, `status`, `summary`) — **no OCR text in the list**; the agent must call `get_document_text` to read.
  - `get_document_text` — merged OCR (`full_text`) from the document row, returned in chunks; caps: `_DEFAULT_TEXT_CHARS = 40_000`, `_TEXT_CAP = 200_000`. The handler tracks which spans were read (`_has_read_full_text` bookkeeping is used by save gates to forbid citations of unread spans — full-OCR-coverage rule).
- Save path `save_phase_a_result` (handler `_h_save_phase_a_result`, lines 364+):
  1. Validates against the canonical Phase A Pydantic contract in `agent_schemas.py` (§11): `property_identity`, `title_chain_graph` (string), `detailed_chain` (list of `{documented_transaction{transaction_number, transaction_type, executed_date|execution_date, registration_number, summary_points[], source_refs[]}, related_events[], chain_position}`).
  2. Persists **3 columns** into `title_chains` (`agent_repo.save_title_chain`): `property_identity` (JSON), `title_chain_graph` (LONGTEXT = the ASCII ownership graph the model wrote), `detailed_chain` (JSON). `updated_at` refreshed.
- Data provenance rule (system prompt): the agent may use only `document summaries` and `merged OCR text`; it must **never** read structured extraction JSON (`structured_data`) — totals, parties and schedules cross-checked from OCR, not from the extraction stage. (This is a real, enforced design separation; the structured data is reshown in the UI only.)
- EC triage: a "phase-A-only document" classification gates which documents the phase-A agent can call `get_document_text` on — ECs are visible to Phase A but excluded later from Phase B evidence (§5).
- Transition to Phase B: after `save_phase_a_result` + `finish`, the agent loop ends; `run_agent` proceeds to Phase B verify loop for each chain entry in sequence. Chain entry order and `tx_id` assignment are **application-side**: stable ids `PA-TC-000N` are derived from `detailed_chain` index (`cleartitle_agent` builds the transaction list), not from the model output.

---

## 5. Transaction verification (Phase B)

### 5.1 Verification sequencing and dependency context

- `cleartitle_agent.run_agent` Phase B: for each chain transaction in order, unless already terminal in `case_results` (`_is_terminal_transaction_result` — terminal = `VERIFIED_WITH_AVAILABLE_EVIDENCE`, `ISSUES_IDENTIFIED`, `SKIPPED`/`SKIPPED_BY_USER`, or `INCONCLUSIVE` not exempt per §5.3) or user-skipped (`case_memory.skipped_tx_ids`), or superseded.
- Per-transaction instruction (`_verify_instruction`) = persona + verification skill body + the transaction object + the **upstream chain context block** (`_upstream_chain_context`, agent_tools.py line 626) built from:
  - the previous link's full saved report,
  - earlier-unverified excerpts with their outstanding requests,
  - the aggregated already-requested register (case-wide `_requests_match` register, below),
  - document manifest restricted to case documents.
  - Format enforced by `DEPENDENCY_SECTION_HEADING = "## Earlier transactions"` (line 659) and `_split_dependency_section` (line 671) — every verify report **must** carry that heading while any upstream link is unverified.
- One tool loop per transaction; each loop decides one of three ends:
  1. `save_transaction_result` — full verification (status, report, findings, cited_documents, required_documents);
  2. `request_missing_documents` — persist required list and pause;
  3. `finish` / `request_additional_verification_calls` for budget.

### 5.2 Verifying model call budget

- Config: `CLEARTITLE_VERIFY_MODEL_CALL_BUDGET` default **16**, `CLEARTITLE_VERIFY_MODEL_CALL_MAX` clamps to **[16,24]** (`backend/config.py` lines 68–71).
- `request_additional_verification_calls` (`_h_request_more_calls`, line 1086): requires a `next_step` string 12–400 chars; one-time extension `+8`; grants `{"granted_additional_calls": 8, "hard_cap": 24}`.
- Additionally, the runtime auto-grants **one** bounded continuation on recoverable evidence-validation errors — `agent_runtime._RECOVERABLE_EVIDENCE_ERRORS` matches "whose complete ocr was not reviewed" / "must be read for every selected supporting document" (`_grant_recovery_budget`).

### 5.3 Tool handlers, save gates, duplicate prevention (`backend/services/agent_tools.py`, 1,142 lines total)

Handlers (dispatch table `_HANDLERS`, line 1098): `list_documents`, `get_document_metadata`, `get_document_text`, `record_evidence_requirements`, `select_documents`, `save_phase_a_result`, `list_transactions`, `get_transaction`, `save_transaction_result`, `request_missing_documents`, `request_additional_verification_calls`, `finish`.

`dispatch` (line 1114) facts:
- Never raises; unknown tool → error dict; finished-context gate ("active transaction is already terminal; no further tools may run").
- Dedup cache keyed by `json.dumps([name, args], sort_keys=True)`: **repeated identical tool calls return the cached result** and increment `repeated_tool_calls` — this is the loop-level "repeated_tool_call" signal surfaced in checkpoints.
- `SchemaValidationError` paths surface `issues` arrays.

Save gates (`save_transaction_result` / `request_missing_documents`, lines ~940–1073):
- Canonicalization: `normalize_transaction_verification` → `validate_transaction_verification` (schema 3.0; forbidden legacy aliases `summary`, `findings`-as-string, `conclusion`, `missing_documents`, `impact`, `supporting_evidence` — the verify task prompt declares these off-limits verbatim).
- Documentary-citation completeness: `cited_documents` entries validated against `_has_read_full_text`/read-span coverage — citing a document whose OCR wasn't fully reviewed (when required for the selected supporting docs) returns the recoverable evidence error (§5.2).
- Evidence-exclusion: EC references are rejected as Phase B evidence (ECs feed Phase A only, per `_is_phase_a_only_document`).
- `required_documents` validation (`_validate_missing_requirements`): every requested item must not be satisfied by an existing case document (identifier checks through `_available_document_request_errors`), and `_requests_match` (`_exact` + fuzzy head-of-line fuzzy matcher at lines ~217–238) rejects duplicates **case-wide**, including requests made by earlier links.
- Persist via `repo.save_transaction_result(case_id, tx_id, verification)`; `chain_context` (the upstream block used for this verdict) is persisted inside the result row (`agent_repo`).
- `request_missing_documents` sets `ctx.missing_requests` and marks context finished; the workflow turns this into the pause state (`agent_status=paused`, `case_memory.paused_transaction = tx_id`) — see §6.
- Report rules: ≤ 20,000 chars (`_result_compactness_errors`), no duplicated 'Reason'/'Report' sections.

`INCONCLUSIVE` termination rule (implemented in `cleartitle_agent`): `INCONCLUSIVE` is treated as terminal, **except** when the verification checkpoint is in `{bounded_stop, repeated_tool_call}` — i.e., the run stopped early for budget reasons or kept consuming an identical tool result — or when the `_document_manifest` snapshot of an INCONCLUSIVE transaction has changed; in those cases the link is re-verified.

### 5.4 Downstream refresh (`cleartitle_agent._refresh_downstream_results`, lines 724–794)

After an upstream link's state changes (resume/verify/skip), downstream saved reports are **textually refreshed, never re-verified**: `_split_dependency_section` locates each downstream report's dependency section, `agent_dependency_refresh.txt` prompts the rewriter, and `save_transaction_result`-equivalent persistence keeps the report's other sections intact. This means a later link's "## Earlier transactions" paragraph can change without re-running its evidence checks. Refresh uses a separate budget, not the verification call budget.

---

## 6. Missing evidence, pause, resume, duplicate prevention — the A→B→C→D→E flow

This section describes the designed flow of a case (transaction chain A→B→C→D→E; example is illustrative, the live trace is §12):

1. **Pause (A).** While verifying D, the agent decides evidence is missing and calls `request_missing_documents` with a validated `required_documents` list. Handler persists D's row as `PENDING_NOT_VERIFIED` carrying its own required list, and `cleartitle_agent` sets `case_memory = {current_tx_id: D, current_stage: "paused", status: "PENDING_NOT_VERIFIED", paused_transaction: D, next_action: "…", skipped_tx_ids: […], updated_at}` and `cases.verification_status = "paused"`. The agent loop exits. The per-document results stay persisted in `case_results.case_result`.
2. **User upload (B).** Frontend sees `agent.paused_transaction` on `/results`, and `requirementsForPausedTransaction(agent.transactions, pausedTxId)` — the paused link's **own** required list (no synthetic slot; no inherited asks) — renders `EvidenceRequestDialog` with one slot per request. `POST /api/case/{case_id}/upload` (with no `transaction_id`) stores the new PDFs and restarts their per-doc chord (`finalize` → `_should_start_agent` → resume).
   For uploading against a **skipped/issues** link, the same dialog is opened manually from the card (gated: `canUpload` = (skipped ‖ ISSUES_IDENTIFIED) && requirements.length > 0), and the upload carries `transaction_id` in FormData (`uploadMore(caseId, files, txId)`), routing through the `evidence_retry_tx_id` param: `run_case_analysis_task.apply_async(args=[case_id, False, txId])` → `retry_skipped_transaction` verifies **only that link**.
3. **Re-verify resume (C).** `resume_paused_transaction` (worker `title_chain_tasks.run_case_analysis_task(resume_paused=True)`) acquires the case Redis lock, loads persisted state (skips, results, chain), and re-runs **only the paused transaction** `current_tx_id` first; terminal downstream links are then textually refreshed per §5.4 rather than re-verified; remaining pending links continue sequentially. Duplicate prevention applies inside the new run (`_requests_match` case-wide register loaded from all saved results, so a re-ask of an outstanding document by another link does not duplicate slots in the UI).
4. **Skip (D).** `POST /api/results/{case_id}/agent/skip/{txRef}` → `skip_cleartitle_transaction_task` → `skip_transaction` marks the saved result `SKIPPED_BY_USER` and appends tx_id to `case_memory.skipped_tx_ids`; the agent continues with the next transaction. Skipped links appear "Skipped · not verified" and later become eligible for the manual evidence upload (`canUpload`).
5. **Terminal (E).** The last pending link resolves; `agent.status ∈ {done, error, paused}`; `overall_status` derives case-level `verification_status`/`verdict`. The final report generator (§9) independently computes readiness from the persisted statuses.

**Duplicate-prevention inventory** (each implemented, grep-verified):
- `_requests_match` fuzzy matcher + `_exact` across all saved transaction results (case-level).
- `_available_document_request_errors` identifier check — a request that an already-uploadcd document satisfies is refused with an error dict.
- `dispatch` result-cache keyed on `[tool_name, args]` fingerprints (§5.3) — identical tool calls inside a loop don't re-execute.
- Frontend `canUpload` gate and slot-only-same-source rule (`requirementsForPausedTransaction`, comment at transactionResults.ts:79–85).
- `dismissedPauseKey`/`pausedTxKey` re-render resets (`VerificationDashboard.tsx` lines 698–704, 1235, 1260).

**Known corner:** when a link pauses with **zero own asks** (its evidence was requested upstream — exactly live tx4 of case 8A14D132), `requirementsForPausedTransaction` returns empty, the UI shows no dialog; `case_memory.next_action` invites the user to upload an upstream-requested document or skip the link (verbatim text in §12). An attribution prompt-tail fix (Option A/B discussed with the user) remains **unimplemented** — deliberately out of the current fix scope until asked.

**Locks:** `RedisLock` (TTL 30 min, refresh 300 s) wraps both run and resume — concurrent runs for one case serialize; lock release deletes only on token match (Lua `_RELEASE_LUA`).

---

## 7. Database schema and real queries

### 7.1 Authoritative DDL (`backend/database/migrations.py`, `CREATE_TABLES_SQL`, lines 26–115)

- `users(id VARCHAR(32) PK, email …, password_hash, full_name, created_at)`
- `cases(id PK, user_id, status, total_docs, completed_docs, failed_docs, verification_status, verdict, pipeline_logs JSON/LONGTEXT, created_at, updated_at)`
- `documents(case_id+doc_id PK, doc_index, filename, status, document_type, summary, error, file_paths JSON, expected_type, structured_data JSON/LONGTEXT, retry_count, *_stage/+ *_at historic columns dropped by migration)`
- `title_chains(case_id PK, property_identity JSON, title_chain_graph LONGTEXT, detailed_chain JSON, updated_at)`
- `case_results(case_id PK, case_result LONGTEXT, final_report LONGTEXT, updated_at)`
- `case_memory(case_id PK, case_memory LONGTEXT, updated_at)` — **column is named `case_memory`, not `memory`** (legacy `memory` column collapsed into it with a copy-and-drop migration, lines 180–229).

**Legacy cleanup implemented in the same migration:** drop tables `cross_doc_verifications`, `human_feedback`, `llm_calls`, view `daily_cost_summary`; drop abandoned columns (`documents.verification_notes`, `documents.stage_started_at/…`, `documents.trace_id`) and unused token/cost/metadata columns on `title_chains` and `verification_results`.

### 7.2 Repository layer and representative queries (real)

- `database/connection.py` — threaded mysql-connector pool, `_get_conn()` context manager; `_ensure_database` CREATE DATABASE IF NOT EXISTS (utf8mb4_unicode_ci).
- `repositories/case_repo.py` — `init_case` (INSERT … ON DUPLICATE KEY UPDATE status='uploaded', total_docs=VALUES(total_docs), completed_docs=0, failed_docs=0), `update_case_status` (computed `completed_docs = (SELECT COUNT(*) FROM documents WHERE case_id=? AND status IN ('structured','skipped'))`), `get_case_status_payload`, `list_cases` (for the sidebar), `delete_case`, ownership helpers `get_case_owner/set_case_owner`.
- `repositories/document_repo.py` — `init_document`, `update_status` transitions, `increment_retry`, `set_document_stage`, `load_document_paths`, `get_case_documents` (used by `services/results.build_case_results`), `persist_structured_data`, replace/skip/delete branches, `get_failed_documents`, `get_classification_failed_documents`, `get_document_resume_state`.
- `repositories/agent_repo.py` — Phase B persistence home: `save_transaction_result` (selected-upsert into one-row `case_results.case_result` JSON array keyed by `tx_id`, with last-write-wins and validation), `save_title_chain` (3-column title_chains write), `get_agent_state`/`build_agent_report_payload` (assembles `agent` object for `/results`: status, stage, property_identity, title_chain_graph, title_chain, paused_transaction, transactions = the case_results array, skipped ids, standard budgets metadata), `get_agent_documents`, `case_memory` save/load (plain LONGTEXT, JSON-parsed in `_load`), and `final_report` column persistence helpers used by `final_report.py`.
- `repositories/user_repo.py` — `create_user/get_user_by_email/get_user_by_id/get_or_create_user_by_email`; `_OAUTH_SENTINEL_HASH = "!google-oauth"` deliberately prevents password login for OAuth-only users.
- `repositories/verification_repo.py` — **only pipeline logs today** (`append_pipeline_log`, `get_pipeline_logs`); the docstring states the truth: per-doc verification layer was removed; the modern verification results live in `agent_repo` (there is also a legacy `verification_results_repo` reference in its docstring, absent from the tree — see §10).

### 7.3 MySQL-first state cache (`integrations/redis/state_store.py`, 411 lines)

Every API-visible job field (status, per-file cards, needs_action, errors, logs, progress) is persisted to MySQL via the repos and mirrored to Redis best-effort; reads prefer Redis with a MySQL fallback; no stale-wins path (`append_log` caps 200 entries via `verification_repo.append_pipeline_log`).

---

## 8. API surface and frontend integration

### 8.1 Backend endpoints (routers read in full)

| Endpoint | Method | Router fn | Purpose (verified) |
|---|---|---|---|
| `/api/upload` | POST | `cases.upload` | create case + slots; stores files |
| `/api/process/{case_id}` | POST | `process_case` | fire orchestrator chords |
| `/api/status/{case_id}` | GET | status | processing payload (progress, per-file cards, logs, needs_action, errors) |
| `/api/retry/{case_id}` | POST | retry | rebuild chords for failed docs |
| `/api/case/{case_id}/upload` | POST | upload_more | extra evidence; optional `transaction_id` form field selects scoped retry |
| `/api/case/{case_id}/doc/{doc_id}/skip|replace` | POST | skip/replace | review actions |
| `/api/case/{case_id}` | DELETE | delete_case | hard delete |
| `/api/case/{case_id}/link` | POST | link | claim guest case after login |
| `/api/case/{ids}/doc/…/pdf` | GET | pdf | original PDF (…owner-checked) |
| `/api/results/{case_id}` | GET | `results.get_results` | full payload `{case, documents, needs_action, agent}` |
| `/api/results/{case_id}/ocr` | GET | | merged OCR text for OcrViewerPage |
| `/api/results/{case_id}/analyze` | POST | analyze | `run_case_analysis_task.apply_async(args=[case_id])` (Resume Analysis button) |
| `/api/results/{case_id}/agent/skip/{txRef}` | POST | agent skip | skip paused tx (worker `agent_tasks`) |
| `/api/results/{case_id}/final-report` | GET | | readiness state + last report meta |
| `/api/results/{case_id}/final-report/generate` | POST | | blocked(generation) or generated |
| `/api/results/{case_id}/final-report/pdf` | GET | | ReportLab PDF |
| `/api/results/{case_id}/required-documents/pdf` | GET | | checklist PDF (pure-code, from required_documents) |
| `/api/auth/{register,login,me}` | POST/GET | `auth.*` | JWT (HS256, 7-day) |
| `/auth/google/callback` | GET | | OAuth code exchange; redirects to frontend `/login` (site-root callback per main.py) |
| `/health` | GET | main | key/provider booleans + max_upload_size_mb |

`services/results.py` + `agent_schemas.normalize_transaction_verification` adapt stored rows (v3.0) into the canonical response shape (§11), so the SPA never sees legacy alias fields.

### 8.2 Frontend contract (`frontend/src/api/backend.ts`, 363 lines)

One `API` object; token in `localStorage("cleartitle_token")`; error extraction honors FastAPI `detail[].msg`. Methods map 1:1 onto the endpoints above (`upload`, `uploadMore`, `process`, `status`, `retry`, `skipDoc`, `replaceDoc`, `deleteCase`, `link`, `skipAgentTransaction`, `listCases`, `getResults`, `getFinalReportState`, `generateFinalReport`, `getOcr`, `analyze`). TypeScript shapes (`CaseResults`, `AgentReport`, `FinalReportState`, `FinalReportBlocker`, `TitleChainEntry`) mirror `/results`, with the known loose typing `documents: any[]`.

### 8.3 Dashboard behavior (verification dashboard, 2,019 lines) — the pause/upload loop from the UI side

- Processing view: 2 s `/status` polling → per-file cards (`docStageInfo`).
- Results polling loop (5 s interval + on focus, lines 752–790) refreshes `/results` only when `agent.updated_at`/`paused_transaction` changed; auto-opens the evidence dialog when a pause is detected with nonempty own requirements.
- Pause dialog: `EvidenceRequestDialog` slots = `requirementsForPausedTransaction` (own list only); submit → `uploadMore(caseId, selected)` (paused path, no txRef → full resume) or with a `txId` when opened manually from a skipped/issues card → scoped retry; both switch to processing view and wait `ANALYSIS_WAIT_MS = 8 min` for the next agent state (`waitForEvidenceResume`, `uploadedForPausedTxRef`).
- Skip: guarded `window.confirm`, then `skipAgentTransaction`; polls for next state.
- Transaction cards: `TransactionResultCard` renders normalized status labels (`transactionStatusLabel`, incl. `PENDING_NOT_VERIFIED` → "Pending verification"), report by `##` sections with `[DOC_xxx p.N]` citations resolved against the documents list into PDF chips, "Evidence needed" block, and the upload button under the `canUpload` gate. Resume Analysis button and required-documents checklist PDF download; Final Report generate/preview/download with a stale badge; FinalReportBlockersModal lists exactly the non-terminal transactions and their required docs.
- Guest mode: `GuestReportPreview` shows only parties/property-details of the structured sale deed & blurred lock; sign-in gated.
- OCR viewer page `/ocr(:caseId)` fetches `/api/results/{id}/ocr`.

---

## 9. Final report subsystem (`backend/services/final_report.py`, 650 lines)

- **Readiness gating (implemented):** a case's final audit report can be generated only when every persisted transaction result is terminal (verified-with-available-evidence / issues-identified / skipped-by-user) or explicitly pausing-blocked; anything underpinned by `PENDING_NOT_VERIFIED` with required documents yields `status:"blocked"` with `blockers[]` (`FinalReportBlocker {tx_id, sequence, transaction_type, status, required_documents[], note}` consumed verbatim by the frontend modal).
- **Generation (implemented):** `POST .../generate` re-checks readiness **under the per-case Redis lock** (race cannot emit a report from incomplete verifications), then calls the synthesis LLM with `final_report_task.txt` over the persisted CASE DATA (property identity, chain, each transaction's report/findings/required docs, totals). Contract: synthesize, never re-investigate; no invented facts.
- **Rendering (implemented):** ReportLab A4 flowables (`SimpleDocTemplate`, tables, `HRFlowable`, justified legal styling; `html.escape` on injected strings), stored in `case_results.final_report` with `generated_at`, source hash, `pdf_filename`; PDF served from `/api/results/{case_id}/final-report/pdf`.
- **Staleness (implemented):** a stored source signature is compared with the current case state; `stale: true` surfaces in `/results` (`final-report` state endpoint) and as UI badge.
- **Errors:** `NoCaseResult`, `MalformedCaseResultError`, `ReportSynthesisError`, `FinalReportMissing` exported to the router.
- Separate artifact: `services/report.py` — an older **pure-code** consolidation PDF (`required-documents` checklist companion still served via `/required-documents/pdf`); it is not the final audit report (naming collision worth noting in redesign).

---

## 10. Problems and inconsistencies found (each with evidence)

1. **Result rows can cite deleted documents.** In live case 8A14D132, `PA-TC-0005.reviewed_document_ids` contains `DOC_006`, but the `documents` table holds no row with that id (audit dump §12; DOC ids jump 005→007). Consequence: UI citation resolution falls back to "the cited document" (`TransactionResultCard.resolveDocumentRefs`) and required-docs checklists cannot anchor those cites. No referential integrity exists between result arrays and `documents`.
2. **`case_memory` column naming drift.** Schema creation defines `case_memory.case_memory`; older deployments had `memory` (migrations copy-and-drop, lines 180–206). A query on the wrong name fails loudly (observed first attempt of the audit's own dump script). Only a hazard for anything reading raw SQL.
3. **Docstring/live-code mismatch in `verification_repo.py`.** Docstring names `title_chain_repo` and `verification_results_repo` as the real homes of results; those modules do not exist (only `agent_repo`). Harmless today (the module only exposes pipeline logs), but misleading.
4. **Two different "report.pdf" generators coexist.** `services/report.py` (pure-code legacy pipeline report) and `services/final_report.py` (LLM-synthesized). Same artifact name, unrelated content. Confusing naming, no functional conflict (different routes).
5. **Zero-own-ask pause UX.** When the paused link has no own required docs (live tx4), no dialog appears; the user must infer from `case_memory.next_action` that upstream downloads unblock the run (§6). The prompt-tail attribution fix (Option A/B) is unimplemented.
6. **Duplicated priors can linger in the manifest.** `documents` ids with gaps (DOC_024/025 missing in §12) are the result of in-session replacements/skip — case-level replace deletes, old ids remain embedded in previously computed chains/results (same mechanism as #1).
7. **`title_chain_task.txt` date says "21-06-2010" while the graph says "21-07-2010".** In §12 the Phase A graph and tx4 metadata assert executed/registered 21-07-2010; tx4's own report explicitly flags the not-reliably-established execution date with a handwritten "21 May 2010" reading. This is data-level ambiguity faithfully stored — a reminder the pipeline preserves document ambiguity rather than overwriting it.
8. **Provider-race hazard (documented-intent only):** rate limiting exists only in the Gemini provider path; OpenAI (production) has none in-process beyond retries (`agent_llm` capped backoff). Fine for a single user; untested at concurrency.
9. **Auth scope asymmetry:** `_enforce_access` in `routers/results.py` denies only when a case has an owner (guest cases are wide-open by design); combined with guest session persistence in `sessionStorage["currentCaseId"]` this means any visitor who knows a guest case id can read guest results. (Owner-only cases are enforced.)
10. **The knowledge in skills/prompts is duplicated taxonomies.** Doc type constants exist in `shared/constants.py`, the SCHEMA_MAP in `schemas/static.py`, and the skill text; levels are not pinned to one source.

No claim beyond items perceived from code/tests could be made about the correctness of LLM judgments themselves (out of scope; see §12 status).

---

## 11. Data contracts (all real, from `agent_schemas.py` v3.0)

`SCHEMA_VERSION = "3.0"`; controlled enum (§8 of the spec):

```python
class VerificationStatus(str, Enum):
    PENDING, IN_PROGRESS, PENDING_NOT_VERIFIED,
    VERIFIED_WITH_AVAILABLE_EVIDENCE, ISSUES_IDENTIFIED, INCONCLUSIVE,
    SKIPPED, SKIPPED_BY_USER
```

Canonical per-transaction shape (validated pre-persist; `/results` returns this verbatim via `normalize_transaction_verification`):

```jsonc
{
  "tx_id": "PA-TC-0004",
  "sequence": 4,
  "status": "PENDING_NOT_VERIFIED",
  "report": "**Verdict: …**\n\n## Conveyance and parcel\n- …",
  "cited_documents": [{"doc_id": "DOC_019", "pages": "1-3, 6-7"}],
  "required_documents": [
    {"document_type": "Official survey/subdivision map or land-record extract — R.S. No. 699-A/14 to 699A/15, Angol; Prashant 17 gunthas",
     "reason": "Establishes whether the Schedule B allotment was officially surveyed …",
     "for_transaction": "PA-TC-0002"}
  ],
  "reviewed_document_ids": ["DOC_017", "DOC_019"],
  "transaction_metadata": {"transaction_type": "Sale", "executed_date": "21-06-2010", "metadata fields …"},
  "verified_at": null,
  "schema_version": "3.0"
}
```

Phase A contract (the `title_chains` columns): `property_identity: {details: [{label, value, source_refs: [{doc_id, passage}]}]}`; `title_chain_graph: string` (free-form ascii diamond diagram); `detailed_chain: [{documented_transaction, related_events, chain_position}]` with `documented_transaction = {transaction_number, transaction_type, executed_date|execution_date, registration_number, summary_points: string[], source_refs: [{doc_id, filename, passage?]}}`.

Adapter notes (verified behavior, not code citation): a legacy report row is normalized so old alias fields map to canonical; `chain_context`, `_verification_checkpoint`, `_document_manifest`, and `_has_read_full_text` are internal only — stripped from `/results` payloads.

---

## 12. Execution trace — live case 8A14D132 (real stored data; verbatim dump 2026-11-05)

**`cases` row (verbatim):**
```json
{"id": "8A14D132", "user_id": "7bb4ea01874143e89ee60d317d9c60ac", "status": "complete",
 "total_docs": 23, "completed_docs": 23, "failed_docs": 0,
 "verification_status": "paused", "verdict": "ATTENTION_REQUIRED",
 "created_at": "2026-10-30 11:28:54", "updated_at": "2026-11-04 13:01:40"}
```

**Documents:** 23 rows, **all `structured`**, ids DOC_001…DOC_026 with gaps (no DOC_006, DOC_024, DOC_025): 4× SALE_DEED (2007/2010/2019/2024), 1× ENCUMBRANCE_CERTIFICATE (EC 2010 to 2026), 3× PROPERTY_REGISTER_CARD, 2× PROPERTY_CARD, plus PROPERTY_REGISTER_EXTRACT, PROPERTY_RECORD, FORM_2_PROPERTY_RECORD (Katha), MEMORANDUM_OF_DEPOSIT_OF_TITLE_DEEDS, MUTATION, CONVERSION_ORDER (NA Order), PARTITION_DEED, BUILDING_PERMIT, 2× COMPLETION_CERTIFICATE_BY_ARCHITECT, CONVERSION, SURVIVING_FAMILY_MEMBERS_CERTIFICATE, TAX_RECEIPT, DEATH_CERTIFICATE, E_PAYMENT… (types abbreviated from the raw `(type,status)` counts; the 23 filenames above are exact).

**`case_memory` (verbatim JSON):**
```json
{"case_id": "8A14D132", "current_tx_id": "PA-TC-0004", "current_stage": "paused",
 "status": "PENDING_NOT_VERIFIED", "paused_transaction": "PA-TC-0004",
 "result_ref": "PA-TC-0004",
 "next_action": "PA-TC-0004 relies on documents already requested by earlier transactions. Upload one of those documents to continue, or skip this transaction.",
 "updated_at": "2026-11-04T13:01:40.591722+00:00",
 "skipped_tx_ids": ["PA-TC-0001","PA-TC-0002","PA-TC-0003","PA-TC-0005","PA-TC-0006","PA-TC-0007"]}
```

**`title_chains`:** `property_identity` = 3 ordered details (target property from DOC_001 schedule; area/boundaries; evolution/match across DOC_001/019/020); graph reproduced from storage (abridged header): Dinanath/Prashant/Santosh Revankar joint purchasers of R.S. 699-A/14 (50 gunthas) → 06-12-2007 sale BEL-1-07200-2007-08 → partition 09-06-2008 BEL-1-01711-2008-09 (Party II 17 gunthas ⇒ R.S. 699A/15) → NA conversion 22-12-2008 + BUDA layout July 2009 recital → 21-07-2010 sale BEL-1-03678-2010-11 → I.A. Gundappa (Plot 9/CTS 1360B/9) → succession after death 02-07-2018 → Bharati G.R., Puneet G. Kousik, Ramalakshmi I.C. → 17-07-2019 sale BEL-1-06795-2019-20 → Arjun Baburao Patil → 25-03-2021 sale BEL-1-21142-2020-21 → Kiran Basavant Yallurkar & Shatavaji Bharama Ghugretkar → **04-10-2024 sale BEL-1-08825-2024-25 registered 07-10-2024** → Narayan Ramu Avachari & Pooja Narayan Avachari = current owners. Closing line: "Earlier land title before the 2007 purchase is not established in the available uploads; a 1985 deed is only mentioned in a recital and was not supplied."
`detailed_chain` = **8 entries** (Sale 2007, Partition 2008, NA conversion & layout, Sale 2010, Succession (inferred), Sale 2019, Sale 2021, Sale 2024) with per-entry `source_refs`.

**Per-transaction state in `case_results` (verbatim statuses + own asks; 10 required-document entries total):**

| tx | seq | status | own required_documents (count) | verified_at |
|---|---|---|---|---|
| PA-TC-0001 Sale 06-12-2007 | 1 | PENDING_NOT_VERIFIED | non-container includes (a) Sale deed 27-03-1985 Doc No. 4966, (b) Will 26-11-1996 Parvatibai→Manohar Kalkundrikar, (c) POA Kalkundrikar→Girish Nemagoudar, (d) Siddharth Education Society agreement/POA — 4 items | — |
| PA-TC-0002 Partition 09-06-2008 | 2 | PENDING_NOT_VERIFIED | ① official survey/subdivision map or land-record extract R.S. 699-A/14→699A/15 (Prashant 17 gunthas) — 1 | — |
| PA-TC-0003 NA conversion + layout | 3 | PENDING_NOT_VERIFIED | ① BUDA layout approval BUDA/PLN/LAY/CR-20/1329/2009-10 (12-07-2009), ② corrected conversion order RB/LNA/SR-1/125/08-09 (survey-number discrepancy) — 2 | — |
| PA-TC-0004 Sale 21-06/07-2010 | 4 | **PENDING_NOT_VERIFIED (paused)** | **0 (relies on tx2/tx3 asks)** | — |
| PA-TC-0005 Succession | 5 | PENDING_NOT_VERIFIED | ① succession instrument/devolution record Gundappa heirs — 1 | — |
| PA-TC-0006 Sale 17-07-2019 | 6 | PENDING_NOT_VERIFIED | ① succession basis readable mutation/property-card record — 1 | — |
| PA-TC-0007 Sale 25-03-2021 | 7 | PENDING_NOT_VERIFIED | 0 | — |
| PA-TC-0008 Sale 04-10-2024 | 8 | **ISSUES_IDENTIFIED (terminal)** | ① Canara Bank release/satisfaction or outstanding statement — 1 | 2026-11-04T12:18:45+00:00 |

tx4 report excerpt (verbatim head, 1,889 chars total): "**Verdict: The registered 2010 deed supports the conveyance of Plot 9 to I.A. Gundappa, but Prashant's right to convey that specific parcel remains unverified because the parent-land and layout identity are unresolved.** … The execution date is not reliably established: the date line is blank (\"____ day of June 2010\"), while a handwritten marking appears to read **21 May 2010**…" — and tx4 `reviewed_document_ids: ["DOC_017","DOC_019"]`.

**Run trace reconstruction (from state, not from a log tail):** Phase A completed 2026-11-04 08:32:44 (`title_chains.updated_at`); Phase B initially walked tx1…tx8, pausing on tx1 (4 asks), tx2 (1), tx3 (2), tx5 (1), tx6 (1), tx8 → the user skipped tx1,2,3,5,6,7 (in `skipped_tx_ids`), tx8 reached terminal ISSUES_IDENTIFIED at 12:18:45, and the run paused at tx4 13:01:40 (`case_memory`/`case_results` updated_at both 13:01:40) with zero own asks because tx2/tx3's identical survey/BUDA/correction requests were already registered case-wide. The three documents required to advance are the tx2/tx3 asks (survey/subdivision map, BUDA approval, corrected conversion order) — exactly the earlier stated upload priority.

**Blocked on:** nothing the system can do alone — the case is waiting on user uploads (`documents` unchanged since; the only next system action is `resume_paused`/scoped retry wiring per §6 after a new doc finishes processing, or plain re-run via `/api/results/{case_id}/analyze`).

---

## 13. Summary — what matters before redesign (file list)

**Implemented end-to-end (verified by code + live data):** 6-stage OCR/extraction pipeline with idempotent resume from checkpoints; single-agent Phase A + Phase B with stable ids, per-link persistence, case-wide duplicate prevention, textual downstream refresh; evidence pause/resume/skip including scoped (`evidence_retry_tx_id`) verification; final-readiness gating + staleness-tracked synthesized PDF; MySQL-first state, Redis thread-safe lock; user-scoped results with guest mode.

**Partial / documented-intent:** rate limiting (Gemini-only), `verification_repo` scope (pipeline logs only), two overlapping report generators, prompt material requiring manual curation (skills spliced in code).

**Deliberately deferred (per user decisions):** zero-own-ask pause attribution prompt tail (Option A/B); Gemini switching is prohibited.

**Redesign touch-list** (files a redesign must account for, not modify now):

- Agent brain: `backend/services/cleartitle_agent.py`, `agent_runtime.py`, `agent_tools.py`, `agent_schemas.py`
- Prompt layer: `backend/prompts/*` (7 files + `loader.py`), `backend/skills/{title_chain,transaction_verification}/skill.md`
- Pipeline: `backend/workers/{tasks,stages,stage_adapter,context,stage_base,idempotency,finalize,agent_tasks,title_chain_tasks}.py`, `backend/services/orchestrator.py`, `backend/domain/state_machine.py`
- LLM/OCR: `backend/integrations/llm/{agent_llm,rate_limiter}.py`, `backend/integrations/ocr/{sarvam_client,ocr_merger,preprocessor}.py`, `backend/services/document_processor.py`, `backend/services/schemas/{static,generic}.py`, `backend/shared/{constants,ec_ledger}.py`
- Data: `backend/database/{connection,migrations}.py` + `backend/database/repositories/{case,document,agent,verification,user}_repo.py`, `backend/integrations/redis/{state_store,lock}.py`
- API/Frontend: `backend/main.py`, `backend/routers/{cases,results,auth}.py`, `backend/services/{results,auth,final_report,report}.py` docs; `frontend/src/api/backend.ts`, `frontend/src/dashboard/*` (VerificationDashboard.tsx 2,019 lines is the load-bearing component), `frontend/src/pages/OcrViewerPage.tsx`
- Config/deploy: `backend/config.py`, `docker-compose.yml`, `Dockerfile` (frontend baked into api image — frontend iteration requires image rebuild; only `./uploads` and `./outputs` are live).

*End of audit. Document intentionally produced as a single read-only artifact; no code/config/docs were changed.*
