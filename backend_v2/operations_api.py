from threading import Thread
from fastapi import Depends, HTTPException
from .operations import OperationsStore, prepare, execute, summary, live_steps
from .cache import BusyError
from .category_store import CategoryStore


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
    def update(kind:str='quick'):
        try:
            db=store()
            run=prepare(settings,cache,db,kind)
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
