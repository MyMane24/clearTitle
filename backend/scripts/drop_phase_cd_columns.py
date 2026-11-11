# -*- coding: utf-8 -*-
"""Drop Phase C/D columns from case_results and strip phase_c from agent memory."""
import json
import os
import sys

os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 exists on this machine
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.database.connection import _get_conn  # noqa: E402

DROPS = [
    "ALTER TABLE case_results DROP COLUMN final_report",
    "ALTER TABLE case_results DROP COLUMN final_reports",
    "ALTER TABLE case_results DROP COLUMN property_findings",
]

with _get_conn() as conn:
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM case_results")
    cols = [r[0] for r in cursor.fetchall()]
    print("case_results columns before:", cols)

    for sql in DROPS:
        col = sql.split()[-1]
        if col in cols:
            try:
                cursor.execute(sql)
                conn.commit()
                print("dropped:", col)
            except Exception as e:
                conn.rollback()
                print("FAILED", col, "->", e)
        else:
            print("already absent:", col)

    cursor.execute("SHOW COLUMNS FROM case_results")
    print("case_results columns after: ", [r[0] for r in cursor.fetchall()])

    # Strip the phase_c key from every persisted agent memory blob.
    cursor.execute("SELECT case_id, case_memory FROM case_memory")
    rows = cursor.fetchall()
    changed = 0
    for case_id, raw in rows:
        try:
            mem = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if isinstance(mem, dict) and "phase_c" in mem:
            mem.pop("phase_c")
            cursor.execute(
                "UPDATE case_memory SET case_memory = %s WHERE case_id = %s",
                (json.dumps(mem, default=str), case_id),
            )
            changed += 1
            print("stripped phase_c from memory:", case_id)
    conn.commit()
    print(f"memory rows scanned: {len(rows)}, updated: {changed}")
