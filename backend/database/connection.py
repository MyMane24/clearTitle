"""
MySQL connection management — pooling and connection context manager.

Extracted verbatim from `backend/services/mysql_store.py` (connection section).
"""

from __future__ import annotations

import threading

from backend.config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)


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
