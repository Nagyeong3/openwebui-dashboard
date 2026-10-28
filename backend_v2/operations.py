"""Durable orchestration of existing collectors. Each source retains its own watermark."""
import json
import time
import uuid
from threading import Event, Thread
from .cache import Cache, BusyError, now_iso
from .client import UpstreamError
from .sync import Synchronizer
from .token_store import TokenStore
from .token_sync import prepare as token_prepare, collect as token_collect
from .category_store import CategoryStore
from .category_sync import prepare as category_prepare, collect as category_collect, configuration
from .categories import taxonomy, profile
from .category_store import key as category_key

APP_ID = 0x4F574F32
STEPS = ('openwebui', 'tokens', 'categories')


class OperationsStore:
    connect = Cache.connect

    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if (tables and (app != APP_ID or version != 1)) or (not tables and version not in (0, 1)):
                raise ValueError('Unsupported operations DB; preserve this file and select a separate OPERATIONS_CACHE_DB_PATH')
            db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS operation_runs(id TEXT PRIMARY KEY,kind TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS operation_steps(run_id TEXT,name TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT,source_id TEXT,stats TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(run_id,name));
PRAGMA user_version=1;''')
            db.execute(f'PRAGMA application_id={APP_ID}')

    def start(self, kind):
        if kind not in ('quick', 'full', 'classify'):
            raise ValueError('Operation kind must be quick, full or classify')
        run = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM operation_runs WHERE status='running' AND expires>?", (time.time(),)).fetchone():
                raise BusyError('An operation is already running')
            db.execute("UPDATE operation_steps SET status='interrupted',finished_at=? WHERE status='running' AND run_id IN (SELECT id FROM operation_runs WHERE status='running')", (now_iso(),))
            db.execute("UPDATE operation_runs SET status='interrupted',finished_at=?,error='Server stopped or operation lease expired' WHERE status='running'", (now_iso(),))
            db.execute("INSERT INTO operation_runs VALUES(?,?,'running',?,NULL,NULL,?)", (run, kind, now_iso(), time.time()+600))
            db.executemany("INSERT INTO operation_steps(run_id,name,status) VALUES(?,?,'waiting')", [(run, s) for s in STEPS])
        return run

    def heartbeat(self, run):
        with self.connect() as db:
            count = db.execute("UPDATE operation_runs SET expires=? WHERE id=? AND status='running' AND expires>?", (time.time()+600, run, time.time())).rowcount
            if not count:
                raise BusyError('Operation lease expired')

    def step(self, run, name, status, *, source_id=None, stats=None, error=None):
        self.heartbeat(run)
        with self.connect() as db:
            current = db.execute('SELECT * FROM operation_steps WHERE run_id=? AND name=?', (run, name)).fetchone()
            db.execute('UPDATE operation_steps SET status=?,started_at=?,finished_at=?,source_id=?,stats=?,error=? WHERE run_id=? AND name=?',
                       (status, current['started_at'] or (now_iso() if status == 'running' else None),
                        None if status == 'running' else now_iso(), source_id or current['source_id'],
                        json.dumps(stats if stats is not None else json.loads(current['stats'])), error, run, name))

    def finish(self, run, status, error=None):
        self.heartbeat(run)
        with self.connect() as db:
            db.execute('UPDATE operation_runs SET status=?,finished_at=?,error=?,expires=0 WHERE id=?', (status, now_iso(), error, run))

    def read(self, run=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM operation_runs '+('WHERE id=? ' if run else '')+'ORDER BY started_at DESC LIMIT 20', (run,) if run else ()).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                if r['status']=='running' and r['expires']<=time.time():
                    r['status']='interrupted'
                del r['expires']
                r['steps'] = []
                for name in STEPS:
                    step = dict(db.execute('SELECT * FROM operation_steps WHERE run_id=? AND name=?', (r['id'], name)).fetchone())
                    step['stats']=json.loads(step['stats'])
                    if r['status']=='interrupted' and step['status']=='running':
                        step['status']='interrupted'
                    r['steps'].append(step)
                result.append(r)
        return result


def safe_error(error):
    return str(error) if isinstance(error, (ValueError, UpstreamError, BusyError)) else 'Step failed; check the corresponding collector status. Completed data is preserved.'


def prepare(settings, cache, store, kind='quick'):
    # Source locks remain authoritative, including collectors started from CLI.
    sources = [cache.status(), TokenStore(settings.token_cache_path).status(), CategoryStore(settings.category_cache_path).status()]
    if any(s['activeRunId'] for s in sources):
        raise BusyError('A data, token or category job is already running; wait for it to finish')
    return store.start(kind)


def question_hashes(cache):
    with cache.connect() as db:
        return dict(db.execute("SELECT id,content_hash FROM messages WHERE role='user'"))


def execute(settings, cache, store, run, *, owui_client=None, spend_client=None, classifier=None):
    job = store.read(run)[0]
    stopped, lost = Event(), Event()

    def renew():
        while not stopped.wait(15):
            try:
                store.heartbeat(run)
            except Exception:
                lost.set()
                return
    worker = Thread(target=renew, daemon=True, name='operation-lease')
    worker.start()
    outcomes = []
    try:
        for name in STEPS:
            if lost.is_set():
                raise BusyError('Operation lease lost')
            if job['kind']=='classify' and name!='categories':
                store.step(run,name,'skipped')
                continue
            store.step(run,name,'running')
            try:
                if name=='openwebui':
                    before = question_hashes(cache)
                    class BoundCache:
                        def __getattr__(self, key):
                            return getattr(cache,key)
                        def start(self, *args, **kwargs):
                            source_id = cache.start(*args, **kwargs)
                            store.step(run,'openwebui','running',source_id=source_id)
                            return source_id
                        def stage_users(self, source_id, users):
                            cache.stage_users(source_id,users)
                            store.step(run,'openwebui','running',stats={'usersTotal':len(users)})
                    result = Synchronizer(settings,BoundCache(),owui_client).run(job['kind'])
                    after = question_hashes(cache)
                    stats = {'newQuestions':len(after.keys()-before.keys()), 'updatedQuestions':sum(after[k]!=before[k] for k in after.keys()&before.keys()),
                             'deletedQuestions':len(before.keys()-after.keys()), 'usersDone':result['users'], 'usersTotal':result['users'], 'messagesSeen':result['messages'], 'mode':result['kind']}
                    state = 'success'
                elif name=='tokens':
                    db = TokenStore(settings.token_cache_path)
                    source_id = token_prepare(settings,db,job['kind'])
                    store.step(run,name,'running',source_id=source_id)
                    token_collect(settings,db,source_id,spend_client)
                    native = next(r for r in db.status()['runs'] if r['id']==source_id)
                    stats = {k:native[k] for k in ('scanned','saved','skipped','pages','start','end')}
                    stats['mode']=native['kind']
                    state = 'success'
                else:
                    db = CategoryStore(settings.category_cache_path)
                    source_id = category_prepare(settings,cache,db,'pending')
                    store.step(run,name,'running',source_id=source_id)
                    category_collect(settings,cache,db,source_id,owui_client,classifier)
                    native = next(r for r in db.status()['runs'] if r['id']==source_id)
                    stats = {k:native[k] for k in ('total','processed','calls','reused','unavailable','window_size')}
                    state = native['status']
                store.step(run,name,state,stats=stats)
                outcomes.append(state)
            except Exception as error:
                message = safe_error(error)
                stats = None
                # Native collectors persist sanitized errors/progress. Bind by ID,
                # so an unrelated standalone job cannot replace this stage's error.
                try:
                    owned = next(s for s in store.read(run)[0]['steps'] if s['name']==name)
                    native_db = cache if name=='openwebui' else TokenStore(settings.token_cache_path) if name=='tokens' else CategoryStore(settings.category_cache_path)
                    native = next((r for r in native_db.status()['runs'] if r['id']==owned['source_id']),None)
                    if native:
                        message = native.get('error') or message
                        if name=='openwebui':
                            stats={**owned['stats'],'usersDone':native['users_done'],'messagesSeen':native['messages_seen']}
                        else:
                            fields=('scanned','saved','skipped','pages') if name=='tokens' else ('total','processed','calls','reused','unavailable','window_size')
                            stats={k:native[k] for k in fields}
                except Exception:
                    pass
                store.step(run,name,'failed',error=message,stats=stats)
                outcomes.append('failed')
                if name=='openwebui':
                    for later in ('tokens','categories'):
                        store.step(run,later,'skipped',error='OpenWebUI collection failed; previous successful data preserved')
                    store.finish(run,'failed',message)
                    return store.read(run)[0]
        final = 'success' if all(s=='success' for s in outcomes) else 'cancelled' if outcomes and outcomes[-1]=='cancelled' and 'failed' not in outcomes else 'partial'
        store.finish(run,final)
        return store.read(run)[0]
    except Exception:
        try:
            store.finish(run,'failed','Operation interrupted; completed source data is preserved')
        except BusyError:
            pass
        return store.read(run)[0]
    finally:
        stopped.set()
        worker.join(timeout=1)


def live_steps(job, cache, settings):
    if job['status']!='running':
        return job
    for step in job['steps']:
        if step['status']!='running' or not step['source_id']:
            continue
        if step['name']=='openwebui':
            native=next((r for r in cache.status()['runs'] if r['id']==step['source_id']),None)
            if native:
                step['stats'].update(usersDone=native['users_done'],messagesSeen=native['messages_seen'])
        else:
            db = TokenStore(settings.token_cache_path) if step['name']=='tokens' else CategoryStore(settings.category_cache_path)
            native=next((r for r in db.status()['runs'] if r['id']==step['source_id']),None)
            if native:
                keys=('scanned','saved','skipped','pages') if step['name']=='tokens' else ('total','processed','calls','reused','unavailable','stop_requested')
                step['stats'].update({k:native[k] for k in keys})
    return job


def summary(settings, cache, store):
    data=cache.status()
    tokens=TokenStore(settings.token_cache_path).status()
    categories=CategoryStore(settings.category_cache_path).status()
    configured=bool(settings.litellm_url and settings.litellm_key and settings.litellm_alias and settings.litellm_start_date)
    try:
        configuration(settings)
        category_configured=True
    except ValueError:
        category_configured=False
    category_counts = {'questions':None,'pending':None,'classified':None}
    if data['ready']:
        try:
            definitions=taxonomy(settings.category_csv)
            decisions=CategoryStore(settings.category_cache_path).read(profile(settings,definitions))
            with cache.connect() as db:
                rows=db.execute("SELECT content_hash,has_files,COUNT(*) AS count FROM messages WHERE role='user' GROUP BY content_hash,has_files").fetchall()
            total=pending=classified=0
            other=any(d['category']=='기타' for d in definitions)
            for row in rows:
                decision=decisions.get(category_key(row))
                total+=row['count']
                if not decision:
                    pending+=row['count']
                elif decision['state']=='classified' or (other and decision['state'] in ('uncertain','fallback')):
                    classified+=row['count']
            category_counts={'questions':total,'pending':pending,'classified':classified}
        except (ValueError,RuntimeError):
            pass
    jobs=store.read()
    for job in jobs:
        live_steps(job,cache,settings)
    active=next((j['id'] for j in jobs if j['status']=='running'),None)
    return {'schemaVersion':1, 'activeRunId':active, 'runs':jobs,
            'sources':{'openwebui':{'ready':data['ready'],'configured':bool(settings.base_url and settings.api_token),'lastSuccess':data['lastSuccess'],'users':data['users'],'messages':data['messages'],'activeRunId':data['activeRunId']},
                       'tokens':{'ready':tokens['ready'],'configured':configured,'lastSuccess':tokens['lastSuccess'],'logs':tokens['logs'],'activeRunId':tokens['activeRunId']},
                       'categories':{**category_counts,'configured':category_configured,'activeRunId':categories['activeRunId'],'lastRun':categories['runs'][0] if categories['runs'] else None}},
            'overlap':{'openwebuiDays':settings.overlap_days,'litellmHours':settings.litellm_lookback_hours}}
