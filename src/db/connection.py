"""SQLite DB 연결 유틸리티."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class DatabaseNotFoundError(FileNotFoundError):
    """분석용 DB 복사본을 찾을 수 없을 때 발생합니다."""


def connect(db_path: Path) -> sqlite3.Connection:
    """분석용 SQLite DB에 연결합니다.

    운영 DB 접근을 피하기 위해 앱은 사용자가 지정한 복사본 경로만 사용합니다.
    """

    if not db_path.exists():
        raise DatabaseNotFoundError(f"SQLite DB not found: {db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection
