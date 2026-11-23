# Verification Agent: Tasks and Implementation Log

Design reference: [PLAN.md](PLAN.md). Read it before starting a task.

## How to work on this
1. Take the first task that is `[ ]` and whose dependencies are `[x]`. Mark it `[~]` while working.
2. Keep to the layering in [AGENTS.md](../../AGENTS.md) and the extension points in PLAN.md ("Design for change").
3. Run the checks listed in the task and in AGENTS.md. A task is done only when its "Done when" items pass.
4. Mark the task `[x]` and add an entry to the log at the bottom.
5. If you had to deviate from PLAN.md, update PLAN.md in the same change and say why in the log.
6. Never trigger real OCR, LLM or government-portal calls in tests. Use Pydantic AI `TestModel` / `FunctionModel`.

Status: `[ ]` open · `[~]` in progress · `[x]` done

---

## 0. Spec
- [x] **0.1 Save the plan and task list.** `specs/verification-agent/PLAN.md`, this file, and the "Active work" pointer in `AGENTS.md`.

## 1. Foundation: Case File and storage
- [x] **1.1 Shared continuity logic.** Move the name-matching and continuity helpers out of `services/chain_builder.py` into `backend/domain/chain_continuity.py`, then make `chain_builder.py` import them. No behaviour change.
  - Done when: `test_chain_builder.py` and the rest of the suite pass unchanged.
- [x] **1.2 Case File model.** `backend/services/verification/case_file.py`: Pydantic models for the working chain, link verdicts, facts and citations, leads, issues, requisitions, tasks, examiner reports and documents examined, plus `schema_version` and `migrate()`. Initialise from the saved Phase A chain and the case's document list.
  - Done when: unit tests cover init from a Phase A chain, a JSON round trip, and migration of an older `schema_version`.
- [x] **1.3 Tables and repository.** Additive, idempotent DDL in `database/migrations.py` for `verification_case_files`, `verification_runs`, `verification_events` and `due_diligence_reports`, with all SQL in `database/repositories/verification_repo.py`.
  - Done when: repository tests pass, and the migration runs twice without error.
- [x] **1.4 Config.** Add `VERIFY_LEAD_MODEL`, `VERIFY_EXAMINER_MODEL`, `VERIFY_REPORT_MODEL`, the budgets and `VERIFY_KEEP_TOOL_RESULTS` to `backend/config.py` and `.env.example`. Let `build_agent_model()` take an optional model name per role.
  - Done when: the defaults load, and the existing Phase A behaviour is unchanged.

## 2. Gates and tools (no LLM)
- [x] **2.1 Gates.** `backend/services/verification/gates.py` is a list of small pure functions, each with a test:
  - full read;
  - quote on cited page (whitespace-normalised, UTF-8 / Kannada safe);
  - EC never counts as link evidence;
  - chain integrity on amend: continuity, date order, no non-transfer links, `evidence_status` rules;
  - closure: every link has a verdict, no unrecorded breaks, no open leads, every document examined, every requisition names what it affects;
  - report: every statement references Case File items, the opinion is consistent, a requisition is never shown as resolved.
  - Done when: every gate has a passing and a failing test.
- [x] **2.2 Case-file tools.** In `tools.py`, as `FunctionToolset`s:
  - `record_link_verdict`
  - `amend_chain`
  - `open_lead` / `resolve_lead`
  - `record_issue`
  - `add_requisition`
  - `update_tasks`

  Each one validates its input, applies the relevant gates, writes to the Case File and emits an event.
  - Done when: tool tests run against an in-memory Case File.
- [x] **2.3 Evidence tools.** `read_pages` (split by the `--- Page N ---` markers in `merged_ocr_text`) and `load_skill` (from `backend/skills/<name>/skill.md` plus a generated skill index).
  - Done when: tests cover page splitting, an out-of-range page, and an unknown skill.
- [x] **2.4 Events.** `events.py` writes `verification_events` and turns `agent.iter()` nodes and tool calls into short, readable lines.
  - Done when: unit test.

