# Langfuse Observability — Implementation Plan

Goal: capture every **LLM call** (prompt, response, model, tokens, latency, cost,
status) + **pipeline/API spans**, with **prompt versioning**, and view it all in a
Langfuse dashboard — running self-hosted next to the existing Docker stack.

Based on real code audit:
- Python **3.12** (Langfuse SDK ok)
- Stack is Docker: `api`, `worker`, `mysql`, `redis` (+ phpMyAdmin)
- **3 LLM call sites** to instrument:
  1. `backend/integrations/llm/analysis_executor.py` — case-level (title chain + verification), Gemini
  2. `backend/integrations/llm/gemini_executor.py` — per-doc structuring (extraction), Gemini
  3. `backend/integrations/llm/groq_executor.py` — per-doc structuring fallback, Groq
- Prompts all load via `backend/prompts/loader.py` (`load_prompt` / `load_schema`)
- Existing `LLMCallTracker` already writes numeric metrics to Redis `llm_call_log` (keep it — Langfuse adds request/response + UI on top)

---

## 1. Add Langfuse as a Docker service

Add to `docker-compose.yml` a `langfuse` service (postgres-backed). Langfuse self-hosts
as: `langfuse/langfuse` image + a local **Postgres**. Two services total.

**Docker Compose additions:**
```yaml
  langfuse-db:
    image: postgres:16
    environment:
      POSTGRES_USER: ${LANGFUSE_DB_USER:-langfuse}
      POSTGRES_PASSWORD: ${LANGFUSE_DB_PASSWORD:-langfuse_pass}
      POSTGRES_DB: ${LANGFUSE_DB_NAME:-langfuse}
    volumes:
      - langfuse_db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 5s
      timeout: 3s
      retries: 10

  langfuse:
    image: langfuse/langfuse:2
    restart: unless-stopped
    depends_on:
      langfuse-db:
        condition: service_healthy
      mysql:          # optional, only if storing traces in your MySQL; otherwise skip
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse_pass@langfuse-db:5432/langfuse
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET:-changeme_in_prod}
      SALT: ${LANGFUSE_SALT:-changeme_in_prod}
      ENCRYPTION_KEY: ${LANGFUSE_ENCRYPTION_KEY:-changeme_in_prod}
    ports:
      - "3000:3000"
```

Named volume: `langfuse_db:`

> Note: you only need ONE of (a) Langfuse's own Postgres here, or (b) reusing your
> existing MySQL. Langfuse officially supports PostgreSQL out of the box — we use its
> own small Postgres so we don't overload `property_ocr_v2`. MySQL support exists but
> Postgres is the supported path.

**Access:** Langfuse UI at `http://localhost:3000`. First-login creates the project.

---

## 2. Instruments vs manual wrapping — decision

Langfuse has a Python SDK `langfuse` with TWO trigger modes:

1. **Decorators / context managers** (preferred here — explicit, per-call, easy to
   add metadata like `prompt_version`, `case_id`, `doc_type`).
2. **Instrumentation hooks** (e.g. `@observe()`) — good for FastAPI/pipeline spans.

We use **manual `@observe()` decorators + `langfuse_context`/Handler** at the 3 LLM
call sites so we can attach `case_id`, `doc_type`, and `prompt_version` per span.

---

## 3. Dependency

Add to `requirements.txt`:
```
langfuse>=2.0
```

Env vars (`.env` / `.env.example`):
```
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://...  # or http://langfuse:3000 inside Docker network
```

> The SDK picks these up via `Langfuse()` defaults. Inside Docker, `api`/`worker`
> reach Langfuse at `http://langfuse:3000`.

---

## 4. Prompt versioning

Prompt files live in `backend/prompts/`. Add a stable **version identifier** derived
from the file content hash so a trace records exactly which prompt revision was used.

Modify `backend/prompts/loader.py`:
```python
from pathlib import Path
import hashlib

_PROMPTS_DIR = Path(__file__).parent

def _version(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:8]

def load_prompt(name: str) -> tuple[str, str]:
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8"), _version(path)

def load_schema(name: str) -> tuple[dict, str]:
    path = _PROMPTS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, _version(path)
```

