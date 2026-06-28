"""OpenWebUI SQLite 조회 함수.

SQL은 화면 코드와 분리해 두어 지표 기준이 바뀌어도 유지보수하기 쉽게 합니다.
"""

from __future__ import annotations

import sqlite3

import pandas as pd


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    query = """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
    """
    return connection.execute(query, (table_name,)).fetchone() is not None


def read_users(connection: sqlite3.Connection) -> pd.DataFrame:
    """사용자 기본 정보를 조회합니다."""

    if not table_exists(connection, "user"):
        return pd.DataFrame()

    query = """
        SELECT
            id,
            name,
            email,
            role,
            created_at,
            updated_at,
            last_active_at
        FROM user
    """
    return pd.read_sql_query(query, connection)


def read_chats(connection: sqlite3.Connection) -> pd.DataFrame:
    """채팅방과 JSON 대화 내용을 조회합니다."""

    if not table_exists(connection, "chat"):
        return pd.DataFrame()

    query = """
        SELECT
            id,
            user_id,
            title,
            chat,
            created_at,
            updated_at
        FROM chat
    """
    return pd.read_sql_query(query, connection)


def count_feedback(connection: sqlite3.Connection) -> int:
    """피드백 테이블이 있으면 전체 피드백 수를 반환합니다."""

    if not table_exists(connection, "feedback"):
        return 0

    return int(connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0])


def count_files(connection: sqlite3.Connection) -> int:
    """파일 테이블이 있으면 전체 파일 수를 반환합니다."""

    if not table_exists(connection, "file"):
        return 0

    return int(connection.execute("SELECT COUNT(*) FROM file").fetchone()[0])