## 3. Document Examiner
- [x] **3.1 Examiner agent.** `examiner_agent` with output `ExaminerReport` (instrument, parties with capacity, schedule, consideration, recitals, encumbrances and restrictions, `unexpected[]`; every item has a page and quote). Its prompt is `prompts/verify_examiner.txt`. It must read every page; a full-read gate and a quote gate run as output validators.
  - Done when: `FunctionModel` tests cover a successful report, a retry on a fabricated quote, and a retry when pages were left unread.
- [x] **3.2 `examine_document` tool.** Delegates with `await examiner_agent.run(...)` under its own budget (usage added to run totals; PLAN.md decision 3) and caches the report in the Case File by `doc_id` and content hash, so later runs reuse it.
  - Done when: test shows a cache hit on a second call and a cache miss when the text changes.

## 4. Lead Examiner and runner
- [x] **4.1 Lead agent.** `lead_agent` with the toolsets registered from one list, output `LeadClosure` with the closure gate as its output validator, and prompt `prompts/verify_lead_system.txt`.
- [x] **4.2 Context builder.** `context.py` renders a compact Case File snapshot (first prompt and `view_case_file`; PLAN.md decision 1) and, via `ProcessHistory`, replaces old tool results beyond the most recent `VERIFY_KEEP_TOOL_RESULTS` with one-line references.
  - Done when: a test shows the context size stays bounded over many tool calls.
- [x] **4.3 Runner.** `runner.py` implements `start_full`, `resume` and `get_state`:
  - async, driven by `agent.iter()`;
  - a Redis case lock;
  - checkpoints the Case File after every node;
  - status `running` / `done` / `incomplete` / `error`;
  - budget exhaustion gives `incomplete` with the unexamined items listed.
  - Celery task in `workers/verification_tasks.py`, which calls `asyncio.run(...)`.
  - Done when: `FunctionModel` tests cover a full run, a discovery that blocks closure until its lead is resolved, a missing document that becomes a requisition while the run continues, resume after a simulated crash, and budget exhaustion giving `incomplete`.

## 5. Report
- [x] **5.1 Report schema.** `backend/schemas/due_diligence.py`: generic sections `{id, title, blocks[]}` with block types `paragraph`, `table`, `findings` and `list`, plus the opinion and its reasons. Define the default section list from PLAN.md section 6.
- [x] **5.2 Report agent.** Writes the report from the Case File only, with prompt `prompts/verify_report.txt` and the report gate as its output validator. Saves a new version with a "changes since previous version" section.
  - Done when: tests cover an opinion forced to `NOT_CLEAR` by a high-severity issue, and version 2 listing its changes.

## 6. Requisitions and incremental runs
- [x] **6.1 Document sources.** `backend/integrations/document_sources/base.py` defines the `DocumentSource` interface, with `manual_upload.py` as the first implementation. Requisitions record only *what* is needed.
- [x] **6.2 Upload against a requisition.** The upload stores the file through `ManualUploadSource`, sends it through the existing pipeline and links the new `doc_id` to the requisition. `workers/finalize.py` queues `start_incremental` once the document is structured.
- [x] **6.3 Incremental run.** The Lead starts from the Case File with a "new documents for R…" message and examines only those documents. A new report version follows.
- [ ] **6.4 Flag links that rest on contradicted facts.** Not built: when a new document contradicts a cached examiner fact, code should list the links citing that document for re-check. Today the playbook only tells the Lead to update every link a new document affects.
  - Done when: a test shows only the new documents are examined and the other verdicts are kept.

## 7. API and dashboard
- [x] **7.1 Router.** `backend/routers/verification.py` calls only the service interface:

  | Method | Route |
  |---|---|
  | POST | `/api/verify/{case_id}` |
  | GET | `/api/verify/{case_id}/events?after=` |
  | GET | `/api/verify/{case_id}` |
  | POST | `/api/verify/{case_id}/requisitions/{id}/upload` |

  - Done when: router tests pass.
- [x] **7.2 Frontend.** In `frontend/src/dashboard/verification/`:
  - `AgentPlan.tsx`
  - `LiveFeed.tsx` (polls by cursor)
  - `DueDiligenceReport.tsx` (a generic section and block renderer)
  - `Requisitions.tsx` (upload per item)

  Wire them into `api/backend.ts` and `VerificationDashboard.tsx`, with a "Verify title" button. Follow the README's UI design system and use `lucide-react` icons.
  - Done when: `npm run lint` and `npm run test` pass.
