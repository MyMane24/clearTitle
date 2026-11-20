# clearTitle — AI Property Title Verification

An end-to-end property title platform for **Karnataka property documents**. clearTitle reads scanned PDFs with Sarvam OCR, classifies and summarises each one, then hands the case to a tool-using **ClearTitle agent** that reconstructs the title chain from the property's history documents — pausing to request missing evidence instead of guessing. A verification agent then checks the chain and writes a due diligence report.

Transaction-by-transaction verification and reports are **not part of this application**; they are being rebuilt from scratch. The pipeline, document processing, and title-chain construction (Phase A) are complete and working.

---

## Highlights

- **Agent-driven chain building, not keyword matching** — the agent decides which documents to read from summaries alone; the application enforces process guarantees (full-OCR gate, citation scope, history-first order) but never suggests candidates.
- **Read what you rely on** — every history document must be read in full (100% of its OCR text) before it can support a saved chain; citations are validated against what was actually read.
- **Honest pauses** — with no history document uploaded, the agent pauses and asks for the Encumbrance Certificate instead of guessing a chain from deeds alone.
- **History-first** — the chain is built from the EC, mutation and RTC records, using title deeds only to extend the chain backward or settle an unclear history entry.
- **No misleading success on failure** — if the chain build cannot complete (e.g. a temporary LLM outage), the case is marked `error` and the dashboard shows a clear retry state; no fabricated chain.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Frontend["Frontend Layer (React SPA)"]
        UI["clearTitle SPA\nReact 19 + Vite + TypeScript\nLanding page (/) + Dashboard (/#/app)"]
        DASH["Verification Dashboard\nUpload . Processing . Title chain . History"]
        AUTH["Auth Screen\nRegister / Login / Google OAuth / Link guest case"]
        HOME["Landing sections\nHero . Pipeline . Audit demo . FAQ"]
    end

    subgraph API["API Gateway Layer (FastAPI)"]
        R_AUTH["Auth Router\n/api/auth/register . /login . /me\nGoogle OAuth at /auth/google/*"]
        R_CASES["Cases Router\n/api/upload . /api/cases . /api/process\n/api/status . /api/retry\nreplace / skip / case upload / link"]
        R_RESULTS["Results Router\n/api/results/{id} . /chain . /ocr"]
    end

    subgraph Orchestration["Async Task Queue"]
        CELERY["Celery Workers\nbackend/workers/* (stages, finalize, title_chain_tasks)"]
        REDIS_BROKER["Redis Broker / State Store"]
    end

    subgraph Pipeline["Document Pipeline (per PDF, 5 stages)"]
        PREPROC["1 Preprocess\n(denoise & deskew)"]
        OCR["2 Sarvam OCR\n(PDF -> Raw Text)"]
        MERGE["3 Merge Chunks"]
        CLASSIFY["4 Classify + summary\n(LLM on a text prefix + explicit rules)"]
        PERSIST["5 Persist\n(mark ready in MySQL)"]
    end

    subgraph Analysis["Case-Level Analysis (after finalize)"]
        FINALIZE["Finalize\n(recompute status + queue chain build)"]
        PHASE_A["ClearTitle agent - Phase A\ntitle chain: history first, deeds on the path"]
    end

    subgraph Storage["Storage Layer"]
        MYSQL["MySQL\nusers, cases, documents, title_chains"]
        REDIS["Redis State Store"]
        FS["File System\noutputs/"]
    end

    UI -->|"HTTP API Requests"| API
    DASH -->|"HTTP API Requests"| API
    R_CASES -->|"Dispatches tasks"| CELERY
    CELERY -->|"Reads/writes status"| REDIS
    CELERY --> PREPROC --> OCR --> MERGE --> CLASSIFY --> PERSIST
    PERSIST -->|"chord"| FINALIZE
    FINALIZE --> PHASE_A
    CLASSIFY -->|"Saves type and summary"| MYSQL
    PHASE_A -->|"Saves property identity and chain"| MYSQL
