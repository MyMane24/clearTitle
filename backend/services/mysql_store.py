"""
MySQL storage — consolidated database connection and operations for `property_ocr_v2`.
All documents go through LLM structurer.
Structured data + verification_notes stored together in JSON columns.
"""

from __future__ import annotations

import json
import os
import threading

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", os.getenv("MYSQL_DATABASE_V2", "property_ocr_v2"))


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
_pool_lock = threading.Lock()

def _get_pool():
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                connector = _mysql_connector()
                _ensure_database(connector)
                try:
                    from mysql.connector.pooling import MySQLConnectionPool
                except ImportError as exc:
                    raise RuntimeError("mysql-connector-python not installed") from exc
                _connection_pool = MySQLConnectionPool(
                    pool_name="property_ocr_pool",
                    pool_size=10,
                    pool_reset_session=True,
                    host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                    password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
                )
    return _connection_pool


class ManagedConnection:
    def __init__(self, pool):
        self.pool = pool
        self.conn = None

    def __enter__(self):
        self.conn = self.pool.get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


def _get_conn():
    pool = _get_pool()
    return ManagedConnection(pool)


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


_tables_initialized = False

def ensure_tables():
    """Run DDL once at startup. Do NOT call from per-request handlers."""
    global _tables_initialized
    if _tables_initialized:
        return
    with _get_conn() as conn:
        cursor = conn.cursor()
        for statement in CREATE_TABLES_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt + ";")
        conn.commit()

        for col_def in [
            ("documents", "stage_started_at", "ALTER TABLE documents ADD COLUMN stage_started_at TIMESTAMP NULL DEFAULT NULL"),
            ("documents", "stage_completed_at", "ALTER TABLE documents ADD COLUMN stage_completed_at TIMESTAMP NULL DEFAULT NULL"),
            ("documents", "trace_id", "ALTER TABLE documents ADD COLUMN trace_id VARCHAR(64) NULL DEFAULT NULL"),
            ("cases", "pipeline_logs", "ALTER TABLE cases ADD COLUMN pipeline_logs JSON NULL DEFAULT NULL"),
        ]:
            table, col, sql = col_def
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                pass

        try:
            cursor.execute("UPDATE documents SET stage_completed_at = updated_at WHERE status IN ('structured', 'skipped') AND stage_completed_at IS NULL")
            conn.commit()
        except Exception:
            pass
    _tables_initialized = True


def _ensure_tables():
    """Deprecated: use ensure_tables() at startup instead."""
    ensure_tables()


# ── Case operations ──────────────────────────────────────────────────────

def init_case(*, case_id: str, total_docs: int) -> None:
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
        values = [*list(fields.values())]

        # Use MySQL JSON_MERGE_PATCH for atomic file_paths merge (no read-modify-write race)
        if file_paths is not None:
            for key, val in file_paths.items():
                set_clause += f", file_paths = JSON_SET(COALESCE(file_paths, '{{}}'), %s, %s)"
                values.extend([f"$.{key}", json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val])

        values.extend([case_id, doc_id])
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


