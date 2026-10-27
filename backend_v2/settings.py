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

    token_cache_path: Path = Path("data/token_usage_v2.sqlite3")
    litellm_url: str = ""
    litellm_key: str = field(default="", repr=False)
    litellm_logs_path: str = "/spend/logs/v2"
    litellm_alias: str = ""
    litellm_page_size: int = 100
    litellm_lookback_hours: int = 24
    litellm_start_date: str = ""
    litellm_timezone: str = "UTC"
    litellm_max_pages: int = 10000
    model_prices_csv: Path | None = None

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
        if self.litellm_url:
            parsed = urlsplit(self.litellm_url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "LITELLM_BASE_URL must be an http(s) base URL without credentials/query/fragment"
                )
        if (
            not self.litellm_logs_path.startswith("/")
            or self.litellm_logs_path.startswith("//")
            or any(c in self.litellm_logs_path for c in ("?", "#", ":"))
        ):
            raise ValueError("Invalid LITELLM_SPEND_LOGS_PATH")
        if (
            not 1 <= self.litellm_page_size <= 100
            or self.litellm_lookback_hours < 1
            or self.litellm_max_pages < 1
        ):
            raise ValueError("Invalid LiteLLM page size/lookback/maximum pages")
        from zoneinfo import ZoneInfo

        ZoneInfo(self.litellm_timezone)
        if self.token_cache_path.resolve() == self.cache_path.resolve():
            raise ValueError("Token cache must be separate from OpenWebUI cache")
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
            token_cache_path=local_path(
                "TOKEN_CACHE_DB_PATH", "data/token_usage_v2.sqlite3"
            ),
            litellm_url=config("LITELLM_BASE_URL", default="").rstrip("/"),
            litellm_key=config("LITELLM_API_KEY", default=""),
            litellm_logs_path=config(
                "LITELLM_SPEND_LOGS_PATH", default="/spend/logs/v2"
            ),
            litellm_alias=config("LITELLM_REQUIRED_API_KEY_ALIAS", default=""),
            litellm_page_size=min(
                100, config("LITELLM_LOG_LIMIT", cast=int, default=100)
            ),
            litellm_lookback_hours=config(
                "LITELLM_SYNC_LOOKBACK_HOURS", cast=int, default=24
            ),
            litellm_start_date=config("LITELLM_SYNC_START_DATE", default=""),
            litellm_timezone=config("LITELLM_LOG_TIMEZONE", default="UTC"),
            litellm_max_pages=config(
                "LITELLM_MAX_PAGES_PER_WINDOW", cast=int, default=10000
            ),
            model_prices_csv=local_path("MODEL_PRICES_CSV_PATH"),
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
