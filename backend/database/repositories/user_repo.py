"""User account persistence."""

from __future__ import annotations

import uuid

from backend.database.connection import _get_conn

# Not a valid bcrypt hash: password login can never succeed for OAuth-only users.
_OAUTH_SENTINEL_HASH = "!google-oauth"


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


def get_or_create_user_by_email(email: str, full_name: str | None = None) -> dict:
    """Find a user by email, creating an OAuth-only account if none exists."""
    existing = get_user_by_email(email)
    if existing:
        return existing
    user_id = uuid.uuid4().hex
    create_user(
        user_id=user_id,
        email=email,
        password_hash=_OAUTH_SENTINEL_HASH,
        full_name=full_name,
    )
    return get_user_by_email(email) or {
        "id": user_id,
        "email": email,
        "full_name": full_name,
    }