def delete_case(case_id: str) -> None:
    """Delete all records for a single case from database."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in (
            "human_feedback",
            "cross_doc_verifications",
            "documents",
        ):
            try:
                cursor.execute(f"DELETE FROM {table} WHERE case_id = %s", (case_id,))
            except Exception:
                pass
        try:
            cursor.execute("DELETE FROM cases WHERE id = %s", (case_id,))
        except Exception:
            pass
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()


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


def get_document_status(case_id: str, doc_id: str) -> str | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def set_document_stage(case_id: str, doc_id: str, stage) -> None:
    status_str = stage.name.lower()
    with _get_conn() as conn:
        cursor = conn.cursor()
        
        start_stages = {"preprocessing", "ocr_in_progress", "merging", "classifying", "structuring", "persisting"}
        complete_stages = {"preprocessed", "ocr_done", "merged", "classified", "structuring_done", "structured", "skipped"}
        
        sql = "UPDATE documents SET status = %s"
        params = [status_str]
        
        if status_str in start_stages:
            sql += ", stage_started_at = CURRENT_TIMESTAMP"
        elif status_str in complete_stages:
            sql += ", stage_completed_at = CURRENT_TIMESTAMP"
            
        sql += " WHERE case_id = %s AND doc_id = %s"
        params.extend([case_id, doc_id])
        
        cursor.execute(sql, tuple(params))
        conn.commit()


def load_document_paths(case_id: str, doc_id: str) -> dict:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_paths FROM documents WHERE case_id = %s AND doc_id = %s", (case_id, doc_id))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                pass
        return {}


def recompute_case_status(case_id: str) -> None:
    update_case_status(case_id=case_id)


def append_pipeline_log(case_id: str, msg: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        # Acquire lock on the cases row to prevent race conditions from concurrent updates
        cursor.execute("SELECT pipeline_logs FROM cases WHERE id = %s FOR UPDATE", (case_id,))
        row = cursor.fetchone()
        logs = []
        if row and row[0]:
            try:
                logs = json.loads(row[0])
            except Exception:
                logs = []
        if not isinstance(logs, list):
            logs = []
        logs.append(msg)
        logs = logs[-200:]
        cursor.execute(
            "UPDATE cases SET pipeline_logs = %s WHERE id = %s",
            (json.dumps(logs, ensure_ascii=False), case_id)
        )
        conn.commit()


def get_pipeline_logs(case_id: str) -> list[str]:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pipeline_logs FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                logs = json.loads(row[0])
                if isinstance(logs, list):
                    return logs
            except Exception:
                pass
        return []


def get_case_status_payload(case_id: str) -> dict:
    with _get_conn() as conn:
        # 1. Fetch case info
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT status, total_docs, completed_docs, failed_docs, pipeline_logs "
            "FROM cases WHERE id = %s",
            (case_id,)
        )
        case_row = cursor.fetchone()
        if not case_row:
            raise KeyError(f"Case {case_id} not found in DB")
            
        # 2. Fetch documents
        cursor.execute(
            "SELECT doc_id, filename, document_type, status, structured_data, file_paths, error, "
            "page_count, input_tokens, output_tokens, latency_ms, cost_usd, model_used "
            "FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,)
        )
        doc_rows = cursor.fetchall()
        
    # Reconstruct log list
    logs = []
    if case_row.get("pipeline_logs"):
        try:
            logs = json.loads(case_row["pipeline_logs"])
        except Exception:
            pass
            
    # Reconstruct files list
    files = []
    results = []
    errors = []
    
    for d in doc_rows:
        file_paths = {}
        if d.get("file_paths"):
            try:
                file_paths = json.loads(d["file_paths"])
            except Exception:
                pass
                
        # files element
        files.append({
            "doc_id": d["doc_id"],
            "original_name": d["filename"],
            "saved_path": file_paths.get("raw")
        })
        
        # results element (only if status is structured)
        if d["status"] == "structured":
            structured_data = {}
            if d.get("structured_data"):
                try:
                    structured_data = json.loads(d["structured_data"])
                except Exception:
                    pass
            
            doc_type = d.get("document_type") or ""
            safe_type = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())
            results.append({
                "doc_id": d["doc_id"],
                "filename": d["filename"],
                "doc_type": doc_type,
                "status": "complete",
                "structured": structured_data,
                "result_file": f"{d['doc_id']}_{safe_type}.json",
                "total_pages": d["page_count"],
                "chunks_used": 1,  # derived placeholder
                "input_tokens": d["input_tokens"],
                "output_tokens": d["output_tokens"],
                "cost_usd": float(d["cost_usd"]),
                "latency_ms": d["latency_ms"],
                "model_used": d["model_used"],
                "provider": "gemini" if "gemini" in (d["model_used"] or "").lower() else "groq"
            })
            
        # errors element (if failed or classification_failed)
        if d["status"] in ("failed", "classification_failed"):
            action_required = None
            if d["status"] == "classification_failed":
                action_required = "replace_or_skip"
            errors.append({
                "doc_id": d["doc_id"],
                "step": "classify" if d["status"] == "classification_failed" else "pipeline",
                "error": d["error"],
                "action_required": action_required
            })
            
    # Calculate progress
    total = case_row["total_docs"]
    done = case_row["completed_docs"] + case_row["failed_docs"]
    case_status = case_row["status"]
    
    if total > 0:
        progress = min(100, int((done / total) * 90)) if case_status == "processing" else 100
    else:
        progress = 0
        
    return {
        "case_id": case_id,
        "status": case_status,
        "files": files,
        "results": results,
        "errors": errors,
        "progress": progress,
        "log": logs
    }

