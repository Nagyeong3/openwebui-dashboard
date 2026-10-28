import json,unittest,io,time
from dataclasses import replace
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend_v2.tests import test_operations as fixtures
from backend_v2.tests.test_categories import FakeClassifier
from backend_v2.tests.test_backend import FakeClient,message
from backend_v2.operations import prepare,execute,OperationsStore
from backend_v2.category_store import CategoryStore
from backend_v2.category_sync import prepare as cat_prepare,collect as cat_collect,configuration
from backend_v2.category_analytics import category_usage
from backend_v2.sync import Synchronizer
from backend_v2.token_store import TokenStore

class ControlsTests(unittest.TestCase):
    setUp=fixtures.OperationsTests.setUp
    tearDown=fixtures.OperationsTests.tearDown
    run_job=fixtures.OperationsTests.run_job
    def test_pause_data_discards_incomplete_stage_and_resumes_after_restart(self):
        run=prepare(self.s,self.cache,self.db)
        test=self
        class Pause(FakeClient):
            paused=False
            def messages(self,*args):
                rows=super().messages(*args)
                if not self.paused:
                    self.paused=True;test.db.request_control(run,'pause')
                return rows
        client=Pause()
        result=execute(self.s,self.cache,self.db,run,owui_client=client,spend_client=self.spend,classifier=self.model)
        self.assertEqual(result['status'],'paused');self.assertFalse(self.cache.status()['ready'])
        restored=OperationsStore(self.s.operations_path);restored.resume(run)
        result=execute(self.s,self.cache,restored,run,owui_client=client,spend_client=self.spend,classifier=self.model)
        self.assertEqual(result['status'],'success');self.assertEqual(result['steps'][0]['stats']['newQuestions'],3)
    def test_pause_token_keeps_prior_watermark_and_skips_completed_data_on_resume(self):
        self.run_job();previous=TokenStore(self.s.token_cache_path).status()['lastSuccess']
        run=prepare(self.s,self.cache,self.db)
        test=self
        class Pause:
            paused=False
            def page(self,*args):
                rows=test.spend.page(*args)
                if not self.paused:self.paused=True;test.db.request_control(run,'pause')
                return rows
        client=Pause()
        result=execute(self.s,self.cache,self.db,run,owui_client=self.client,spend_client=client,classifier=self.model)
        self.assertEqual(result['status'],'paused')
        self.assertEqual(TokenStore(self.s.token_cache_path).status()['lastSuccess'],previous)
        runs=len(self.cache.status()['runs'])
        self.db.resume(run)
        result=execute(self.s,self.cache,self.db,run,owui_client=self.client,spend_client=client,classifier=self.model)
        self.assertEqual(result['status'],'success');self.assertEqual(len(self.cache.status()['runs']),runs)
    def test_operation_category_pause_reuses_exact_completed_targets(self):
        settings=replace(self.s,category_batch_size=1)
        run=prepare(settings,self.cache,self.db)
        test=self
        class Pause(FakeClassifier):
            def classify(self,inputs):
                out=super().classify(inputs)
                if len(self.calls)==1:test.db.request_control(run,'pause')
                return out
        model=Pause()
        result=execute(settings,self.cache,self.db,run,owui_client=self.client,spend_client=self.spend,classifier=model)
        self.assertEqual(result['status'],'paused')
        self.assertEqual(category_usage(self.cache,settings,range_value='all')['summary']['classified'],1)
        self.db.resume(run)
        result=execute(settings,self.cache,self.db,run,owui_client=self.client,spend_client=self.spend,classifier=model)
        self.assertEqual(result['status'],'success');self.assertEqual(result['steps'][2]['stats']['processed'],3)
        self.assertEqual(len(model.calls),2)
    def test_interrupted_category_job_resumes_after_process_restart(self):
        settings=replace(self.s,category_batch_size=1)
        run=prepare(settings,self.cache,self.db)
        test=self
        class Pause(FakeClassifier):
            def classify(self,inputs):
                result=super().classify(inputs)
                if len(self.calls)==1:test.db.request_control(run,'pause')
                return result
        model=Pause()
        result=execute(settings,self.cache,self.db,run,owui_client=self.client,spend_client=self.spend,classifier=model)
        source=result['steps'][2]['source_id']
        with self.db.connect() as db:db.execute("UPDATE operation_runs SET status='running',expires=0 WHERE id=?",(run,))
        with CategoryStore(settings.category_cache_path).connect() as db:db.execute("UPDATE category_runs SET status='running',expires=0 WHERE id=?",(source,))
        restarted=OperationsStore(settings.operations_path);restarted.resume(run)
        result=execute(settings,self.cache,restarted,run,owui_client=self.client,spend_client=self.spend,classifier=model)
        self.assertEqual(result['status'],'success');self.assertEqual(len(model.calls),2)
        self.assertEqual(result['steps'][2]['stats']['processed'],3)

    def test_standalone_sample_pause_freezes_target_set(self):
        Synchronizer(self.s,self.cache,self.client).run('full')
        settings=replace(self.s,category_max_questions=1,category_batch_size=1)
        store=CategoryStore(settings.category_cache_path)
        run=cat_prepare(settings,self.cache,store,'sample')
        class Pause(FakeClassifier):
            def classify(self,inputs):
                out=super().classify(inputs);store.request_pause();return out
        model=Pause();result=cat_collect(settings,self.cache,store,run,self.client,model)
        self.assertEqual(result['status'],'paused')
        self.client.items.append(message('new-after-pause',created=int(time.time())-1,content='new sample'))
        Synchronizer(settings,self.cache,self.client).run('full')
        _,version=configuration(settings);store.resume(run,version)
        result=cat_collect(settings,self.cache,store,run,self.client,model)
        self.assertEqual(result['processed'],1);self.assertEqual(len(model.calls),1)
        self.assertEqual(store.status()['runs'][0]['total'],1)
    def test_cancel_and_selection_retry_only_failed_steps(self):
        self.spend.fail=True
        first=self.run_job()
        selected=[s['name'] for s in first['steps'] if s['status']=='failed']
        self.assertEqual(selected,['tokens'])
        self.spend.fail=False
        previous=len(self.cache.status()['runs'])
        run=prepare(self.s,self.cache,self.db,'quick',selected,parent_id=first['id'])
        result=execute(self.s,self.cache,self.db,run,owui_client=self.client,spend_client=self.spend,classifier=self.model)
        self.assertEqual(result['status'],'success');self.assertEqual(result['parent_id'],first['id'])
        self.assertEqual(len(self.cache.status()['runs']),previous)
        self.assertEqual([s['status'] for s in result['steps']],['skipped','success','skipped'])
        run=prepare(self.s,self.cache,self.db,'quick',['openwebui'])
        self.db.request_control(run,'cancel')
        result=execute(self.s,self.cache,self.db,run,owui_client=self.client)
        self.assertEqual(result['status'],'cancelled');self.assertTrue(all(s['status'] in ('cancelled','skipped') for s in result['steps']))
    def test_correction_is_per_question_and_survives_model_updates(self):
        self.run_job()
        with TestClient(__import__('backend_v2.app',fromlist=['create_app']).create_app(self.s,self.cache)) as web:
            reply=web.post('/api/dashboard/v2/categories/correction',json={'messageId':'q2','category':'기타'})
            self.assertEqual(reply.status_code,200)
            with patch('backend_v2.client.OpenWebUIClient',return_value=self.client):
                preview=web.get('/api/dashboard/v2/categories/question?messageId=q2')
            self.assertEqual(preview.status_code,200);self.assertEqual(preview.json()['text'],'synthetic question')
        result=category_usage(self.cache,self.s,range_value='all')
        rows={r['id']:r for r in result['detail']['records']}
        self.assertEqual(rows['q2']['category'],'기타');self.assertTrue(rows['q2']['manual'])
        self.assertEqual(rows['q3']['category'],'문서/RAG')
        self.run_job();self.assertEqual(category_usage(self.cache,self.s,range_value='all')['summary']['classified'],3)
        changed=replace(self.s,category_model='new-model')
        current=category_usage(self.cache,changed,range_value='all')
        self.assertTrue(next(r for r in current['detail']['records'] if r['id']=='q2')['manual'])
        with CategoryStore(self.s.category_cache_path).connect() as db:dump='\n'.join(db.iterdump())
        self.assertNotIn('synthetic question',dump)
    def test_control_api_step_selection_retry_and_resume(self):
        from backend_v2.app import create_app
        with TestClient(create_app(self.s,self.cache)) as web:
            self.assertEqual(web.post('/api/dashboard/v2/operations/update?steps=').status_code,422)
            with patch('backend_v2.operations_api.Thread'):
                started=web.post('/api/dashboard/v2/operations/update?steps=openwebui').json()['runId']
            self.assertEqual(web.post(f'/api/dashboard/v2/operations/runs/{started}/control?action=pause').status_code,200)
            paused=execute(self.s,self.cache,self.db,started,owui_client=self.client)
            self.assertEqual(paused['status'],'paused')
            with patch('backend_v2.operations_api.Thread'):
                self.assertEqual(web.post(f'/api/dashboard/v2/operations/runs/{started}/resume').status_code,202)
            completed=execute(self.s,self.cache,self.db,started,owui_client=self.client)
            self.assertEqual(completed['status'],'success');self.assertEqual(completed['steps'][1]['status'],'skipped')
            self.spend.fail=True;failed=self.run_job()
            with patch('backend_v2.operations_api.Thread'):
                reply=web.post(f"/api/dashboard/v2/operations/runs/{failed['id']}/retry")
            self.assertEqual(reply.status_code,202)
            child=self.db.read(reply.json()['runId'])[0]
            self.assertEqual([s['status'] for s in child['steps']],['skipped','waiting','skipped'])
            self.db.request_control(child['id'],'cancel');execute(self.s,self.cache,self.db,child['id'])
    def test_standalone_control_endpoints_and_manual_override_auth(self):
        from backend_v2.app import create_app
        Synchronizer(self.s,self.cache,self.client).run('full')
        store=CategoryStore(self.s.category_cache_path)
        run=cat_prepare(self.s,self.cache,store)
        with TestClient(create_app(self.s,self.cache)) as web:
            self.assertEqual(web.post('/api/dashboard/v2/categories/pause').status_code,200)
            cat_collect(self.s,self.cache,store,run,self.client,self.model)
            self.assertEqual(store.status()['pausedRunId'],run)
            with patch('backend_v2.category_api.Thread'):
                self.assertEqual(web.post('/api/dashboard/v2/categories/resume?runId='+run).status_code,202)
            cat_collect(self.s,self.cache,store,run,self.client,self.model)
            self.assertEqual(store.status()['runs'][0]['status'],'success')
            self.assertEqual(web.post('/api/dashboard/v2/categories/correction',json={'messageId':'q1','category':'invalid'}).status_code,422)
        with TestClient(create_app(replace(self.s,dashboard_token='secret'),self.cache)) as web:
            self.assertEqual(web.get('/api/dashboard/v2/categories/question?messageId=q1').status_code,401)
            self.assertEqual(web.post('/api/dashboard/v2/categories/correction',json={'messageId':'q1','category':'기타'}).status_code,401)

    def test_cookie_login_preserves_bearer_and_never_exposes_password(self):
        from backend_v2.app import create_app
        settings=replace(self.s,dashboard_token='local-secret')
        with TestClient(create_app(settings,self.cache)) as web:
            self.assertFalse(web.get('/api/dashboard/v2/auth/status').json()['authenticated'])
            self.assertEqual(web.get('/api/dashboard/v2/operations/status').status_code,401)
            self.assertEqual(web.post('/api/dashboard/v2/auth/login',json={'password':'wrong'}).status_code,401)
            reply=web.post('/api/dashboard/v2/auth/login',json={'password':'local-secret'})
            self.assertEqual(reply.status_code,200);self.assertIn('HttpOnly',reply.headers['set-cookie']);self.assertNotIn('local-secret',reply.headers['set-cookie'])
            self.assertEqual(web.get('/api/dashboard/v2/operations/status').status_code,200)
            web.cookies.clear();web.cookies.set('oui_dashboard_session','tampered')
            self.assertEqual(web.get('/api/dashboard/v2/operations/status').status_code,401)
            self.assertEqual(web.get('/api/dashboard/v2/operations/status',headers={'Authorization':'Bearer local-secret'}).status_code,200)
