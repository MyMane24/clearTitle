"""
DDL + table bootstrap for the simplified schema.

Tables:
  users                 — auth accounts
  cases                 — pipeline cases (user-scoped)
  documents             — per-doc extraction state (no per-doc verification)
  title_chains          — LLM-built title chain for a case
  verification_results  — LLM field-verification results for a case

Obsolete tables (cross_doc_verifications, human_feedback, llm_calls and the
daily_cost_summary view) are dropped best-effort so an existing DB upgrades
cleanly, as are abandoned columns: documents.verification_notes,
documents.stage_started_at, documents.stage_completed_at, documents.trace_id,
and the unused token/cost/metadata columns on title_chains and
verification_results that are no longer surfaced to any consumer.
"""

from __future__ import annotations

from backend.database.connection import _get_conn

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cases (
    id VARCHAR(32) NOT NULL,
    user_id VARCHAR(32) DEFAULT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    total_docs INT NOT NULL DEFAULT 0,
    completed_docs INT NOT NULL DEFAULT 0,
    failed_docs INT NOT NULL DEFAULT 0,
    pipeline_status VARCHAR(32) DEFAULT NULL,
    verification_status VARCHAR(32) DEFAULT NULL,
    verdict VARCHAR(32) DEFAULT NULL,
    pipeline_logs JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_status (status),
    KEY idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    doc_id VARCHAR(32) NOT NULL,
    doc_index INT NOT NULL DEFAULT 0,
    filename VARCHAR(512) NOT NULL,
    expected_type VARCHAR(32) DEFAULT NULL,
    document_type VARCHAR(128) NOT NULL DEFAULT '',
    page_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    structured_data JSON NULL,
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

CREATE TABLE IF NOT EXISTS title_chains (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    chain JSON NULL,
    source JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_results (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    verdict VARCHAR(32) DEFAULT NULL,
    summary JSON NULL,
    items JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


DROP_OBSOLETE_SQL = [
    "DROP VIEW IF EXISTS daily_cost_summary",
    "DROP TABLE IF EXISTS llm_calls",
    "DROP TABLE IF EXISTS human_feedback",
    "DROP TABLE IF EXISTS cross_doc_verifications",
]


_tables_initialized = False


def ensure_tables():
    """Run DDL once at startup. Do NOT call from per-request handlers."""
    global _tables_initialized
    if _tables_initialized:
        return
    with _get_conn() as conn:
        cursor = conn.cursor()
        for stmt in DROP_OBSOLETE_SQL:
            try:
                cursor.execute(stmt)
                conn.commit()
            except Exception:
                conn.rollback()

        for statement in CREATE_TABLES_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt + ";")
        conn.commit()

        # Best-effort column migrations for pre-existing DBs
        for col_def in [
            ("cases", "user_id", "ALTER TABLE cases ADD COLUMN user_id VARCHAR(32) NULL DEFAULT NULL AFTER id"),
            ("documents", "expected_type", "ALTER TABLE documents ADD COLUMN expected_type VARCHAR(32) NULL DEFAULT NULL"),
        ]:
            _, _, sql = col_def
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()

        # Best-effort removal of abandoned columns from older schemas
        for sql in [
            "ALTER TABLE documents DROP COLUMN verification_notes",
            "ALTER TABLE documents DROP COLUMN stage_started_at",
            "ALTER TABLE documents DROP COLUMN stage_completed_at",
            "ALTER TABLE documents DROP COLUMN trace_id",
            "ALTER TABLE title_chains DROP COLUMN sale_deed_doc_id",
            "ALTER TABLE title_chains DROP COLUMN ec_doc_id",
            "ALTER TABLE title_chains DROP COLUMN input_tokens",
            "ALTER TABLE title_chains DROP COLUMN output_tokens",
            "ALTER TABLE title_chains DROP COLUMN latency_ms",
            "ALTER TABLE title_chains DROP COLUMN cost_usd",
            "ALTER TABLE title_chains DROP COLUMN model_used",
            "ALTER TABLE verification_results DROP COLUMN input_tokens",
            "ALTER TABLE verification_results DROP COLUMN output_tokens",
            "ALTER TABLE verification_results DROP COLUMN latency_ms",
            "ALTER TABLE verification_results DROP COLUMN cost_usd",
            "ALTER TABLE verification_results DROP COLUMN model_used",
        ]:
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()
    _tables_initialized = True


def _ensure_tables():
    """Deprecated: use ensure_tables() at startup instead."""
    ensure_tables()
