# Title Verification Agent: Main Plan

## Context
Phase A builds a **draft** title chain. It is deliberately unverified; its skill says "a later stage reads every deed in full". We now need the stage a property lawyer performs:

- read every document;
- prove each transfer is connected and supported;
- **discover what the draft chain missed** (a partition in a recital, a GPA sale, a minor's share, a mortgage with no release, a court case), and fix the chain;
- never stop mid-run for a missing document: note it, keep going, and list it in the report;
- write a **due diligence report** in the dashboard;
- re-verify only what new uploads affect, then update the report.

The design follows published agent guidance:
- Anthropic, *Building effective agents*: the orchestrator-workers pattern, tool design treated as interface design, stopping conditions.
- Anthropic, *Effective context engineering*: just-in-time retrieval, structured notes, sub-agents with clean contexts, clearing old tool results.
- Anthropic, *Multi-agent research system*: a lead agent that adapts its plan from what workers find, memory outside the context, resuming from state.
- OpenAI, *Practical guide to building agents* and the Agents SDK: start with one loop, layered guardrails, turn limits.
- OpenAI, *Conversation state*: history management and compaction.
- Pydantic AI (already in our stack): `agent.iter()`, agent delegation, `UsageLimits`, output validators, history processors.

---

## 0. First deliverable: the spec in the codebase (handoff for any coding agent)
`docs/` is gitignored, so the spec lives in a new tracked folder, **`specs/verification-agent/`**:

| File | Purpose |
|---|---|
| `PLAN.md` | **This main plan, saved in full**: context, the two layers, loop, tools, Case File contract, gates, report format, design for change, simplicity choices, future document sources, the worked example and the sources. It is the single design reference (no separate SPEC, so nothing drifts) and changes only when a design decision changes. |
| `TASKS.md` | Small, independently testable tasks, each with "done when" criteria (tests to pass) and a status of `[ ]`, `[~]` or `[x]`. Ends with an **implementation log**: date, task, files changed, any deviation from SPEC and why, and the next step. |

`AGENTS.md` gets a short section, **"Active work: verification agent"**, telling every coding agent (Claude, Codex, Cursor and others) to:
1. read `PLAN.md` and `TASKS.md` first;
2. take the next open task;
3. run the checks;
4. tick the task and append to the log;
5. update `PLAN.md` whenever a design decision changes.

This follows the spec-driven practice of a living, version-controlled spec, small testable tasks, and keeping the spec in step with the code. Avoiding drift is the main rule.

## Design for change (so we never rebuild the whole agent)
Each likely change has one place to make it:

| If we want to change… | Change only… | Code touched |
|---|---|---|
| What a lawyer checks, or how | a `backend/skills/<name>/skill.md` playbook, or a new skill folder (the Lead discovers it through the skill index) | none |
| Agent wording or behaviour | `backend/prompts/verify_*.txt` | none |
| Model or provider per role | config `VERIFY_LEAD_MODEL`, `VERIFY_EXAMINER_MODEL`, `VERIFY_REPORT_MODEL` (each passed to `build_agent_model`) | none |
| Budgets | config | none |
| A new capability (e.g. a court-case lookup or a portal fetch) | a new tool in its own Pydantic AI `FunctionToolset`, registered in one list | 1 file + register |
| A new rule the agent must obey | a new pure function added to the gate list in `gates.py` | 1 function + test |
| A new report section | a section entry in the report schema. Sections are generic `{id, title, blocks[]}` (`paragraph`, `table`, `findings`, `list`) and the frontend renders any section | schema only, no UI change |
| The Case File shape | a new field plus a `schema_version` bump and a small `migrate()` step; old case files still load | `case_file.py` |
| The orchestration itself (e.g. a second worker type) | `agents.py` and `runner.py`; tools, gates, Case File and report are untouched | 2 files |
| Where documents come from (manual upload now, government portals later) | a new `DocumentSource` adapter (see "Future: government document sources") | 1 adapter |

Rules that keep the agent flexible:
- **The Case File is the one contract.** Tools write it, gates read it, the report is written from it, the UI shows it. Layers talk only through it.
- **The runner knows no law.** It only drives the loop, checkpoints, emits events, and calls the gates. Legal knowledge lives in skills and prompts.
- **One public service interface:** `start_full(case_id)`, `start_incremental(case_id, requisition_ids)`, `resume(run_id)`, `get_state(case_id)`. Routers and workers call only these.

## Future: government document sources (planned, not built now)
Later, documents will be fetched directly from government sources instead of being uploaded by hand. Likely sources are Kaveri for ECs and registered deeds and Bhoomi for RTC and mutation. We design for this now without building it:

- **A requisition is the request; a document source fulfils it.** Each requisition records *what* is needed (document type, property identifiers, registration number, year, reason, affected links). It never records *how* it will be obtained.
- **The `DocumentSource` interface** lives in `backend/integrations/document_sources/`:
  - `can_fulfil(requisition) -> bool`
  - `fetch(requisition) -> file`
- The first implementation is `ManualUploadSource` (today's flow). A later `GovtPortalSource` plugs in beside it.
- **Same path after the file arrives.** Every fetched or uploaded file goes through the existing six-stage pipeline (preprocess, OCR, merge, classify, structure, persist). It is then linked to its requisition and triggers the incremental run. The agent, gates, Case File and report do not change.
- **A possible later agent tool,** `fetch_document(requisition_id)`, lets the Lead fetch during a run instead of only noting the requisition. It is added as one more toolset, behind a config flag, because portal calls may cost money or need credentials.
- **The invariant still holds:** a fetch happens only for a requisition the agent explicitly raised. The application never searches for or suggests documents on its own.

## Simplicity choices (deliberately avoided)
These are things the guides say to add only when they are needed:
- **No new frameworks.** We use the pinned `pydantic-ai-slim==2.68.0`: delegation is written as an async tool following the Pydantic AI multi-agent guide. Each Examiner run has its own budget; its usage is added to the run's totals, not to the Lead's budget (see Implementation decisions). We do not add the Harness `SubAgents` package, Temporal or LangGraph.
- **No SSE or WebSockets.** The dashboard polls events by cursor, the same pattern it uses today.
- **One Case File JSON row per case** instead of many normalized tables. Checkpointing it after every step makes runs resumable without a durable-execution engine.
- **One orchestrator and one worker type.** More agent roles only if evaluation shows a need.
- **Deterministic gates first.** An LLM "senior reviewer" pass is an optional later step, added only if the evaluation set shows unsupported claims getting through.

## Implementation decisions (updated during the build)
These refine the design below. Where they differ from a later section, these win.

1. **Case File snapshot as tool output, not instructions.** The snapshot contains text taken from documents. Pydantic AI's guidance is never to build instructions from untrusted content. The Lead therefore gets the snapshot in its first prompt and from the `view_case_file` tool, which also lists what is still to do before closing. Only the playbook and skill index (operator-written files) are instructions.
2. **History trimming** uses Pydantic AI 2.x `capabilities=[ProcessHistory(trim_tool_results)]`; `history_processors=` no longer exists in v2.
3. **Separate budgets.** The Lead's `VERIFY_LEAD_CALL_BUDGET` counts only Lead calls. Each Examiner run has `VERIFY_EXAMINER_CALL_BUDGET` and the report writer has `VERIFY_REPORT_CALL_BUDGET`. All usage is summed in `verification_runs.usage_json`.
4. **Verification owns the chain once it starts.** When a case has a Case File, `finalize_case_task` no longer triggers an automatic Phase A rebuild after uploads, because a rebuild changes `phase_a_hash` and would discard verification progress. Documents uploaded for requisitions start an incremental run instead. A manual "Rebuild title chain" still resets the Case File; examiner reports for documents whose text is unchanged are carried over.
5. **Requisition lifecycle:** `open` → `fulfilled` (a document arrived; set by the upload route) → `resolved` or back to `open` (decided by the Lead with `review_requisition`). A fulfilled requisition whose document fails processing returns to `open`. The closure gate requires every fulfilled requisition to be reviewed. One PDF per requisition upload.
6. **Documents that cannot be examined** (no OCR text, or the Examiner failed twice) get `examination_error`. They are report limitations, cannot be cited, and prevent a `CLEAR` opinion.
7. **No report from an incomplete run.** A run that hits its budget or fails ends `incomplete` or `error` with the Case File saved; running again continues from it.
8. **Report assembly** (revised 2026-11-21, decision 21). The model writes only the opinion and its reasons. The application builds the findings from the Case File and lists what changed since the previous version from `CaseFile.report_basis` (verdicts, issues, requisitions and opinion when the last report was written).
9. **Severity:** high = a defect, title is not clear; medium = clear only subject to rectification; low = observation. The opinion gate: any high issue, defective link or break forces `NOT_CLEAR`; `CLEAR` needs every link verified and no medium issue, open requisition or unexamined document.
10. **Shared upload path.** The "upload more documents" logic moved from `routers/cases.py` into `services/case_documents.py`, so manual uploads and requisition uploads (and future government sources) use one path.
11. **Extra Case File tools** beyond the original list: `view_case_file`, `correct_link`, `mark_break`, `remove_link` (the `amend_chain` operations as separate, clearer tools) and `review_requisition`.
12. **The Document Examiner is one model call.** The full OCR text goes in the brief and a structured report comes back. There are no examiner tools, no read loop and no quote retries. Afterwards, code keeps only facts whose quote is in the text, correcting the page when the quote is found on another page, and drops the rest (counted in the report summary). A second call happens only if the output is not valid for the schema. Documents too large for the model's context are not handled yet. This replaces the earlier `read_next` loop, `VERIFY_EXAMINER_CALL_BUDGET` and `VERIFY_READ_CHUNK_CHARS`.
13. **No full-document read at upload.** The pipeline is preprocess → OCR → merge → classify → persist. The structuring stage (`extract_document` with large JSON schemas) is removed. Classification reads a 3,000-token prefix as before and also returns a 2–3 sentence summary in the same call; Phase A uses that summary to choose deeds, with `ensure_summaries` as the fallback for older documents. Persist only marks the document `structured` (the status name is kept because Phase A and verification select by it). The examiner is now the only full read of a document. The `structured_data` column stays but is no longer filled.
14. **Lean Lead.**
    - All playbooks go into the Lead's fixed instructions. They are identical on every call, so they form a cacheable prefix. There is no `load_skill` tool and no skill index.
    - `update_tasks` is removed.
    - `add_requisition(closes_leads=...)` resolves the covered leads in the same call.
    - Every tool that changes the Case File replies with a one-line "Still to do", so `view_case_file` is needed rarely.
    - The prompt asks for independent actions to be batched into one turn.
    - Trimming is replaced by compaction: history stays append-only (so the provider's prompt cache keeps hitting) until tool traffic passes `VERIFY_COMPACT_AT_CHARS`. Then older tool results and long tool-call arguments are cleared at once, keeping the newest batch.
15. **Hard cost cap.** `VERIFY_RUN_COST_LIMIT_USD` (default 0.50). After every Lead step the runner estimates Lead + examiner cost from `genai-prices` per-token rates and ends the run `incomplete`, with progress saved, once over the cap. Models without price data skip the cap, with a log warning.
16. **Results page.**
    - **Two pages under one shared case header** (property, status, one main action), switched by tabs and kept in the URL as `?page=chain|report`:
      - **Title chain page:** property identity, chain timeline, documents list. The timeline shows the chain as Phase A built it; each transfer carries its verification verdict, property type and documents checklist. Transfers inserted during verification appear in the findings and requests, not as timeline rows (2026-11-21).
      - **Verification report page:** opinion card, findings, documents needed (requisitions with upload). Agent steps show only while a run is live, one by one; they are not shown after the run (2026-11-21). Before any verification it shows a short explanation and a "Verify title" button.
      - The report page opens by default when a report exists, otherwise the chain page.
    - References are shown as file names and transfer names.
    - **Removed:** the old metric tiles and task list, the separate requisition cards, the structured-data viewer, the text chain graph, and their CSS.
    - Code lives in `frontend/src/dashboard/results/`.
18. **The report is a case-level result** (product owner's decision; buyers do not read per-transfer scrutiny, and the chain is already on its own page).
    - **Sections:** opinion and reasons; Issues identified; Documents needed; Limitations.
    - **Removed:** flow of title, scrutiny of each transaction, property schedule, the documents table, and the separate encumbrance, revenue and land-use sections.
    - **Built by code from the Case File, not the model:** "Issues identified" is every recorded issue, plus defective transfers and chain breaks no issue covers, most serious first (`report.case_issues`); "Documents needed" lists each requisition and its reason. The report writer writes only a one-line property summary, the opinion with 2–4 reasons, and a short limitations note, so its output drops from about 6.5K tokens to a few hundred. The opinion gate is unchanged.
    - **Lead prompt:** it must record every buyer-relevant problem as an issue in plain words, and give every requisition a one-sentence reason saying what the document will prove.
    - **Where per-transfer verdicts show:** they stay in the Case File and show on the title chain page.
17. **Read only what a transaction needs** (product owner's decision). *Superseded by decision 20: every uploaded document is examined.*
    - **Choice:** the Lead chooses from the document list and summaries the documents each transaction needs: its own deed, the documents its chain entry cites, the revenue records for its mutation, and anything a lead points to. It leaves unrelated documents unread. The application still never suggests documents.
    - **Closing check:** requires every transaction's own source documents to be examined, not every document (`gates._link_sources_examined` replaces `_every_document_examined`). The "Still to do" digest names the unexamined sources.
    - **Report and page:** unread documents are listed as "Not examined: not needed to verify any transaction". This alone does not block a `CLEAR` opinion; only unreadable documents do. The results page marks them "Not needed".
    - **Trade-off:** land-use and approval documents are read only when a transaction or lead calls for them.
19. **No internal ids in buyer-facing text.** Ids (PA-TC-0002, VL-1, DOC_018, I1, R1, L1) stay in the hidden fields that link records: `refs`, id fields and basis keys. Everything a buyer reads names the transfer and document in words: the prompts require it, the tools refuse text that mentions an id (`tools._plain`), built report text and events are worded without ids, and the results page replaces any id found in older saved data. The existing report for 8A14D132 is covered by the page replacement.
20. **Transaction-by-transaction verification** (product owner's decision, 2026-11-21). Replaces the activity-wide method ("read everything, follow up, judge every link at the end"), which spent run f0223f1e's 80 Lead calls and judged only 3 of 8 links.
    - **Goal:** prove the chain is valid and unbroken, one transfer at a time, from the root owner to the current owner.
    - **Window:** 30 years. The root is the latest transfer on or before today minus 30 years (or the earliest link if none is that old). Older links stay on the chain page, greyed out; they are neither judged nor requested.
    - **Order:** the Lead verifies links strictly oldest first. For each link:
      1. **read the transaction first:** its chain entry and its own instrument, so it knows who transferred what, when and how;
      2. record what was transferred: **property type** (agricultural land, converted plot, layout site, house, flat, other) and extent;
      3. **decide which documents legally prove this transfer** (the model decides, from the playbooks). For each one: if it is uploaded, examine it and confirm it really proves this transfer (right parties, right property, right date, registered or issued by the right authority); if it is not uploaded, raise a requisition;
      4. **continuity:** the seller is the previous buyer (or their heirs, GPA holder or successor, with evidence), and the property sold is the one the previous buyer received (same survey or site, extent not larger). If not, insert the missing transfer (succession, partition, ...) or mark a break before judging;
      5. **property-type change:** when the type differs from the previous link (agricultural land bought, Flat 302 sold), the model works out what happened in between (conversion, layout, construction, apartment project) and which documents prove it (NA order, layout approval, building plan, CC/OC, RERA where it applies). **No rules table in code:** the model applies the lawyer guidance in the playbooks;
      6. record the verdict with each needed document as found (cited) or missing (its requisition), then move to the next link.
    - **After the last link:** case-level checks (EC up to today, every mortgage released, revenue records and khata in the current owner's name, taxes paid) become findings.
    - **Code enforces only the process,** never legal rules:
      - a link's verdict is refused until every earlier in-window link has one;
      - the verdict must carry the property type, extent and the list of documents the transfer needs (found or missing);
      - every uploaded document is examined (reverses decision 17); the page says "Not examined" for any left over;
      - each requisition names exactly one document, the transfer it is for, and a one-sentence reason; a requisition that repeats an open one is refused;
      - every rejected tool call is written to the feed and the log, so wasted calls are visible.
    - **Report and dashboard (refines decision 18): one page.**
      - Opinion (NOT CLEAR / CLEAR SUBJECT TO / CLEAR) with at most 2 one-line reasons.
      - Count chips: `n critical`, `n to resolve`, `n clear`.
      - Finding cards: badge, title (at most 70 characters), text (at most 220 characters); the schema enforces both limits. Critical = high severity, To resolve = medium, Clear = a positive check that cites its evidence ("Chain of title is unbroken" is built by code from the verified chain).
      - Documents needed: one row per document with a one-line reason, the transfer it is for, and Upload.
      - The chain page shows each transfer's property-type chip and its documents checklist.
    - **As built (2026-11-21):** low-severity issues show as a grey "Note" card; positive findings come from the `record_clear_check` tool (cited) plus the code-built "Chain of title is unbroken"; refused tool calls are stored as "rejected" events, hidden from the buyer's feed.
    - **Example:** A→B 1995 agricultural land, Sy 45 (RTC and mutation found: verified). B→C 2006 "Site No. 12": the type changed, so the model looks for the conversion order and layout approval; the conversion order is found, the layout approval is missing (one requisition). C→D 2016 "Flat 302": changed again, so it looks for the building plan, CC/OC, the JDA with the landowner and the undivided share; the OC is missing (requisition); RERA is not needed because the building was completed before 2017 (a note, not a requisition).
21. **The saved report holds only what the report page shows** (product owner's decision, 2026-11-21). The report is `{version, opinion, reasons, findings, changes}`.
    - **Removed:** `property_summary` (the header already names the property from Phase A), `refs` (hidden ids nobody read), `basis` (moved to `CaseFile.report_basis`, hidden from the dashboard), and the generic sections with their "Documents needed" table and "Limitations" note. The Documents needed list on the page reads the live Case File, and unreadable documents show as "Could not be read" on the chain page.
    - **The writer** returns only `{opinion, reasons}`. The gates check the opinion against the Case File and the reasons' length (at most 2, 140 characters each).
    - **Older reports** (saved with sections) are converted when read (`DueDiligenceReport._from_older_shape`), so v1–v4 still display.
    - **Writer input is a short text, not the Case File JSON:** each in-window transfer's verdict and summary, breaks, issues, open requests, unreadable documents and passed checks, in words without ids (`report.report_input`). On 8A14D132 it dropped from 85K to 6K characters.
    - **Case File schema 2** drops fields nothing read: `tasks`, `property_identity`, and each link's `amendments` and `related_events`. `migrate` removes them from stored version-1 files. The live feed still records every chain correction.

---

## 1. The two layers

```
 Dashboard  ◄── events / case file / report ──┐
                                              │
 ┌──────────────── CONVERSATION MANAGEMENT LAYER (our code: state, context, tools, gates) ───────────┐
 │  Case File (memory)  │  Context Builder  │  Tool Executor  │  Gates  │  Event Log  │  Run Manager    │
 └────────────▲──────────────────┬───────────────────▲──────────────────────────────────────────────────┘
              │ state changes     │ built context      │ tool calls / final output
 ┌────────────┴──────────────────▼───────────────────┴──────────────────────────────────────────────────┐
 │  MODEL INFERENCE LAYER: Pydantic AI on build_agent_model()                                            │
 │    Lead Examiner (orchestrator)  ──delegates──►  Document Examiner (worker, clean context per doc)   │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Conversation management layer (we own all state and decisions about context)
| Part | What it does |
|---|---|
| **Case File** | The agent's durable memory (one JSON per case, versioned): the working chain, facts, open leads, issues, requisitions and a task list. It is the source of truth; message history is only a log. |
| **Context Builder** | Before every Lead model call, renders a compact snapshot of the Case File into the context and **clears old tool results**, keeping the last few. The Lead's context stays small however long the run gets. |
| **Tool Executor** | Runs tool calls and writes their effects into the Case File. |
| **Gates** | Code checks that the model cannot skip (section 4). A failed gate sends the error back to the model, which tries again. |
| **Event Log** | Every step becomes an event ("Examining Sale Deed 2010", "Discovered: 2005 partition not in chain"), shown live in the dashboard. |
| **Run Manager** | Runs a full or incremental run as a Celery task under a Redis lock and saves the Case File after every step. A crashed run **resumes from the Case File** rather than starting over. |

### Model inference layer (thin; the model only reasons and calls tools)
- **Lead Examiner:** one agentic loop per run. It holds the case-level view, decides what to do next, delegates reading, amends the chain, and closes the case.
- **Document Examiner:** a sub-agent called as a tool. It gets a **clean context** with one document plus a brief from the Lead, reads it **end to end**, and returns a structured, cited report. Raw OCR text never enters the Lead's context.
- Both agents use `build_agent_model()`. The loop is Pydantic AI's: model call → tool calls (run in parallel when several are issued) → results → model call … → final output. We drive it with `agent.iter()` so every step passes through our event log and gates.
- The runner is async because delegation requires `await examiner.run(...)` and `run_sync` is not allowed inside tools. The Celery task calls `asyncio.run(runner.run(...))`.

---

## 2. The agent loop

```python
case_file = load_or_init(case_id)            # draft chain from Phase A + document index
async with lead_agent.iter(task_prompt(case_file), deps=deps,
                           usage_limits=UsageLimits(request_limit=LEAD_BUDGET)) as run:
    async for node in run:                   # each model call and each tool batch is a node
        event_log.record(node)               # live feed
        case_file.save()                     # checkpoint after every step
# run.result = LeadClosure → closure gates → report writer → report gates → saved report v(n)
```

**Lead tools** (few, distinct, hard to misuse):
| Tool | Purpose |
|---|---|
| `examine_document(doc_id, focus_questions)` | Runs the Document Examiner. It returns facts and discoveries with page and quote, and caches the report per document so later runs reuse it. |
| `read_pages(doc_id, from, to)` | A targeted look at specific pages to settle a doubt, without a full examination. |
| `load_skill(name)` | Loads lawyer playbooks on demand (title link, succession, partition, GPA, encumbrances, revenue, land use…). |
| `record_link_verdict(tx_id, checks[], verdict, citations)` | Per-transfer verification result. |
| `amend_chain(op, …)` | Changes the working chain: insert a link, correct a party or extent, mark a break, merge duplicates. Each change needs citations and passes the chain gates. |
| `open_lead(text, source)` / `resolve_lead(id, outcome)` | Tracks something discovered that must be followed up. |
| `record_issue(severity, text, citations)` | Records a red flag or observation. |
| `add_requisition(document, reason, affects[])` | Notes a missing document **without stopping**. |
| `update_tasks(...)` | The Lead's own plan or to-do list, visible in the UI like Codex's checklist. |
| final output `LeadClosure` | Lets the Lead declare it is done, and is checked by the closure gates. |

**Document Examiner** output (`ExaminerReport`):
- instrument: type, registration number and date, office, stamp duty, execution;
- parties, including capacity: GPA holder, guardian of a minor, legal heir;
- schedule: survey/hissa, extent, boundaries;
- consideration;
- recitals, meaning every prior step of title the document states;
- encumbrances and restrictions;
- **`unexpected[]`**: anything outside the brief that a lawyer would care about.

Every item carries `{page, quote}`.

### How the agent handles something nobody planned for
The plan is not fixed. Every `ExaminerReport` returns `recitals` and `unexpected`, and the Lead's instructions and skills say:
1. **Compare every recital and history entry against the working chain.** A step that is missing becomes `amend_chain(insert)` if supported, or `open_lead` if it needs more evidence.
2. **Every discovery becomes a lead.** A lead is closed only by evidence, by a requisition, or by a recorded reason why it does not affect title.
3. **New leads can add tasks:** examine another document, load another skill, re-check a neighbouring link.

The closure gate rejects `LeadClosure` while any lead is open, so the agent cannot ignore what it found.

---

## 3. Worked example

**Uploads:** EC (2000–2024), RTC, MR, Sale Deed 1998 (A→B), Sale Deed 2010 (B→C), Sale Deed 2018 (C→D), conversion order.
**Draft chain from Phase A:** T1 A→B 1998 · T2 B→C 2010 · T3 C→D 2018.

| # | What the Lead does | What happens in the Case File |
|---|---|---|
| 1 | Reads the snapshot (draft chain, 7 documents with summaries, empty task list). Writes its plan with `update_tasks`: examine all history documents, then each deed, then encumbrances, revenue and land use. | task list created |
| 2 | Calls `examine_document` on the EC, RTC and MR **in parallel**. | 3 examiner reports cached |
| 3 | EC report `unexpected`: **"2005: Partition deed among B, B2, B3, Sy.No.45"**. That is not in the chain. | `open_lead L1` "2005 partition may change B's title" |
| 4 | EC also shows a **2012 mortgage by C to Canara Bank with no release entry**. RTC column 11 shows the same loan. | `record_issue` (high) and `open_lead L2` |
| 5 | Examines the 2010 deed with focus "B's source of title, all vendors, capacity". The report: vendors are **B and B1 (minor, through guardian B)**; the recital says B got the land "by the 2005 partition, Schedule B". | `amend_chain(insert T1a: partition 2005, B allotted the target parcel, recital_reported)`; the chain gate confirms continuity A→B→(partition)→B→C; `open_lead L3` "minor's share sold without court permission?" |
| 6 | `load_skill("partition")`, then `load_skill("minor_property")`. The partition deed was not uploaded. | `add_requisition R1` "2005 partition deed" (affects T1a, L1); `add_requisition R2` "court permission for sale of minor's share" (affects T2, L3) |
| 7 | Examines the 1998 and 2018 deeds. Both links check out: vendor title, schedule, extent 2A-10G, registration, stamp duty. | `record_link_verdict(T1, verified)`, `record_link_verdict(T3, verified)` |
| 8 | Revenue check: the RTC still shows **C** after the 2018 sale. | `record_issue` (medium) "mutation pending"; `add_requisition R3` "MR in D's name" |
| 9 | L2: no release deed among the uploads. | `add_requisition R4` "release deed or bank NOC"; L2 resolved as "requisition" |
| 10 | Returns `LeadClosure`. The gates check that every link has a verdict, the chain has no break, no lead is open, every document was examined, and every citation quote exists. | pass |
| 11 | **Report writer** (one call, using the Case File only, no OCR) → report v1. Opinion **NOT CLEAR at present**, with 4 requisitions and the reasons. | report v1 saved |

**Later:** the user uploads the partition deed against R1 and the release deed against R4. The pipeline OCRs them, then an **incremental run** starts.
- It begins with the Case File and the message "R1 and R4 now have documents".
- The Lead examines only those two documents. It finds the partition deed's Schedule B matches the parcel, so T1a becomes `corroborated` and L1 is resolved. The release deed closes R4.
- The report writer produces **v2**, with a "changes since v1" section. Opinion: **CLEAR SUBJECT TO** R2 (court permission) and R3 (mutation).
- Other links are not re-examined; their cached reports and verdicts are reused. If a new document contradicts a cached fact, the Lead is told which links cite that fact and re-checks only those.

---

## 4. Gates (code-enforced, failure is sent back to the model)
1. **Full read:** the Examiner must read every page before returning, and a citation may use only fully examined documents (same principle as Phase A's full-OCR gate).
2. **Quote check:** every quote must exist on the cited page of `merged_ocr_text`. Matching normalizes whitespace and is Kannada-safe.
3. **EC rule:** an EC may support encumbrances or open a lead. It **never** counts as evidence in a link verdict (an existing invariant).
4. **Chain integrity on every `amend_chain`:**
   - each transferor continues the previous acquirer; we reuse `_check_continuity` / `_name_words`, moved into a shared `backend/domain/chain_continuity.py`;
   - dates never go backwards;
   - non-transfers (mortgage, lease, POA, agreement) never become links;
   - the `evidence_status` rules match Phase A's.
5. **Closure gate on `LeadClosure`:**
   - every link has a verdict;
   - every adjacent pair is connected or has a recorded break;
   - no open leads;
   - every uploaded document examined;
   - every requisition says what it affects.
6. **Report gate:**
   - every statement references Case File items;
   - the opinion is consistent with them (no `CLEAR` while a break, a high issue or an unverified link exists);
   - a requisition is never presented as resolved.
7. **Honest failure:** an exhausted budget or crash gives status `error` or `incomplete`, with unexamined items listed. The report never claims a check was done that wasn't.

---

## 5. Context engineering in detail
- **Every Lead call contains:**
  - the system role and rules, plus the skill index (bodies load on demand);
  - the Case File snapshot, rendered as compact tables, in the first prompt and from the `view_case_file` tool (see Implementation decisions);
  - the last *K* raw tool results.
- Older tool results are replaced by one line, e.g. "examiner report saved as ER-12". This is the lightest form of compaction and loses nothing, because the facts live in the Case File.
- **Examiner context:** its own rules, the Lead's brief, and the document's pages. It is discarded after the call; only the structured report survives.
- **Just-in-time reading:** the Lead sees summaries and identifiers and opens content only through tools. Nothing is preloaded.
- **Budgets:** `UsageLimits` per Lead run and per Examiner call, plus a cost limit. Close to the limit, the Lead is told to wrap up. Anything left becomes an "not examined (budget)" item, and the opinion cannot be `CLEAR`.

---

## 6. Report (`backend/schemas/due_diligence.py`): lawyer format
1. Property schedule.
2. Documents examined: a table of each document, its pages, and whether it was fully examined.
3. **Flow of title**: the verified chain in narrative form, with amendments marked "added during verification".
4. Per-transaction scrutiny: vendor's title, parties and capacity, schedule and extent, execution, registration, stamp duty, consideration, mutation followed.
5. Encumbrances: mortgages with or without release, attachments, agreements.
6. Revenue records: RTC and MR consistency.
7. Land use and approvals: conversion, khata, plan, tax, PTCL/grant restrictions.
8. Red flags, by severity.
9. Requisitions: documents required, why, and what each affects.
10. **Opinion**: `CLEAR`, `CLEAR_SUBJECT_TO` or `NOT_CLEAR`, with reasons.
11. Limitations.
12. Changes since the previous version.

Every finding links to its document, page and quote.

---

## 7. Data (additive, idempotent, in `backend/database/migrations.py`)
| Table | Contents |
|---|---|
| `verification_case_files` | case_id, version, data JSON (chain, facts, leads, issues, requisitions, tasks, examiner reports) |
| `verification_runs` | id, case_id, kind (`full` or `incremental`), status, usage, error, timestamps |
| `verification_events` | id, run_id, kind, text, ref, created_at (live feed, read by cursor) |
| `due_diligence_reports` | id, case_id, version, report JSON, opinion, created_at |

The Phase A `title_chains` row stays as the draft. If the user rebuilds the chain in Phase A, the Case File resets and a full run is needed.

## 8. Files
**Spec (first):** `specs/verification-agent/PLAN.md` (this plan), `specs/verification-agent/TASKS.md`, plus the AGENTS.md pointer section.

**Document sources:** `backend/integrations/document_sources/base.py` (the `DocumentSource` interface) and `manual_upload.py`. The requisition upload route goes through this interface, so a government source can be added later without touching the agent.

**Conversation management layer:** `backend/services/verification/`
- `case_file.py`: model plus load and save.
- `context.py`: snapshot rendering and the history processor.
- `tools.py`: tools grouped into `FunctionToolset`s (chain, evidence, case-file) and registered in one list
- `gates.py`: a list of small pure gate functions
- `events.py`
- `runner.py`: full and incremental runs, resume, report step.

Also `backend/domain/chain_continuity.py` (shared with `chain_builder.py`).

**Inference layer**
- `backend/services/verification/agents.py`: `lead_agent`, `examiner_agent`, `report_agent`.
- Prompts: `backend/prompts/verify_lead_system.txt`, `verify_examiner.txt`, `verify_report.txt`.
- Skills: `backend/skills/verification/skill.md` (the lead playbook) and one folder per topic under `backend/skills/verification/`: `title_link/`, `succession/`, `partition/`, `gpa_and_capacity/`, `minor_property/`, `encumbrances/`, `revenue_records/`, `land_use_approvals/`. The skill index is generated from these folders. Coding agents draft the structure; the legal content comes from the product owner's lawyer instructions.

**Data, API, worker**
- `backend/database/repositories/verification_repo.py`
- `backend/workers/verification_tasks.py`
- `backend/routers/verification.py`, with these routes:

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/verify/{case_id}` | start a full run |
| GET | `/api/verify/{case_id}/events?after=` | live feed |
| GET | `/api/verify/{case_id}` | Case File summary and latest report |
| POST | `/api/verify/{case_id}/requisitions/{id}/upload` | upload against a requisition; this triggers the incremental run |

- Modified: `workers/finalize.py` (queue an incremental run when requisition documents are structured), `config.py` and `.env.example` (budgets).

**Frontend:** `frontend/src/dashboard/verification/`
- `AgentPlan.tsx`: the Lead's task list, live.
- `LiveFeed.tsx`: steps and discoveries.
- `DueDiligenceReport.tsx`
- `Requisitions.tsx`: an upload button per requisition.

Plus additions to `api/backend.ts` and `VerificationDashboard.tsx`.

**Reused:**
- `build_agent_model` (`integrations/llm/agent_models.py`)
- `load_prompt`
- `agent_repo.get_document_raw_text`, which keeps `--- Page N ---` markers for page citations
- `agent_repo.get_agent_result` for the draft chain
- `chain_identity` for stable `tx_id`s
- the Redis lock pattern from `cleartitle_agent.run_case_analysis`
- the continuity logic from `chain_builder.py`

## 9. Build order
0. Save this plan as `specs/verification-agent/PLAN.md`, write `TASKS.md` from it, and add the AGENTS.md pointer. Each step below becomes one or more tasks in `TASKS.md`.
1. Case File schema, tables and repository; move the continuity logic into `domain/`.
2. Gates and tools, with unit tests.
3. Examiner agent and its caching (tests with Pydantic AI `TestModel`/`FunctionModel`, no real LLM calls).
4. Lead agent, context builder and runner (full run, checkpoint and resume).
5. Report agent and report gate.
6. Requisition upload and incremental run.
7. API and dashboard: plan, live feed, report, requisitions.
8. Skills: draft the structure, then add the product owner's lawyer instructions; tune on 3–5 real cases.
9. Evaluation set: about 10 real cases with a lawyer's expected findings. A small judge rubric covers citation accuracy, missed discoveries and opinion correctness.

## 10. Verification
- `.\venv\Scripts\python.exe -m pytest backend/tests`. New tests cover:
  - every gate;
  - an "unexpected" discovery forces a lead and blocks closure until it is resolved;
  - an `amend_chain` insert keeps continuity;
  - a missing document becomes a requisition while the run continues;
  - an incremental run examines only the new documents;
  - resume after a crash;
  - an EC is never accepted as link evidence.
- `.\venv\Scripts\ruff.exe check backend`, and `cd frontend; npm run lint; npm run test`
- One real case on Docker MySQL (port 3307), **only with the product owner's approval** (OCR and LLM calls cost money). Watch the plan and feed, check that discoveries become leads, upload against one requisition, and confirm v2 changes only what it should.

## Sources
- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, How we built our multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- OpenAI, Conversation state: https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI, A practical guide to building agents: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- OpenAI Agents SDK, Running agents: https://openai.github.io/openai-agents-python/running_agents/
- Pydantic AI, Agents: https://pydantic.dev/docs/ai/core-concepts/agent/
- Pydantic AI, Multi-agent applications: https://pydantic.dev/docs/ai/guides/multi-agent-applications/
- Pydantic AI, Message history: https://pydantic.dev/docs/ai/core-concepts/message-history/
- Addy Osmani, How to write a good spec for AI agents: https://addyosmani.com/blog/good-spec/
