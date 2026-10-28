from collections import Counter
from datetime import datetime, time, timedelta
from .analytics import period, SEOUL, ALL, choices
from .organization import enrich, load_org
from .categories import taxonomy, profile, UNCLASSIFIED, digest
from .category_store import CategoryStore, key


def category_usage(cache, settings, *, start=None,end=None,range_value='7d',division=ALL,team=ALL,position=ALL,category=ALL,page=1,page_size=50):
    if page<1 or not 1<=page_size<=1000:
        raise ValueError('Invalid pagination')
    definitions = taxonomy(settings.category_csv)
    version = profile(settings,definitions)
    users,messages,meta = cache.read()
    org, org_status = load_org(settings.org_csv)
    users = enrich(users,org)
    a,b = period(start,end,range_value,meta['last_success'])
    if a and (b-a).days>3659:
        raise ValueError('Date range must not exceed 3660 days')
    lo = datetime.combine(a,time.min,SEOUL).timestamp() if a else float('-inf')
    hi = datetime.combine(b+timedelta(days=1),time.min,SEOUL).timestamp() if b else float('inf')
    selected = {u['id']:u for u in users if all(v==ALL or u[k]==v for k,v in (('division',division),('team',team),('position',position)))}
    store = CategoryStore(settings.category_cache_path)
    results = store.read(version)
    overrides = store.overrides(version)
    dist = Counter({d['category']:0 for d in definitions})
    dist[UNCLASSIFIED]=0
    rows, states, daily = [], Counter(), Counter()
    total = truncated = 0
    for m in reversed(messages):
        if m['role']!='user' or m['user_id'] not in selected or not lo<=m['created_at']<hi:
            continue
        r = results.get(key(m))
        cat = r['category'] if r and r['category'] else UNCLASSIFIED
        state = r['state'] if r else 'pending'
        fallback = state in ('uncertain','fallback') and '기타' in dist
        if fallback:
            cat, state = '기타', 'classified'
        manual=overrides.get(digest(m['id']))
        manual=manual if manual and manual['content_key']==key(m) and manual['category'] in dist else None
        if manual:
            cat,state,fallback=manual['category'],'classified',False
        total+=1; states[state]+=1; dist[cat]+=1
        truncated+=int(bool(r and r['truncated']))
        date = datetime.fromtimestamp(m['created_at'],SEOUL).date().isoformat()
        if category!=ALL and cat!=category:
            continue
        daily[date]+=1
        u = selected[m['user_id']]
        rows.append({'id':m['id'],'at':m['created_at'],'userName':u['name'],'division':u['division'],'team':u['team'],'category':cat,'state':state,'manual':bool(manual),'fallback':fallback,'confidence':r['confidence'] if r and not manual else None,'truncated':bool(r and r['truncated'])})
    records = [{'name':name,'value':n,'percent':round(n/total*100,1) if total else 0} for name,n in sorted(dist.items(),key=lambda p:(-p[1],p[0]))]
    return {'schemaVersion':1,'source':'category-llm-cache','period':{'start':str(a) if a else None,'end':str(b) if b else None,'timezone':'Asia/Seoul'},'updatedAt':meta['last_success'],
            'summary':{'questions':total,'classified':states['classified'],'pending':states['pending'],'uncertain':states['uncertain'],'noText':states['no-text'],'truncated':truncated,'coveragePercent':round(states['classified']/total*100,1) if total else 0},
            'distribution':records,'daily':[{'date':d,'questions':n} for d,n in sorted(daily.items())],
            'filters':{'divisions':choices(u['division'] for u in users),'teams':choices(u['team'] for u in users if division==ALL or u['division']==division),'positions':choices(u['position'] for u in users),'categories':[ALL,*[d['category'] for d in definitions],UNCLASSIFIED]},
            'definitions':[{'category':d['category'],'description':d['description']} for d in definitions],
            'dataState':{'organization':org_status,'profile':version,'contentStored':False},
            'detail':{'total':len(rows),'page':page,'pageSize':page_size,'records':rows[(page-1)*page_size:page*page_size]},**store.status()}
