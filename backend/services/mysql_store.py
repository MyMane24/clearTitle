"""
MySQL storage for structured document results.
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


def store_structured_result(
    *,
    case_id: str,
    doc_id: str,
    filename: str,
    document_type: str,
    structured: dict[str, Any],
    result_path: Path,
    status: str = "complete",
) -> None:
    """
    Create the result table if needed and upsert a structured document result.
    """
    connector = _mysql_connector()
    _ensure_database(connector)

    connection = connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(_create_table_sql())
        cursor.execute(
            """
            INSERT INTO document_results (
                case_id, doc_id, filename, document_type, status,
                structured_json, result_path
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                filename = VALUES(filename),
                document_type = VALUES(document_type),
                status = VALUES(status),
                structured_json = VALUES(structured_json),
                result_path = VALUES(result_path),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                case_id,
                doc_id,
                filename,
                document_type,
                status,
                json.dumps(structured, ensure_ascii=False),
                str(result_path),
            ),
        )
        connection.commit()
    finally:
        connection.close()


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


def _create_table_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS document_results (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        case_id VARCHAR(32) NOT NULL,
        doc_id VARCHAR(32) NOT NULL,
        filename VARCHAR(512) NOT NULL,
        document_type VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'complete',
        structured_json JSON NOT NULL,
        result_path VARCHAR(1024) NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uq_case_doc (case_id, doc_id),
        KEY idx_case_id (case_id),
        KEY idx_document_type (document_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
