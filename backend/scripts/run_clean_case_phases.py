"""Run the title-chain build (Phase A) on DEMO-CLEAN-001.

Stops at the persisted title chain. Transaction verification is not part of this
application.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 env var exists on this machine and setdefault would silently target the stale local MySQL

from backend.database.repositories import agent_repo  # noqa: E402
from backend.services.cleartitle_agent import run_case_analysis  # noqa: E402

CASE = "DEMO-CLEAN-001"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    print(f"=== building title chain for {CASE} ===", flush=True)
    outcome = run_case_analysis(CASE)
    print("chain outcome:", json.dumps(outcome, default=str))

    chain = agent_repo.get_agent_result(CASE) or {}
    links = chain.get("title_chain") or []
    print(f"\n=== phase A: {len(links)} persisted chain links ===")
    for link in links:
        transaction = link.get("documented_transaction") or {}
        print(f"  {link.get('tx_id')} {transaction.get('transaction_type')}"
              f" {transaction.get('executed_date') or ''}")


if __name__ == "__main__":
    main()
