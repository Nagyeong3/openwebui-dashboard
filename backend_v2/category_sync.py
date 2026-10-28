"""Refetch only pending users' questions into memory; classify against the published snapshot."""
from collections import defaultdict
from .client import OpenWebUIClient, UpstreamError, ContractError
from .sync import normalize_message
from .categories import taxonomy, profile, Classifier, text_content
from .category_store import key


class Stopped(Exception):
    pass


def configuration(settings):
    definitions = taxonomy(settings.category_csv)
    if not (settings.category_url or settings.litellm_url) or not settings.category_key or not settings.category_model:
        raise ValueError('Set CATEGORY_LITELLM_API_KEY, CATEGORY_LLM_MODEL and category/LiteLLM base URL')
    if not settings.base_url or not settings.api_token:
        raise ValueError('OpenWebUI API credentials are required to read question text')
    if '기타' not in {d['category'] for d in definitions}:
        raise ValueError('An active 기타 category is required for uncertain answers')
    return definitions, profile(settings, definitions)


def snapshot(cache, settings):
    users, messages, meta = cache.read()
    if meta.get('source') != digest_url(settings.base_url):
        raise ValueError('OpenWebUI source differs from saved snapshot; select the matching cache')
    return users, messages, meta


def digest_url(url):
    import hashlib
    return hashlib.sha256(url.rstrip('/').encode()).hexdigest()


def prepare(settings, cache, store, kind='pending'):
    if kind not in ('pending','sample','retry'):
        raise ValueError('Category kind must be pending, sample or retry')
    definitions, version = configuration(settings)
    snapshot(cache, settings)
    return store.start(version, kind, settings.category_max_questions)


def collect(settings, cache, store, run, upstream=None, classifier=None):
    try:
        definitions, version = configuration(settings)
        with store.connect() as db:
            job = db.execute('SELECT * FROM category_runs WHERE id=?',(run,)).fetchone()
        if not job or job['profile']!=version:
            raise ValueError('Category definitions changed before job started; start a new job')
        _, messages, _ = snapshot(cache, settings)
        results = store.read(version)
        targets = [m for m in messages if m['role']=='user' and
                   (key(m) not in results if job['kind'] in ('pending','sample') else
                    key(m) in results and results[key(m)]['state'] in ('uncertain','fallback'))]
        # Bounded work, newest first. Already valid hashes never require API reads.
        targets.sort(key=lambda m:(-m['created_at'],m['id']))
        if job['kind']=='sample':
            targets = targets[:min(20,settings.category_max_questions)]
        store.set_total(run,len(targets))
        groups = defaultdict(dict)
        for m in targets:
            groups[m['user_id']][m['id']] = m
        client = upstream or OpenWebUIClient(settings)
        model = classifier or Classifier(settings, definitions)
        processed = calls = reused = unavailable = 0
        batch = []
        completed_keys = set()

        def check_stop():
            if store.stopped(run):
                raise Stopped()

        def progress(decisions=()):
            store.progress(run,processed,calls,reused,unavailable,decisions)

        def flush():
            nonlocal processed, calls
            if not batch:
                return
            check_stop()
            progress()
            inputs = [{'id':f'Q{i}','text':q[1], 'hasAttachments':bool(q[0]['has_files'])} for i,q in enumerate(batch)]
            out = model.classify(inputs)
            # Validate injected clients too; no partial batch publication.
            allowed = {d['category'] for d in definitions}
            if set(out)!={q['id'] for q in inputs} or any(cat is not None and cat not in allowed for cat,_ in out.values()):
                raise ContractError('Category model returned invalid batch')
            decisions = []
            for i,(message,text,truncated) in enumerate(batch):
                cat, confidence = out[f'Q{i}']
                k = key(message)
                state = 'classified' if cat else 'fallback'
                cat = cat or '기타'
                row = (k,cat,confidence,state,int(truncated))
                decisions.append(row)
                results[k] = {'category':cat,'state':row[3]}
                completed_keys.add(k)
            calls += 1
            processed += len(batch)
            progress(decisions)
            batch.clear()

        for uid, wanted in groups.items():
            check_stop()
            seen = set()
            previous = float('inf')
            for page in range(settings.max_pages_per_user):
                check_stop()
                progress()
                items = client.messages(uid,page*settings.page_size)
                for raw in items:
                    row = normalize_message(raw,uid)
                    if row[0] in seen or row[6]>previous:
                        raise ContractError('OpenWebUI message pagination shifted; synchronize and retry')
                    seen.add(row[0]); previous=row[6]
                    if row[0] not in wanted:
                        continue
                    m = wanted.pop(row[0])
                    # Skip edits since snapshot; never classify new text under an old hash.
                    if row[3]!='user' or row[9]!=m['content_hash'] or bool(row[8])!=bool(m['has_files']):
                        unavailable += 1
                        continue
                    k = key(m)
                    if (k in results and job['kind'] in ('pending','sample')) or k in completed_keys:
                        reused+=1; processed+=1; progress(); continue
                    if any(key(q[0])==k for q in batch):
                        flush()
                        reused+=1; processed+=1; progress(); continue
                    text = text_content(raw.get('content'))
                    if not text:
                        processed+=1
                        results[k]={'category':None,'state':'no-text'}
                        progress([(k,None,None,'no-text',0)])
                        continue
                    batch.append((m,text[:settings.category_max_chars],len(text)>settings.category_max_chars))
                    if len(batch)>=settings.category_batch_size or (processed+unavailable+len(batch)) % job['window_size'] == 0:
                        flush()
                if not wanted or len(items)<settings.page_size:
                    break
            else:
                raise ContractError('Maximum OpenWebUI pages reached; category collection incomplete')
            unavailable += len(wanted)
            flush()
            progress()
        if store.stopped(run):
            store.cancel(run)
            return {'ok':True,'runId':run,'status':'cancelled','processed':processed}
        store.finish(run,status='partial' if unavailable else 'success')
        return {'ok':True,'runId':run,'processed':processed,'calls':calls,'reused':reused,'unavailable':unavailable}
    except Stopped:
        store.cancel(run)
        return {'ok':True,'runId':run,'status':'cancelled','processed':processed}
    except Exception as e:
        safe = str(e) if isinstance(e,(UpstreamError,ValueError)) else 'Category classification failed; completed batches preserved'
        store.finish(run,safe)
        raise RuntimeError(safe) from None
