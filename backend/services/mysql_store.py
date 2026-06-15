"""
MySQL storage for document processing pipeline.
Schema: cases (per case) + case_documents (per file in a case).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "property_ocr")


# ── Connection helpers ──────────────────────────────────────────────────────────

def _mysql_connector():
    try:
        import mysql.connector
    except ImportError as exc:
        raise RuntimeError(
            "mysql-connector-python is not installed. Run pip install -r requirements.txt"
        ) from exc
    return mysql.connector


def _ensure_database(connector) -> None:
    connection = connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        connection.commit()
    finally:
        connection.close()


def _get_conn():
    connector = _mysql_connector()
    _ensure_database(connector)
    return connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )


# ── Table creation ──────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    total_docs INT NOT NULL DEFAULT 0,
    completed_docs INT NOT NULL DEFAULT 0,
    failed_docs INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS case_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    doc_id VARCHAR(32) NOT NULL,
    doc_index INT NOT NULL DEFAULT 0,
    filename VARCHAR(512) NOT NULL,
    document_type VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    retry_count INT NOT NULL DEFAULT 0,
    error TEXT NULL,
    structured_json JSON NULL,
    file_paths JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_doc (case_id, doc_id),
    KEY idx_case_id (case_id),
    KEY idx_status (status),
    KEY idx_document_type (document_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def _ensure_tables():
    with _get_conn() as conn:
        cursor = conn.cursor()
        for statement in CREATE_TABLES_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt + ";")
        conn.commit()


# ── Case-level operations ───────────────────────────────────────────────────────

def init_case(*, case_id: str, total_docs: int) -> None:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cases (id, status, total_docs)
            VALUES (%s, 'uploaded', %s)
            ON DUPLICATE KEY UPDATE
                status = 'uploaded',
                total_docs = VALUES(total_docs),
                completed_docs = 0,
                failed_docs = 0
            """,
            (case_id, total_docs),
        )
        conn.commit()


def update_case_status(*, case_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE cases SET
                completed_docs = (SELECT COUNT(*) FROM case_documents
                    WHERE case_id = %s AND status = 'structured'),
                failed_docs = (SELECT COUNT(*) FROM case_documents
                    WHERE case_id = %s AND status IN ('failed','classification_failed')),
                status = CASE
                    WHEN (SELECT COUNT(*) FROM case_documents
                        WHERE case_id = %s AND status IN ('failed','classification_failed')) > 0
                    THEN 'partial'
                    WHEN (SELECT COUNT(*) FROM case_documents
                        WHERE case_id = %s AND status = 'structured')
                        = total_docs
                    THEN 'complete'
                    ELSE 'processing'
                END
            WHERE id = %s
            """,
            (case_id, case_id, case_id, case_id, case_id),
        )
        conn.commit()


# ── Document-level operations ───────────────────────────────────────────────────

def init_document(
    *,
    case_id: str,
    doc_id: str,
    doc_index: int,
    filename: str,
    file_paths: dict | None = None,
) -> None:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO case_documents
                (case_id, doc_id, doc_index, filename, status, file_paths)
            VALUES (%s, %s, %s, %s, 'uploaded', %s)
            ON DUPLICATE KEY UPDATE
                filename = VALUES(filename),
                doc_index = VALUES(doc_index),
                file_paths = VALUES(file_paths)
            """,
            (case_id, doc_id, doc_index, filename,
             json.dumps(file_paths) if file_paths else None),
        )
        conn.commit()


def update_document_status(
    *,
    case_id: str,
    doc_id: str,
    status: str,
    document_type: str | None = None,
    structured: dict | None = None,
    error: str | None = None,
    file_paths: dict | None = None,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        fields = {"status": status}
        if document_type is not None:
            fields["document_type"] = document_type
        if structured is not None:
            fields["structured_json"] = json.dumps(structured, ensure_ascii=False)
        if error is not None:
            fields["error"] = error
        if file_paths is not None:
            existing = _get_doc_file_paths(cursor, case_id, doc_id)
            merged = {**(existing or {}), **file_paths}
            fields["file_paths"] = json.dumps(merged, ensure_ascii=False)

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [case_id, doc_id]
        cursor.execute(
            f"UPDATE case_documents SET {set_clause} "
            "WHERE case_id = %s AND doc_id = %s",
            values,
        )
        conn.commit()


def increment_retry(*, case_id: str, doc_id: str, error: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE case_documents SET
                retry_count = retry_count + 1,
                status = 'failed',
                error = %s
            WHERE case_id = %s AND doc_id = %s
            """,
            (error, case_id, doc_id),
        )
        conn.commit()


def _get_doc_file_paths(cursor, case_id: str, doc_id: str) -> dict | None:
    cursor.execute(
        "SELECT file_paths FROM case_documents WHERE case_id = %s AND doc_id = %s",
        (case_id, doc_id),
    )
    row = cursor.fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return None


# ── Query operations ────────────────────────────────────────────────────────────

def get_case_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT doc_id, doc_index, filename, document_type, status,
                   retry_count, error, structured_json, file_paths
            FROM case_documents
            WHERE case_id = %s
            ORDER BY doc_index ASC
            """,
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_case_bundle(case_id: str) -> list[dict]:
    """Return only structured docs for verification engine."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT doc_id, doc_index, filename, document_type, structured_json
            FROM case_documents
            WHERE case_id = %s AND status = 'structured'
            ORDER BY doc_index ASC
            """,
            (case_id,),
        )
        result = []
        for row in cursor.fetchall():
            doc = dict(row)
            if doc.get("structured_json") and isinstance(doc["structured_json"], str):
                doc["structured_json"] = json.loads(doc["structured_json"])
            result.append(doc)
        return result


def get_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT doc_id, doc_index, filename, document_type, error, retry_count
            FROM case_documents
            WHERE case_id = %s AND status IN ('failed', 'pending_retry')
            ORDER BY doc_index ASC
            """,
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_classification_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT doc_id, doc_index, filename, document_type, error
            FROM case_documents
            WHERE case_id = %s AND status = 'classification_failed'
            ORDER BY doc_index ASC
            """,
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def replace_document(
    *,
    case_id: str,
    doc_id: str,
    filename: str,
    file_paths: dict,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE case_documents SET
                filename = %s,
                file_paths = %s,
                status = 'failed',
                retry_count = 0,
                error = 'Document replaced — pending retry',
                document_type = '',
                structured_json = NULL
            WHERE case_id = %s AND doc_id = %s
            """,
            (filename, json.dumps(file_paths, ensure_ascii=False),
             case_id, doc_id),
        )
        conn.commit()


def skip_document(*, case_id: str, doc_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE case_documents SET
                status = 'skipped',
                retry_count = 0,
                error = NULL
            WHERE case_id = %s AND doc_id = %s
            """,
            (case_id, doc_id),
        )
        conn.commit()
