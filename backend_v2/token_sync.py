"""Read paginated LiteLLM logs, sanitize and publish only after a complete run."""

import json
import math
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .analytics import date_value
from .client import OpenWebUIClient, ContractError, UpstreamError
from .token_store import TokenStore
from .control import JobPaused, JobCancelled


def numeric(value, integer=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ContractError("Invalid LiteLLM numeric field")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ContractError("Invalid LiteLLM numeric field") from None
    if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
        raise ContractError("Invalid LiteLLM numeric field")
    return int(number) if integer else number


def timestamp(value, tz):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result = float(value)
        else:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            result = (d if d.tzinfo else d.replace(tzinfo=ZoneInfo(tz))).timestamp()
        if not math.isfinite(result):
            raise ValueError()
        datetime.fromtimestamp(result, timezone.utc)
        return result
    except (ValueError, TypeError, OverflowError, OSError):
        raise ContractError("Invalid LiteLLM log timestamp") from None


def obj(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def identity(log, metadata):
    roots = [
        log,
        metadata,
        obj(metadata.get("spend_logs_metadata")),
        obj(metadata.get("metadata")),
    ]

    def pick(keys):
        for root in roots:
            for k in keys:
                v = root.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()[:512]
        return ""

    # Never use log.user or metadata.user_api_key_user_id: these identify the key owner.
    return (
        pick(("openwebui_user_id",)) or pick(("end_user", "user_api_key_end_user_id")),
        pick(("openwebui_user_email",)),
        pick(("openwebui_user_name",)),
    )


def normalize(log, settings):
    if not isinstance(log, dict):
        raise ContractError("Invalid LiteLLM log row")
    metadata = obj(log.get("metadata"))
    alias = log.get("api_key_alias") or metadata.get("user_api_key_alias")
    if alias != settings.litellm_alias:
        return None
    request_id = log.get("request_id") or log.get("id")
    if not isinstance(request_id, str) or not request_id:
        raise ContractError("LiteLLM request_id missing")
    at = timestamp(
        log.get("startTime", log.get("start_time")), settings.litellm_timezone
    )
    prompt = numeric(log.get("prompt_tokens"), True)
    completion = numeric(log.get("completion_tokens"), True)
    total = numeric(log.get("total_tokens"), True)
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    model = log.get("model_group") or log.get("model") or "(unknown model)"
    if not isinstance(model, str):
        raise ContractError("Invalid LiteLLM model")
    return (
        request_id,
        at,
        model,
        prompt,
        completion,
        total,
        numeric(log.get("spend")),
        *identity(log, metadata),
    )


class SpendClient:
    def __init__(self, settings, opener=None):
        self.settings = settings
        self.http = OpenWebUIClient(
            replace(
                settings, base_url=settings.litellm_url, api_token=settings.litellm_key
            ),
            opener=opener,
        )

    def page(self, start, end, page):
        tz = ZoneInfo(self.settings.litellm_timezone)
        params = {
            "start_date": datetime.fromtimestamp(start, tz).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "end_date": datetime.fromtimestamp(end, tz).strftime("%Y-%m-%d %H:%M:%S"),
            "page": page,
            "page_size": self.settings.litellm_page_size,
            "group_by_session": "false",
        }
        try:
            body = self.http._get(self.settings.litellm_logs_path, params)
        except UpstreamError as e:
            raise UpstreamError(str(e).replace("OpenWebUI", "LiteLLM")) from None
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ContractError(
                "Expected LiteLLM v2 paginated response with data array"
            )
        if (
            body.get("page", page) != page
            or len(body["data"]) > self.settings.litellm_page_size
        ):
            raise ContractError("Invalid LiteLLM pagination response")
        return body["data"]


def prepare(settings, store, kind="quick"):
    if kind not in ("quick", "full"):
        raise ValueError("Token sync kind must be quick or full")
    if (
        not settings.litellm_url
        or not settings.litellm_key
        or not settings.litellm_alias
    ):
        raise ValueError(
            "Set LITELLM_BASE_URL, LITELLM_API_KEY and LITELLM_REQUIRED_API_KEY_ALIAS"
        )
    if not settings.litellm_start_date:
        raise ValueError(
            "Set LITELLM_SYNC_START_DATE (YYYY-MM-DD) for initial/full history"
        )
    start = datetime.combine(
        date_value(settings.litellm_start_date),
        datetime.min.time(),
        ZoneInfo(settings.litellm_timezone),
    ).timestamp()
    state = store.status()
    end = math.floor(time.time())
    if not state["ready"]:
        kind = "full"
    if kind == "quick":
        start = max(
            start,
            datetime.fromisoformat(state["lastSuccess"]).timestamp()
            - settings.litellm_lookback_hours * 3600,
        )
    if start > end:
        raise ValueError("LiteLLM synchronization start is in the future")
    return store.start(settings, kind, start, end)


def collect(settings, store, run, client=None, check=None):
    check = check or (lambda: None)
    try:
        client = client or SpendClient(settings)
        job = next(r for r in store.status()["runs"] if r["id"] == run)
        start, end = job["start"], job["end"]
        scanned = skipped = pages = 0
        while start <= end:
            stop = min(start + 86400, end)
            seen = set()
            for page in range(1, settings.litellm_max_pages + 1):
                store.stage(run, [], scanned, skipped, pages)
                raw = client.page(start, stop, page)
                pages += 1
                rows = []
                # Ignore total_pages: recent LiteLLM versions cap advertised totals.
                if not raw:
                    break
                for log in raw:
                    if not isinstance(log, dict):
                        raise ContractError("Invalid LiteLLM row")
                    request_id = log.get("request_id") or log.get("id")
                    if (
                        not isinstance(request_id, str)
                        or not request_id
                        or request_id in seen
                    ):
                        raise ContractError(
                            "Repeated LiteLLM pagination or missing request IDs; retry sync"
                        )
                    seen.add(request_id)
                    scanned += 1
                    row = normalize(log, settings)
                    if row is None:
                        skipped += 1
                    elif start <= row[1] <= stop:
                        rows.append(row)
                    else:
                        raise ContractError(
                            "LiteLLM returned logs outside requested time window"
                        )
                store.stage(run, rows, scanned, skipped, pages)
            else:
                raise ContractError(
                    "LiteLLM maximum pages reached; previous cache preserved"
                )
            if stop == end:
                break
            start = (
                stop  # overlap the inclusive boundary; ID upsert removes duplicates.
            )
        store.stage(run, [], scanned, skipped, pages)
        check()
        store.publish(settings, run)
    except (JobPaused, JobCancelled) as signal:
        store.fail(run, '작업이 일시 중단되었습니다.' if isinstance(signal,JobPaused) else '작업이 중단되었습니다.')
        with store.connect() as db:
            db.execute('UPDATE token_runs SET status=? WHERE id=?',('paused' if isinstance(signal,JobPaused) else 'cancelled',run))
        raise
    except Exception as error:
        message = (
            str(error)
            if isinstance(error, (ValueError, UpstreamError, RuntimeError))
            else "Token collection failed; check local cache permissions"
        )
        store.fail(run, message)
        raise RuntimeError(message) from None
    return store.status()
