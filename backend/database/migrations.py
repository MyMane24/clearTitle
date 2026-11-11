"""
DDL + table bootstrap for the simplified schema.

Tables:
  users                 — auth accounts
  cases                 — pipeline cases (user-scoped)
  documents             — per-doc extraction state (no per-doc verification)
  title_chains          — Phase A property identity, graph, and detailed chain
  case_results          — one case-level verification result document
  case_memory           — one concise text checkpoint per case
  evidence_requirements — Stage 1 ledger: one stable-ID row per requested document

Obsolete tables (cross_doc_verifications, human_feedback, llm_calls and the
daily_cost_summary view) are dropped best-effort so an existing DB upgrades
cleanly, as are abandoned columns: documents.verification_notes,
documents.stage_started_at, documents.stage_completed_at, documents.trace_id,
and the unused token/cost/metadata columns on title_chains and
verification_results that are no longer surfaced to any consumer.
"""

from __future__ import annotations

import json

from backend.database.connection import _get_conn
from backend.logger import get_logger
from backend.schemas import new_requirement_id

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
    source JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS case_results (
    case_id VARCHAR(32) NOT NULL,
    case_result JSON NULL,
    final_report JSON NULL,
    final_reports JSON NULL,
    dossier_meta JSON NULL,
    property_findings JSON NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS case_memory (
    case_id VARCHAR(32) NOT NULL,
    case_memory LONGTEXT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Stage 1 (target architecture): one row per requested document with a stable
-- identity, owned by the transaction that asked for it. Additive only, revert
-- with downgrade_stage1().
CREATE TABLE IF NOT EXISTS evidence_requirements (
    case_id VARCHAR(32) NOT NULL,
    requirement_id VARCHAR(32) NOT NULL,
    owner_tx_id VARCHAR(32) NULL,
    document_type VARCHAR(255) NOT NULL,
    reason TEXT NULL,
    what_it_establishes TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
    match_status VARCHAR(24) NULL,
    matched_doc_id VARCHAR(32) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (case_id, requirement_id),
    KEY ix_evidence_requirements_status (case_id, status)
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
            ("documents", "merged_ocr_text", "ALTER TABLE documents ADD COLUMN merged_ocr_text LONGTEXT NULL AFTER structured_data"),
            # ClearTitle agent status and resume memory; Phase A's deliverable lives
            # in the three dedicated title_chains columns below.
            ("documents", "summary", "ALTER TABLE documents ADD COLUMN summary TEXT NULL"),
            ("cases", "agent_status", "ALTER TABLE cases ADD COLUMN agent_status VARCHAR(32) NULL DEFAULT NULL"),
            ("title_chains", "property_identity", "ALTER TABLE title_chains ADD COLUMN property_identity JSON NULL"),
            ("title_chains", "title_chain_graph", "ALTER TABLE title_chains ADD COLUMN title_chain_graph LONGTEXT NULL"),
            ("title_chains", "detailed_chain", "ALTER TABLE title_chains ADD COLUMN detailed_chain JSON NULL"),
            ("case_memory", "case_memory", "ALTER TABLE case_memory ADD COLUMN case_memory LONGTEXT NULL"),
            # Generated final property title audit report (PDF lives on disk;
            # the JSON column holds the report document and traceability).
            ("case_results", "final_report", "ALTER TABLE case_results ADD COLUMN final_report JSON NULL"),
            # M2 (Stage 3): per-tx dossier revision index — the append-only
            # history of superseded dossier snapshots lives here, one JSON doc.
            ("case_results", "dossier_meta", "ALTER TABLE case_results ADD COLUMN dossier_meta JSON NULL"),
            # M3 (Stage 5): one consolidated property-findings container row per
            # case (in-contract version + input hash; no per-finding rows).
            ("case_results", "property_findings", "ALTER TABLE case_results ADD COLUMN property_findings JSON NULL"),
            # M4 (Stage 6): append-only final-report history — version, report
            # type, source hashes and superseding metadata, one JSON array.
            ("case_results", "final_reports", "ALTER TABLE case_results ADD COLUMN final_reports JSON NULL"),
            # Stage 1 (target architecture): case-level phase state and the
            # analysis run that produced the persisted output. Additive only.
            ("cases", "phases", "ALTER TABLE cases ADD COLUMN phases JSON NULL"),
            ("cases", "analysis_run_id", "ALTER TABLE cases ADD COLUMN analysis_run_id CHAR(36) NULL"),
            # Stage 2: chain-integrity hash stamped on every Phase A save.
            ("title_chains", "phase_a_hash", "ALTER TABLE title_chains ADD COLUMN phase_a_hash CHAR(64) NULL"),
        ]:
            _, _, sql = col_def
            try:
                cursor.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()

        # Consolidate legacy verification stores before removing them. Every
        # transaction result is copied into the one per-case result row.
        try:
            cursor.execute("SHOW COLUMNS FROM case_memory LIKE 'memory'")
            has_legacy_memory = cursor.fetchone() is not None
            if has_legacy_memory:
                cursor.execute("ALTER TABLE case_memory MODIFY memory LONGTEXT NULL")
                cursor.execute("UPDATE case_memory SET case_memory = memory WHERE case_memory IS NULL")
                cursor.execute("SELECT case_id, case_memory FROM case_memory")
                for case_id, raw_memory in cursor.fetchall():
                    try:
                        old = json.loads(raw_memory) if isinstance(raw_memory, str) else raw_memory
                    except (TypeError, ValueError):
                        old = None
                    if isinstance(old, dict):
                        notes = []
                        for key, label in (("stage", "Progress"), ("current_tx_id", "Current transaction"),
                                           ("paused_transaction", "Paused transaction"), ("next_action", "Next action")):
                            if old.get(key):
                                notes.append(f"{label}: {old[key]}")
                        for key, label in (("completed_tx_ids", "Completed transactions"),
                                           ("pending_tx_ids", "Pending transactions"),
                                           ("skipped_tx_ids", "Skipped this run")):
                            if old.get(key):
                                notes.append(f"{label}: {', '.join(map(str, old[key]))}")
                        for missing in old.get("missing_documents") or []:
                            if isinstance(missing, dict):
                                notes.append(f"Missing document: {missing.get('document_type') or 'Document'} — {missing.get('reason') or ''}")
                        cursor.execute("UPDATE case_memory SET case_memory = %s WHERE case_id = %s", ("\n".join(notes), case_id))
                cursor.execute("ALTER TABLE case_memory DROP COLUMN memory")

            cursor.execute("SHOW COLUMNS FROM cases LIKE 'agent_memory'")
            if cursor.fetchone():
                cursor.execute("SELECT id, agent_memory FROM cases WHERE agent_memory IS NOT NULL")
                for case_id, raw_memory in cursor.fetchall():
                    cursor.execute("SELECT 1 FROM case_memory WHERE case_id = %s", (case_id,))
                    if cursor.fetchone():
                        continue
                    try:
                        old = json.loads(raw_memory) if isinstance(raw_memory, str) else raw_memory
                    except (TypeError, ValueError):
                        old = None
                    if isinstance(old, dict):
                        notes = [f"Progress: {old['stage']}"] if old.get("stage") else []
                        if old.get("next_action"):
                            notes.append(f"Next action: {old['next_action']}")
                        cursor.execute("INSERT INTO case_memory (case_id, case_memory) VALUES (%s, %s)", (case_id, "\n".join(notes)))

            cursor.execute("SHOW TABLES LIKE 'agent_todos'")
            if cursor.fetchone():
                cursor.execute("SELECT case_id, state, description, required_evidence FROM agent_todos ORDER BY case_id, tx_index")
                for case_id, state, description, evidence in cursor.fetchall():
                    cursor.execute("SELECT case_memory FROM case_memory WHERE case_id = %s", (case_id,))
                    row = cursor.fetchone()
                    note = f"Legacy transaction progress: {state or 'PENDING'}"
                    if description:
                        note += f" — {description}"
                    if evidence:
                        note += f"; required evidence: {evidence}"
                    existing = (row[0] or "") if row else ""
                    updated = f"{existing}\n{note}".strip()
                    cursor.execute(
                        "INSERT INTO case_memory (case_id, case_memory) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE case_memory = VALUES(case_memory)",
                        (case_id, updated),
                    )

            cursor.execute("SELECT case_id, case_result FROM case_results")
            consolidated = {}
            for case_id, raw in cursor.fetchall():
                try:
                    value = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    consolidated[case_id] = value if isinstance(value, list) else (value.get("transactions") or [])
                except (TypeError, ValueError):
                    consolidated[case_id] = []

            cursor.execute("SHOW TABLES LIKE 'findings'")
            if cursor.fetchone():
                cursor.execute("SELECT case_id, payload, tx_id, tx_index, status, finding FROM findings ORDER BY tx_index, id")
                for case_id, payload, tx_id, tx_index, status, finding in cursor.fetchall():
                    target = consolidated.setdefault(case_id, [])
                    try:
                        item = json.loads(payload) if isinstance(payload, str) else (payload or {})
                    except (TypeError, ValueError):
                        item = {}
                    if not item:
                        item = {"tx_id": tx_id, "sequence": tx_index, "status": status, "conclusion": finding or ""}
                    target[:] = [old for old in target if old.get("tx_id") != (item.get("tx_id") or tx_id)]
                    target.append(item)

            cursor.execute("SHOW TABLES LIKE 'reports'")
            if cursor.fetchone():
                cursor.execute("SELECT case_id, result FROM reports ORDER BY id")
                for case_id, raw in cursor.fetchall():
                    try:
                        report = json.loads(raw) if isinstance(raw, str) else raw
                    except (TypeError, ValueError):
                        report = None
                    if report and report.get("transactions"):
                        target = consolidated.setdefault(case_id, [])
                        known = {item.get("tx_id") for item in target}
                        target.extend(item for item in report["transactions"] if item.get("tx_id") not in known)

            cursor.execute("SHOW COLUMNS FROM cases LIKE 'agent_result'")
            if cursor.fetchone():
                cursor.execute("SELECT id, agent_result FROM cases WHERE agent_result IS NOT NULL")
                for case_id, raw in cursor.fetchall():
                    try:
                        report = json.loads(raw) if isinstance(raw, str) else raw
                    except (TypeError, ValueError):
                        report = None
                    if report and report.get("transactions"):
                        target = consolidated.setdefault(case_id, [])
                        known = {item.get("tx_id") for item in target}
                        target.extend(item for item in report["transactions"] if item.get("tx_id") not in known)

            for case_id, payload in consolidated.items():
                cursor.execute(
                    "INSERT INTO case_results (case_id, case_result) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE case_result = VALUES(case_result)",
                    (case_id, json.dumps(payload, ensure_ascii=False)),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Retire redundant result stores only after the copy above succeeds.
        for table in ("findings", "reports", "verification_results"):
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
            except Exception:
                conn.rollback()
        for table in ("agent_todos", "agent_verification_plans"):
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
            except Exception:
                conn.rollback()

        for column in ("agent_result", "agent_memory"):
            try:
                cursor.execute(f"ALTER TABLE cases DROP COLUMN {column}")
                conn.commit()
            except Exception:
                conn.rollback()

        # Best-effort removal of abandoned columns from older schemas
        for sql in [
            "ALTER TABLE cases DROP COLUMN pipeline_status",
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
            "ALTER TABLE documents DROP COLUMN raw_ocr_path",
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

        # Stage 1 backfill (target architecture): materialize one
        # evidence_requirements row per persisted required document, in
        # transaction-sequence order, with deterministic app-assigned IDs.
        # Idempotent: cases that already have ledger rows are skipped.
        try:
            cursor.execute("SELECT case_id, case_result FROM case_results")
            for case_id, raw in cursor.fetchall():
                cursor.execute(
                    "SELECT COUNT(*) FROM evidence_requirements WHERE case_id = %s", (case_id,)
                )
                if (cursor.fetchone() or [0])[0] > 0:
                    continue
                try:
                    transactions = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    if isinstance(transactions, dict):
                        transactions = transactions.get("transactions") or []
                except (TypeError, ValueError):
                    continue
                rows = derive_evidence_requirements(case_id, transactions if isinstance(transactions, list) else [])
                if not rows:
                    continue
                cursor.executemany(
                    "INSERT IGNORE INTO evidence_requirements "
                    "(case_id, requirement_id, owner_tx_id, document_type, reason) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    rows,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.warning("evidence_requirements backfill skipped (non-fatal)", exc_info=True)

        # Split Phase A results previously stored as one JSON object in chain.
        try:
            cursor.execute(
                "UPDATE title_chains SET "
                "property_identity = JSON_EXTRACT(chain, '$.property_identity'), "
                "title_chain_graph = JSON_UNQUOTE(JSON_EXTRACT(chain, '$.title_chain_graph')), "
                "detailed_chain = JSON_EXTRACT(chain, '$.title_chain') "
                "WHERE chain IS NOT NULL "
                "AND JSON_CONTAINS_PATH(chain, 'all', '$.property_identity', '$.title_chain_graph', '$.title_chain') "
                "AND property_identity IS NULL AND title_chain_graph IS NULL AND detailed_chain IS NULL"
            )
            cursor.execute(
                "UPDATE title_chains SET chain = NULL "
                "WHERE property_identity IS NOT NULL AND title_chain_graph IS NOT NULL "
                "AND detailed_chain IS NOT NULL "
                "AND JSON_CONTAINS_PATH(chain, 'all', '$.property_identity', '$.title_chain_graph', '$.title_chain')"
            )
            conn.commit()
        except Exception:
            conn.rollback()
    _tables_initialized = True


def derive_evidence_requirements(case_id: str, transactions: list[dict]) -> tuple[tuple, ...]:
    """Pure derivation for the Stage 1 requirements ledger backfill.

    One row per persisted ``required_documents`` entry, deterministically
    numbered (transaction sequence order, then item order) so the same
    persisted case always yields the same stable IDs:

        rows = [ (case_id, requirement_id, owner_tx_id, document_type, reason), ... ]

    Existing rows are never renumbered (``INSERT IGNORE`` + case-level skip in
    ``ensure_tables`` / ``agent_repo.sync_case_requirements`` keeps earlier
    appends intact).
    """
    def _fold(value: str | None) -> str:
        return (value or "").strip().casefold()

    rows: list[tuple] = []
    seen_keys: set[tuple] = set()
    number = 0
    ordered = sorted(
        (item for item in (transactions or []) if isinstance(item, dict)),
        key=lambda item: int(item.get("sequence") or 0),
    )
    for tx in ordered:
        tx_id = str(tx.get("tx_id") or "").strip() or None
        for item in tx.get("required_documents") or []:
            if not isinstance(item, dict):
                continue
            document_type = str(item.get("document_type") or "").strip()
            if not document_type:
                continue
            reason = str(item.get("reason") or "").strip() or None
            owner = str(item.get("for_transaction") or "").strip() or tx_id
            key = (_fold(owner), _fold(document_type), _fold(reason))
            if key in seen_keys:
                continue
            number += 1
            if number > 9999:
                logger.error("requirement ID exhaustion for case %s; stopping backfill", case_id)
                return tuple(rows)
            seen_keys.add(key)
            rows.append((case_id, new_requirement_id(number), owner, document_type, reason))
    return tuple(rows)


def downgrade_stage1(conn=None) -> None:
    """Revert the Stage 1 additive migration (docs/architecture §5 M1).

    Best-effort and manual: drops the requirements ledger and the two
    case columns. Never run as part of the startup path.
    """
    if conn is None:
        with _get_conn() as conn:
            downgrade_stage1(conn)
            return
    cursor = conn.cursor()
    for sql in (
        "DROP TABLE IF EXISTS evidence_requirements",
        "ALTER TABLE cases DROP COLUMN phases",
        "ALTER TABLE cases DROP COLUMN analysis_run_id",
        "ALTER TABLE title_chains DROP COLUMN phase_a_hash",
        "ALTER TABLE case_results DROP COLUMN dossier_meta",
        "ALTER TABLE case_results DROP COLUMN property_findings",
        "ALTER TABLE case_results DROP COLUMN final_reports",
    ):
        try:
            cursor.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()