- [x] **7.3 No internal ids where a buyer can see them.** Prompts and tools require plain names in buyer-facing text (ids stay in `refs` and id fields); report wording, "what changed", issues and the step feed name transfers and documents in words; the page replaces any id left in a saved report, Case File or event. Done when backend and frontend tests show no internal id in displayed text.

## 8. Skills and prompts
- [x] **8.1 Skill structure.** Create `backend/skills/verification/skill.md` (the lead playbook and skill index) and stubs for `title_link`, `succession`, `partition`, `gpa_and_capacity`, `minor_property`, `encumbrances`, `revenue_records` and `land_use_approvals`. Each stub has these sections: purpose, when to load, checks, evidence required, red flags, requisitions.
- [ ] **8.2 Lawyer instructions.** The product owner supplies the legal content for each skill. Tune on 3–5 real cases, only with approval, because the calls cost money.

## 9. Evaluation
- [ ] **9.1 Evaluation set.** About 10 real cases with a lawyer's expected findings, plus a small judge rubric covering citation accuracy, missed discoveries and opinion correctness. Re-run it after any prompt or skill change.

## 10. Transaction-by-transaction verification (PLAN.md decision 20)
- [x] **10.1 Log rejected tool calls.** Every `ModelRetry` from a Lead tool becomes a feed event and a log line naming the tool and the reason.
  - Done when: a test shows a rejected `record_link_verdict` emits one "rejected" event.
- [x] **10.2 One document per requisition.** `add_requisition` takes one document, the transfer it is for and a one-sentence reason; a requisition that repeats an open one is refused (same approach as the duplicate-issue guard).
  - Done when: tests cover a duplicate refused and two documents giving two requisitions.
- [x] **10.3 Verdict carries property type and needed documents; oldest first.** `record_link_verdict` requires the property type, extent and the documents the transfer needs (found with a citation, or missing with a requisition). A verdict is refused until every earlier in-window link has one. The 30-year window is computed from link dates.
  - Done when: tests cover an out-of-order verdict refused, a missing document without a requisition refused, and a link older than the window skipped.
- [x] **10.4 Examine every document.** The closing gate again requires every uploaded document to be examined (reverses decision 17); the page shows "Not examined" instead of "Not needed".
  - Done when: gate test and frontend test.
