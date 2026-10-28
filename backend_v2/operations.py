"""Durable orchestration of existing collectors. Each source retains its own watermark."""
import json
import time
import uuid
from threading import Event, Thread
from .cache import Cache, BusyError, now_iso
from .client import UpstreamError
from .sync import Synchronizer
from .control import JobPaused, JobCancelled, ControlledClient
from .client import OpenWebUIClient
from .token_sync import SpendClient
from .token_store import TokenStore
from .token_sync import prepare as token_prepare, collect as token_collect
from .category_store import CategoryStore
from .category_sync import prepare as category_prepare, collect as category_collect, configuration
from .categories import taxonomy, profile, digest
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
            columns={r[1] for r in db.execute('PRAGMA table_info(operation_runs)')}
            for name,declaration in (('control',"TEXT DEFAULT ''"),('parent_id','TEXT')):
                if name not in columns:
                    db.execute(f'ALTER TABLE operation_runs ADD COLUMN {name} {declaration}')

    def start(self, kind, selected=None, parent_id=None):
        if kind not in ('quick', 'full', 'classify'):
            raise ValueError('Operation kind must be quick, full or classify')
        selected=tuple((('categories',) if kind=='classify' else STEPS) if selected is None else selected)
        if not selected or len(set(selected))!=len(selected) or any(s not in STEPS for s in selected):
            raise ValueError('실행할 항목을 선택하세요.')
        run = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM operation_runs WHERE (status='running' AND expires>?) OR status='paused'", (time.time(),)).fetchone():
                raise BusyError('업데이트가 진행 중이거나 일시 중단 상태입니다.')
            db.execute("UPDATE operation_steps SET status='interrupted',finished_at=? WHERE status='running' AND run_id IN (SELECT id FROM operation_runs WHERE status='running')", (now_iso(),))
            db.execute("UPDATE operation_runs SET status='interrupted',finished_at=?,error='서버 연결이 중단되었습니다.' WHERE status='running'", (now_iso(),))
            db.execute("INSERT INTO operation_runs(id,kind,status,started_at,finished_at,error,expires,parent_id) VALUES(?,?,'running',?,NULL,NULL,?,?)", (run, kind, now_iso(), time.time()+600,parent_id))
            db.executemany("INSERT INTO operation_steps(run_id,name,status) VALUES(?,?,?)", [(run, s,'waiting' if s in selected else 'skipped') for s in STEPS])
        return run

    def request_control(self, run, command):
        if command not in ('pause','cancel'):
            raise ValueError('지원하지 않는 작업입니다.')
        with self.connect() as db:
            row=db.execute('SELECT * FROM operation_runs WHERE id=?',(run,)).fetchone()
            if not row or row['status'] not in ('running','paused','interrupted'):
                raise BusyError('진행 중인 작업이 없습니다.')
            db.execute('UPDATE operation_runs SET control=? WHERE id=?',(command,run))
            if row['status']!='running' or row['expires']<=time.time():
                db.execute("UPDATE operation_runs SET status='cancelled',finished_at=?,expires=0 WHERE id=?",(now_iso(),run))
                db.execute("UPDATE operation_steps SET status='cancelled',finished_at=? WHERE run_id=? AND status IN ('waiting','paused','interrupted','running')",(now_iso(),run))

    def check(self, run):
        with self.connect() as db:
            row=db.execute('SELECT status,control,expires FROM operation_runs WHERE id=?',(run,)).fetchone()
        if not row or row['status']!='running' or row['expires']<=time.time():
            raise BusyError('작업을 계속할 수 없습니다.')
        if row['control']=='cancel':
            raise JobCancelled()
        if row['control']=='pause':
            raise JobPaused()

    def resume(self, run):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM operation_runs WHERE id=?',(run,)).fetchone()
            if not row or row['status'] not in ('paused','interrupted','running') or (row['status']=='running' and row['expires']>time.time()):
                raise BusyError('이 작업은 계속할 수 없습니다.')
            if db.execute("SELECT 1 FROM operation_runs WHERE id<>? AND ((status='running' AND expires>?) OR status='paused')",(run,time.time())).fetchone():
                raise BusyError('다른 업데이트가 있습니다.')
            db.execute("UPDATE operation_runs SET status='running',control='',error=NULL,finished_at=NULL,expires=? WHERE id=?",(time.time()+600,run))
            # Atomic collectors safely restart their unfinished stage, not an unstable API offset.
            db.execute("UPDATE operation_steps SET status='waiting',error=NULL WHERE run_id=? AND status IN ('running','paused','interrupted')",(run,))

    def heartbeat(self, run):
        with self.connect() as db:
            count = db.execute("UPDATE operation_runs SET expires=? WHERE id=? AND status='running' AND expires>?", (time.time()+600, run, time.time())).rowcount
            if not count:
                raise BusyError('작업이 중단되었습니다. 계속하기를 눌러주세요.')

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
    return str(error) if isinstance(error, (ValueError, UpstreamError, BusyError)) else '작업에 실패했습니다. 연결 상태를 확인하세요.'


