"""User account persistence."""

from __future__ import annotations

from backend.database.connection import _get_conn


def create_user(*, user_id: str, email: str, password_hash: str, full_name: str | None = None) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
            (user_id, email, password_hash, full_name),
        )
        conn.commit()


def get_user_by_email(email: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, email, password_hash, full_name, created_at FROM users WHERE email = %s", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, email, full_name, created_at FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
