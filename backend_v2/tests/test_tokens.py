import copy, json, sqlite3, tempfile, time, unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from backend_v2.tests.test_backend import FakeClient, Opener
from backend_v2.settings import Settings
from backend_v2.cache import Cache, BusyError
from backend_v2.sync import Synchronizer
from backend_v2.app import create_app
from backend_v2.token_store import TokenStore
from backend_v2.token_sync import SpendClient, prepare, collect, normalize
from backend_v2.token_analytics import token_usage


def log(i, alias="OUI-test", **extra):
    return {
        "request_id": str(i),
        "startTime": datetime.now(timezone.utc).isoformat(),
        "model_group": "synthetic-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "spend": 0.002,
        "end_user": "u1",
        "metadata": {"user_api_key_alias": alias},
        **extra,
    }


class FakeSpend:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.fail = False

    def page(self, start, end, page):
        self.calls.append((start, end, page))
        if self.fail:
            raise RuntimeError("Synthetic fetch failure")
        from backend_v2.token_sync import timestamp

        rows = [
            r for r in self.rows if start <= timestamp(r["startTime"], "UTC") <= end
        ]
        return copy.deepcopy(rows[(page - 1) * 2 : page * 2])


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(
            base_url="http://example.invalid",
            api_token="synthetic",
            cache_path=self.root / "users.sqlite3",
            token_cache_path=self.root / "tokens.sqlite3",
            litellm_url="http://litellm.invalid",
            litellm_key="synthetic-token-secret",
            litellm_alias="OUI-test",
            litellm_page_size=2,
            litellm_start_date=datetime.now(timezone.utc).date().isoformat(),
        )
        self.cache = Cache(self.settings.cache_path)
        Synchronizer(self.settings, self.cache, FakeClient()).run("full")
        self.store = TokenStore(self.settings.token_cache_path)
        self.rows = [
            log(
                i,
                startTime=datetime.fromtimestamp(
                    int(time.time()) - 10 - i, timezone.utc
                ).isoformat(),
            )
            for i in range(4)
        ]

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, rows=None, kind="full"):
        run = prepare(self.settings, self.store, kind)
        collect(
            self.settings,
            self.store,
            run,
            FakeSpend(self.rows if rows is None else rows),
        )
        return run

    def test_pagination_alias_idempotence_and_no_secrets(self):
        self.rows.append(
            log("other", alias="category-key", startTime=self.rows[0]["startTime"])
        )
        self.run_sync()
        first = token_usage(self.cache, self.settings, range_value="all")
        self.assertEqual(first["summary"]["requests"], 4)
        self.assertEqual(first["summary"]["total"], 60)
        self.assertEqual(first["summary"]["users"], 1)
        self.run_sync(kind="quick")
        self.assertEqual(self.store.status()["logs"], 4)
        with self.store.connect() as db:
            text = "\n".join(db.iterdump())
        self.assertNotIn("synthetic-token-secret", text)
        self.assertNotIn("category-key", text)

    def test_failed_sync_atomicity_busy_and_source_change(self):
        self.run_sync()
        run = prepare(self.settings, self.store)
        with self.assertRaises(BusyError):
            prepare(self.settings, self.store)
        client = FakeSpend(self.rows)
        client.fail = True
        with self.assertRaises(RuntimeError):
            collect(self.settings, self.store, run, client)
        self.assertEqual(self.store.status()["logs"], 4)
        self.assertTrue(self.store.status()["ready"])
        with self.assertRaises(ValueError):
            prepare(replace(self.settings, litellm_alias="changed"), self.store)

    def test_missing_spend_csv_estimate_and_real_zero(self):
        path = self.root / "prices.csv"
        path.write_text(
            "model,input_per_million_usd,output_per_million_usd\nsynthetic-model,2,4\n",
            encoding="utf-8-sig",
        )
        rows = [{**self.rows[0], "spend": None}, {**self.rows[1], "spend": 0}]
        self.run_sync(rows)
        s = token_usage(self.cache, self.settings, range_value="all")["summary"]
        self.assertIsNone(s["costUsd"])
        self.assertEqual(s["missingCostRequests"], 1)
        result = token_usage(
            self.cache, replace(self.settings, model_prices_csv=path), range_value="all"
        )
        self.assertAlmostEqual(result["summary"]["costUsd"], 0.00004)
        self.assertEqual(result["summary"]["estimatedCostRequests"], 1)

    def test_key_owner_is_not_end_user_and_org_filter(self):
        self.rows[0]["end_user"] = ""
        self.rows[0]["user"] = "u1"
        self.rows[0]["metadata"]["user_api_key_user_id"] = "u1"
        self.run_sync([self.rows[0]])
        result = token_usage(self.cache, self.settings, range_value="all")
        self.assertEqual(result["summary"]["unidentifiedRequests"], 1)
        self.assertEqual(result["summary"]["total"], 15)
        self.assertEqual(result["topUsers"], [])
        self.assertEqual(
            token_usage(self.cache, self.settings, range_value="all", team="기타")[
                "summary"
            ]["requests"],
            0,
        )

    def test_identity_id_precedence_duplicate_email_and_metadata(self):
        row = {
            **self.rows[0],
            "end_user": "u1",
            "metadata": {
                "user_api_key_alias": "OUI-test",
                "openwebui_user_id": "deleted",
                "openwebui_user_email": "u1@example.invalid",
            },
        }
        self.run_sync([row])
        self.assertEqual(
            token_usage(self.cache, self.settings, range_value="all")["summary"][
                "users"
            ],
            0,
        )
        row["metadata"]["openwebui_user_id"] = "u2"
        self.run_sync([row])
        self.assertEqual(
            token_usage(self.cache, self.settings, range_value="all")["users"][0]["id"],
            "u2",
        )

    def test_repeated_pages_and_max_pages_do_not_publish(self):
        class Repeat:
            def page(_, a, b, p):
                return [self.rows[0]]

        run = prepare(self.settings, self.store)
        with self.assertRaises(RuntimeError):
            collect(self.settings, self.store, run, Repeat())
        self.assertFalse(self.store.status()["ready"])
        run = prepare(self.settings, self.store)
        with self.assertRaises(RuntimeError):
            collect(
                replace(self.settings, litellm_max_pages=1),
                self.store,
                run,
                FakeSpend(self.rows),
            )
        self.assertFalse(self.store.status()["ready"])

    def test_old_cache_protected(self):
        path = self.root / "legacy.db"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE legacy(id TEXT)")
            db.commit()
        with self.assertRaises(RuntimeError):
            TokenStore(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertIsNotNone(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name='legacy'"
                ).fetchone()
            )

    def test_full_replaces_deleted_quick_retains_unseen(self):
        self.run_sync()
        self.run_sync([self.rows[0]], "quick")
        self.assertEqual(self.store.status()["logs"], 4)
        self.run_sync([self.rows[0]], "full")
        self.assertEqual(self.store.status()["logs"], 1)

    def test_http_transport_capped_totals_date_format_and_redaction(self):
        opener = Opener(
            [
                {
                    "data": [self.rows[0]],
                    "page": 1,
                    "total": 10000,
                    "total_pages": 1,
                    "total_is_capped": True,
                }
            ]
        )
        client = SpendClient(self.settings, opener=opener)
        client.page(1, 2, 1)
        request = opener.requests[0] if hasattr(opener, "requests") else None
        if request:
            from urllib.parse import parse_qs, urlsplit

            params = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(params["page_size"], ["2"])
            self.assertNotIn("api_key", params)

    def test_api_status_auth_and_full_csv(self):
        self.run_sync()
        app = create_app(
            replace(self.settings, dashboard_token="dashboard-only"), self.cache
        )
        with TestClient(app) as c:
            self.assertEqual(c.get("/api/dashboard/v2/tokens").status_code, 401)
            h = {"Authorization": "Bearer dashboard-only"}
            p = c.get("/api/dashboard/v2/tokens?range=all&pageSize=1", headers=h).json()
            self.assertEqual(len(p["detail"]["records"]), 1)
            self.assertEqual(p["detail"]["total"], 4)
            r = c.get("/api/dashboard/v2/tokens/export?range=all", headers=h)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(r.content.decode("utf-8-sig").splitlines()), 5)
            self.assertTrue(
                c.get("/api/dashboard/v2/tokens/status", headers=h).json()["ready"]
            )
            self.assertEqual(
                c.post(
                    "/api/dashboard/v2/tokens/sync?kind=invalid", headers=h
                ).status_code,
                422,
            )
            o = c.get("/api/dashboard/v2/overview?range=all", headers=h).json()
            self.assertEqual(o["integrations"]["tokens"]["total"], 60)

    def test_async_job_acknowledgement_poll_and_busy(self):
        with TestClient(create_app(self.settings, self.cache)) as client:
            with patch("backend_v2.token_api.Thread") as thread:
                response = client.post("/api/dashboard/v2/tokens/sync")
                self.assertEqual(response.status_code, 202)
                run = response.json()["runId"]
                self.assertEqual(
                    client.get("/api/dashboard/v2/tokens/status").json()["activeRunId"],
                    run,
                )
                self.assertEqual(
                    client.post("/api/dashboard/v2/tokens/sync").status_code, 409
                )
                target = thread.call_args.kwargs["target"]
            with patch(
                "backend_v2.token_sync.SpendClient", return_value=FakeSpend(self.rows)
            ):
                target()
            state = client.get("/api/dashboard/v2/tokens/status").json()
            self.assertIsNone(state["activeRunId"])
            self.assertEqual(state["runs"][0]["status"], "success")
            self.assertEqual(state["logs"], 4)

    def test_paging_continues_past_capped_total_and_422_is_redacted(self):
        responses = [
            {
                "data": self.rows[:2],
                "page": 1,
                "total": 2,
                "total_pages": 1,
                "total_is_capped": True,
            },
            {
                "data": self.rows[2:],
                "page": 2,
                "total": 2,
                "total_pages": 1,
                "total_is_capped": True,
            },
            {"data": [], "page": 3},
        ]
        opener = Opener(responses)
        run = prepare(self.settings, self.store)
        collect(self.settings, self.store, run, SpendClient(self.settings, opener))
        self.assertEqual(self.store.status()["logs"], 4)
        self.assertEqual(len(opener.requests), 3)
        import io

        error = HTTPError(
            "http://example.invalid?api_key=PRIVATE",
            422,
            "bad",
            {},
            io.BytesIO(b"PRIVATE_BODY"),
        )
        client = SpendClient(replace(self.settings, retries=0), Opener([error]))
        with self.assertRaisesRegex(RuntimeError, "LiteLLM HTTP 422") as caught:
            client.page(1, 2, 1)
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_missing_usage_is_not_a_zero(self):
        row = {
            **self.rows[0],
            "prompt_tokens": None,
            "total_tokens": None,
            "spend": None,
            "messages": "PRIVATE_PROMPT",
        }
        self.run_sync([row])
        summary = token_usage(self.cache, self.settings, range_value="all")["summary"]
        self.assertIsNone(summary["total"])
        self.assertIsNone(summary["averagePerRequest"])
        self.assertEqual(summary["missingTokenRequests"], 1)
        with self.store.connect() as db:
            self.assertNotIn("PRIVATE_PROMPT", "\n".join(db.iterdump()))

    def test_settings_cap_and_env(self):
        env = self.root / ".env"
        env.write_text(
            "LITELLM_BASE_URL=http://litellm.invalid\nLITELLM_API_KEY=private-key\nLITELLM_REQUIRED_API_KEY_ALIAS=OUI-test\nLITELLM_LOG_LIMIT=999\nTOKEN_CACHE_DB_PATH=data/token-v2.db\n",
            encoding="utf-8-sig",
        )
        settings = Settings.from_env(env)
        self.assertEqual(settings.litellm_page_size, 100)
        self.assertNotIn("private-key", repr(settings))
        self.assertEqual(settings.token_cache_path, self.root / "data/token-v2.db")