```

### Key Components

| Component | Technology | Description |
|---|---|---|
| **Frontend** | React 19, Vite 6, TypeScript, Tailwind CSS 4 | Landing page + dashboard with AI pipeline view, title-chain details, document extractions, and case history |
| **API Layer** | FastAPI, Uvicorn | Async REST API with JWT auth (plus optional Google OAuth) for cases, documents, and results |
| **Async Tasks** | Celery, Redis | Idempotent background stages — preprocess, OCR, merge, classify, persist, finalize, chain build, verification |
| **OCR Service** | Sarvam AI Vision OCR | High-accuracy OCR for mixed English/Kannada text; chunks >10-page PDFs with overlap |
| **Document processing** | OpenAI-compatible API | Classification and full-text schema-based extraction |
| **Title-chain agent** | OpenAI by default (`GPT-6 Luna`); Gemini optional | Tool-calling agent that builds the history-first title chain (Phase A) |
| **Relational DB** | MySQL | Unified tables for users, cases, documents, and title chains |

---

## How the Title Chain Is Built

The application's job is to make dishonest shortcuts impossible; the agent's job is to reason over evidence. The chain builder works **history-first**:

1. **Record what the property identity needs**, then list the case's documents from their summaries.
2. **Read every history document in full** — the encumbrance certificate, mutation records and RTC (pahani). These give the backbone of the chain, including entries that are not deeds. Property register cards are excluded from chain building.
3. **Open title deeds only on the path** — to follow the chain further back through a deed recital when the history stops short of thirty years, or to settle a history entry that OCR left unclear. Receipts, plans and certificates are never shown to it.
4. **Save the chain** — property identity, an ordered list of transactions, and the documents still needed to reach thirty years or close a gap.

Each link is marked by how it is known: `corroborated`, `register_reported`, `deed_reported`, or `recital_reported`. The chain graph is drawn by the application from the links. Transaction-by-transaction verification is not implemented here; it is being rebuilt from scratch.

### The guarantees (application-enforced)

| Guarantee | Rule |
|---|---|
| **History-first** | The chain can only be built after every uploaded history document (EC, mutation, RTC) was read end to end in that session |
| **Full-OCR gate** | A completed chain is rejected unless every selected document was read end-to-end in this session |
| **Citation validation** | Every source reference points at a history document or title deed that was read end to end |
| **Chain order** | Links run in date order, each names who acquired the property, and a mortgage or lease can never be a link |
| **No candidate suggestion** | There is no keyword matcher; the agent alone decides what to read from summaries |
| **No misleading completion** | With no history document uploaded the agent pauses and asks for the Encumbrance Certificate; it never builds a chain from deeds alone |

### Pause and rebuild

- **Pause** — a case with no history document saves no chain and returns the request for an Encumbrance Certificate. The dashboard shows the request and accepts the documents.
- **Rebuild** — uploading more documents and running the chain build again (`POST /api/results/{case_id}/chain`) rebuilds from scratch. Chain transaction ids stay stable for links that still match, so a rebuilt chain keeps its identity.

### Stored chain

| Field | Content |
|---|---|
| `property_identity` | Identifiers recorded from the property's documents |
| `title_chain` | Ordered links, each with the documented transaction, `evidence_status`, and `source_refs` |
| `title_chain_graph` | Text graph drawn by the application from the links |
| `missing_documents` | Documents still needed to reach thirty years or close a gap |
| `phase_a_hash` | Integrity hash of the stored chain |

---

## Supported Document Types

| Category | Types |
|---|---|
| **Ownership & Transfer** | `SALE_DEED`, `GIFT_DEED`, `PARTITION_DEED` |
| **Government Registry** | `ENCUMBRANCE_CERTIFICATE` (EC), `PROPERTY_REGISTER_CARD` (PRC) |
| **Municipal & Tax** | `KHATA`, `PROPERTY_TAX_ASSESSMENT`, `TAX_RECEIPT`, `E_PAYMENT_RECEIPT` |
| **Revenue & Clearances** | `MUTATION`, `CONVERSION_ORDER`, `POSSESSION_CERTIFICATE` |
| **Legal & Others** | `RTC_PAHANI`, `LEGAL_HEIR_CERTIFICATE`, `COURT_ORDER` |

Extraction uses 18 hand-written JSON schemas (plus two completion-certificate subtype variants and a generic fallback for unknown types). Classification runs an LLM over a bounded OCR prefix with deterministic rules for known formats such as Karnataka Form 9 and issuer-specific completion certificates. A document classified as unrelated is marked for user action.

---

## Quick Start (Docker)

> **Only requirement:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed. No Python, MySQL, or Redis needed on your machine.

### 1. Clone and configure

```bash
git clone https://github.com/MyMane24/clearTitle.git
cd clearTitle
cp .env.example .env
```

Open `.env` and fill in the API keys (everything else works as-is):

```env
SARVAM_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
DOCUMENT_PROCESSOR_MODEL=gpt-6-luna

