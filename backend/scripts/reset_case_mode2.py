"""Mode-2 case reset: back up + wipe derived case state, keep the documents.

Explicitly NOT touching: `documents` rows (uploaded evidence, OCR, summaries).
Wiped (after a JSON backup to backups/): title_chains, case_results
(verification history + findings container + reports), case_memory — exactly
the state a from-zero Phase A→B→C run must not reuse.
Run with the dev DB: set MYSQL_PORT=3307 before starting python.
"""
import json
import os
import sys
from pathlib import Path

os.environ["MYSQL_PORT"] = os.environ.get("RESET_DB_PORT") or "3307"  # dev DB contract
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import backend.config as cfg  # noqa: E402  (env must be set before this import)

from mysql.connector import connect  # noqa: E402

CASE = sys.argv[1] if len(sys.argv) > 1 else "8A14D132"
TABLES = ("title_chains", "case_results", "case_memory")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = connect(host=cfg.MYSQL_HOST, port=int(cfg.MYSQL_PORT), user=cfg.MYSQL_USER,
               password=cfg.MYSQL_PASSWORD, database=cfg.MYSQL_DATABASE,
               connection_timeout=5)
cur = conn.cursor(dictionary=True)

backup, counts = {}, {}
for table in TABLES:
    cur.execute(f"SELECT * FROM {table} WHERE case_id=%s", (CASE,))
    backup[table] = cur.fetchall()
    counts[table] = len(backup[table])

out = Path(__file__).resolve().parents[2] / "backups" / f"case_{CASE}_reset.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(backup, default=str, indent=1), encoding="utf-8")
print("backup written:", out, f"({out.stat().st_size} bytes)")
print("rows backed up:", counts)
assert out.stat().st_size > 500, "backup suspiciously small — aborting without deletes"

for table in TABLES:
    cur.execute(f"DELETE FROM {table} WHERE case_id=%s", (CASE,))
conn.commit()
print("deleted. verifying zero rows:")
for table in TABLES:
    cur.execute(f"SELECT COUNT(*) n FROM {table} WHERE case_id=%s", (CASE,))
    print("  ", table, "=", cur.fetchone()["n"])
cur.execute("SELECT COUNT(*) n FROM documents WHERE case_id=%s", (CASE,))
print("documents preserved:", cur.fetchone()["n"])
conn.close()
