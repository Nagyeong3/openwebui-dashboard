from dataclasses import dataclass, field
from pathlib import Path
import os
from urllib.parse import urlsplit


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
    def from_env(cls):
        return cls(
            base_url=os.getenv("OPENWEBUI_URL", "").rstrip("/"),
            api_token=os.getenv("OPENWEBUI_API_TOKEN", ""),
            cache_path=Path(
                os.getenv("DASHBOARD_CACHE_PATH", "data/dashboard-v2.sqlite3")
            ),
            org_csv=(
                Path(os.environ["ORG_USER_CSV_PATH"])
                if os.getenv("ORG_USER_CSV_PATH")
                else None
            ),
            timeout=int(os.getenv("OPENWEBUI_TIMEOUT_SECONDS", "30")),
            retries=int(os.getenv("OPENWEBUI_MAX_RETRIES", "2")),
            page_size=int(os.getenv("OPENWEBUI_PAGE_SIZE", "100")),
            max_pages_per_user=int(os.getenv("OPENWEBUI_MAX_PAGES_PER_USER", "10000")),
            overlap_days=int(os.getenv("SYNC_OVERLAP_DAYS", "7")),
            dashboard_token=os.getenv("DASHBOARD_API_TOKEN", ""),
        )
