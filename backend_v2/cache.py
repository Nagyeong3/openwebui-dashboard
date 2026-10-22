"""Atomic staged publication, durable job state and a cross-process expiring lease."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid


class BusyError(RuntimeError):
    pass


class NotReadyError(RuntimeError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


USER_COLUMNS = "id,name,email,role"
MESSAGE_COLUMNS = "id,user_id,chat_id,role,parent_id,model_id,created_at,updated_at,has_files,content_hash,usage"
CACHE_APP_ID = 0x4F574132


class Cache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            application = db.execute("PRAGMA application_id").fetchone()[0]
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if (
                (version == 0 and tables)
                or (version == 1 and application != CACHE_APP_ID)
                or version not in (0, 1)
            ):
                raise RuntimeError(
                    "Unsupported cache schema; preserve this file and use a separate cache"
                )
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,role TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(
                    id TEXT PRIMARY KEY,user_id TEXT NOT NULL,chat_id TEXT NOT NULL,role TEXT NOT NULL,
                    parent_id TEXT,model_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,
                    has_files INTEGER NOT NULL,content_hash TEXT NOT NULL,usage TEXT);
                CREATE INDEX IF NOT EXISTS message_date ON messages(role,created_at,user_id);
                CREATE INDEX IF NOT EXISTS message_chat ON messages(chat_id);
                CREATE TABLE IF NOT EXISTS staged_users(run_id TEXT,id TEXT,name TEXT,email TEXT,role TEXT,PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS staged_messages(
                    run_id TEXT,id TEXT,user_id TEXT,chat_id TEXT,role TEXT,parent_id TEXT,model_id TEXT,
                    created_at REAL,updated_at REAL,has_files INTEGER,content_hash TEXT,usage TEXT,PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY,kind TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT,
                    users_done INTEGER DEFAULT 0,messages_seen INTEGER DEFAULT 0,cutoff REAL);
                CREATE TABLE IF NOT EXISTS lease(singleton INTEGER PRIMARY KEY CHECK(singleton=1),run_id TEXT,expires REAL);
                PRAGMA user_version=1;
            """
            )
            db.execute(f"PRAGMA application_id={CACHE_APP_ID}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def start(self, kind, cutoff, source, lease_seconds=600):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            origin = db.execute("SELECT value FROM meta WHERE key='source'").fetchone()
            if origin and origin[0] != source:
                raise RuntimeError(
                    "Upstream instance changed; select a separate DASHBOARD_CACHE_PATH"
                )
            lock = db.execute(
                "SELECT run_id,expires FROM lease WHERE singleton=1"
            ).fetchone()
            if lock and lock["expires"] > time.time():
                raise BusyError("A synchronization is already running")
            if lock:
                db.execute(
                    "UPDATE runs SET status='interrupted',finished_at=?,error='Lease expired before completion' WHERE id=? AND status='running'",
                    (now_iso(), lock["run_id"]),
                )
            db.execute("DELETE FROM staged_users")
            db.execute("DELETE FROM staged_messages")
            db.execute(
                "INSERT OR REPLACE INTO lease VALUES(1,?,?)",
                (run_id, time.time() + lease_seconds),
            )
            db.execute(
                "INSERT INTO runs(id,kind,status,started_at,cutoff) VALUES(?,?,'running',?,?)",
                (run_id, kind, now_iso(), cutoff),
            )
        return run_id

    def heartbeat(self, run_id, lease_seconds=600):
        with self.connect() as db:
            count = db.execute(
                "UPDATE lease SET expires=? WHERE singleton=1 AND run_id=?",
                (time.time() + lease_seconds, run_id),
            ).rowcount
            if not count:
                raise BusyError(
                    "Synchronization lease was lost; previous data preserved"
                )

    def stage_users(self, run_id, users):
        with self.connect() as db:
            db.executemany(
                "INSERT INTO staged_users VALUES(?,?,?,?,?)",
                [
                    (run_id, u["id"], u["name"], u["email"], u.get("role", "user"))
                    for u in users
                ],
            )

    def stage_messages(self, run_id, rows):
        with self.connect() as db:
            db.executemany(
                "INSERT INTO staged_messages VALUES("
                + ",".join("?" for _ in range(12))
                + ")",
                [(run_id, *row) for row in rows],
            )

    def progress(self, run_id, users_done, messages_seen):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET users_done=?,messages_seen=? WHERE id=?",
                (users_done, messages_seen, run_id),
            )

    def publish(self, run_id, source, collected_at):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lock = db.execute("SELECT run_id FROM lease WHERE singleton=1").fetchone()
            if not lock or lock[0] != run_id:
                raise BusyError("Synchronization lease was lost")
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            # Roster and message publication share a single transaction.
            db.execute("DELETE FROM users")
            db.execute(
                f"INSERT INTO users SELECT {USER_COLUMNS} FROM staged_users WHERE run_id=?",
                (run_id,),
            )
            if run["kind"] == "full":
                db.execute("DELETE FROM messages")
            else:
                db.execute("DELETE FROM messages WHERE created_at>=?", (run["cutoff"],))
            db.execute(
                "DELETE FROM messages WHERE user_id NOT IN (SELECT id FROM users)"
            )
            db.execute(
                f"INSERT OR REPLACE INTO messages SELECT {MESSAGE_COLUMNS} FROM staged_messages WHERE run_id=?",
                (run_id,),
            )
            for key, value in [
                ("source", source),
                ("last_success", collected_at),
                ("last_run_id", run_id),
            ]:
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
            if run["kind"] == "full":
                db.execute(
                    "INSERT OR REPLACE INTO meta VALUES('last_full',?)", (collected_at,)
                )
            db.execute(
                "UPDATE runs SET status='success',finished_at=? WHERE id=?",
                (now_iso(), run_id),
            )
            db.execute("DELETE FROM staged_users WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM staged_messages WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM lease WHERE run_id=?", (run_id,))

    def fail(self, run_id, message):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='failed',finished_at=?,error=? WHERE id=? AND status='running'",
                (now_iso(), message, run_id),
            )
            db.execute("DELETE FROM staged_users WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM staged_messages WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM lease WHERE run_id=?", (run_id,))

    def status(self):
        with self.connect() as db:
            meta = dict(db.execute("SELECT key,value FROM meta"))
            runs = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT 10"
                )
            ]
            lock = db.execute(
                "SELECT run_id,expires FROM lease WHERE singleton=1"
            ).fetchone()
            return {
                "ready": "last_success" in meta,
                "lastSuccess": meta.get("last_success"),
                "lastFullReconciliation": meta.get("last_full"),
                "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                "activeRunId": lock[0] if lock and lock[1] > time.time() else None,
                "runs": runs,
            }

    def user_ids(self):
        with self.connect() as db:
            return {row[0] for row in db.execute("SELECT id FROM users")}

    def read(self):
        with self.connect() as db:
            db.execute("BEGIN")
            meta = dict(db.execute("SELECT key,value FROM meta"))
            if "last_success" not in meta:
                raise NotReadyError(
                    "No successful API synchronization; run a full sync first"
                )
            users = [dict(r) for r in db.execute("SELECT * FROM users ORDER BY id")]
            messages = [
                dict(r)
                for r in db.execute("SELECT * FROM messages ORDER BY created_at,id")
            ]
            return users, messages, meta
