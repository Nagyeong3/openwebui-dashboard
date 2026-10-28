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
            db.execute('CREATE TABLE IF NOT EXISTS category_targets(run_id TEXT,fingerprint TEXT,done INTEGER DEFAULT 0,PRIMARY KEY(run_id,fingerprint))')
            db.execute('CREATE TABLE IF NOT EXISTS category_overrides(profile TEXT,message_key TEXT,content_key TEXT,category TEXT,updated_at TEXT,PRIMARY KEY(profile,message_key))')
            # Add progress/cancellation metadata to recognized v2 databases only.
            columns = {r[1] for r in db.execute('PRAGMA table_info(category_runs)')}
            for name, declaration in (('total','INTEGER DEFAULT 0'),('stop_requested','INTEGER DEFAULT 0'),('window_size','INTEGER DEFAULT 200'),('pause_requested','INTEGER DEFAULT 0'),('initialized','INTEGER DEFAULT 0')):
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
        return {'pausedRunId':next((r['id'] for r in runs if r['status']=='paused'),None),'activeRunId': next((r['id'] for r in runs if r['status']=='running'),None), 'runs':runs}

    def start(self, profile, kind, window_size=200):
        run = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM category_runs WHERE (status='running' AND expires>?) OR status='paused'",(time.time(),)).fetchone():
                raise BusyError('진행 중이거나 일시 중단한 분류가 있습니다.')
            db.execute("UPDATE category_runs SET status='interrupted',finished_at=?,error='Previous classification interrupted' WHERE status='running'",(now_iso(),))
            db.execute("INSERT INTO category_runs(id,profile,kind,status,started_at,expires,window_size) VALUES(?,?,?,'running',?,?,?)",(run,profile,kind,now_iso(),time.time()+600,window_size))
        return run

    def progress(self, run, processed, calls, reused, unavailable, decisions=(), done=()):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM category_runs WHERE id=? AND status='running' AND expires>?",(run,time.time())).fetchone()
            if not job:
                raise BusyError('Category worker lease expired')
            db.executemany('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?)',[(job['profile'],*d,now_iso()) for d in decisions])
            db.executemany('UPDATE category_targets SET done=1 WHERE run_id=? AND fingerprint=?',[(run,f) for f in done])
            db.execute('UPDATE category_runs SET processed=?,calls=?,reused=?,unavailable=?,expires=? WHERE id=?',(processed,calls,reused,unavailable,time.time()+600,run))

    def targets(self, run, fingerprints):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT initialized FROM category_runs WHERE id=?',(run,)).fetchone()
            if not row['initialized']:
                db.executemany('INSERT OR IGNORE INTO category_targets(run_id,fingerprint) VALUES(?,?)',[(run,f) for f in fingerprints])
                db.execute('UPDATE category_runs SET initialized=1,total=? WHERE id=?',(len(fingerprints),run))
            return {r[0] for r in db.execute('SELECT fingerprint FROM category_targets WHERE run_id=? AND done=0',(run,))}

    def request_pause(self, expected_run=None):
        with self.connect() as db:
            row=db.execute("SELECT id FROM category_runs WHERE status='running' AND expires>?"+(' AND id=?' if expected_run else ''),(time.time(),expected_run) if expected_run else (time.time(),)).fetchone()
            if not row:
                raise BusyError('진행 중인 분류가 없습니다.')
            db.execute('UPDATE category_runs SET pause_requested=1 WHERE id=?',(row[0],))
            return row[0]

    def pause(self, run):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET status='paused',pause_requested=0,expires=0 WHERE id=? AND status='running'",(run,))

    def resume(self, run, expected_profile):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM category_runs WHERE id=?',(run,)).fetchone()
            if not row or row['profile']!=expected_profile:
                raise ValueError('분류 기준이 변경되었습니다. 중단한 뒤 새 분류를 시작하세요.')
            if row['status'] not in ('paused','running','interrupted') or (row['status']=='running' and row['expires']>time.time()):
                raise BusyError('이 분류는 계속할 수 없습니다.')
            if db.execute("SELECT 1 FROM category_runs WHERE id<>? AND ((status='running' AND expires>?) OR status='paused')",(run,time.time())).fetchone():
                raise BusyError('다른 분류 작업이 있습니다.')
            if not row['initialized']:
                db.execute('UPDATE category_runs SET processed=0,calls=0,reused=0,unavailable=0 WHERE id=?',(run,))
            db.execute("UPDATE category_runs SET status='running',pause_requested=0,stop_requested=0,error=NULL,finished_at=NULL,expires=? WHERE id=?",(time.time()+600,run))

    def overrides(self, version):
        with self.connect() as db:
            return {r['message_key']:dict(r) for r in db.execute('SELECT * FROM category_overrides ORDER BY updated_at',())}

    def set_override(self, version, message_key, content_key, category):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO category_overrides VALUES(?,?,?,?,?)',(version,message_key,content_key,category,now_iso()))

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
            r = db.execute("SELECT id FROM category_runs WHERE status IN ('running','paused','interrupted')" + (" AND id=?" if expected_run else "") + ' ORDER BY started_at DESC LIMIT 1', (expected_run,) if expected_run else ()).fetchone()
            if not r:
                raise BusyError('진행 중인 분류가 없습니다.')
            db.execute('UPDATE category_runs SET stop_requested=1 WHERE id=?',(r[0],))
            return r[0]

    def cancel(self, run):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET status='cancelled',finished_at=?,expires=0 WHERE id=? AND status IN ('running','paused','interrupted')",(now_iso(),run))

    def finish(self, run, error=None, status="success"):
        with self.connect() as db:
            db.execute("UPDATE category_runs SET status=?,finished_at=?,error=?,expires=0 WHERE id=? AND status='running'",('failed' if error else status,now_iso(),error,run))
