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

---

## Implementation log
Newest first. Format: date · task · files · notes (deviations from PLAN.md and why) · next step.

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