> ⚠️ `load_prompt`/`load_schema` currently return strings/dicts directly and are called
> in several places. **Changing the return shape to a tuple is a breaking change across
> every caller.** Two options:
> - **(A, recommended)** Keep `load_prompt`/`load_schema` as-is, add new helpers
>   `load_prompt_observed(name) -> (text, version)` used only at the 3 instrumented
>   sites. No ripple.
> - (B) Change the signature everywhere (more churn, touches all prompt consumers).
>
> We go with **(A): add `load_prompt_observed` / `load_schema_observed`**, leaving
> existing callers untouched.

Each trace span then tags `prompt_version: <hash>`, `prompt_name: <name>`. In the
Langfuse UI you can then compare traces across prompt versions and see which version
produced which response.

---

## 5. Instrumentation — the 3 call sites

### 5a. `analysis_executor.py` — `run_analysis()` (title chain + verification)

Wrap the single `client.models.generate_content` call and the JSON parse with an
`@observe()` span. Capture full prompt + response + metadata.

```python
from langfuse.decorators import observe, langfuse_context
from backend.prompts.loader import load_prompt_observed

@observe(name="analysis_executor")
def run_analysis(prompt: str, *, task: str, response_schema: dict) -> dict:
    ...
    langfuse_context.update_current_trace(
        input=prompt,
        output=raw_response,
        metadata={
            "task": task,
            "model": model,
            "provider": provider,
            "latency_ms": latency_ms,
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "prompt_system_version": <version of analysis_system.txt>,
        },
    )
```

### 5b. `gemini_executor.py` — `structure_document_with_gemini()` (structuring)

Same pattern. Capture `input` (the OCR content block) or a trimmed version, `output`
(structured JSON), and metadata: `doc_type`, `model`, `prompt_version`
(`gemini_system` / `gemini_user` versions), tokens, latency, cost.

### 5c. `groq_executor.py` — Groq structuring fallback

Same pattern with Groq. `provider: "groq"`.

---

## 6. What gets captured per LLM call (summary)

| Field | Source |
|---|---|
| Prompt (system+user) | `input=` on the observed span |
| Response text | `output=` |
| Model / provider | already computed (`model`, `provider`) |
| Tokens (in/out/cached) | `usage_metadata` |
| Latency | `time.time()` diff (already computed) |
| Cost | already computed |
| Status / error | span exception / status |
| `prompt_version` | new loader hash |
| `case_id`, `doc_type`, `task` | metadata |

Existing `LLMCallTracker` → Redis stays for the quick numeric view; Langfuse is the
rich request/response + versioned store.

---

## 7. Backfill / ack of any existing data

The Redis `llm_call_log` already holds historic numeric metrics but **not** prompt
text. Langfuse starts empty going forward. Optional one-off: a small script to push
`llm_call_log` entries into Langfuse as traces (metadata only). **Not required for MVP.**

---

## 8. Files touched (summary)

| File | Change |
|---|---|
| `docker-compose.yml` | add `langfuse` + `langfuse-db` services + volume |
| `.env` / `.env.example` | `LANGFUSE_*` keys, `NEXTAUTH_SECRET`, etc. |
| `requirements.txt` | `langfuse>=2.0` |
| `backend/prompts/loader.py` | add `load_prompt_observed`/`load_schema_observed` (non-breaking) |
| `backend/integrations/llm/analysis_executor.py` | `@observe` + metadata |
| `backend/integrations/llm/gemini_executor.py` | `@observe` + metadata |
| `backend/integrations/llm/groq_executor.py` | `@observe` + metadata |

---

## 9. Not in scope (for now)

- **Frontend** metrics (you chose backend/pipeline).
- Full **tracing** of every Celery stage (preprocess/OCR/merge/classify/persist) as
  separate fine-grained spans — MVP instruments the 3 LLM call sites; stage-level can
  be added later with `@observe()` on each stage.
- Persisting Langfuse traces into your MySQL `property_ocr_v2` (separate Postgres used).

---

## 10. Verification

```bash
docker compose up -d --build api worker langfuse langfuse-db
# open http://localhost:3000 → create project → see a new trace keyed by prompt_version on each case run
```
Then run one case through the pipeline and confirm traces appear with prompt/response/
tokens/latency/cost and the prompt version tag.

---

*Plan prepared 2 Sep 2026. Not yet implemented — pending review.*
