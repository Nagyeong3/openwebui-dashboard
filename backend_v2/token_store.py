"""Separate v2 spend cache. Never migrate or overwrite an unrecognized legacy DB."""

import hashlib
import json
import time
import uuid
from .cache import Cache, BusyError, NotReadyError, now_iso

APP_ID = 0x4F575432
FIELDS = (
    "id,at,model,prompt,completion,total,spend,identity_id,identity_email,identity_name"
)


def source(settings):
    return hashlib.sha256(
        json.dumps(
            [
                settings.litellm_url,
                settings.litellm_logs_path,
                settings.litellm_alias,
                settings.litellm_timezone,
            ]
        ).encode()
    ).hexdigest()


class TokenStore:
    connect = Cache.connect

    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            app = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if (tables and (app != APP_ID or version != 1)) or (
                not tables and version not in (0, 1)
            ):
                raise RuntimeError(
                    "Unsupported token cache schema; keep legacy DB and use a new TOKEN_CACHE_DB_PATH"
                )
            db.executescript(
                """PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS token_logs(id TEXT PRIMARY KEY,at REAL NOT NULL,model TEXT NOT NULL,prompt INTEGER,completion INTEGER,total INTEGER,spend REAL,identity_id TEXT,identity_email TEXT,identity_name TEXT);
CREATE INDEX IF NOT EXISTS token_date ON token_logs(at);
CREATE TABLE IF NOT EXISTS token_stage(run_id TEXT,id TEXT,at REAL,model TEXT,prompt INTEGER,completion INTEGER,total INTEGER,spend REAL,identity_id TEXT,identity_email TEXT,identity_name TEXT,PRIMARY KEY(run_id,id));
CREATE TABLE IF NOT EXISTS token_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS token_runs(id TEXT PRIMARY KEY,kind TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT,scanned INTEGER DEFAULT 0,saved INTEGER DEFAULT 0,skipped INTEGER DEFAULT 0,pages INTEGER DEFAULT 0,start REAL,end REAL,expires REAL);
PRAGMA user_version=1;"""
            )
            db.execute(f"PRAGMA application_id={APP_ID}")

    def status(self):
        with self.connect() as db:
            meta = dict(db.execute("SELECT key,value FROM token_meta"))
            runs = [
                dict(r)
                for r in db.execute(
                    "SELECT id,kind,status,started_at,finished_at,error,scanned,saved,skipped,pages,start,end,expires FROM token_runs ORDER BY started_at DESC LIMIT 10"
                )
            ]
            for r in runs:
                if r["status"] == "running" and r["expires"] < time.time():
                    r["status"] = "interrupted"
                del r["expires"]
            return {
                "ready": "last_success" in meta,
                "lastSuccess": meta.get("last_success"),
                "coverageStart": meta.get("coverage_start"),
                "lastRequestAt": db.execute(
                    "SELECT MAX(at) FROM token_logs"
                ).fetchone()[0],
                "logs": db.execute("SELECT COUNT(*) FROM token_logs").fetchone()[0],
                "runs": runs,
                "activeRunId": next(
                    (r["id"] for r in runs if r["status"] == "running"), None
                ),
            }

    def start(self, settings, kind, start, end):
        run = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            meta = dict(db.execute("SELECT key,value FROM token_meta"))
            if meta.get("source") and meta["source"] != source(settings):
                raise ValueError(
                    "LiteLLM URL/path/alias/timezone changed; use a separate token cache"
                )
            if db.execute(
                "SELECT 1 FROM token_runs WHERE status='running' AND expires>?",
                (time.time(),),
            ).fetchone():
                raise BusyError("Token synchronization is already running")
            db.execute(
                "UPDATE token_runs SET status='failed',error='Previous collection interrupted',finished_at=? WHERE status='running'",
                (now_iso(),),
            )
            db.execute("DELETE FROM token_stage")
            db.execute(
                "INSERT INTO token_runs(id,kind,status,started_at,start,end,expires) VALUES(?,?,?,?,?,?,?)",
                (run, kind, "running", now_iso(), start, end, time.time() + 600),
            )
        return run

    def stage(self, run, rows, scanned, skipped, pages):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute(
                "SELECT 1 FROM token_runs WHERE id=? AND status='running' AND expires>?",
                (run, time.time()),
            ).fetchone()
            if not owner:
                raise BusyError("Token collector lease expired")
            db.executemany(
                "INSERT OR REPLACE INTO token_stage VALUES("
                + ",".join("?" for _ in range(11))
                + ")",
                [(run, *r) for r in rows],
            )
            db.execute(
                "UPDATE token_runs SET scanned=?,skipped=?,pages=?,saved=(SELECT COUNT(*) FROM token_stage WHERE run_id=?),expires=? WHERE id=?",
                (scanned, skipped, pages, run, time.time() + 600, run),
            )

    def publish(self, settings, run):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                "SELECT * FROM token_runs WHERE id=? AND status='running' AND expires>?",
                (run, time.time()),
            ).fetchone()
            if not job:
                raise BusyError("Token collector lease expired")
            if job["kind"] == "full":
                db.execute("DELETE FROM token_logs")
            db.execute(
                f"INSERT OR REPLACE INTO token_logs({FIELDS}) SELECT {FIELDS} FROM token_stage WHERE run_id=?",
                (run,),
            )
            for k, v in {
                "source": source(settings),
                "last_success": job["started_at"],
                "coverage_start": (
                    str(job["start"])
                    if job["kind"] == "full"
                    else dict(db.execute("SELECT key,value FROM token_meta")).get(
                        "coverage_start", str(job["start"])
                    )
                ),
            }.items():
                db.execute("INSERT OR REPLACE INTO token_meta VALUES(?,?)", (k, v))
            db.execute(
                "UPDATE token_runs SET status='success',finished_at=?,expires=0 WHERE id=?",
                (now_iso(), run),
            )
            db.execute("DELETE FROM token_stage WHERE run_id=?", (run,))

    def fail(self, run, error):
        with self.connect() as db:
            db.execute(
                "UPDATE token_runs SET status='failed',error=?,finished_at=?,expires=0 WHERE id=? AND status='running'",
                (error, now_iso(), run),
            )
            db.execute("DELETE FROM token_stage WHERE run_id=?", (run,))

    def read(self, settings):
        with self.connect() as db:
            db.execute("BEGIN")
            meta = dict(db.execute("SELECT key,value FROM token_meta"))
            if "last_success" not in meta:
                raise NotReadyError(
                    "No successful LiteLLM synchronization; run token sync first"
                )
            if settings.litellm_url and meta.get("source") != source(settings):
                raise ValueError("LiteLLM source settings differ from saved cache")
            return [
                dict(r) for r in db.execute("SELECT * FROM token_logs ORDER BY at,id")
            ], meta
