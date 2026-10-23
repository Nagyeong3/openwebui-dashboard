import copy
from contextlib import closing
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_v2.analytics import user_usage
from backend_v2.app import create_app
from backend_v2.cache import Cache, BusyError, NotReadyError
from backend_v2.client import OpenWebUIClient, UpstreamError, ContractError
from backend_v2.organization import enrich, load_org, MappingError
from backend_v2.settings import Settings
from backend_v2.sync import Synchronizer


def message(
    id,
    uid="u1",
    *,
    role="user",
    created=None,
    chat="chat-1",
    files=None,
    model=None,
    content="synthetic question",
    updated=None,
):
    t = int(time.time()) - 100 if created is None else created
    return {
        "id": id,
        "user_id": uid,
        "chat_id": chat,
        "role": role,
        "created_at": t,
        "updated_at": updated or t,
        "files": files,
        "model_id": model,
        "parent_id": None,
        "content": content,
        "usage": None,
    }


class FakeClient:
    def __init__(self, size=2):
        self.size = size
        self.people = [
            {
                "id": f"u{i}",
                "name": f"Synthetic {i}",
                "email": f"u{i}@example.invalid",
                "role": "user",
            }
            for i in (1, 2, 3)
        ]
        now = int(time.time())
        self.items = [
            message("q1", files=[{"id": "f1"}], created=now - 600),
            message("q2", created=now - 601),
            message("q3", created=now - 602, chat="chat-2"),
            message("a1", role="assistant", created=now - 599, model="synthetic-model"),
        ]
        self.calls = []
        self.failure = False

    def users(self):
        return copy.deepcopy(self.people)

    def messages(self, user_id, skip):
        self.calls.append((user_id, skip))
        if self.failure and user_id == "u2":
            raise UpstreamError("OpenWebUI HTTP 403")
        records = sorted(
            [m for m in self.items if m["user_id"] == user_id],
            key=lambda m: (
                -m["created_at"] if isinstance(m["created_at"], (int, float)) else 0
            ),
        )
        return copy.deepcopy(records[skip : skip + self.size])


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(
            base_url="http://example.invalid",
            api_token="synthetic-secret",
            cache_path=self.root / "cache.sqlite3",
            page_size=2,
        )
        self.cache = Cache(self.settings.cache_path)
        self.client = FakeClient()
        self.sync = Synchronizer(self.settings, self.cache, self.client)

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        return self.sync.run("full")

    def test_full_pagination_and_zero_users(self):
        result = self.load()
        self.assertEqual(result["messages"], 4)
        self.assertIn(("u1", 4), self.client.calls)
        result = user_usage(self.cache, self.settings, range_value="all")
        self.assertEqual(
            result["summary"],
            {
                "users": 3,
                "activeUsers": 1,
                "zeroUsageUsers": 2,
                "questions": 3,
                "chats": 2,
                "attachmentQuestions": 1,
            },
        )
        self.assertEqual(len(result["detail"]["records"]), 3)
        self.assertEqual(
            result["detail"]["records"][0]["primaryModel"], "synthetic-model"
        )
        self.assertEqual(sum(d["questions"] for d in result["daily"]), 3)

    def test_quick_collects_new_users_full_history(self):
        self.load()
        self.client.people.append(
            {"id": "new", "name": "New Synthetic", "email": "", "role": "user"}
        )
        old = int(time.time()) - 365 * 86400
        self.client.items.extend(
            message(f"old-{i}", "new", created=old - i) for i in range(4)
        )
        self.sync.run("quick")
        result = user_usage(self.cache, self.settings, range_value="all")
        new_user = next(r for r in result["detail"]["records"] if r["id"] == "new")
        self.assertEqual(new_user["questions"], 4)
        self.assertIn(("new", 4), self.client.calls)

    def test_initial_quick_promotes_to_full(self):
        self.assertEqual(self.sync.run("quick")["kind"], "full")

    def test_full_retry_idempotent(self):
        self.load()
        self.load()
        self.assertEqual(self.cache.status()["messages"], 4)

    def test_no_cache_is_not_a_zero_dashboard(self):
        with self.assertRaises(NotReadyError):
            user_usage(self.cache, self.settings)
        response = TestClient(create_app(self.settings, self.cache)).get(
            "/api/dashboard/v2/users"
        )
        self.assertEqual(response.status_code, 503)

    def test_failed_sync_preserves_previous_cache(self):
        self.load()
        old = self.cache.read()
        self.client.items = [message("replacement")]
        self.client.failure = True
        with self.assertRaises(UpstreamError):
            self.load()
        self.assertEqual(self.cache.read(), old)
        response = user_usage(self.cache, self.settings, range_value="all")
        self.assertTrue(response["dataState"]["stale"])
        self.assertEqual(response["summary"]["questions"], 3)

    def test_invalid_timestamp_does_not_publish(self):
        self.load()
        self.client.items[0]["created_at"] = "invalid"
        with self.assertRaises(ContractError):
            self.load()
        self.assertEqual(self.cache.status()["messages"], 4)

    def test_full_reconciles_deletion_and_edits(self):
        self.load()
        self.client.items = [message("q1", content="edited", files=None)]
        self.client.people = self.client.people[:2]
        self.load()
        result = user_usage(self.cache, self.settings, range_value="all")
        self.assertEqual(result["summary"]["users"], 2)
        self.assertEqual(result["summary"]["questions"], 1)
        self.assertEqual(result["summary"]["attachmentQuestions"], 0)

    def test_quick_replaces_recent_messages_but_retains_old(self):
        self.client.items.append(message("old", created=int(time.time()) - 30 * 86400))
        self.load()
        self.client.items = [message("new")]
        self.sync.run("quick")
        ids = {m["id"] for m in self.cache.read()[1]}
        self.assertEqual(ids, {"new", "old"})

    def test_quick_covers_downtime_from_last_success(self):
        self.load()
        previous = datetime.fromtimestamp(
            time.time() - 30 * 86400, timezone.utc
        ).isoformat()
        with self.cache.connect() as db:
            db.execute("UPDATE meta SET value=? WHERE key='last_success'", (previous,))
        self.client.items = [message("gap", created=int(time.time()) - 20 * 86400)]
        self.sync.run("quick")
        self.assertEqual({m["id"] for m in self.cache.read()[1]}, {"gap"})

    def test_duplicate_page_fails_instead_of_truncating(self):
        self.load()
        self.client.messages = lambda uid, skip: (
            [message("repeated"), message("repeated-2")] if uid == "u1" else []
        )
        with self.assertRaises(ContractError):
            self.load()
        self.assertEqual(self.cache.status()["messages"], 4)

    def test_max_pages_is_failure_not_partial_success(self):
        settings = Settings(
            base_url=self.settings.base_url,
            api_token="synthetic",
            cache_path=self.cache.path,
            page_size=2,
            max_pages_per_user=1,
        )
        with self.assertRaises(ContractError):
            Synchronizer(settings, self.cache, self.client).run("full")
        self.assertFalse(self.cache.status()["ready"])

    def test_roster_drift_does_not_publish(self):
        original = self.client.users
        calls = []

        def drift():
            calls.append(1)
            return original() if len(calls) == 1 else original()[:2]

        self.client.users = drift
        with self.assertRaises(ContractError):
            self.load()
        self.assertFalse(self.cache.status()["ready"])

    def test_cross_process_lease_blocks_second_cache(self):
        self.cache.start("full", None, "source")
        other = Cache(self.cache.path)
        with self.assertRaises(BusyError):
            other.start("full", None, "source")

    def test_expired_lease_owner_cannot_publish(self):
        run = self.cache.start("full", None, "source")
        with self.cache.connect() as db:
            db.execute("UPDATE lease SET expires=0")
        self.cache.start("full", None, "source")
        with self.assertRaises(BusyError):
            self.cache.publish(run, "source", "2026-01-01T00:00:00+00:00")

    def test_unknown_sqlite_is_not_migrated(self):
        path = self.root / "unrelated.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute("CREATE TABLE unrelated(id INTEGER)")
        with self.assertRaises(RuntimeError):
            Cache(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall(),
                [("unrelated",)],
            )

    def test_source_change_requires_separate_cache(self):
        self.load()
        settings = Settings(
            base_url="http://other.invalid", api_token="synthetic", page_size=2
        )
        with self.assertRaises(RuntimeError):
            Synchronizer(settings, self.cache, self.client).run("full")

    def test_cache_contains_no_prompt_or_attachment_paths(self):
        self.client.items[0]["content"] = "PRIVATE_SYNTHETIC_PROMPT_12345"
        self.client.items[0]["files"] = [{"path": "PRIVATE_SYNTHETIC_FILE_PATH_12345"}]
        self.load()
        dumped = json.dumps(self.cache.read())
        self.assertNotIn("PRIVATE_SYNTHETIC", dumped)
        self.assertNotIn("synthetic-secret", dumped)

    def test_timezone_and_exclusive_end(self):
        def epoch(s):
            return datetime.fromisoformat(s).timestamp()

        self.client.items = [
            message("before", created=epoch("2026-01-01T14:59:59+00:00")),
            message("inside", created=epoch("2026-01-01T15:00:00+00:00")),
            message("after", created=epoch("2026-01-02T15:00:00+00:00")),
        ]
        self.load()
        result = user_usage(
            self.cache, self.settings, start="2026-01-02", end="2026-01-02"
        )
        self.assertEqual(result["summary"]["questions"], 1)
        self.assertEqual(result["daily"], [{"date": "2026-01-02", "questions": 1}])

    def test_zero_leaders_org_mapping_and_csv_only_exclusion(self):
        path = self.root / "org.csv"
        path.write_text(
            "이름,실,팀,직급,사용자 ID\nSynthetic 1,본부A,팀A,연구원,u1\nSynthetic 2,본부A,팀B,팀장,u2\nSynthetic 3,본부B,팀C,팀장,u3\nOnly CSV,본부Z,팀Z,팀장,csv-only\n",
            encoding="utf-8-sig",
        )
        settings = Settings(org_csv=path)
        self.load()
        result = user_usage(
            self.cache, settings, range_value="all", view="leader", page_size=1
        )
        self.assertEqual(result["detail"]["total"], 2)
        self.assertEqual(result["summary"]["zeroUsageUsers"], 2)
        self.assertNotIn("팀Z", result["filters"]["teams"])
        result2 = user_usage(
            self.cache, settings, range_value="all", view="leader", page=2, page_size=1
        )
        self.assertEqual(result2["detail"]["records"][0]["questions"], 0)

    def test_org_reloaded_without_resync(self):
        path = self.root / "org.csv"
        path.write_text("이름,실,팀,직급\nSynthetic 1,A,old,팀장\n", encoding="utf-8")
        settings = Settings(org_csv=path)
        self.load()
        self.assertEqual(
            user_usage(self.cache, settings, range_value="all")["detail"]["records"][0][
                "team"
            ],
            "old",
        )
        path.write_text("이름,실,팀,직급\nSynthetic 1,A,new,팀장\n", encoding="utf-8")
        self.assertEqual(
            user_usage(self.cache, settings, range_value="all")["detail"]["records"][0][
                "team"
            ],
            "new",
        )

    def test_duplicate_names_are_not_guessed(self):
        people = [{"id": "a", "name": "same"}, {"id": "b", "name": "same"}]
        records = [
            {"id": "", "name": "same", "division": "A", "team": "T", "position": "팀장"}
        ]
        result = enrich(people, records)
        self.assertTrue(all(u["mapping"] == "동명이인 확인 필요" for u in result))
        records[0]["id"] = "a"
        result = enrich(people, records)
        self.assertEqual(result[0]["mapping"], "매핑 완료")

    def test_cp949_and_bad_csv(self):
        path = self.root / "org.csv"
        path.write_bytes("이름,실,팀,직급\n가상,A,가상팀,팀장\n".encode("cp949"))
        self.assertEqual(load_org(path)[0][0]["team"], "가상팀")
        path.write_text("wrong,header\na,b\n")
        with self.assertRaises(MappingError):
            load_org(path)

    def test_http_api_contract_auth_and_validation(self):
        self.load()
        secured = Settings(dashboard_token="synthetic-dashboard-token")
        client = TestClient(create_app(secured, self.cache))
        self.assertEqual(client.get("/api/dashboard/v2/users").status_code, 401)
        headers = {"Authorization": "Bearer synthetic-dashboard-token"}
        self.assertEqual(
            client.get("/api/dashboard/v2/health", headers=headers).json()["ready"],
            True,
        )
        response = client.get(
            "/api/dashboard/v2/users?range=all&pageSize=2", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"]["total"], 3)
        self.assertEqual(len(response.json()["detail"]["records"]), 2)
        self.assertEqual(
            client.get(
                "/api/dashboard/v2/users?start=2026-02-01", headers=headers
            ).status_code,
            422,
        )

        self.assertEqual(
            client.get(
                "/api/dashboard/v2/users?range=invalid", headers=headers
            ).status_code,
            422,
        )
        self.assertEqual(
            client.get(
                "/api/dashboard/v2/users?view=invalid", headers=headers
            ).status_code,
            422,
        )
        self.assertEqual(
            client.get(
                "/api/dashboard/v2/users?pageSize=1001", headers=headers
            ).status_code,
            422,
        )

    def test_csv_export_is_full_authenticated_and_formula_safe(self):
        import csv

        self.client.people = [
            {
                "id": f"export-{i}",
                "name": "=FORMULA" if i == 0 else f"Synthetic {i}",
                "email": "",
                "role": "user",
            }
            for i in range(1005)
        ]
        self.client.items = []
        self.load()
        client = TestClient(create_app(Settings(dashboard_token="test"), self.cache))
        url = "/api/dashboard/v2/users/export?range=all&page=2&pageSize=10"
        self.assertEqual(client.get(url).status_code, 401)
        result = client.get(url, headers={"Authorization": "Bearer test"})
        self.assertEqual(result.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(result.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1005)
        self.assertTrue(all(r["질문 수"] == "0" for r in rows))
        self.assertIn("'=FORMULA", [r["사용자명"] for r in rows])
        self.assertEqual(result.headers["cache-control"], "no-store")

    def test_static_frontend_and_api_share_origin(self):
        directory = self.root / "frontend"
        directory.mkdir()
        (directory / "index.html").write_text("<h1>synthetic UI</h1>")
        with patch.dict("os.environ", {"DASHBOARD_FRONTEND_DIR": str(directory)}):
            client = TestClient(create_app(self.settings, self.cache))
            self.assertEqual(client.get("/").status_code, 200)
            self.assertIn("synthetic UI", client.get("/").text)
            self.assertEqual(client.get("/api/dashboard/v2/health").status_code, 200)
            self.assertEqual(client.get("/api/dashboard/v2/users").status_code, 503)


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())


class ClientTests(unittest.TestCase):
    def settings(self, retries=0):
        return Settings(
            base_url="https://example.invalid",
            api_token="NEVER_PRINT_THIS",
            retries=retries,
            page_size=100,
        )

    def test_users_all_contract_complete(self):
        opener = Opener(
            [
                {
                    "users": [
                        {"id": "a", "name": "Synthetic", "email": "a@example.invalid"}
                    ],
                    "total": 1,
                }
            ]
        )
        client = OpenWebUIClient(self.settings(), opener)
        self.assertEqual(len(client.users()), 1)
        self.assertTrue(opener.requests[0].full_url.endswith("/api/v1/users/all"))
        self.assertEqual(
            opener.requests[0].get_header("Authorization"), "Bearer NEVER_PRINT_THIS"
        )

    def test_incomplete_roster_and_duplicate_ids_rejected(self):
        user = {"id": "a", "name": "Synthetic", "email": "a@example.invalid"}
        for result in (
            {"users": [user], "total": 2},
            {"users": [user, user], "total": 2},
        ):
            with self.assertRaises(ContractError):
                OpenWebUIClient(self.settings(), Opener([result])).users()

    def test_retry_429_and_redact_auth_error(self):
        error = HTTPError(
            "https://example.invalid?secret=NEVER_PRINT_THIS",
            429,
            "NEVER_PRINT_THIS",
            {"Retry-After": "0"},
            io.BytesIO(b"NEVER_PRINT_THIS"),
        )
        client = OpenWebUIClient(
            self.settings(1), Opener([error, []]), sleep=lambda _: None
        )
        self.assertEqual(client.messages("user-with-space &", 100), [])
        self.assertNotIn("user-with-space &", client.opener.requests[1].full_url)
        error = HTTPError(
            "https://example.invalid",
            403,
            "NEVER_PRINT_THIS",
            {},
            io.BytesIO(b"NEVER_PRINT_THIS"),
        )
        with self.assertRaises(UpstreamError) as caught:
            OpenWebUIClient(self.settings(3), Opener([error])).users()
        self.assertNotIn("NEVER_PRINT_THIS", str(caught.exception))

    def test_ok_false_is_error_even_on_successful_transport(self):
        with self.assertRaises(UpstreamError):
            OpenWebUIClient(
                self.settings(), Opener([{"ok": False, "error": "secret"}])
            ).users()

    def test_no_credentials_in_url_or_repr(self):
        self.assertNotIn("NEVER_PRINT_THIS", repr(self.settings()))
        for url in (
            "https://user:pass@example.invalid",
            "https://example.invalid?key=secret",
            "file:///example",
        ):
            with self.assertRaises(ValueError):
                Settings(base_url=url)

    def test_connection_errors_sanitized(self):
        with self.assertRaises(UpstreamError) as caught:
            OpenWebUIClient(
                self.settings(), Opener([URLError("NEVER_PRINT_THIS")])
            ).users()
        self.assertNotIn("NEVER_PRINT_THIS", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
