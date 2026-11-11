"""Copy one case's rows between the dev DB (3307) and the live backend DB (3306).

Usage:
    venv\\Scripts\\python.exe backend\\scripts\\copy_case_between_dbs.py <case_id> <owner_email>

Copies cases, documents, title_chains, case_results, case_memory and
evidence_requirements rows for the case from MYSQL_PORT_SRC (default 3307)
to MYSQL_PORT_DST (default 3306), replacing any existing rows for that case,
and sets the case owner to the given user account on the destination.
Row counts are printed as proof.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("MYSQL_PORT_SRC", "3307")
os.environ.setdefault("MYSQL_PORT_DST", "3306")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import backend.config as cfg  # noqa: E402
from mysql.connector import connect  # noqa: E402

TABLES = ("cases", "documents", "title_chains", "case_results", "case_memory",
          "evidence_requirements")
CASE_COL = {"cases": "id"}  # everything else keys on case_id


def _conn(port: int):
    return connect(host=cfg.MYSQL_HOST, port=port, user=cfg.MYSQL_USER,
                   password=cfg.MYSQL_PASSWORD, database=cfg.MYSQL_DATABASE,
                   connection_timeout=5)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python copy_case_between_dbs.py <case_id> <owner_email>")
    case_id, email = sys.argv[1], sys.argv[2].strip().lower()

    src, dst = _conn(int(os.environ["MYSQL_PORT_SRC"])), _conn(int(os.environ["MYSQL_PORT_DST"]))
    s_cur, d_cur = src.cursor(dictionary=True), dst.cursor(dictionary=True)

    d_cur.execute("SELECT id, email FROM users WHERE email = %s", (email,))
    user = d_cur.fetchone()
    if not user:
        sys.exit(f"no user {email!r} on destination DB — are you logged in on the backend?")
    print(f"owner: {email} -> user {user['id']}")

    for table in TABLES:
        col = CASE_COL.get(table, "case_id")
        # Destination schema is authoritative: copy only columns it actually
        # has, and let auto-increment columns (e.g. documents.id) regenerate —
        # the two DBs drift and source ids collide with live rows.
        d_cur.execute(f"SHOW COLUMNS FROM {table}")
        dest_cols = d_cur.fetchall()
        copy_cols = [c["Field"] for c in dest_cols
                     if "auto_increment" not in (c.get("Extra") or "")]
        s_cur.execute(f"SELECT * FROM {table} WHERE {col} = %s", (case_id,))
        rows = s_cur.fetchall()
        d_cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (case_id,))
        if not rows:
            print(f"  {table}: 0 rows (nothing to copy)")
            continue
        for row in rows:  # owner is set on the destination, not copied
            if table == "cases":
                row["user_id"] = user["id"]
        placeholders = ", ".join(f"%({c})s" for c in copy_cols)
        d_cur.executemany(
            f"INSERT INTO {table} ({', '.join(copy_cols)}) VALUES ({placeholders})", rows)
        print(f"  {table}: {len(rows)} row(s) copied "
              f"(skipped auto-inc: {sorted(set(r['Field'] for r in dest_cols) - set(copy_cols))})")

    # truthful sidebar count: structured documents
    d_cur.execute(
        "UPDATE cases SET completed_docs = "
        "(SELECT COUNT(*) FROM documents WHERE case_id = %s AND status = 'structured') "
        "WHERE id = %s", (case_id, case_id))
    d_cur.execute("SELECT id, user_id, status, verdict, total_docs, completed_docs "
                  "FROM cases WHERE id = %s", (case_id,))
    print("destination case row:", d_cur.fetchone())
    dst.commit()
    src.close()
    dst.close()
    print("done.")


if __name__ == "__main__":
    main()