def prepare(settings, cache, store, kind='quick', selected=None, parent_id=None):
    # Source locks remain authoritative, including collectors started from CLI.
    sources = [cache.status(), TokenStore(settings.token_cache_path).status(), CategoryStore(settings.category_cache_path).status()]
    if any(s['activeRunId'] or s.get('pausedRunId') for s in sources):
        raise BusyError('다른 수집이나 분류가 진행 중입니다.')
    return store.start(kind,selected,parent_id)


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
            store.check(run)
            current=next(s for s in store.read(run)[0]['steps'] if s['name']==name)
            if current['status'] not in ('waiting','paused','interrupted'):
                if current['status']!='skipped':
                    outcomes.append(current['status'])
                continue
            if lost.is_set():
                raise BusyError('작업이 중단되었습니다. 계속하기를 눌러주세요.')
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
                    result = Synchronizer(settings,BoundCache(),ControlledClient(owui_client or OpenWebUIClient(settings),lambda:store.check(run)),check=lambda:store.check(run)).run(job['kind'])
                    after = question_hashes(cache)
                    stats = {'newQuestions':len(after.keys()-before.keys()), 'updatedQuestions':sum(after[k]!=before[k] for k in after.keys()&before.keys()),
                             'deletedQuestions':len(before.keys()-after.keys()), 'usersDone':result['users'], 'usersTotal':result['users'], 'messagesSeen':result['messages'], 'mode':result['kind']}
                    state = 'success'
                elif name=='tokens':
                    db = TokenStore(settings.token_cache_path)
                    source_id = token_prepare(settings,db,job['kind'])
                    store.step(run,name,'running',source_id=source_id)
                    token_collect(settings,db,source_id,ControlledClient(spend_client or SpendClient(settings),lambda:store.check(run)),check=lambda:store.check(run))
                    native = next(r for r in db.status()['runs'] if r['id']==source_id)
                    stats = {k:native[k] for k in ('scanned','saved','skipped','pages','start','end')}
                    stats['mode']=native['kind']
                    state = 'success'
                else:
                    db = CategoryStore(settings.category_cache_path)
                    previous=current['source_id']
                    native_previous=next((r for r in db.status()['runs'] if r['id']==previous),None)
                    if native_previous and native_previous['status'] in ('paused','interrupted'):
                        _,version=configuration(settings)
                        db.resume(previous,version)
                        source_id=previous
                    else:
                        source_id = category_prepare(settings,cache,db,'pending')
                    store.step(run,name,'running',source_id=source_id)
                    category_collect(settings,cache,db,source_id,owui_client,classifier,check=lambda:store.check(run))
                    native = next(r for r in db.status()['runs'] if r['id']==source_id)
                    stats = {k:native[k] for k in ('total','processed','calls','reused','unavailable','window_size')}
                    state = native['status']
                    if state=='paused':
                        raise JobPaused()
                    if state=='cancelled':
                        raise JobCancelled()
                store.step(run,name,state,stats=stats)
                outcomes.append(state)
            except (JobPaused,JobCancelled) as signal:
                progress=None
                owned=next(s for s in store.read(run)[0]['steps'] if s['name']==name)
                try:
                    native_db=cache if name=='openwebui' else TokenStore(settings.token_cache_path) if name=='tokens' else CategoryStore(settings.category_cache_path)
                    native=next((r for r in native_db.status()['runs'] if r['id']==owned['source_id']),None)
                    if native:
                        if name=='openwebui':
                            progress={**owned['stats'],'usersDone':native['users_done'],'messagesSeen':native['messages_seen']}
                        else:
                            fields=('scanned','saved','skipped','pages') if name=='tokens' else ('total','processed','calls','reused','unavailable','window_size')
                            progress={k:native[k] for k in fields}
                except Exception:
                    pass
                store.step(run,name,'paused' if isinstance(signal,JobPaused) else 'cancelled',stats=progress)
                raise
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
                        store.step(run,later,'skipped',error='데이터 업데이트 실패로 실행하지 않았습니다.')
                    store.finish(run,'failed',message)
                    return store.read(run)[0]
        store.check(run)
        final = 'success' if all(s=='success' for s in outcomes) else 'failed' if outcomes and all(s=='failed' for s in outcomes) else 'cancelled' if outcomes and outcomes[-1]=='cancelled' and 'failed' not in outcomes else 'partial'
        store.finish(run,final)
        return store.read(run)[0]
    except (JobPaused,JobCancelled) as signal:
        if isinstance(signal,JobCancelled):
            for step in store.read(run)[0]['steps']:
                if step['status']=='waiting':
                    store.step(run,step['name'],'cancelled')
        store.finish(run,'paused' if isinstance(signal,JobPaused) else 'cancelled')
        return store.read(run)[0]
    except Exception:
        try:
            store.finish(run,'failed','작업이 중단되었습니다. 완료된 데이터는 유지됩니다.')
        except BusyError:
            pass
        return store.read(run)[0]
    finally:
        stopped.set()
        worker.join(timeout=1)


