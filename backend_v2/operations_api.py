from threading import Thread
from fastapi import Depends, HTTPException
from .operations import OperationsStore, prepare, execute, summary, live_steps
from .cache import BusyError
from .category_store import CategoryStore
from .token_store import TokenStore


def attach(app, settings, cache, authorized):
    def store():
        return OperationsStore(settings.operations_path)

    @app.get('/api/dashboard/v2/operations/status',dependencies=[Depends(authorized)])
    def status():
        try:
            return summary(settings,cache,store())
        except (ValueError, RuntimeError) as error:
            raise HTTPException(422,str(error)) from None

    @app.get('/api/dashboard/v2/operations/runs/{run_id}',dependencies=[Depends(authorized)])
    def detail(run_id:str):
        jobs=store().read(run_id)
        if not jobs:
            raise HTTPException(404,'Operation not found')
        return live_steps(jobs[0],cache,settings)

    @app.post('/api/dashboard/v2/operations/update',status_code=202,dependencies=[Depends(authorized)])
    def update(kind:str='quick', steps:str|None=None):
        try:
            db=store()
            run=prepare(settings,cache,db,kind,steps.split(',') if steps is not None else None)
        except BusyError as error:
            raise HTTPException(409,str(error)) from None
        except (ValueError,RuntimeError) as error:
            raise HTTPException(422,str(error)) from None
        def work():
            execute(settings,cache,db,run)
        Thread(target=work,daemon=True,name='operations-worker').start()
        return {'ok':True,'runId':run,'status':'running'}

    @app.post('/api/dashboard/v2/operations/stop-classification',status_code=202,dependencies=[Depends(authorized)])
    def stop():
        db=store()
        jobs=db.read()
        active=next((j for j in jobs if j['status']=='running'),None)
        step=next((s for s in active['steps'] if s['name']=='categories' and s['status']=='running'),None) if active else None
        if not step or not step['source_id']:
            raise HTTPException(409,'Classification is not running in this operation')
        source=CategoryStore(settings.category_cache_path)
        if source.status()['activeRunId']!=step['source_id']:
            raise HTTPException(409,'The classification job is no longer active')
        try:
            source.request_stop(expected_run=step['source_id'])
        except BusyError as error:
            raise HTTPException(409,str(error)) from None
        return {'ok':True,'runId':active['id'],'status':'stopping'}

    def launch(db, run):
        Thread(target=lambda:execute(settings,cache,db,run),daemon=True,name='operations-worker').start()

    @app.post('/api/dashboard/v2/operations/runs/{run_id}/control',dependencies=[Depends(authorized)])
    def control(run_id:str, action:str):
        db=store()
        try:
            jobs=db.read(run_id)
            if not jobs:
                raise HTTPException(404,'작업을 찾을 수 없습니다.')
            db.request_control(run_id,action)
            if action=='cancel' and jobs[0]['status'] in ('paused','interrupted'):
                source=CategoryStore(settings.category_cache_path)
                for step in jobs[0]['steps']:
                    if step['name']=='categories' and step['source_id']:
                        source.cancel(step['source_id'])
            return {'ok':True}
        except BusyError as error:
            raise HTTPException(409,str(error)) from None
        except ValueError as error:
            raise HTTPException(422,str(error)) from None

    @app.post('/api/dashboard/v2/operations/runs/{run_id}/resume',status_code=202,dependencies=[Depends(authorized)])
    def resume(run_id:str):
        db=store()
        try:
            source_status=[cache.status(),TokenStore(settings.token_cache_path).status(),CategoryStore(settings.category_cache_path).status()]
            if any(s['activeRunId'] for s in source_status):
                raise BusyError('다른 수집이나 분류가 진행 중입니다.')
            db.resume(run_id)
            launch(db,run_id)
            return {'ok':True,'runId':run_id}
        except BusyError as error:
            raise HTTPException(409,str(error)) from None

    @app.post('/api/dashboard/v2/operations/runs/{run_id}/retry',status_code=202,dependencies=[Depends(authorized)])
    def retry(run_id:str):
        db=store()
        previous=db.read(run_id)
        if not previous:
            raise HTTPException(404,'작업을 찾을 수 없습니다.')
        selected=[s['name'] for s in previous[0]['steps'] if s['status'] in ('failed','partial','cancelled','interrupted') or (s['status']=='skipped' and s['error'])]
        if not selected:
            raise HTTPException(409,'다시 실행할 항목이 없습니다.')
        try:
            run=prepare(settings,cache,db,previous[0]['kind'],selected,parent_id=run_id)
            launch(db,run)
            return {'ok':True,'runId':run}
        except BusyError as error:
            raise HTTPException(409,str(error)) from None
