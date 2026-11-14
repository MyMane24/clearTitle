"""Run the ClearTitle agent end-to-end on DEMO-CLEAN-001 (Phases A + B only).

Phase A (title chain) + Phase B (per-transaction verification) happen inside
run_agent. Phases C/D (consolidation + final report) were removed — this
script stops at the persisted transaction results.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 env var exists on this machine and setdefault would silently target the stale local MySQL

from backend.database.repositories import agent_repo  # noqa: E402
from backend.services.cleartitle_agent import run_agent  # noqa: E402

CASE = "DEMO-CLEAN-001"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def brief(value, keys):
    return {k: value.get(k) for k in keys if isinstance(value, dict)}


def main() -> None:
    print(f"=== running agent on {CASE} (phases A+B) ===", flush=True)
    outcome = run_agent(CASE)
    print("agent outcome:", json.dumps(brief(outcome, (
        "case_id", "status", "overall_status")), default=str))

    results = agent_repo.list_transaction_results(CASE) or []
    print(f"\n=== phase B: {len(results)} persisted transaction results ===")
    for r in results:
        findings = r.get("findings") or []
        print(f"  {r.get('tx_id')} seq={r.get('sequence')} {r.get('status')}"
              f" findings={len(findings)} reqs={len(r.get('required_documents') or [])}")


if __name__ == "__main__":
    main()
