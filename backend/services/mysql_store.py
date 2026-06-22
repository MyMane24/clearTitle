"""
MySQL storage for document processing pipeline.
Schema: cases (per case) + case_documents (per file in a case).
"""

from __future__ import annotations

import json
import os

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

CREATE TABLE IF NOT EXISTS verification_reports (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    report_json JSON NULL,
    findings_json JSON NULL,
    human_feedback JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_feedback (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    report_id BIGINT UNSIGNED NOT NULL,
    doc_id VARCHAR(32) NULL,
    original_flag TEXT NOT NULL,
    human_correction TEXT NOT NULL,
    reason TEXT NULL,
    accepted TINYINT(1) NOT NULL DEFAULT 1,
    finding_type VARCHAR(64) NULL,
    embedded TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_case_id (case_id),
    KEY idx_report_id (report_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_training_data (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    input_documents JSON NOT NULL,
    agent_report JSON NOT NULL,
    human_feedback JSON NULL,
    corrected_report JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_case_id (case_id),
    KEY idx_created_at (created_at)
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

def list_cases(limit: int = 50, offset: int = 0) -> list[dict]:
    """Return all cases ordered by most recent first."""
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, status, total_docs, completed_docs, failed_docs,
                   created_at, updated_at
            FROM cases
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

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
        values = [*list(fields.values()), case_id, doc_id]
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


# ── Verification operations ────────────────────────────────────────────────

def create_verification_report(*, case_id: str, report_json: dict) -> int:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO verification_reports
                (case_id, status, report_json, findings_json)
            VALUES (%s, 'completed', %s, %s)
            ON DUPLICATE KEY UPDATE
                status = 'completed',
                report_json = VALUES(report_json),
                findings_json = VALUES(findings_json),
                updated_at = CURRENT_TIMESTAMP
            """,
            (case_id,
             json.dumps(report_json, ensure_ascii=False),
             json.dumps(report_json.get("findings", []), ensure_ascii=False)),
        )
        conn.commit()
        return cursor.lastrowid or 0


def get_verification_report(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, case_id, status, report_json, findings_json,
                   human_feedback, created_at, updated_at
            FROM verification_reports
            WHERE case_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("report_json", "findings_json", "human_feedback"):
            if result.get(field) and isinstance(result[field], str):
                result[field] = json.loads(result[field])
        return result


def update_verification_report(case_id: str, report_json: dict, *,
                                status: str = "reviewed") -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE verification_reports SET
                report_json = %s,
                status = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE case_id = %s
            """,
            (json.dumps(report_json, ensure_ascii=False), status, case_id),
        )
        conn.commit()


def store_feedback(*, case_id: str, report_id: int,
                   feedback_list: list[dict]) -> list[int]:
    ids = []
    with _get_conn() as conn:
        cursor = conn.cursor()
        for fb in feedback_list:
            cursor.execute(
                """
                INSERT INTO verification_feedback
                    (case_id, report_id, doc_id, original_flag,
                     human_correction, reason, accepted, finding_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (case_id, report_id,
                 fb.get("doc_id", ""),
                 fb.get("original_flag", ""),
                 fb.get("human_correction", ""),
                 fb.get("reason", ""),
                 1 if fb.get("accepted", True) else 0,
                 fb.get("finding_type", "")),
            )
            ids.append(cursor.lastrowid or 0)
        conn.commit()
    return ids


def mark_feedback_embedded(feedback_id: int) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE verification_feedback SET embedded = 1 WHERE id = %s",
            (feedback_id,),
        )
        conn.commit()


# ── Training data operations ──────────────────────────────────────────────

def create_training_record(*, case_id: str, input_documents: dict,
                            agent_report: dict) -> int:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO verification_training_data
                (case_id, input_documents, agent_report)
            VALUES (%s, %s, %s)
            """,
            (case_id,
             json.dumps(input_documents, ensure_ascii=False),
             json.dumps(agent_report, ensure_ascii=False)),
        )
        conn.commit()
        return cursor.lastrowid or 0


def update_training_record_with_feedback(
    *, case_id: str, human_feedback: list[dict],
    corrected_report: dict | None = None,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        if corrected_report:
            cursor.execute(
                """
                UPDATE verification_training_data SET
                    human_feedback = %s,
                    corrected_report = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = %s
                ORDER BY id DESC LIMIT 1
                """,
                (json.dumps(human_feedback, ensure_ascii=False),
                 json.dumps(corrected_report, ensure_ascii=False),
                 case_id),
            )
        else:
            cursor.execute(
                """
                UPDATE verification_training_data SET
                    human_feedback = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = %s
                ORDER BY id DESC LIMIT 1
                """,
                (json.dumps(human_feedback, ensure_ascii=False), case_id),
            )
        conn.commit()


def get_training_record(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, case_id, input_documents, agent_report,
                   human_feedback, corrected_report, created_at, updated_at
            FROM verification_training_data
            WHERE case_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("input_documents", "agent_report", "human_feedback", "corrected_report"):
            if result.get(field) and isinstance(result[field], str):
                result[field] = json.loads(result[field])
        return result


def list_training_records(limit: int = 50, offset: int = 0) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, case_id, created_at, updated_at,
                   JSON_EXTRACT(agent_report, '$.verdict') AS verdict,
                   JSON_EXTRACT(agent_report, '$.summary.total_findings') AS total_findings,
                   CASE WHEN human_feedback IS NOT NULL THEN 1 ELSE 0 END AS has_feedback
            FROM verification_training_data
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]
