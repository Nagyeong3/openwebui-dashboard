"""환경별 설정값을 한곳에서 관리합니다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "openwebui.db"


@dataclass(frozen=True)
class AppSettings:
    """앱 전역에서 공유하는 설정값."""

    app_title: str
    db_path: Path
    default_recent_days: int = 30

    @classmethod
    def from_env(cls) -> "AppSettings":
        """환경변수를 읽어 설정을 구성합니다."""

        return cls(
            app_title=os.getenv("APP_TITLE", "OpenWebUI Analytics"),
            db_path=Path(os.getenv("OPENWEBUI_DB_PATH", DEFAULT_DB_PATH)).expanduser(),
            default_recent_days=int(os.getenv("DEFAULT_RECENT_DAYS", "30")),
        )
