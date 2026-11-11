"""Attach a case to a user account (ops tool).

Usage:
    venv\\Scripts\\python.exe backend\\scripts\\link_case_to_user.py <case_id> <email>

Links the case (sets cases.user_id) so it appears in that user's dashboard
Case History, and fixes completed_docs to the real structured-doc count.
Refuses unknown emails and already-owned cases.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ["MYSQL_PORT"] = "3307"  # hard-set: a global MYSQL_PORT=3306 env var exists on this machine and setdefault would silently target the stale local MySQL
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.database.connection import _get_conn  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python link_case_to_user.py <case_id> <email>")
    case_id, email = sys.argv[1], sys.argv[2].strip().lower()

    with _get_conn() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, email FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user:
            sys.exit(f"no user with email {email!r} — register it on the frontend first")
        cur.execute("SELECT id, user_id, completed_docs FROM cases WHERE id = %s", (case_id,))
        case = cur.fetchone()
        if not case:
            sys.exit(f"case {case_id!r} not found")
        if case["user_id"] and case["user_id"] != user["id"]:
            sys.exit(f"case {case_id!r} already belongs to another user")
        cur.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE case_id = %s AND status = 'structured'",
            (case_id,))
        structured = cur.fetchone()["n"]
        cur.execute(
            "UPDATE cases SET user_id = %s, completed_docs = %s WHERE id = %s",
            (user["id"], structured, case_id))
        conn.commit()
        print(f"linked {case_id} -> {email} (user {user['id']}); "
              f"completed_docs = {structured}")


if __name__ == "__main__":
    main()
