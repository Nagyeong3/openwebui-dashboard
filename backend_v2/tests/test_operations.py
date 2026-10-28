import json,sqlite3,time,tempfile,unittest
from pathlib import Path
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch
from datetime import datetime,timezone
from fastapi.testclient import TestClient
from backend_v2.settings import Settings
from backend_v2.cache import Cache,BusyError
from backend_v2.sync import Synchronizer
from backend_v2.client import UpstreamError
from backend_v2.app import create_app
from backend_v2.operations import OperationsStore,prepare,execute,summary
from backend_v2.token_store import TokenStore
from backend_v2.category_store import CategoryStore
from backend_v2.tests.test_backend import FakeClient,message
from backend_v2.tests.test_tokens import FakeSpend,log
from backend_v2.tests.test_categories import FakeClassifier

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        csv=self.root/'definitions.csv';csv.write_text('category,description,keywords,examples,active\n문서/RAG,Documents,rag,Find,true\n기타,Other,,,true\n',encoding='utf-8')
        self.s=Settings(base_url='http://oui.invalid',api_token='private-oui',cache_path=self.root/'users.db',token_cache_path=self.root/'tokens.db',category_cache_path=self.root/'categories.db',org_csv=None,category_csv=csv,category_url='http://llm.invalid',category_key='private-classifier',category_model='test',litellm_url='http://llm.invalid',litellm_key='private-token',litellm_alias='OUI-test',litellm_start_date=datetime.now(timezone.utc).date().isoformat(),page_size=2)
        self.cache=Cache(self.s.cache_path);self.db=OperationsStore(self.s.operations_path)
        self.client=FakeClient()
        self.spend=FakeSpend([log('1',startTime=datetime.fromtimestamp(int(time.time())-10,timezone.utc).isoformat())])
        self.model=FakeClassifier()
    def tearDown(self):self.temp.cleanup()
    def run_job(self,kind='quick',**clients):
        r=prepare(self.s,self.cache,self.db,kind)
        return execute(self.s,self.cache,self.db,r,owui_client=clients.get('owui_client',self.client),spend_client=clients.get('spend_client',self.spend),classifier=clients.get('classifier',self.model))
    def test_initial_quick_automatically_full_then_idempotent_quick(self):
        first=self.run_job()
        self.assertEqual(first['status'],'success');self.assertEqual(first['steps'][0]['stats']['mode'],'full')
        self.assertEqual(first['steps'][0]['stats']['newQuestions'],3)
        self.assertEqual(first['steps'][1]['stats']['saved'],1)
        self.assertEqual(first['steps'][2]['stats']['total'],3)
        calls=len(self.model.calls)
        second=self.run_job()
        self.assertEqual(second['steps'][0]['stats']['mode'],'quick')
        self.assertEqual(second['steps'][0]['stats']['newQuestions'],0)
        self.assertEqual(second['steps'][2]['stats']['total'],0)
        self.assertEqual(len(self.model.calls),calls)
        self.assertEqual(TokenStore(self.s.token_cache_path).status()['logs'],1)
        status=summary(self.s,self.cache,self.db)
        self.assertEqual(status['sources']['categories']['pending'],0)
        self.assertEqual(status['sources']['categories']['classified'],3)
    def test_advanced_full_reconciles_old_deletions(self):
        self.client.items.append(message('old',created=int(time.time())-40*86400,content='Old synthetic question'))
        self.run_job()
        self.client.items=[m for m in self.client.items if m['id']!='old']
        quick=self.run_job()
        self.assertEqual(quick['steps'][0]['stats']['deletedQuestions'],0)
        full=self.run_job('full')
        self.assertEqual(full['status'],'success');self.assertEqual(full['steps'][0]['stats']['mode'],'full')
        self.assertEqual(full['steps'][0]['stats']['deletedQuestions'],1)
        self.assertEqual(full['steps'][1]['stats']['mode'],'full')
    def test_live_progress_is_bound_to_own_source_run(self):
        from backend_v2.operations import live_steps
        run=prepare(self.s,self.cache,self.db)
        self.db.step(run,'tokens','running',source_id='own-run')
        native=TokenStore(self.s.token_cache_path)
        # Current native collector is not this operation's source job.
        with patch.object(TokenStore,'status',return_value={'runs':[{'id':'unrelated','scanned':999,'saved':999,'skipped':0,'pages':1}]}):
            view=live_steps(self.db.read(run)[0],self.cache,self.s)
        self.assertNotIn('scanned',view['steps'][1]['stats'])
        self.db.finish(run,'cancelled')

    def test_only_new_question_classified_on_next_update(self):
        self.run_job();before=len(self.model.calls)
        self.client.items.append(message('new',created=int(time.time())-1,content='A new synthetic question'))
        r=self.run_job()
        self.assertEqual(r['status'],'success');self.assertEqual(r['steps'][0]['stats']['newQuestions'],1)
        self.assertEqual(r['steps'][2]['stats']['processed'],1)
        self.assertEqual(len(self.model.calls),before+1)
    def test_openwebui_failure_stops_later_steps_and_preserves_data(self):
        self.run_job();self.client.failure=True
        calls=len(self.spend.calls);model_calls=len(self.model.calls)
        r=self.run_job()
        self.assertEqual(r['status'],'failed');self.assertEqual([s['status'] for s in r['steps']],['failed','skipped','skipped'])
        self.assertEqual(self.cache.status()['users'],3)
        self.assertEqual(len(self.spend.calls),calls);self.assertEqual(len(self.model.calls),model_calls)
    def test_token_failure_does_not_skip_categories_or_advance_token_watermark(self):
        self.run_job();previous=TokenStore(self.s.token_cache_path).status()['lastSuccess']
        self.spend.fail=True
        self.client.items.append(message('later',created=int(time.time())-1,content='New question while spend API fails'))
        r=self.run_job()
        self.assertEqual(r['status'],'partial');self.assertEqual([s['status'] for s in r['steps']],['success','failed','success'])
        self.assertEqual(TokenStore(self.s.token_cache_path).status()['lastSuccess'],previous)
        self.assertEqual(r['steps'][2]['stats']['processed'],1)
    def test_category_failure_preserves_successful_sources_and_completed_batches(self):
        self.s=replace(self.s,category_batch_size=1)
        r=self.run_job(classifier=FakeClassifier(fail_at=2))
        self.assertEqual(r['status'],'partial')
        self.assertEqual(self.cache.status()['users'],3)
        self.assertEqual(TokenStore(self.s.token_cache_path).status()['logs'],1)
        self.assertNotIn('PRIVATE raw text',json.dumps(r))
        self.assertEqual(r['steps'][2]['stats']['calls'],2)
        retry=self.run_job()
        self.assertEqual(retry['status'],'success')
    def test_global_and_native_job_locks(self):
        run=prepare(self.s,self.cache,self.db)
        with self.assertRaises(BusyError):prepare(self.s,self.cache,self.db)
        self.db.finish(run,'cancelled')
        from backend_v2.category_sync import prepare as category_prepare
        store=CategoryStore(self.s.category_cache_path)
        other=category_prepare(self.s,self.cache,store) if self.cache.status()['ready'] else None
        if not other:
            Synchronizer(self.s,self.cache,self.client).run('full');other=category_prepare(self.s,self.cache,store)
        with self.assertRaises(BusyError):prepare(self.s,self.cache,self.db)
        store.cancel(other)
    def test_interrupted_job_visible_after_restart_and_reclaimable(self):
        run=prepare(self.s,self.cache,self.db)
        self.db.step(run,'openwebui','running')
        with self.db.connect() as db:db.execute('UPDATE operation_runs SET expires=0')
        restarted=OperationsStore(self.s.operations_path)
        self.assertEqual(restarted.read(run)[0]['status'],'interrupted')
        with self.assertRaises(BusyError):self.db.heartbeat(run)
        r=self.run_job();self.assertEqual(r['status'],'success')
    def test_classify_only_skips_collectors_and_durable_history(self):
        Synchronizer(self.s,self.cache,self.client).run('full')
        r=self.run_job('classify')
        self.assertEqual([s['status'] for s in r['steps']],['skipped','skipped','success'])
        self.assertFalse(self.spend.calls)
        saved=OperationsStore(self.s.operations_path).read(r['id'])[0]
        self.assertEqual(saved['status'],'success')
        self.assertEqual(saved['steps'][2]['stats']['processed'],3)
    def test_classification_stop_through_operation_api(self):
        app=create_app(self.s,self.cache)
        with TestClient(app) as web:
            test=self
            class Stop(FakeClassifier):
                def classify(self,inputs):
                    out=super().classify(inputs)
                    self.response=web.post('/api/dashboard/v2/operations/stop-classification')
                    test.assertEqual(self.response.status_code,202)
                    return out
            r=self.run_job(classifier=Stop())
            self.assertEqual(r['status'],'cancelled')
    def test_authorized_202_poll_detail_and_duplicate_start(self):
        settings=replace(self.s,dashboard_token='dashboard')
        with TestClient(create_app(settings,self.cache)) as web:
            self.assertEqual(web.get('/api/dashboard/v2/operations/status').status_code,401)
            self.assertEqual(web.post('/api/dashboard/v2/operations/update').status_code,401)
            headers={'Authorization':'Bearer dashboard'}
            with patch('backend_v2.operations_api.Thread'):
                r=web.post('/api/dashboard/v2/operations/update',headers=headers)
                self.assertEqual(r.status_code,202);run=r.json()['runId']
                self.assertEqual(web.post('/api/dashboard/v2/operations/update',headers=headers).status_code,409)
            execute(self.s,self.cache,self.db,run,owui_client=self.client,spend_client=self.spend,classifier=self.model)
            status=web.get('/api/dashboard/v2/operations/status',headers=headers).json()
            self.assertIsNone(status['activeRunId']);self.assertEqual(status['runs'][0]['status'],'success')
            detail=web.get('/api/dashboard/v2/operations/runs/'+run,headers=headers)
            self.assertEqual(detail.status_code,200)
            self.assertEqual(web.get('/api/dashboard/v2/operations/runs/missing',headers=headers).status_code,404)
            self.assertEqual(web.post('/api/dashboard/v2/operations/stop-classification',headers=headers).status_code,409)
            self.assertEqual(web.post('/api/dashboard/v2/operations/update?kind=invalid',headers=headers).status_code,422)
            body=json.dumps(status)
            for secret in ('private-oui','private-token','private-classifier','http://oui.invalid','Synthetic 1'):
                self.assertNotIn(secret,body)
    def test_legacy_db_rejected_and_path_collision(self):
        path=self.root/'legacy.db'
        with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE old(x)');db.commit()
        with self.assertRaises(ValueError):OperationsStore(path)
        with self.assertRaises(ValueError):replace(self.s,operations_cache_path=self.s.cache_path)
    def test_monthly_gap_uses_last_success_not_only_last_day(self):
        self.run_job()
        from datetime import timedelta
        old=datetime.now(timezone.utc)-timedelta(days=30)
        token=TokenStore(self.s.token_cache_path)
        # Source history starts earlier than the watermark so no clamp hides the assertion.
        settings=replace(self.s,litellm_start_date=(old-timedelta(days=10)).date().isoformat())
        with token.connect() as db:db.execute("UPDATE token_meta SET value=? WHERE key='last_success'",(old.isoformat(),))
        from backend_v2.token_sync import prepare as token_prepare
        run=token_prepare(settings,token,'quick')
        job=next(j for j in token.status()['runs'] if j['id']==run)
        self.assertAlmostEqual(job['start'],old.timestamp()-86400,places=2)
        token.fail(run,'Synthetic test complete')