def live_steps(job, cache, settings):
    if job['status'] not in ('running','paused','interrupted'):
        return job
    for step in job['steps']:
        if step['status'] not in ('running','paused','interrupted') or not step['source_id']:
            continue
        if step['name']=='openwebui':
            native=next((r for r in cache.status()['runs'] if r['id']==step['source_id']),None)
            if native:
                step['stats'].update(usersDone=native['users_done'],messagesSeen=native['messages_seen'])
        else:
            db = TokenStore(settings.token_cache_path) if step['name']=='tokens' else CategoryStore(settings.category_cache_path)
            native=next((r for r in db.status()['runs'] if r['id']==step['source_id']),None)
            if native:
                keys=('scanned','saved','skipped','pages') if step['name']=='tokens' else ('total','processed','calls','reused','unavailable','stop_requested','pause_requested')
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
            overrides=CategoryStore(settings.category_cache_path).overrides(profile(settings,definitions))
            if overrides:
                with cache.connect() as db:
                    individual=db.execute("SELECT id,content_hash,has_files FROM messages WHERE role='user'").fetchall()
                for m in individual:
                    o=overrides.get(digest(m['id']))
                    if not o or o['content_key']!=category_key(m) or o['category'] not in {d['category'] for d in definitions}:
                        continue
                    base=decisions.get(category_key(m))
                    if not base:
                        pending-=1;classified+=1
                    elif base['state'] not in ('classified','uncertain','fallback'):
                        classified+=1
            category_counts={'questions':total,'pending':pending,'classified':classified}
        except (ValueError,RuntimeError):
            pass
    jobs=store.read()
    for job in jobs:
        live_steps(job,cache,settings)
    active=next((j['id'] for j in jobs if j['status'] in ('running','paused')),None)
    return {'schemaVersion':1, 'activeRunId':active, 'runs':jobs,
            'sources':{'openwebui':{'ready':data['ready'],'configured':bool(settings.base_url and settings.api_token),'lastSuccess':data['lastSuccess'],'users':data['users'],'messages':data['messages'],'activeRunId':data['activeRunId']},
                       'tokens':{'ready':tokens['ready'],'configured':configured,'lastSuccess':tokens['lastSuccess'],'logs':tokens['logs'],'activeRunId':tokens['activeRunId']},
                       'categories':{**category_counts,'pausedRunId':categories.get('pausedRunId'),'configured':category_configured,'activeRunId':categories['activeRunId'],'lastRun':categories['runs'][0] if categories['runs'] else None}},
            'overlap':{'openwebuiDays':settings.overlap_days,'litellmHours':settings.litellm_lookback_hours}}
