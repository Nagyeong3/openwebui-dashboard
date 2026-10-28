"""Resumable classification. Text stays in memory; durable targets contain hashes only."""
from collections import defaultdict
from .client import OpenWebUIClient, UpstreamError, ContractError
from .sync import normalize_message
from .categories import taxonomy, profile, Classifier, text_content, digest
from .category_store import key
from .control import JobPaused, JobCancelled


def configuration(settings):
    definitions = taxonomy(settings.category_csv)
    if not (settings.category_url or settings.litellm_url) or not settings.category_key or not settings.category_model:
        raise ValueError('분류 모델 연결 설정을 확인하세요.')
    if not settings.base_url or not settings.api_token:
        raise ValueError('OpenWebUI 연결 설정을 확인하세요.')
    if '기타' not in {d['category'] for d in definitions}:
        raise ValueError('기타 카테고리를 활성화하세요.')
    return definitions, profile(settings, definitions)


def digest_url(url):
    import hashlib
    return hashlib.sha256(url.rstrip('/').encode()).hexdigest()


def snapshot(cache, settings):
    users, messages, meta = cache.read()
    if meta.get('source') != digest_url(settings.base_url):
        raise ValueError('저장된 데이터와 OpenWebUI 연결 설정이 다릅니다.')
    return users, messages, meta


def fingerprint(m):
    return digest([m['id'], key(m)])


def prepare(settings, cache, store, kind='pending'):
    if kind not in ('pending', 'sample', 'retry'):
        raise ValueError('지원하지 않는 분류 작업입니다.')
    _, version = configuration(settings)
    snapshot(cache, settings)
    return store.start(version, kind, settings.category_max_questions)


def collect(settings, cache, store, run, upstream=None, classifier=None, check=None):
    try:
        definitions, version = configuration(settings)
        with store.connect() as db:
            job = dict(db.execute('SELECT * FROM category_runs WHERE id=?', (run,)).fetchone())
        if job['profile'] != version:
            raise ValueError('분류 기준이 변경되었습니다. 새 분류를 시작하세요.')
        _, messages, _ = snapshot(cache, settings)
        results = store.read(version)
        overrides=store.overrides(version)
        def manual(m):
            o=overrides.get(digest(m['id']))
            return bool(o and o['content_key']==key(m) and o['category'] in {d['category'] for d in definitions})
        candidates = [m for m in messages if m['role']=='user' and not manual(m) and
                      (key(m) not in results if job['kind'] in ('pending','sample') else
                       key(m) in results and results[key(m)]['state'] in ('uncertain','fallback'))]
        candidates.sort(key=lambda m:(-m['created_at'],m['id']))
        if job['kind']=='sample':
            candidates=candidates[:min(20,settings.category_max_questions)]
        remaining=store.targets(run,[fingerprint(m) for m in candidates])
        current={fingerprint(m):m for m in messages if m['role']=='user'}
        targets=[current[f] for f in remaining if f in current]
        targets.sort(key=lambda m:(-m['created_at'],m['id']))
        processed,calls,reused,unavailable=(job[k] for k in ('processed','calls','reused','unavailable'))
        ack=list(remaining-current.keys())
        unavailable+=len(ack)
        batch=[]
        completed_keys=set()
        client=upstream or OpenWebUIClient(settings)
        model=classifier or Classifier(settings,definitions)

        def progress(decisions=()):
            store.progress(run,processed,calls,reused,unavailable,decisions,done=ack)
            ack.clear()

        def boundary():
            if check:
                check()
            with store.connect() as db:
                control=db.execute('SELECT stop_requested,pause_requested FROM category_runs WHERE id=?',(run,)).fetchone()
            if control['stop_requested']:
                raise JobCancelled()
            if control['pause_requested']:
                raise JobPaused()

        def flush():
            nonlocal processed,calls
            if not batch:
                return
            boundary()
            calls+=1
            progress()
            inputs=[{'id':f'Q{i}','text':q[1],'hasAttachments':bool(q[0]['has_files'])} for i,q in enumerate(batch)]
            out=model.classify(inputs)
            allowed={d['category'] for d in definitions}
            if set(out)!={q['id'] for q in inputs} or any(cat is not None and cat not in allowed for cat,_ in out.values()):
                raise ContractError('분류 응답 형식이 올바르지 않습니다.')
            decisions=[]
            for i,(m,text,truncated) in enumerate(batch):
                cat,confidence=out[f'Q{i}']
                state='classified' if cat else 'fallback'
                cat=cat or '기타'
                k=key(m)
                decisions.append((k,cat,confidence,state,int(truncated)))
                results[k]={'category':cat,'state':state}
                completed_keys.add(k)
                ack.append(fingerprint(m))
            processed+=len(batch)
            progress(decisions)
            batch.clear()

        groups=defaultdict(dict)
        for m in targets:
            groups[m['user_id']][m['id']]=m
        progress()
        for uid,wanted in groups.items():
            boundary()
            seen=set()
            previous=float('inf')
            for page in range(settings.max_pages_per_user):
                boundary()
                progress()
                items=client.messages(uid,page*settings.page_size)
                for raw in items:
                    row=normalize_message(raw,uid)
                    if row[0] in seen or row[6]>previous:
                        raise ContractError('질문 목록이 변경되었습니다. 데이터를 업데이트한 뒤 다시 실행하세요.')
                    seen.add(row[0]);previous=row[6]
                    if row[0] not in wanted:
                        continue
                    m=wanted.pop(row[0])
                    if row[3]!='user' or row[9]!=m['content_hash'] or bool(row[8])!=bool(m['has_files']):
                        unavailable+=1;ack.append(fingerprint(m));progress();continue
                    k=key(m)
                    if manual(m) or (k in results and job['kind'] in ('pending','sample')) or k in completed_keys:
                        processed+=1;reused+=1;ack.append(fingerprint(m));progress();continue
                    if any(key(q[0])==k for q in batch):
                        flush()
                        processed+=1;reused+=1;ack.append(fingerprint(m));progress();continue
                    text=text_content(raw.get('content'))
                    if not text:
                        processed+=1;ack.append(fingerprint(m))
                        results[k]={'category':None,'state':'no-text'}
                        progress([(k,None,None,'no-text',0)])
                        continue
                    batch.append((m,text[:settings.category_max_chars],len(text)>settings.category_max_chars))
                    if len(batch)>=settings.category_batch_size or (processed+unavailable+len(batch))%job['window_size']==0:
                        flush()
                if not wanted or len(items)<settings.page_size:
                    break
            else:
                raise ContractError('조회 한도에 도달했습니다. 연결 설정을 확인하세요.')
            unavailable+=len(wanted)
            ack.extend(fingerprint(m) for m in wanted.values())
            flush();progress()
        boundary()
        store.finish(run,status='partial' if unavailable else 'success')
        return {'ok':True,'runId':run,'processed':processed,'calls':calls,'reused':reused,'unavailable':unavailable}
    except JobPaused:
        store.pause(run)
        return {'ok':True,'runId':run,'status':'paused','processed':processed}
    except JobCancelled:
        store.cancel(run)
        return {'ok':True,'runId':run,'status':'cancelled','processed':processed}
    except Exception as error:
        safe=str(error) if isinstance(error,(UpstreamError,ValueError)) else '분류에 실패했습니다. 완료한 결과는 유지됩니다.'
        store.finish(run,safe)
        raise RuntimeError(safe) from None
