"""Dedicated resumable category cache; compatible result batches survive later failures."""
import time
import uuid
from .cache import Cache, BusyError, now_iso
from .categories import digest

APP_ID = 0x4F574332


def key(message):
    return digest([message['content_hash'], bool(message['has_files'])])


class CategoryStore:
    connect = Cache.connect

    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if (tables and (app != APP_ID or version != 1)) or (not tables and version not in (0,1)):
                raise RuntimeError('Unsupported category cache; preserve legacy DB and use a new CATEGORY_CACHE_DB_PATH')
            db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS decisions(profile TEXT,key TEXT,category TEXT,confidence REAL,state TEXT,truncated INTEGER,updated_at TEXT,PRIMARY KEY(profile,key));
CREATE TABLE IF NOT EXISTS category_runs(id TEXT PRIMARY KEY,profile TEXT,kind TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT,processed INTEGER DEFAULT 0,calls INTEGER DEFAULT 0,reused INTEGER DEFAULT 0,unavailable INTEGER DEFAULT 0,expires REAL);
PRAGMA user_version=1;''')
            db.execute(f'PRAGMA application_id={APP_ID}')
            # Add progress/cancellation metadata to recognized v2 databases only.
            columns = {r[1] for r in db.execute('PRAGMA table_info(category_runs)')}
            for name, declaration in (('total','INTEGER DEFAULT 0'),('stop_requested','INTEGER DEFAULT 0'),('window_size','INTEGER DEFAULT 200')):
                if name not in columns:
                    db.execute(f'ALTER TABLE category_runs ADD COLUMN {name} {declaration}')

    def read(self, profile):
        with self.connect() as db:
            return {r['key']:dict(r) for r in db.execute('SELECT * FROM decisions WHERE profile=?',(profile,))}

    def status(self):
        with self.connect() as db:
            runs = [dict(r) for r in db.execute('SELECT * FROM category_runs ORDER BY started_at DESC LIMIT 10')]
        for r in runs:
            if r['status']=='running' and r['expires']<=time.time():
                r['status']='interrupted'
            del r['expires']
            del r['profile']
            done = r['processed'] + r['unavailable']
            r['chunksDone'] = (done + r['window_size'] - 1)//r['window_size'] if r['status'] in ('success','partial') else done//r['window_size']
        return {'activeRunId': next((r['id'] for r in runs if r['status']=='running'),None), 'runs':runs}

    def start(self, profile, kind, window_size=200):
        run = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM category_runs WHERE status='running' AND expires>?",(time.time(),)).fetchone():
                raise BusyError('Category classification is already running')
            db.execute("UPDATE category_runs SET status='interrupted',finished_at=?,error='Previous classification interrupted' WHERE status='running'",(now_iso(),))
            db.execute("INSERT INTO category_runs(id,profile,kind,status,started_at,expires,window_size) VALUES(?,?,?,'running',?,?,?)",(run,profile,kind,now_iso(),time.time()+600,window_size))
        return run

    def progress(self, run, processed, calls, reused, unavailable, decisions=()):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM category_runs WHERE id=? AND status='running' AND expires>?",(run,time.time())).fetchone()
            if not job:
                raise BusyError('Category worker lease expired')
            db.executemany('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?)',[(job['profile'],*d,now_iso()) for d in decisions])
            db.execute('UPDATE category_runs SET processed=?,calls=?,reused=?,unavailable=?,expires=? WHERE id=?',(processed,calls,reused,unavailable,time.time()+600,run))

    def set_total(self, run, total):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET total=? WHERE id=? AND status='running'",(total,run))

    def stopped(self, run):
        with self.connect() as db:
            r = db.execute("SELECT stop_requested FROM category_runs WHERE id=?",(run,)).fetchone()
            return bool(r and r[0])

    def request_stop(self, expected_run=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            r = db.execute("SELECT id FROM category_runs WHERE status='running' AND expires>?" + (" AND id=?" if expected_run else ""), (time.time(),expected_run) if expected_run else (time.time(),)).fetchone()
            if not r:
                raise BusyError('No active category classification')
            db.execute('UPDATE category_runs SET stop_requested=1 WHERE id=?',(r[0],))
            return r[0]

    def cancel(self, run):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET status='cancelled',finished_at=?,expires=0 WHERE id=? AND status='running'",(now_iso(),run))

    def finish(self, run, error=None, status="success"):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET status=?,finished_at=?,error=?,expires=0 WHERE id=? AND status='running'",('failed' if error else status,now_iso(),error,run))
