"""Read-only upstream client. v0.12.3 commit 91ea4e3421d1d8069f13d4a463fcb5986d94ea60.

The user_id branch of analytics/messages ignores dates; filter locally during sync.
Never follow redirects with the admin credential, log bodies, or log request URLs.
"""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .settings import Settings


class UpstreamError(RuntimeError):
    pass


class ContractError(UpstreamError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenWebUIClient:
    def __init__(self, settings: Settings, opener=None, sleep=time.sleep):
        if not settings.base_url or not settings.api_token:
            raise ValueError(
                "Set OPENWEBUI_URL and OPENWEBUI_API_TOKEN locally before syncing"
            )
        self.settings = settings
        self.opener = opener or build_opener(NoRedirect())
        self.sleep = sleep

    def _get(self, path, params=None):
        url = self.settings.base_url + path
        if params:
            url += "?" + urlencode(params)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.settings.api_token,
            },
            method="GET",
        )
        for attempt in range(self.settings.retries + 1):
            delay = min(2**attempt, 8)
            try:
                with self.opener.open(
                    request, timeout=self.settings.timeout
                ) as response:
                    raw = response.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ContractError(
                        "Upstream JSON exceeds 32 MiB; use a narrower collection strategy"
                    )
                body = json.loads(raw)
                if isinstance(body, dict) and body.get("ok") is False:
                    raise UpstreamError("Upstream returned ok:false")
                return body
            except HTTPError as error:
                code = error.code
                if error.headers:
                    try:
                        delay = min(
                            max(float(error.headers.get("Retry-After", delay)), 0), 10
                        )
                    except (TypeError, ValueError):
                        pass
                error.close()
                if (
                    code not in (429, 500, 502, 503, 504)
                    or attempt == self.settings.retries
                ):
                    raise UpstreamError(
                        f"OpenWebUI HTTP {code}; check authentication, API permissions and enabled endpoints"
                    ) from None
            except (URLError, TimeoutError, OSError):
                if attempt == self.settings.retries:
                    raise UpstreamError(
                        "OpenWebUI connection failed or timed out"
                    ) from None
            except (ValueError, UnicodeError):
                raise ContractError("OpenWebUI did not return valid JSON") from None
            self.sleep(delay)
        raise UpstreamError("Upstream request failed")

    def users(self):
        result = self._get("/api/v1/users/all")
        if not isinstance(result, dict) or not isinstance(result.get("users"), list):
            raise ContractError("Expected users/all: {users: [...], total: integer}")
        users, total = result["users"], result.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total != len(users):
            raise ContractError("users/all did not return the complete roster")
        seen = set()
        for user in users:
            if (
                not isinstance(user, dict)
                or not isinstance(user.get("id"), str)
                or not user["id"]
                or user["id"] in seen
            ):
                raise ContractError("Invalid or duplicate upstream user ID")
            if not isinstance(user.get("name"), str) or not isinstance(
                user.get("email"), str
            ):
                raise ContractError("User name/email must be strings")
            seen.add(user["id"])
        return users

    def messages(self, user_id, skip):
        result = self._get(
            "/api/v1/analytics/messages",
            {"user_id": user_id, "skip": skip, "limit": self.settings.page_size},
        )
        if not isinstance(result, list) or len(result) > self.settings.page_size:
            raise ContractError("Expected paged analytics/messages array")
        return result
