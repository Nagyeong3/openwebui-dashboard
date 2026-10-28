from threading import Thread
from fastapi import Depends, HTTPException, Query, Response
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
            return {**store.status(),'configured':configured,'configurationError':error,'batchLimit':settings.category_max_questions,'sampleLimit':min(20,settings.category_max_questions),'model':settings.category_model,'separateModelUrl':bool(settings.category_url)}
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

    @app.post('/api/dashboard/v2/categories/stop',status_code=202,dependencies=[Depends(authorized)])
    def stop():
        try:
            db=CategoryStore(settings.category_cache_path)
            run=db.request_stop()
            if next(r for r in db.status()['runs'] if r['id']==run)['status'] in ('paused','interrupted'):
                db.cancel(run)
            return {'ok':True,'runId':run,'status':'stopping'}
        except BusyError as e:
            raise HTTPException(409,str(e)) from None

    @app.get('/api/dashboard/v2/categories',dependencies=[Depends(authorized)])
    def usage(start:str|None=None,end:str|None=None,range:str='7d',division:str='전체',team:str='전체',position:str='전체',category:str='전체',page:int=Query(1,ge=1),pageSize:int=Query(50,ge=1,le=1000)):
        try:
            return category_usage(cache,settings,start=start,end=end,range_value=range,division=division,team=team,position=position,category=category,page=page,page_size=pageSize)
        except NotReadyError as e:
            raise HTTPException(503,str(e)) from None
        except (ValueError,RuntimeError,MappingError) as e:
            raise HTTPException(422,str(e)) from None

    def current_question(message_id):
        from .category_sync import digest_url
        with cache.connect() as db:
            origin=db.execute("SELECT value FROM meta WHERE key='source'").fetchone()
            row=db.execute("SELECT * FROM messages WHERE id=? AND role='user'",(message_id,)).fetchone()
        if not origin or origin[0]!=digest_url(settings.base_url):
            raise HTTPException(409,'데이터 연결을 확인하세요.')
        if not row:
            raise HTTPException(404,'질문을 찾을 수 없습니다.')
        return dict(row)

    @app.get('/api/dashboard/v2/categories/question',dependencies=[Depends(authorized)])
    def question(messageId:str, response:Response):
        response.headers['Cache-Control']='no-store'
        from .client import OpenWebUIClient, UpstreamError
        from .sync import normalize_message
        from .categories import text_content
        row=current_question(messageId)
        try:
            client=OpenWebUIClient(settings)
            for raw in client.chat_messages(row['chat_id']):
                if not isinstance(raw,dict) or raw.get('id')!=messageId:
                    continue
                normalized=normalize_message(raw,row['user_id'])
                if normalized[9]!=row['content_hash']:
                    raise HTTPException(409,'질문이 변경되었습니다. 데이터를 업데이트하세요.')
                text=text_content(raw.get('content'))
                return {'id':messageId,'text':text[:20000],'truncated':len(text)>20000}
        except UpstreamError as error:
            raise HTTPException(502,str(error)) from None
        except ValueError as error:
            raise HTTPException(422,'연결 설정을 확인하세요.') from None
        raise HTTPException(404,'질문을 조회하지 못했습니다. 데이터를 업데이트하세요.')

    from pydantic import BaseModel, Field
    class Correction(BaseModel):
        messageId:str=Field(min_length=1,max_length=1024)
        category:str=Field(min_length=1,max_length=80)

    @app.post('/api/dashboard/v2/categories/correction',dependencies=[Depends(authorized)])
    def correction(body:Correction):
        from .categories import taxonomy,profile,digest
        from .category_store import key
        try:
            definitions=taxonomy(settings.category_csv)
            if body.category not in {d['category'] for d in definitions}:
                raise HTTPException(422,'카테고리를 확인하세요.')
            row=current_question(body.messageId)
            CategoryStore(settings.category_cache_path).set_override(profile(settings,definitions),digest(body.messageId),key(row),body.category)
            return {'ok':True}
        except ValueError as error:
            raise HTTPException(422,str(error)) from None

    def owner(run):
        from .operations import OperationsStore
        db=OperationsStore(settings.operations_path)
        job=next((j for j in db.read() if j['status'] in ('running','paused','interrupted') and any(step['name']=='categories' and step['source_id']==run for step in j['steps'])),None)
        return db,job

    @app.post('/api/dashboard/v2/categories/pause',dependencies=[Depends(authorized)])
    def pause():
        try:
            run=CategoryStore(settings.category_cache_path).request_pause()
            return {'ok':True,'runId':run}
        except BusyError as error:
            raise HTTPException(409,str(error)) from None

    @app.post('/api/dashboard/v2/categories/resume',status_code=202,dependencies=[Depends(authorized)])
    def resume(runId:str):
        try:
            _,version=configuration(settings)
            db=CategoryStore(settings.category_cache_path)
            operations,parent=owner(runId)
            if parent and parent['status'] in ('paused','interrupted'):
                from .operations import execute
                operations.resume(parent['id'])
                Thread(target=lambda:execute(settings,cache,operations,parent['id']),daemon=True,name='operations-worker').start()
                return {'ok':True,'runId':runId}
            db.resume(runId,version)
            def work():
                try:
                    collect(settings,cache,db,runId)
                except RuntimeError:
                    pass
            Thread(target=work,daemon=True,name='category-classifier').start()
            return {'ok':True,'runId':runId}
        except BusyError as error:
            raise HTTPException(409,str(error)) from None
        except ValueError as error:
            raise HTTPException(422,str(error)) from None
