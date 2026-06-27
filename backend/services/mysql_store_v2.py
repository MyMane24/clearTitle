"""
MySQL storage V2 — fresh database `property_ocr_v2` with unified schema.
All documents go through LLM structurer (no custom parsers).
Structured data + verification_notes stored together in JSON columns.
"""

from __future__ import annotations

import json
import os

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE_V2", "property_ocr_v2")


def _mysql_connector():
    try:
        import mysql.connector
    except ImportError as exc:
        raise RuntimeError("mysql-connector-python not installed") from exc
    return mysql.connector


def _ensure_database(connector):
    connection = connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
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


_connection_pool = None

def _get_pool():
    global _connection_pool
    if _connection_pool is None:
        connector = _mysql_connector()
        _ensure_database(connector)
        try:
            from mysql.connector.pooling import MySQLConnectionPool
        except ImportError as exc:
            raise RuntimeError("mysql-connector-python not installed") from exc
        _connection_pool = MySQLConnectionPool(
            pool_name="property_ocr_v2_pool",
            pool_size=10,
            pool_reset_session=True,
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
    return _connection_pool


def _get_conn():
    pool = _get_pool()
    return pool.get_connection()


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS cases (
    id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    total_docs INT NOT NULL DEFAULT 0,
    completed_docs INT NOT NULL DEFAULT 0,
    failed_docs INT NOT NULL DEFAULT 0,
    pipeline_status VARCHAR(32) DEFAULT NULL,
    verification_status VARCHAR(32) DEFAULT NULL,
    verdict VARCHAR(32) DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    doc_id VARCHAR(32) NOT NULL,
    doc_index INT NOT NULL DEFAULT 0,
    filename VARCHAR(512) NOT NULL,
    document_type VARCHAR(128) NOT NULL DEFAULT '',
    page_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    structured_data JSON NULL,
    verification_notes JSON NULL,
    file_paths JSON NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10,6) NOT NULL DEFAULT 0,
    model_used VARCHAR(64) DEFAULT '',
    raw_ocr_path VARCHAR(512) DEFAULT NULL,
    error TEXT NULL,
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_doc (case_id, doc_id),
    KEY idx_case_id (case_id),
    KEY idx_status (status),
    KEY idx_document_type (document_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cross_doc_verifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    verdict VARCHAR(32) DEFAULT NULL,
    findings JSON NULL,
    final_report TEXT NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10,6) NOT NULL DEFAULT 0,
    model_used VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

 CREATE TABLE IF NOT EXISTS human_feedback (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    finding_id VARCHAR(64) DEFAULT NULL,
    finding_type VARCHAR(64) DEFAULT NULL,
    original_severity VARCHAR(16) DEFAULT NULL,
    corrected_severity VARCHAR(16) DEFAULT NULL,
    accepted TINYINT(1) NOT NULL DEFAULT 1,
    reason TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

 CREATE TABLE IF NOT EXISTS llm_calls (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) DEFAULT NULL,
    doc_id VARCHAR(32) DEFAULT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT '',
    model VARCHAR(64) NOT NULL DEFAULT '',
    doc_type VARCHAR(64) DEFAULT '',
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cached_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10,8) NOT NULL DEFAULT 0,
    retry_count INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'success',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_created_at (created_at),
    KEY idx_provider_model (provider, model),
    KEY idx_doc_type (doc_type),
    KEY idx_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

 CREATE OR REPLACE VIEW daily_cost_summary AS
    SELECT
        DATE(created_at) AS call_date,
        provider,
        model,
        COUNT(*) AS call_count,
        SUM(input_tokens) AS total_input_tokens,
        SUM(output_tokens) AS total_output_tokens,
        SUM(cached_tokens) AS total_cached_tokens,
        SUM(cost_usd) AS total_cost_usd,
        AVG(latency_ms) AS avg_latency_ms,
        SUM(CASE WHEN retry_count > 0 THEN 1 ELSE 0 END) AS retry_count
    FROM llm_calls
    GROUP BY DATE(created_at), provider, model;

"""


def _ensure_tables():
    with _get_conn() as conn:
        cursor = conn.cursor()
        for statement in CREATE_TABLES_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt + ";")
        conn.commit()


# ── Case operations ──────────────────────────────────────────────────────

def init_case(*, case_id: str, total_docs: int) -> None:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cases (id, status, total_docs) VALUES (%s, 'uploaded', %s) "
            "ON DUPLICATE KEY UPDATE status='uploaded', total_docs=VALUES(total_docs), "
            "completed_docs=0, failed_docs=0",
            (case_id, total_docs),
        )
        conn.commit()


def update_case_status(*, case_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cases SET
                completed_docs = (SELECT COUNT(*) FROM documents
                    WHERE case_id = %s AND status = 'structured'),
                failed_docs = (SELECT COUNT(*) FROM documents
                    WHERE case_id = %s AND status IN ('failed','classification_failed')),
                status = CASE
                    WHEN (SELECT COUNT(*) FROM documents
                        WHERE case_id = %s AND status IN ('failed','classification_failed')) > 0
                    THEN 'partial'
                    WHEN (SELECT COUNT(*) FROM documents
                        WHERE case_id = %s AND status = 'structured') = total_docs
                    THEN 'complete'
                    ELSE 'processing'
                END
            WHERE id = %s
        """, (case_id, case_id, case_id, case_id, case_id))
        conn.commit()


