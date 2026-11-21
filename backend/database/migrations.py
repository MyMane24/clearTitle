"""
DDL + table bootstrap for the simplified schema.

Tables:
  users                 — auth accounts
  cases                 — pipeline cases (user-scoped)
  documents             — per-doc extraction state (no per-doc verification)
  title_chains          — Phase A property identity, graph, and detailed chain
  verification_case_files — verification agent memory, one JSON Case File per case
  verification_runs     — one row per verification run (full or incremental)
  verification_events   — the live step feed shown in the dashboard
  due_diligence_reports — versioned due diligence reports

Obsolete tables and columns from earlier designs are dropped best-effort so an
existing DB upgrades cleanly. ``title_chains.chain`` stays: older chains are still
read from it.
"""

from __future__ import annotations

from backend.database.connection import _get_conn
from backend.logger import get_logger

logger = get_logger(__name__)

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
    merged_ocr_text LONGTEXT NULL,
    file_paths JSON NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    cost_usd DECIMAL(10,6) NOT NULL DEFAULT 0,
    model_used VARCHAR(64) DEFAULT '',
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
    property_identity JSON NULL,
    title_chain_graph LONGTEXT NULL,
    detailed_chain JSON NULL,
    chain JSON NULL,
    phase_a_hash CHAR(64) NULL,
    chain_doc_ids JSON NULL,
    missing_documents JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_case_files (
    case_id VARCHAR(32) NOT NULL,
    version INT NOT NULL DEFAULT 0,
    data JSON NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_runs (
    id CHAR(36) NOT NULL,
    case_id VARCHAR(32) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    usage_json JSON NULL,
    error TEXT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    KEY idx_case_started (case_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS verification_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    run_id CHAR(36) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    ref VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_case_event (case_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS due_diligence_reports (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    case_id VARCHAR(32) NOT NULL,
    version INT NOT NULL,
    opinion VARCHAR(32) NOT NULL,
    report JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_version (case_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


DROP_OBSOLETE_SQL = [
    "DROP VIEW IF EXISTS daily_cost_summary",
    "DROP TABLE IF EXISTS llm_calls",
    "DROP TABLE IF EXISTS human_feedback",
    "DROP TABLE IF EXISTS cross_doc_verifications",
    "DROP TABLE IF EXISTS evidence_requirements",
    "DROP TABLE IF EXISTS findings",
    "DROP TABLE IF EXISTS reports",
    "DROP TABLE IF EXISTS verification_results",
    "DROP TABLE IF EXISTS agent_todos",
    "DROP TABLE IF EXISTS agent_verification_plans",
    "DROP TABLE IF EXISTS case_results",
    "DROP TABLE IF EXISTS case_memory",
]

# Columns added after the first release, for databases created before them.
ADD_COLUMNS_SQL = [
    "ALTER TABLE cases ADD COLUMN user_id VARCHAR(32) NULL DEFAULT NULL AFTER id",
    "ALTER TABLE cases ADD COLUMN agent_status VARCHAR(32) NULL DEFAULT NULL",
    "ALTER TABLE documents ADD COLUMN expected_type VARCHAR(32) NULL DEFAULT NULL",
    "ALTER TABLE documents ADD COLUMN merged_ocr_text LONGTEXT NULL AFTER structured_data",
    "ALTER TABLE documents ADD COLUMN summary TEXT NULL",
    "ALTER TABLE title_chains ADD COLUMN property_identity JSON NULL",
    "ALTER TABLE title_chains ADD COLUMN title_chain_graph LONGTEXT NULL",
    "ALTER TABLE title_chains ADD COLUMN detailed_chain JSON NULL",
    "ALTER TABLE title_chains ADD COLUMN phase_a_hash CHAR(64) NULL",
    "ALTER TABLE title_chains ADD COLUMN chain_doc_ids JSON NULL",
    "ALTER TABLE title_chains ADD COLUMN missing_documents JSON NULL",
]

# Columns from earlier designs that nothing reads any more.
DROP_COLUMNS_SQL = [
    "ALTER TABLE cases DROP COLUMN pipeline_status",
    "ALTER TABLE cases DROP COLUMN agent_result",
    "ALTER TABLE cases DROP COLUMN agent_memory",
    "ALTER TABLE cases DROP COLUMN phases",
    "ALTER TABLE cases DROP COLUMN analysis_run_id",
    "ALTER TABLE documents DROP COLUMN verification_notes",
    "ALTER TABLE documents DROP COLUMN stage_started_at",
    "ALTER TABLE documents DROP COLUMN stage_completed_at",
    "ALTER TABLE documents DROP COLUMN trace_id",
    "ALTER TABLE documents DROP COLUMN raw_ocr_path",
    "ALTER TABLE title_chains DROP COLUMN sale_deed_doc_id",
    "ALTER TABLE title_chains DROP COLUMN ec_doc_id",
    "ALTER TABLE title_chains DROP COLUMN input_tokens",
    "ALTER TABLE title_chains DROP COLUMN output_tokens",
    "ALTER TABLE title_chains DROP COLUMN latency_ms",
    "ALTER TABLE title_chains DROP COLUMN cost_usd",
    "ALTER TABLE title_chains DROP COLUMN model_used",
    "ALTER TABLE title_chains DROP COLUMN source",
]

# Phase A results once stored as one JSON object in title_chains.chain.
SPLIT_LEGACY_CHAIN_SQL = [
    "UPDATE title_chains SET "
    "property_identity = JSON_EXTRACT(chain, '$.property_identity'), "
    "title_chain_graph = JSON_UNQUOTE(JSON_EXTRACT(chain, '$.title_chain_graph')), "
    "detailed_chain = JSON_EXTRACT(chain, '$.title_chain') "
    "WHERE chain IS NOT NULL "
    "AND JSON_CONTAINS_PATH(chain, 'all', '$.property_identity', '$.title_chain_graph', "
    "'$.title_chain') "
    "AND property_identity IS NULL AND title_chain_graph IS NULL AND detailed_chain IS NULL",
    "UPDATE title_chains SET chain = NULL "
    "WHERE property_identity IS NOT NULL AND title_chain_graph IS NOT NULL "
    "AND detailed_chain IS NOT NULL "
    "AND JSON_CONTAINS_PATH(chain, 'all', '$.property_identity', '$.title_chain_graph', "
    "'$.title_chain')",
]


_tables_initialized = False


def _try_each(cursor, conn, statements: list[str]) -> None:
    """Run each statement on its own; one that does not apply is skipped."""
    for sql in statements:
        try:
            cursor.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()


def ensure_tables():
    """Run DDL once at startup. Do NOT call from per-request handlers."""
    global _tables_initialized
    if _tables_initialized:
        return
    with _get_conn() as conn:
        cursor = conn.cursor()
        _try_each(cursor, conn, DROP_OBSOLETE_SQL)
        for statement in CREATE_TABLES_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt + ";")
        conn.commit()
        _try_each(cursor, conn, ADD_COLUMNS_SQL)
        _try_each(cursor, conn, DROP_COLUMNS_SQL)
        _try_each(cursor, conn, SPLIT_LEGACY_CHAIN_SQL)
    _tables_initialized = True