# Chain agent (OpenAI by default)
CLEARTITLE_AGENT_PROVIDER=openai
CLEARTITLE_AGENT_MODEL=GPT-6 Luna

# Optional: use Gemini for the chain agent instead
# CLEARTITLE_AGENT_PROVIDER=gemini
# GEMINI_API_KEY=your_key_here

# Optional: Google OAuth ("Continue with Google")
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...
# GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

### 2. Start everything

```bash
docker compose up --build
```

This starts 5 services automatically:

| Service | URL / Port | Purpose |
|---|---|---|
| **App (FastAPI + React SPA)** | http://localhost:8000 | Main application — open `/#/app` for the dashboard |
| **phpMyAdmin** | http://localhost:8080 | Browse MySQL data in browser |
| **MySQL** | `127.0.0.1:3307` | Database (exposed for GUI tools) |
| **Redis** | internal only | Celery broker + state store |
| **Celery Worker** | internal only | Background task processing (`--concurrency=2`) |

On subsequent runs just use `docker compose up`. Rebuild with `docker compose up --build` after changing code — the React SPA is baked into the image. A rebuild replaces the `:latest` tag, so tag the current image before a risky change (see [Backup & Rollback](#backup--rollback)).

### 3. Build a title chain

1. Open `/#/app`, upload the property PDFs, and press **Process**.
2. Watch the five-stage pipeline run live (`/api/status/{case_id}`).
3. When processing completes, the chain build starts automatically. If no history document was uploaded, the dashboard asks for the **Encumbrance Certificate**.
4. Upload the requested history documents; the chain is built again when processing finishes. **Rebuild title chain** re-runs it on demand.
5. The results view shows the property identity, the chain links with their sources, and the documents still needed.

---

## Frontend Development (Without Docker)

The React app lives in `frontend/`. It has its own dev server (Express + Vite HMR) on port 3000:

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

| Command | Description |
|---|---|
| `npm run dev` | Dev server (Express + Vite middleware) on :3000 |
| `npm run build` | Build the Vite frontend + bundle the server to `dist/` |
| `npm run lint` | Type-check with `tsc --noEmit` |
| `npm run test` | Unit tests for the results rendering layer (`node --test` + tsx) |
| `npm start` | Run the production server from `dist/` |

When deployed via Docker, the built SPA is served by FastAPI from `frontend/dist`.

---

## Inspecting the Database

### Option A — phpMyAdmin (browser, zero install)

Open **http://localhost:8080** — you'll see all tables (`users`, `cases`, `documents`, `title_chains`) and can browse/query data directly. `case_results` and `case_memory` are legacy tables kept dormant for old data.

### Option B — MySQL Workbench / DBeaver / TablePlus

```
Host:     127.0.0.1
Port:     3307
User:     root
Password: password
Database: property_ocr_v2
```

### Option C — Terminal

```bash
docker compose exec mysql mysql -u root -ppassword property_ocr_v2
```

---

## API Endpoints

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register a new account |
| `POST` | `/api/auth/login` | Log in, returns a JWT |
| `GET` | `/api/auth/me` | Current user (requires Bearer token) |
| `GET` | `/auth/google/login` | Start Google OAuth (optional, when configured) |
| `GET` | `/auth/google/callback` | Google OAuth callback |

### Pipeline & Cases
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/cases` | List cases (requires auth) |
| `POST` | `/api/upload` | Upload PDFs and initialize a new case |
| `POST` | `/api/process/{case_id}` | Trigger the async OCR + classification pipeline |
| `GET` | `/api/status/{case_id}` | Real-time pipeline status (progress, log, chain status) |
| `POST` | `/api/retry/{case_id}` | Retry failed documents |
| `POST` | `/api/case/{case_id}/upload` | Add more documents to an existing case |
| `POST` | `/api/case/{case_id}/link` | Link a guest case to the logged-in account |
| `POST` | `/api/case/{case_id}/doc/{doc_id}/replace` | Replace a document file |
| `POST` | `/api/case/{case_id}/doc/{doc_id}/skip` | Mark a document as skipped |
| `GET` | `/api/case/{case_id}/doc/{doc_id}/pdf` | Serve the original PDF (authenticated, opens in new tab) |
| `DELETE` | `/api/case/{case_id}` | Delete a single case (MySQL + files) |

### Results & Chain
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/results/{case_id}` | Full results payload: case info, documents + structured JSON, chain, and chain status |
| `POST` | `/api/results/{case_id}/chain` | (Re)build the title chain for a case |
| `GET` | `/api/results/{case_id}/ocr` | Raw OCR full text for every document in the case |

### Misc
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check + API-key presence |
| `GET` | `/` | React SPA (built) or `frontend/index.html` |

Most case endpoints accept an optional JWT. Guest (anonymous) cases work without auth, but case data can only be accessed by its owner once linked.

---

## The Document Pipeline

Every uploaded PDF goes through **5 stages**, each its own idempotent Celery task, chained and joined by a **chord** that runs one chain per document in parallel:

```
DOC_001 --> preprocess --> ocr --> merge --> classify --> persist --+
DOC_002 --> preprocess --> ocr --> merge --> classify --> persist --+--> finalize --> title chain
DOC_003 --> preprocess --> ocr --> merge --> classify --> persist --+
```

| # | Stage | Work |
|---|---|---|
| 1 | **Preprocess** | CLAHE contrast, denoise, deskew, sharpen via OpenCV (non-fatal: falls back to raw PDF) |
| 2 | **OCR** | Sarvam OCR (Kannada+English); <=10 pages one job, >10 pages overlapping 10-page chunks in parallel |
| 3 | **Merge** | Deduplicate overlapping pages, re-join split tables, strip base64 blobs |
| 4 | **Classify** | LLM classifies a bounded OCR prefix and writes a 2–3 sentence summary in the same call; deterministic rules handle known formats |
| 5 | **Persist** | Mark the document ready (status `structured`). No full-document model read happens at upload: the verification examiner reads each document once, in full |

**Then, once** (case level):

| Stage | Work |
|---|---|
| **Finalize** | Recompute case status (`complete` / `partial` / `failed`), release the pipeline lock, and queue the chain build when at least one document is structured |
| **Title chain (Phase A)** | Builds the title chain from history documents (EC, mutation, RTC), extended backward through deed recitals; pauses and asks for the EC when no history document was uploaded |

The dashboard follows `/api/results/{case_id}` through the chain build and shows the property identity, the chain links, and any requested history documents as they arrive.

---

## Project Structure

```
clearTitle/
├-- backend/                        # FastAPI + Celery
│   ├-- main.py                     # FastAPI entrypoint (API + React SPA)
│   ├-- celery_app.py               # Celery config (acks_late, timeouts, retries)
│   ├-- config.py                   # ALL env vars in one place
│   ├-- logger.py                   # Logging utility
│   │
│   ├-- prompts/                    # Versioned LLM prompts (editable .txt files)
│   │   ├-- loader.py               #   load_prompt() helper
│   │   ├-- title_chain_system.txt  #   Phase A: shared chain-agent instructions
│   │   ├-- title_chain_task.txt    #   Phase A: property identity + title chain task
│   │   └-- agent_summary.txt       #   Per-document navigation summaries
│   │
│   ├-- skills/                     # Procedural playbooks the agent loads on demand
│   │   └-- title_chain/skill.md    #   Chain construction rules
│   │
│   ├-- routers/                    # HTTP layer (thin: validate -> call service)
│   │   ├-- auth.py                 #   /register, /login, /me, Google OAuth
│   │   ├-- cases.py                #   upload, process, status, retry, replace, skip, delete
│   │   └-- results.py              #   /results/{id}, /chain, /ocr
│   │
│   ├-- services/                   # Business logic (no HTTP, no Celery)
│   │   ├-- orchestrator.py         #   builds Celery chains + chords
│   │   ├-- document_processor.py   #   classification + full-text extraction
│   │   ├-- cleartitle_agent.py     #   chain-build entrypoint, pauses, summary cache
│   │   ├-- chain_builder.py        #   Phase A: title chain, history-first (Pydantic AI)
│   │   ├-- chain_identity.py       #   stable chain ids + upstream identity checks
│   │   ├-- extract.py              #   OCR retry + structured output paths
│   │   ├-- results.py              #   assemble /api/results payload
│   │   ├-- auth.py                 #   JWT + bcrypt helpers
│   │   └-- schemas/                #   per-doc-type JSON extraction schemas
│   │       ├-- static.py           #     18 hand-written JSON schemas
│   │       └-- generic.py          #     fallback schema for unknown types
│   │
│   ├-- workers/                    # Celery layer (thin task wrappers)
│   │   ├-- tasks.py                #   6 idempotent stage tasks
│   │   ├-- stages.py               #   the actual stage logic (preprocess->persist)
│   │   ├-- stage_adapter.py        #   task -> stage.invoke adapter
│   │   ├-- stage_base.py           #   stage task base class
│   │   ├-- idempotency.py          #   skip-already-done guard
│   │   ├-- finalize.py             #   chord callback: recompute status + queue chain build
│   │   ├-- title_chain_tasks.py    #   queues the chain-build task
│   │   └-- context.py              #   StageContext (dependencies handed to stages)
│   │
│   ├-- domain/state_machine.py     # Stage enum + status->stage mapping (pure logic)
│   │
│   ├-- integrations/               # Adapters to external/plumbing systems
│   │   ├-- llm/                    #   provider-agnostic agent LLM + rate limiter
│   │   ├-- ocr/                    #   sarvam_client, ocr_merger, preprocessor
│   │   ├-- redis/                  #   client, state_store, lock
│   │   └-- storage/                #   file_utils, file_service
│   │
│   ├-- database/
│   │   ├-- connection.py           #  MySQL connection helper
│   │   ├-- migrations.py           #  DDL bootstrap (runs at startup)
│   │   └-- repositories/           #  SQL access (case, document, title_chain, agent, user)
│   │
│   ├-- shared/constants.py         # doc-type + status string constants
│   ├-- shared/ec_ledger.py         # EC page-split row recombinator (read-boundary fix)
│   └-- tests/                      # pytest suite
│
├-- frontend/                       # React SPA (Vite)
│   ├-- src/
│   │   ├-- components/             # Landing-page sections (Navbar, Hero, FAQ, ...)
│   │   ├-- dashboard/              # Verification dashboard (upload, results, history, auth)
│   │   │   ├-- VerificationDashboard.tsx    # Main dashboard with AI pipeline view
│   │   │   ├-- PhaseAResult.tsx              # Title-chain, identity, and source rendering
│   │   │   └-- dashboard.css                # All dashboard styles + pipeline animations
│   │   ├-- api/backend.ts          # API client (JWT auth, typed responses)
│   │   ├-- data/                   # Landing content
│   │   ├-- App.tsx                 # Route: homepage / + dashboard /#/app
│   │   ├-- index.css               # Tailwind theme + brand fonts
│   │   └-- main.tsx
│   ├-- public/                     # Favicon, static assets
│   ├-- server.ts                   # Dev server (Express + Vite middleware)
│   └-- index.html
│
├-- outputs/                        # PDFs + structured outputs (bind-mounted, persists across restarts, NOT in git)
├-- uploads/                        # Original uploaded PDFs (bind-mounted, NOT in git)
├-- backups/                        # Local mysqldump snapshots (NOT in git)
├-- docs/                           # Local-only design notes (gitignored — not in a fresh clone)
├-- docker-compose.yml              # 5 services: api, worker, mysql, redis, phpmyadmin
├-- Dockerfile                      # Multi-stage build (Node 20 builds SPA → Python 3.11 runtime)
├-- requirements.txt                # Python dependencies
└-- .env                            # Environment variables (not committed)
```

---

## LLM Prompts & Skills

Prompts are versioned text files in `backend/prompts/`; procedural playbooks live in `backend/skills/`. Document classification and extraction instructions live in `backend/services/document_processor.py` alongside their rule-based exceptions.

| File | Phase | Purpose |
|---|---|---|
| `title_chain_system.txt` | A | Shared chain-agent reasoning and tool policy |
| `title_chain_task.txt` | A | Property identity + title-chain construction task |
| `agent_summary.txt` | A | Per-document navigation summaries |
| `skills/title_chain/skill.md` | A | Chain-construction playbook (loaded on demand) |

Load helper: `from backend.prompts.loader import load_prompt`

### Agent guardrails (config)

| Setting | Default | Meaning |
|---|---|---|
| `CLEARTITLE_AGENT_PROVIDER` | `openai` | `openai` or `gemini` |
| `CLEARTITLE_AGENT_MODEL` | `GPT-6 Luna` | Chain-agent + document-processor model |
| `CLEARTITLE_CHAIN_MODEL_CALL_BUDGET` | `16` | Model calls per chain build before an extension is required |
| `CLEARTITLE_AGENT_MAX_ATTEMPTS` | `5` | Retry attempts on recoverable provider errors |

---

## Tests

```bash
pytest backend/tests          # Pipeline, contracts, chain gates, repos, API payloads
cd frontend
npm run test                  # 2 tests — chain rendering
npm run lint                  # tsc --noEmit
```

The backend suite locks the chain builder's behavioral contract: the history-first read gate, the full-OCR gate, citation scope, stable chain ids, and the pause-for-EC behavior are all asserted against the real handlers — not mocks of them.

---

## API Costs

| Provider | Model | Cost per case (3 docs) |
|---|---|---|
| **Sarvam AI** | OCR (Vision) | Free tier: 10,000 chars/call |
| **OpenAI-compatible API** | Configured document/agent models | Usage-based; depends on model and document size |
| **Google Gemini (optional)** | Configured agent model | Usage-based; only when selected for the chain agent |

---

## UI Design System

The frontend follows a warm, editorial design system shared by the landing page and dashboard:

- **Palette** — Cream background (`#FFF8F2`), warm stone neutrals, and an orange brand scale (`#ea580c`, `#f97316`, amber `#fbbf24`). Semantic status colors (emerald / amber / rose) for pipeline and chain states.
- **Typography** — Inter (body), Plus Jakarta Sans (display/headings), Instrument Serif (accent italics).
- **Icons** — lucide-react (no emoji).
- **Dashboard** (`/#/app`) — Custom CSS (`dashboard.css`) with CSS-token theming: cards, badges, metric tiles, AI pipeline view with pulsing animations, title-chain timeline with evidence sources, and case history sidebar.

---

## Backup & Rollback

The app is three independent layers. Each needs its own undo — `git` covers only the first.

| Layer | What it is | Recovered by |
|---|---|---|
| **Code** | `backend/`, `frontend/` | `git reset --hard <tag>` |
| **Running build** | Docker image — code **+ baked-in React SPA** | `docker tag` a known image back onto `:latest` |
| **Data** | MySQL `property_ocr_v2`, plus `outputs/` | `mysqldump` / file copy |

`git reset` alone does **not** roll back the running app: the React bundle is compiled into the image, and MySQL is never touched by git.

### What is not in version control

| Path | In git? | Consequence |
|---|---|---|
| `.env` | No (secrets) | Must be backed up separately, stored securely |
| `outputs/` | No | OCR text + structured JSON. **Irreplaceable** — recovering it means re-running paid OCR |
| `uploads/` | No | Original scanned PDFs. Re-uploadable from your own copies |
| `backups/` | No | Local dump snapshots (see below) |

### Take a database snapshot

```bash
mkdir -p backups                                    # Windows PowerShell: New-Item -ItemType Directory backups
docker compose exec -T mysql sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction --skip-lock-tables --no-tablespaces \
  --default-character-set=utf8mb4 --routines --triggers \
  --set-gtid-purged=OFF property_ocr_v2 > /tmp/db.sql'
docker compose cp mysql:/tmp/db.sql "backups/db-$(date +%F-%H%M%S).sql"
```

Why each flag matters:

| Flag | Reason |
|---|---|
| `--single-transaction` | Consistent snapshot of InnoDB tables with **no table locks** — the app keeps serving during the dump |
| `--skip-lock-tables` | Belt-and-braces: never take a global read lock |
| `--default-character-set=utf8mb4` | Kannada party names survive the round-trip |
| no `--databases` | Omits `CREATE DATABASE`/`USE`, so a restore can only touch the database you name explicitly |
| `docker compose cp` | Avoids piping binary through the host shell — PowerShell redirection corrupts UTF-8 |

### Restore a snapshot

> **This replaces the current contents of the target database** (the dump contains `DROP TABLE IF EXISTS`). Stop the app first and keep a fresh snapshot of anything you want to keep.

```bash
# 1. take a snapshot of the CURRENT state before overwriting it
# 2. stop everything that writes to MySQL
docker compose stop api worker

# 3. copy the dump in and restore it
docker compose cp backups/db-2026-10-05-pre-big-change.sql mysql:/tmp/restore.sql
docker compose exec -T mysql sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" \
  -D property_ocr_v2 < /tmp/restore.sql'

docker compose up -d
```

### Roll back the running build

`docker compose up --build` overwrites the `:latest` tag, so a rebuild makes the previously working image unreachable. Name the image **before** you start changing things:

```bash
docker tag cleartitle-api:latest   cleartitle-api:<commit-sha>     # e.g. 68a4aaa
docker tag cleartitle-worker:latest cleartitle-worker:<commit-sha>
```

Later, to return to it without rebuilding:

```bash
docker tag cleartitle-api:<commit-sha>    cleartitle-api:latest
docker tag cleartitle-worker:<commit-sha> cleartitle-worker:latest
docker compose up -d --force-recreate --no-build
```

Always confirm an image really contains the code you think it does — a build from a dirty working tree can look fine while missing your newest commits:

```bash
# Linux / macOS
docker create --name chk cleartitle-api:<commit-sha>
docker cp chk:/app/backend/services/chain_builder.py /tmp/chain_builder.py
git hash-object /tmp/chain_builder.py
git rev-parse <commit-sha>:backend/services/chain_builder.py   # the two hashes must match
docker rm chk
```

```powershell
# Windows PowerShell
docker create --name chk cleartitle-api:<commit-sha>
docker cp chk:/app/backend/services/chain_builder.py "$env:TEMP\chain_builder.py"
git hash-object "$env:TEMP\chain_builder.py"
git rev-parse <commit-sha>:backend/services/chain_builder.py
docker rm chk
```

### Known-good baselines

| Date | Git tag / commit | Notes |
|---|---|---|
| **2026-10-29** | `working-2026-10-29` → `68a4aaa` | Schema v3.0 evidence contract, agent-only selection, compact single-pause requests, PDF fixes. Validated: 148/148 backend, 20/20 frontend, live case 390E1B54 end-to-end, full no-LLM runtime audit. |
| 2026-10-05 | `pre-big-change` → `b1196fc` | Pre-agent pipeline baseline. DB dump: `backups/db-2026-10-05-pre-big-change.sql` |

> `docker-compose.yml` sets no `image:` key, so `docker compose build` always writes to `:latest`. Tag explicitly before a risky change, as above.

---

## Manual Setup (Backend, Without Docker)

<details>
<summary>Click to expand — for local backend development without Docker</summary>

**Prerequisites:** Python 3.11+, MySQL 8.0, Redis

### Step 1 — Create the database

```sql
CREATE DATABASE IF NOT EXISTS property_ocr_v2
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Step 2 — Configure environment

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Update these values to match your local MySQL:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=property_ocr_v2
REDIS_URL=redis://localhost:6379/0
```

### Step 3 — Install dependencies

```bash
python -m venv venv
# Windows:  .\venv\Scripts\Activate.ps1
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

### Step 4 — Run the application (3 terminals)

**Terminal 1 — Redis:** `redis-server`

**Terminal 2 — Celery Worker:**

Windows:
```powershell
.\venv\Scripts\celery.exe -A backend.celery_app worker --loglevel=info --pool=solo --concurrency=1
```
Linux / macOS:
```bash
celery -A backend.celery_app worker --loglevel=info --concurrency=2
```

**Terminal 3 — FastAPI Server:**

Windows:
```powershell
.\venv\Scripts\uvicorn.exe backend.main:app --reload --port 8000
```
Linux / macOS:
```bash
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

</details>

---

## Documentation

- **[AGENTS.md](AGENTS.md)** — working notes for coding agents: layout, commands, and the chain-builder invariants.

---

*Last updated: 29 October 2026*
