from dataclasses import dataclass, field
from pathlib import Path
import os
from urllib.parse import urlsplit
from starlette.config import Config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class UTF8Config(Config):
    """Starlette's key=value format, decoded consistently on Windows and Linux."""

    def _read_file(self, file_name):
        values = {}
        for line in Path(file_name).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
        return values


@dataclass(frozen=True)
class Settings:
    base_url: str = ""
    api_token: str = field(default="", repr=False)
    cache_path: Path = Path("data/dashboard-v2.sqlite3")
    org_csv: Path | None = None
    timeout: int = 30
    retries: int = 2
    page_size: int = 100
    max_pages_per_user: int = 10000
    overlap_days: int = 7
    dashboard_token: str = field(default="", repr=False)
    frontend_dir: Path | None = None
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self):
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "OPENWEBUI_URL must be an http(s) base URL without credentials/query/fragment"
                )
        if not 1 <= self.page_size <= 100:
            raise ValueError("OPENWEBUI_PAGE_SIZE must be 1..100")
        if not 1 <= self.timeout <= 120 or not 0 <= self.retries <= 5:
            raise ValueError("Invalid timeout/retry setting")
        if self.overlap_days < 1 or self.max_pages_per_user < 1:
            raise ValueError("Overlap days and maximum pages must be positive")

    @classmethod
    def from_env(cls, env_file=None):
        # Stable project-root location; CLI and Uvicorn use the same file.
        path = (
            Path(env_file).resolve() if env_file is not None else PROJECT_ROOT / ".env"
        )
        if env_file is not None and not path.is_file():
            raise ValueError("Specified .env file does not exist")
        config = UTF8Config(path if path.is_file() else None, environ=os.environ)

        def local_path(key, default=""):
            value = config(key, default=default)
            if not value:
                return None
            result = Path(value)
            return result if result.is_absolute() else path.parent / result

        return cls(
            base_url=config("OPENWEBUI_URL", default="").rstrip("/"),
            api_token=config("OPENWEBUI_API_TOKEN", default=""),
            cache_path=local_path("DASHBOARD_CACHE_PATH", "data/dashboard-v2.sqlite3"),
            org_csv=local_path("ORG_USER_CSV_PATH"),
            timeout=config("OPENWEBUI_TIMEOUT_SECONDS", cast=int, default=30),
            retries=config("OPENWEBUI_MAX_RETRIES", cast=int, default=2),
            page_size=config("OPENWEBUI_PAGE_SIZE", cast=int, default=100),
            max_pages_per_user=config(
                "OPENWEBUI_MAX_PAGES_PER_USER", cast=int, default=10000
            ),
            overlap_days=config("SYNC_OVERLAP_DAYS", cast=int, default=7),
            dashboard_token=config("DASHBOARD_API_TOKEN", default=""),
            frontend_dir=local_path("DASHBOARD_FRONTEND_DIR"),
            cors_origins=tuple(
                s.strip()
                for s in config("DASHBOARD_CORS_ORIGINS", default="").split(",")
                if s.strip()
            ),
        )