- [~] **10.5 Prompt and playbooks.** Rewrite `verify_lead_system.txt` and `skills/verification/skill.md` as the per-transaction loop (continuity, property type, type-change reasoning). Extend `succession` (inheritance needs no registered deed: death certificate, family or legal-heir certificate, mutation in the heirs' names) and `land_use_approvals` (conversion, layout, building plan, CC/OC, apartment documents, RERA applicability). The legal text is drafted from sources and confirmed by the product owner's lawyer (8.2).
  - Done when: the product owner has reviewed the playbook text; the backend tests pass.
- [x] **10.6 Short report.** Opinion with at most 2 reasons; findings with title ≤ 70 and text ≤ 220 characters; clear findings must cite evidence, plus the code-built "chain unbroken" card; limitations in one line.
  - Done when: schema tests for the limits and the clear-finding gate.
- [x] **10.7 One-page dashboard.** Opinion, count chips, finding cards (critical / to resolve / clear), documents needed with Upload per row; property-type chips and per-transfer checklists on the chain page.
  - Done when: `npm run lint` and `npm run test` pass; checked visually with the 8A14D132 data.
- [~] **10.8 Real run.** One run on 8A14D132, **only with the product owner's approval**. Compare calls, cost and findings with run f0223f1e.

---

## Implementation log
Newest first. Format: date · task · files · notes (deviations from PLAN.md and why) · next step.

- 2026-11-23 · Remove verdict checks (product owner's request; PLAN decision 21) · `case_file.py` schema 3: `CheckResult` and `LinkVerdict.checks` are removed, and `migrate` strips them. `tools.record_link_verdict` has no `checks` argument. The citation and encumbrance-certificate gates now run on the found documents' citations, and a non-missing verdict needs at least one found document. `verify_lead_system.txt`, `skills/verification/skill.md` and `title_link/skill.md` are reworded (the checklist stays as guidance). Chain page: the check dots are removed. 258 backend and 20 frontend tests pass; `tsc` is clean; the real 8A14D132 Case File loads as schema 3.

- 2026-11-21 · Remove the duplicate property type (product owner's request) · `schemas/chain.py`: `DocumentedTransaction.property_type` is removed and dropped when older data is read. `prompts/title_chain_task.txt` no longer asks for it. Test added; 257 backend tests pass. Loaded every saved chain in Docker MySQL: 8A14D132 and one other load. Three older chains (1E2DD405, 390E1B54, DEMO-CLEAN-001) fail on fields this change did not touch (missing `transferees`, an old `evidence_status` value); they predate the current chain schema and need a chain rebuild before verification.

- 2026-11-21 · Lean Case File and writer input (product owner's request; PLAN decision 21) · `case_file.py` is now schema 2: `tasks`, `property_identity`, `amendments` and `related_events` are removed, and `migrate` strips them from stored files. `tools.py` no longer writes amendments. `report.report_input` is a short text in words without ids (8A14D132: 85K → 6K characters). `verify_report.txt` was reworded. Frontend: `VerificationTask` and `tasks` removed. 256 backend and 20 frontend tests pass; `tsc` is clean. The real 8A14D132 Case File loads through the migration. · Next: a fresh run on 8A14D132 (paid, needs approval).

- 2026-11-21 · Slim report (product owner's request; PLAN decision 21) · `schemas/due_diligence.py`: the report is now `{version, opinion, reasons, findings, changes}` and the writer returns `{opinion, reasons}`. Older reports are converted when read. `report.py` drops the sections, refs and limitations, and builds findings and changes. `basis` moved to `CaseFile.report_basis`, carried over on a reset and hidden from the dashboard. `prompts/verify_report.txt` was rewritten. Frontend: types, `ReportView`, `issues.ts`, and `CaseResults` (no property summary line; the header uses the Phase A identity). 254 backend and 20 frontend tests pass; `tsc` is clean. · The first report after this change lists no changes, because the old basis lived in the report. · Next: a fresh run on 8A14D132 (paid, needs approval).

- 2026-11-21 · Cleanup (product owner's request) · Dropped the dormant tables `case_results` and `case_memory` and the unused columns `cases.phases`, `cases.analysis_run_id` and `title_chains.source`. `migrations.py` is reduced to drop/create/add/drop lists, and the one-off legacy copy code is gone. `title_chains.chain` is kept because 27 older chains still read from it. `case_repo.delete_case` now also removes the case's verification rows (`CASE_TABLES`). Removed `title_chain_repo.py`, 6 obsolete scripts, 9 dead functions and constants, 3 unused frontend exports and 296 unused CSS selectors. Deleted 10 document rows whose case no longer existed. A mysqldump backup was taken first, in `backups/pre-cleanup-20261121-162201.sql`. 253 backend and 19 frontend tests pass; `tsc` is clean.

- 2026-11-21 · Modern results UI (product owner's request) · `frontend/src/dashboard/dashboard.css` (results block rewritten: cards, segmented tabs, verdict pills, vertical timeline with a dot per verdict, upload buttons, live steps that slide in one by one), `results/ChainTimeline.tsx` (Phase A chain with verdicts overlaid by id), `results/CaseResults.tsx` (no agent steps after a run; "Verifying the title" live card), `verification/LiveFeed.tsx`, tests. 19 frontend tests pass; `tsc` clean; checked visually with the 8A14D132 data (report, chain and live views). PLAN.md decision 16 updated.

- 2026-11-21 · 10.8 fourth run (910c41ee, continued, approved; call cap raised to 100 by the product owner, cost cap $0.50 kept) · **done** in 9 Lead calls + 1 examiner call, 227K input / 7K output tokens, 1.5 min; report v4 NOT CLEAR. All 8 transfers judged ("document missing"; property types agricultural land → layout site → house). Quality gaps, mostly leftover state from the first buggy run: a single catch-all issue ("Title chain remains unverified") instead of separate cards; bundled and pre-root requests created before the checks existed; the 2019 break recorded in run 1 is still there despite the death and family certificates; Limitations called the never-uploaded 2021 deed unreadable. Measured fixed context per call: snapshot in the first prompt 38K characters (31K of it document recitals; never compacted), instructions 21K, tool definitions 18K. Fixes: the first prompt uses a lean snapshot (one line per document); closing refuses an open request that bundles several documents; the prompt asks for one issue per problem; the report prompt distinguishes missing from unreadable; `usage_json` records cached input tokens. 251 backend tests pass; image rebuilt. · Next: one fresh run (clean state) to measure quality and tokens end to end, only with the product owner's approval.

- 2026-11-21 · 10.8 third run (43e2a544, continued, approved) · `incomplete` at 50 Lead calls (1.33M input / 16K output tokens). Progress: it withdrew 4 duplicate requests by itself and judged 3 more transfers (2007 sale, 2008 partition, 2010 sale: all "document missing"); 5 of 8 now have verdicts. The new per-turn call log showed the waste: about 25 turns were a lone `view_case_file`, and citations failed when the model cited the snapshot's "R1"/"U1" labels, "[F43] ..." forms, or the report summary. Fixes: the snapshot numbers recitals and unexpected findings with the report's fact numbers (`recital F12 p.1: ...`); "[F43] ...", "F43: ..." and "F43" are all accepted; the report marks its summary "not citable"; `view_case_file` returns one line when nothing changed since the last view; "document missing" no longer also needs a not_verifiable check (a missing needed document is enough). 249 backend tests pass; image rebuilt. · Next: a fourth continued run, only with the product owner's approval.

- 2026-11-21 · No repeated document requests (product owner's report) · The page listed the same document several times: layout plan and khata twice, the survey-linking order twice, Gundappa's heirs as a "set" and again one by one. It also had bundles ("records plus agreement", "completion certificate and occupancy certificate") and a request older than the root. Cause: the duplicate guard let the model override it with `distinct=true`, and the bundle check missed ":" and "plus". Fix (`tools.py`, `gates.py`, `report.py`, `case_file.py`, frontend):
  - a request alike an active one now always extends that one; the `distinct` override is gone;
  - the bundle check also refuses ":", "plus" and two of the same document noun joined by "and";
  - new `withdraw_requisition` tool (status `withdrawn`, optional `replaced_by` moves what it affects and the verdicts naming it); withdrawn requests are hidden, not counted as open, and listed as "No longer needed" in the changes;
  - closing is refused while two active requests are alike, and the digest names them;
  - prompt and playbook: at the start of a continued run, withdraw duplicates, requests for uploaded documents and requests older than the root.

  245 backend and 17 frontend tests pass (including the real duplicates from 8A14D132); image rebuilt. · Next: the third run, only with the product owner's approval.

- 2026-11-21 · 10.8 second run (65da923b, continued, approved) · Cost cuts first: Lead call cap 80→50, compaction at 30K characters instead of 60K, examiner reports in the Lead's context without the OCR quotes. The run ended `incomplete` at 50 Lead calls (1.33M input / 7.5K output tokens, 0 examiner calls, about 2.5 min); no new verdicts beyond the 1985 sale and the Will. The 2007 sale was refused twice for citing the examiner report's summary line (not a fact), which made 5 later verdicts in the same turn fail the oldest-first order. About 30 calls left no event (likely reopened reports and view_case_file). Fixes: facts are numbered in reports (`[F3 p.2]`) and cited by number (`gates.examiner_fact`); every model turn now logs a hidden "calls" event naming its tools, and reopening a report logs a hidden "reopen" event, so the next run shows where every call goes. 240 backend and 17 frontend tests pass; image rebuilt. · Next: a third run, only with the product owner's approval.

- 2026-11-21 · 10.8 first real run (dc970529, fresh, approved) · Ended `error` after 60 Lead + 23 examiner calls (1.68M input / 66K output tokens, about 3 min): `record_link_verdict` was refused more than 5 times in a row on the 2007 sale. Only 2 verdicts were recorded (1985 sale, the Will succession). The 25 "rejected" events showed why:
  - 10× `open_lead` refused because `source` named document ids. `source` is internal, so ids are now allowed there;
  - verdicts cited the examiner's wording (or a truncated copy) instead of the document's words. `gates.examiner_fact` now maps such a citation to the verified fact's real quote and page;
  - "requisition does not name this link": a missing needed document now links its requisition to the transfer instead of being refused;
  - "the link's own instrument has been examined, so it is not missing" blocked a transfer whose deed was present but whose power of attorney and Will were missing. Removed: needed documents now say exactly what is missing;
  - 6× text over the length limits. The limits are now stated in the tool docstrings; the document limit was raised from 120 to 150.
  - Playbook: never request title older than the root; a death certificate plus a heirship certificate is a succession to insert, never a break (the run again marked a break before the 2019 sale).

  Good signs: one document per request worked (e.g. legal-heir certificate, heirs' mutation and release deeds became 3 rows), and it raised conversion, layout and CC/OC questions from the change of property type. 239 backend tests pass. · Next: rebuild, then a second run only with the product owner's approval.

- 2026-11-21 · 10.1–10.7 (10.5 awaiting the product owner's review of the playbook text) ·
  - **10.1** `events.py`: every refused tool call or closing attempt becomes a "rejected" event and a log line; the buyer's feed hides them.
  - **10.2** `tools.add_requisition`: one document per request (text joining several is refused), it must name a transfer or issue, a request similar to an open one is refused unless `distinct=true`, reason ≤ 160 characters.
  - **10.3** `case_file.py`: `NeededDocument`, `LinkVerdict.property_type / extent / needed_documents`, `CaseFile.window()` (30 years; root = latest link dated at or before the cutoff). `record_link_verdict` requires the property type, extent and needed documents (found with valid citations, EC never; missing with a requisition naming the link), refuses a verdict before the earlier in-window links have one and before a break is settled. Closure, digest ("next transfer to verify"), opinion gate and built issues use the window.
  - **10.4** `gates._every_document_examined` replaces `_link_sources_examined`; the page says "Not examined".
  - **10.5** rewritten `prompts/verify_lead_system.txt` and `skills/verification/skill.md` (per-transfer loop), `succession` (no registered deed for inheritance; death certificate + heirship document + mutation) and `land_use_approvals` (reading a change of property type; conversion, layout, building plan, CC/OC, apartment documents, RERA where it applies). Legal text is a draft for the lawyer.
  - **10.6** issue title ≤ 70 and detail ≤ 220 characters; new `record_clear_check` tool and `CaseFile.clear_checks`; `report.clear_findings` adds "Chain of title is unbroken" only when every window transfer is verified and connected; report gate allows at most 2 opinion reasons of ≤ 140 characters and a one-sentence limitation; `Finding.severity` gains "clear".
  - **10.7** `ReportView.FindingsList` (count chips and cards: Critical / Caution / Note / Clear), bullet reasons, "For: <transfer>" on each document needed, property-type chip and found/needed checklist per transfer on the chain page, `dashboard.css`.

  238 backend tests and 17 frontend tests pass; ruff (verification code) and `tsc` are clean; both pages checked visually from a static render (headless Edge). Not run against a real model. The Docker image still has the old frontend and backend until `docker compose up --build`. · Next: product owner reviews the playbook text (10.5), then 10.8 (one approved paid run on 8A14D132).

- 2026-11-21 · Plan: transaction-by-transaction verification (PLAN.md decision 20) · `PLAN.md`, `TASKS.md` · Why: run f0223f1e (8A14D132) used all 80 Lead calls (2.05M input tokens) and judged only 3 of 8 links. It never examined 5 documents (shown as "Not needed"), marked a break before the 2019 sale even though the death certificate and the surviving family members certificate were uploaded, and raised duplicate and bundled requisitions (R1/R4, R3/R5). The product owner decided: verify oldest first over 30 years, track the property type per transfer, let the model work out the documents a type change needs (no rules table), and show a one-page dashboard. · Next: 10.1.

- 2026-11-20 · 7.3 Buyer-facing text carries no internal ids (PLAN.md decision 19) · `prompts/verify_report.txt`, `prompts/verify_lead_system.txt`, `services/verification/tools.py` (`_plain` on every buyer-facing field, readable transfer names in events), `services/verification/report.py` (`changes()` and the built issues/requisitions in words), `frontend/src/dashboard/results/labels.ts` (`refLabeller` also replaces ids inside longer text), `ReportView.tsx`, `CaseResults.tsx`, `ChainTimeline.tsx`, `verification/LiveFeed.tsx`, tests · 223 backend and 14 frontend tests pass; `tsc` is clean; the saved report, Case File and events for 8A14D132 were checked and their ids now appear only in hidden refs. · Next: one approved real run to measure.

- 2026-11-18 · Case-level report (PLAN.md decision 18) · `schemas/due_diligence.py` (sections: issues, requisitions, limitations), `services/verification/report.py` (`case_issues`, built issues and documents-needed sections, simpler gate), `prompts/verify_report.txt`, `prompts/verify_lead_system.txt`, `frontend/src/dashboard/results/` (`issues.ts`, `IssuesList`, `Limitations`; report sections removed), tests · 222 backend and 12 frontend tests pass; checked with the 8A14D132 data. · Next: one approved real run to measure.

- 2026-11-18 · Separate pages for the title chain and the verification report (PLAN.md decision 16) · `frontend/src/dashboard/results/CaseResults.tsx` (tabs, `ChainPage`, `ReportPage`, `?page=` in the URL), `dashboard.css` (tab styles), `results.test.tsx` · 12 frontend tests pass; `tsc` is clean; both pages checked with the 8A14D132 data. · Next: one approved real run to measure.

- 2026-11-18 · Read only what a transaction needs (PLAN.md decision 17) · `services/verification/gates.py` (new `unexamined_link_sources` and `_link_sources_examined`), `tools.py` (digest), `report.py` (document status), `prompts/verify_lead_system.txt`, `prompts/verify_report.txt`, `skills/verification/skill.md`, `frontend/src/dashboard/results/CaseResults.tsx`, tests · 222 backend and 10 frontend tests pass; ruff and `tsc` are clean. · Next: one approved real run to measure.

- 2026-11-18 · Lean pass (PLAN.md decisions 13–16) ·
  - **Upload:** `workers/stages.py`, `workers/tasks.py`, `services/orchestrator.py` and `services/document_processor.py` lose the structure stage and `extract_document`; classification now also returns the summary.
  - **Lead:** `services/verification/` (`tools.py`, `agents.py`, `skills.py`, `context.py`, new `cost.py`, `runner.py`) and `prompts/verify_lead_system.txt` drop `update_tasks` and `load_skill`, add `closes_leads`, the "Still to do" digest, compaction and the cost cap.
  - **Frontend:** new `frontend/src/dashboard/results/`; deleted `PhaseAResult.tsx`, `utils.tsx` and the old verification panel parts; about 1,400 lines of dead CSS removed.
  - **Docs:** README pipeline text.
  - **Checks:** 220 backend tests and 9 frontend tests pass; ruff and `tsc` are clean; the page was checked visually with the 8A14D132 data (headless Edge).

  · Not measured on a real run yet. · Next: one approved real run to measure tokens and cost against run 3, with the cost cap set.

- 2026-11-18 · Examiner simplified to one call (product owner's decision) · `services/verification/examiner.py`, `prompts/verify_examiner.txt`, `config.py`, `.env.example`, `tests/test_verification_examiner.py`, `tests/test_verification_runner.py` · The full OCR text goes in and the report comes out. The `read_next` tool, the quote-retry loop and two settings are removed; code drops facts whose quotes aren't in the text and corrects pages (PLAN.md decision 12). 220 backend tests pass. Also loaded run 2's report, Case File and run 1–2 events for case 8A14D132 into Docker MySQL, so the dashboard shows them (no model calls); the Docker image was rebuilt with the verification code. · Next: the dashboard fixes found in the visual check (misleading "8/8 transfers verified" tile, uncoloured verdict badges, raw ids in references, overflowing reference line, report placed below the requisition cards, oversized upload buttons, no run separators in the feed, raw document types), then the cost items listed below.

- 2026-11-18 · Real-case testing (case 8A14D132, Docker MySQL, read-only harness, gpt-6-luna) · Full write-up (local, gitignored): `docs/verification-run-8A14D132-runs-1-2.md`. Runs 1+2 = one full verification: 186 calls, 1.95M input / 207K output tokens, $0.194, report v1 NOT CLEAR, about 10.7 min. Run 3 (clean rerun) failed at closing (tool retry limit). Run 4 was stopped by the product owner to save credits. **Ask before every paid run.** · Fixes made from the findings:
  - quote matching ignores HTML and markdown; a real quote on the wrong page gets its page corrected; facts with unfound quotes are dropped, with one retry only when many are missing (OCR page markers are often missing);
  - small documents are preloaded into the examiner brief (no `read_next` round trips);
  - examination failures are retried in a new run;
  - examining a document reopens stale verdicts that rest on it;
  - every verdict except "missing document" must cite, and "missing document" is refused when the link's own deed was examined;
  - `resolve_lead` links the lead to the requisition itself; tool retries raised to 5;
  - duplicate-issue guard plus a new `update_issue` tool;
  - trimming keeps the newest batch whole and fits older results into `VERIFY_KEEP_TOOL_CHARS`;
  - the snapshot lists each document's recitals and unexpected findings;
  - prompt rules: insert any transfer a document reports (break only when none does); reopen saved reports before verdicts; review requisitions a new document settles; don't repeat requisitions.

  223 backend tests pass. · Not yet confirmed on a real run: the fixes above. Clean cost estimate: about $0.10–0.12 per case. · Next (agreed with the product owner, nothing started):
  1. cache-friendly trimming (clear in batches so the provider's prompt cache keeps working);
  2. shorter examiner reports;
  3. a hard USD cost cap per run;
  4. a cheap test mode on a saved Case File or DEMO-CLEAN-001;
  5. a requisition withdraw step;
  6. succession-playbook lawyer rules (8.2).

- 2026-11-18 · 7.2 · `frontend/src/dashboard/verification/` (`VerificationPanel`, `AgentPlan`, `LiveFeed`, `Requisitions`, `DueDiligenceReport`, `verification.test.tsx`); `api/backend.ts`; `VerificationDashboard.tsx` (panel above the chain view); `dashboard.css` (`vf-` styles); `package.json` test script. `npm run lint` and `npm run test` pass (6 tests). · No real run has been done yet: nothing has been run against a live database or a real model. · Next: 8.2 (lawyer instructions for the skills), one approved real run on a Docker MySQL case, then 6.4 and 9.1.

- 2026-11-18 · 1.1–7.1, 8.1 · Backend complete: `backend/domain/chain_continuity.py`; `backend/services/verification/` (`case_file`, `pages`, `gates`, `deps`, `skills`, `context`, `events`, `tools`, `examiner`, `agents`, `report`, `store`, `runner`, `service`); `backend/schemas/due_diligence.py`; `backend/prompts/verify_*.txt`; `backend/skills/verification/`; `backend/integrations/document_sources/`; `backend/services/case_documents.py` (extracted from `routers/cases.py`); `backend/routers/verification.py`; `backend/workers/verification_tasks.py`; additive tables in `migrations.py`; `finalize.py` hook; config and `.env.example`. Tests: `backend/tests/test_verification_*.py` and `test_chain_continuity.py` (211 passing in total). · Deviations are recorded in PLAN.md "Implementation decisions" (11 items). Note: `AGENTS.md`/`CLAUDE.md` are gitignored in this repo, so the AGENTS.md pointer is local only. The new migration was not run against a live database (it is additive `CREATE TABLE IF NOT EXISTS`). · Next: 7.2 frontend.
- 2026-11-18 · 0.1 · `specs/verification-agent/PLAN.md`, `specs/verification-agent/TASKS.md`, `AGENTS.md` · Plan approved and saved. · Next: 1.1.
