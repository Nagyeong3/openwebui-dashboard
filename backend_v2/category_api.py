from threading import Thread
from fastapi import Depends, HTTPException, Query
from .category_store import CategoryStore
from .category_sync import prepare, collect, configuration
from .category_analytics import category_usage
from .cache import BusyError, NotReadyError
from .organization import MappingError


def attach(app, settings, cache, authorized):
    @app.get('/api/dashboard/v2/categories/status',dependencies=[Depends(authorized)])
    def status():
        try:
            store = CategoryStore(settings.category_cache_path)
            try:
                configuration(settings)
                configured,error = True,None
            except ValueError as e:
                configured,error = False,str(e)
            return {**store.status(),'configured':configured,'configurationError':error,'batchLimit':settings.category_max_questions}
        except RuntimeError as e:
            raise HTTPException(422,str(e)) from None

    @app.post('/api/dashboard/v2/categories/classify',status_code=202,dependencies=[Depends(authorized)])
    def classify(kind:str='pending'):
        try:
            store = CategoryStore(settings.category_cache_path)
            run = prepare(settings,cache,store,kind)
        except BusyError as e:
            raise HTTPException(409,str(e)) from None
        except NotReadyError as e:
            raise HTTPException(503,str(e)) from None
        except (ValueError,RuntimeError) as e:
            raise HTTPException(422,str(e)) from None
        def work():
            try:
                collect(settings,cache,store,run)
            except RuntimeError:
                pass
        Thread(target=work,daemon=True,name='category-classifier').start()
        return {'ok':True,'runId':run,'status':'running'}

    @app.get('/api/dashboard/v2/categories',dependencies=[Depends(authorized)])
    def usage(start:str|None=None,end:str|None=None,range:str='7d',division:str='전체',team:str='전체',position:str='전체',category:str='전체',page:int=Query(1,ge=1),pageSize:int=Query(50,ge=1,le=1000)):
        try:
            return category_usage(cache,settings,start=start,end=end,range_value=range,division=division,team=team,position=position,category=category,page=page,page_size=pageSize)
        except NotReadyError as e:
            raise HTTPException(503,str(e)) from None
        except (ValueError,RuntimeError,MappingError) as e:
            raise HTTPException(422,str(e)) from None