def list_cases(limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, status, total_docs, completed_docs, failed_docs, "
            "verification_status, verdict, created_at, updated_at "
            "FROM cases ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]


# ── Document operations ──────────────────────────────────────────────────

def init_document(*, case_id: str, doc_id: str, doc_index: int, filename: str, file_paths: dict | None = None) -> None:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor()
        file_paths_str = json.dumps(file_paths, ensure_ascii=False) if file_paths else None
        cursor.execute(
            "INSERT INTO documents (case_id, doc_id, doc_index, filename, status, file_paths) "
            "VALUES (%s, %s, %s, %s, 'uploaded', %s) "
            "ON DUPLICATE KEY UPDATE filename=VALUES(filename), doc_index=VALUES(doc_index), "
            "file_paths=COALESCE(VALUES(file_paths), file_paths)",
            (case_id, doc_id, doc_index, filename, file_paths_str),
        )
        conn.commit()


def update_document_status(
    *,
    case_id: str,
    doc_id: str,
    status: str,
    document_type: str | None = None,
    structured_data: dict | None = None,
    verification_notes: list | None = None,
    file_paths: dict | None = None,
    error: str | None = None,
    page_count: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0,
    model_used: str = "",
    raw_ocr_path: str | None = None,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        fields = {"status": status}
        if document_type is not None:
            fields["document_type"] = document_type
        if structured_data is not None:
            fields["structured_data"] = json.dumps(structured_data, ensure_ascii=False)
        if verification_notes is not None:
            fields["verification_notes"] = json.dumps(verification_notes, ensure_ascii=False)
        if file_paths is not None:
            fields["file_paths"] = json.dumps(file_paths, ensure_ascii=False)
        if error is not None:
            fields["error"] = error
        if page_count:
            fields["page_count"] = page_count
        if input_tokens:
            fields["input_tokens"] = input_tokens
        if output_tokens:
            fields["output_tokens"] = output_tokens
        if latency_ms:
            fields["latency_ms"] = latency_ms
        if cost_usd:
            fields["cost_usd"] = cost_usd
        if model_used:
            fields["model_used"] = model_used
        if raw_ocr_path:
            fields["raw_ocr_path"] = raw_ocr_path

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = [*list(fields.values()), case_id, doc_id]
        cursor.execute(
            f"UPDATE documents SET {set_clause} WHERE case_id = %s AND doc_id = %s",
            values,
        )
        conn.commit()


def get_case_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, page_count, status, "
            "structured_data AS structured_json, verification_notes, file_paths, input_tokens, output_tokens, "
            "latency_ms, cost_usd, model_used, raw_ocr_path, error, created_at "
            "FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,),
        )
        result = []
        for row in cursor.fetchall():
            doc = dict(row)
            for field in ("structured_json", "verification_notes", "file_paths"):
                if doc.get(field) and isinstance(doc[field], str):
                    doc[field] = json.loads(doc[field])
            result.append(doc)
        return result


def get_case_bundle(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, page_count, "
            "structured_data AS structured_json, verification_notes, "
            "input_tokens, output_tokens, latency_ms, cost_usd, model_used "
            "FROM documents WHERE case_id = %s AND status = 'structured' "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        result = []
        for row in cursor.fetchall():
            doc = dict(row)
            for field in ("structured_json", "verification_notes"):
                if doc.get(field) and isinstance(doc[field], str):
                    doc[field] = json.loads(doc[field])
            result.append(doc)
        return result


def increment_retry(*, case_id: str, doc_id: str, error: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET retry_count = retry_count + 1, "
            "status = 'failed', error = %s "
            "WHERE case_id = %s AND doc_id = %s",
            (error, case_id, doc_id),
        )
        conn.commit()


def get_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, error, retry_count "
            "FROM documents WHERE case_id = %s AND status IN ('failed', 'pending_retry') "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


# ── Cross-doc verification ───────────────────────────────────────────────

def save_cross_doc_verification(*, case_id: str, verdict: str | None = None,
                                 findings: list | None = None,
                                 final_report: str | None = None,
                                 input_tokens: int = 0, output_tokens: int = 0,
                                 latency_ms: int = 0, cost_usd: float = 0,
                                 model_used: str = "") -> None:
    _ensure_tables()
    with _get_conn() as conn:
        cursor = conn.cursor()
        fields = {"status": "completed"}
        if verdict is not None:
            fields["verdict"] = verdict
        if findings is not None:
            fields["findings"] = json.dumps(findings, ensure_ascii=False)
        if final_report is not None:
            fields["final_report"] = final_report
        if input_tokens:
            fields["input_tokens"] = input_tokens
        if output_tokens:
            fields["output_tokens"] = output_tokens
        if latency_ms:
            fields["latency_ms"] = latency_ms
        if cost_usd:
            fields["cost_usd"] = cost_usd
        if model_used:
            fields["model_used"] = model_used

        update_clause = ", ".join(f"{k} = VALUES({k})" for k in fields)
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["%s"] * len(fields))
        values = list(fields.values())
        cursor.execute(
            f"INSERT INTO cross_doc_verifications (case_id, {cols}) "
            f"VALUES (%s, {placeholders}) "
            f"ON DUPLICATE KEY UPDATE {update_clause}",
            (case_id, *values),
        )
        if verdict is not None:
            cursor.execute(
                "UPDATE cases SET verdict = %s, verification_status = 'completed' WHERE id = %s",
                (verdict, case_id)
            )
        conn.commit()


def get_cross_doc_verification(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM cross_doc_verifications WHERE case_id = %s ORDER BY id DESC LIMIT 1",
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        if result.get("findings") and isinstance(result["findings"], str):
            result["findings"] = json.loads(result["findings"])
        return result


# ── Human feedback ───────────────────────────────────────────────────────

def store_feedback(*, case_id: str, feedback_list: list[dict]) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        for fb in feedback_list:
            cursor.execute(
                "INSERT INTO human_feedback (case_id, finding_id, finding_type, "
                "original_severity, corrected_severity, accepted, reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (case_id, fb.get("finding_id"), fb.get("finding_type"),
                 fb.get("original_severity"), fb.get("corrected_severity"),
                 1 if fb.get("accepted", True) else 0, fb.get("reason")),
            )
        conn.commit()


# ── LLM Call logging ────────────────────────────────────────────────────

def log_llm_call(*, case_id: str = "", doc_id: str = "", provider: str = "",
                  model: str = "", doc_type: str = "", input_tokens: int = 0,
                  output_tokens: int = 0, cached_tokens: int = 0,
                  latency_ms: int = 0, cost_usd: float = 0,
                  retry_count: int = 0, status: str = "success") -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO llm_calls (case_id, doc_id, provider, model, doc_type, "
            "input_tokens, output_tokens, cached_tokens, latency_ms, cost_usd, retry_count, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (case_id, doc_id, provider, model, doc_type, input_tokens, output_tokens,
             cached_tokens, latency_ms, cost_usd, retry_count, status),
        )
        conn.commit()


def get_daily_cost_summary(days: int = 7) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                DATE(created_at) AS call_date,
                provider,
                model,
                doc_type,
                COUNT(*) AS call_count,
                SUM(input_tokens) AS total_input_tokens,
                SUM(output_tokens) AS total_output_tokens,
                SUM(cached_tokens) AS total_cached_tokens,
                SUM(cost_usd) AS total_cost_usd,
                AVG(latency_ms) AS avg_latency_ms
            FROM llm_calls
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(created_at), provider, model, doc_type
            ORDER BY call_date DESC, total_cost_usd DESC
        """, (days,))
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("total_cost_usd") is not None:
                d["total_cost_usd"] = float(d["total_cost_usd"])
            if d.get("avg_latency_ms") is not None:
                d["avg_latency_ms"] = float(d["avg_latency_ms"])
            result.append(d)
        return result


def get_quota_tracking() -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                provider,
                model,
                DATE(created_at) AS call_date,
                COUNT(*) AS request_count,
                SUM(input_tokens + output_tokens) AS total_tokens
            FROM llm_calls
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            GROUP BY provider, model, DATE(created_at)
            ORDER BY provider, model
        """)
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("total_tokens") is not None:
                d["total_tokens"] = int(d["total_tokens"])
            result.append(d)
        return result


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
            "UPDATE documents SET "
            "filename = %s, "
            "file_paths = %s, "
            "status = 'failed', "
            "retry_count = 0, "
            "error = 'Document replaced — pending retry', "
            "document_type = '', "
            "structured_data = NULL, "
            "verification_notes = NULL "
            "WHERE case_id = %s AND doc_id = %s",
            (filename, json.dumps(file_paths, ensure_ascii=False),
             case_id, doc_id),
        )
        conn.commit()


def skip_document(*, case_id: str, doc_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET "
            "status = 'skipped', "
            "retry_count = 0, "
            "error = NULL "
            "WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        conn.commit()


def get_classification_failed_documents(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, error "
            "FROM documents "
            "WHERE case_id = %s AND status = 'classification_failed' "
            "ORDER BY doc_index ASC",
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def clear_all_tables() -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        try:
            cursor.execute("TRUNCATE TABLE human_feedback")
        except Exception:
            pass
        try:
            cursor.execute("TRUNCATE TABLE cross_doc_verifications")
        except Exception:
            pass
        try:
            cursor.execute("TRUNCATE TABLE documents")
        except Exception:
            pass
        try:
            cursor.execute("TRUNCATE TABLE cases")
        except Exception:
            pass
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
