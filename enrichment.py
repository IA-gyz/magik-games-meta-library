"""Resumable metadata fetches with per-provider failure isolation and diagnostics."""
from provider_registry import PROVIDERS
from error_messages import explain_store_error
from contracts import SummaryMessages,LogEntry,Severity
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from connectors import steam_details, gog_details, FetchError, Cancelled
from epic_metadata import epic_details, load_heroic_cache, ENRICHMENT_VERSION

PACE_SECONDS=2.5
MAX_ATTEMPTS=3
FETCHERS={spec.name:globals()[spec.metadata_function] for spec in PROVIDERS if spec.metadata_function}

def needs_enrichment(row):
    raw=row.get('raw') or {}
    if row['store']=='Steam':return not raw.get('store_details')
    if row['store']=='GOG':return not (raw.get('product') and raw.get('v2'))
    if row['store']=='Epic':return (raw.get('epic_enrichment') or {}).get('version')!=ENRICHMENT_VERSION
    return False


RETRY_UNAVAILABLE_SECONDS=7*24*60*60
RETRY_FAILED_SECONDS=60*60
RETRY_DEFERRED_SECONDS=15*60

def next_retry(result):
    if result.get('retry_after'):return result['retry_after']
    outcome=result.get('outcome')
    if outcome=='enriched':return None
    delay=RETRY_UNAVAILABLE_SECONDS if outcome=='unavailable' or (outcome=='partial' and '404' in result.get('reason','')) else (RETRY_DEFERRED_SECONDS if outcome=='deferred' else RETRY_FAILED_SECONDS)
    try:
        when=datetime.fromisoformat(result['time'])
        if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
        return (when+timedelta(seconds=delay)).isoformat(timespec='seconds')
    except (ValueError,KeyError):return None

def select_candidates(rows,results,enabled=None,force=False,now=None):
    now=now or datetime.now(timezone.utc)
    previous={(r['store'],r['id']):r for r in results}
    ready=[];postponed=0
    for row in rows:
        if not row.get('active') or not needs_enrichment(row) or (enabled is not None and row['store'] not in enabled):continue
        result=previous.get((row['store'],row['id']))
        retry=next_retry(result) if result else None
        if not force and retry:
            try:
                if datetime.fromisoformat(retry)>now:postponed+=1;continue
            except ValueError:pass
        ready.append(row)
    return ready,postponed

def safe_error(exc, store=None):
    # Unexpected exception text may contain HTTP request information: keep only its class.
    return explain_store_error(exc, store, game_details=True) if isinstance(exc,FetchError) else type(exc).__name__+' while parsing metadata'

def fetch_with_retry(row,cancel,progress,heroic_cache=None):
    for attempt in range(MAX_ATTEMPTS):
        if cancel.is_set(): raise Cancelled()
        try:
            if row['store']=='Epic':return FETCHERS['Epic'](row,heroic_cache,cancel)
            return FETCHERS[row['store']](row)
        except FetchError as exc:
            if exc.category not in ['rate_limit','temporary'] or attempt==MAX_ATTEMPTS-1:
                raise
            delay=max(exc.retry_after,10*(2**attempt))
            # A long Retry-After pauses this provider for the run instead of keeping the UI waiting.
            if delay>60: raise
            progress(f'{row["store"]}: {safe_error(exc, row["store"])} — retry {attempt+1}/{MAX_ATTEMPTS-1} in {delay:g}s')
            if cancel.wait(delay): raise Cancelled()

def run_enrichment(db,candidates,cancel,progress,changed,options=None):
    counters=defaultdict(Counter); blocked={}; consecutive=Counter()
    heroic_cache,warnings=load_heroic_cache(options or {}) if any(r['store']=='Epic' for r in candidates) else ({},[])
    for warning in warnings:progress(warning)
    for i,row in enumerate(candidates):
        if cancel.is_set(): raise Cancelled()
        store=row['store']; outcome='enriched'; reason='Game details saved. The store may not provide every field.'
        if store in blocked:
            outcome='deferred'; reason=blocked[store]
        else:
            progress(f'Metadata {i+1}/{len(candidates)} · {store} · {row["title"]}')
            try:
                enriched=fetch_with_retry(row,cancel,progress,heroic_cache)
                warning=enriched.pop('_metadata_warning',None)
                db.save([enriched])
                if warning:
                    outcome='partial'; reason=('Basic GOG details saved. Additional details could not be loaded: ' if store=='GOG' else 'Saved Heroic details were kept. Additional Epic details could not be loaded: ')+warning['message']
                    category=warning['category']
                    if category=='rate_limit' or warning.get('status') in [401,403]: blocked[store]=reason
                    if category in ['temporary','http']:
                        consecutive[store]+=1
                        if consecutive[store]>=3: blocked[store]='Requests to this store were paused after three failed attempts in a row.'
                    else: consecutive[store]=0
                else: consecutive[store]=0
            except Cancelled: raise
            except Exception as exc:
                reason=safe_error(exc, store)
                category=exc.category if isinstance(exc,FetchError) else 'parse'
                outcome='unavailable' if category=='unavailable' else 'failed'
                if category in ['rate_limit','http','temporary','parse']:
                    consecutive[store]+=1
                    if category=='rate_limit' or getattr(exc,'status',None) in [401,403] or consecutive[store]>=3:
                        blocked[store]='Requests to this store were paused: '+reason
                else: consecutive[store]=0
            if cancel.wait(PACE_SECONDS):
                db.metadata_result(row,outcome,reason,next_retry({'outcome':outcome,'reason':reason,'time':datetime.now(timezone.utc).isoformat()})); raise Cancelled()
        db.metadata_result(row,outcome,reason,next_retry({'outcome':outcome,'reason':reason,'time':datetime.now(timezone.utc).isoformat()})); counters[store][outcome]+=1
        if i%10==0: changed()
    changed()
    events=[]
    for store,counts in counters.items():
        severity=Severity.ERROR if counts['failed'] else Severity.WARNING if any(counts[k] for k in ['partial','unavailable','deferred']) else Severity.SUCCESS
        events.append(LogEntry(f'Game details · {store}: '+', '.join(f'{counts[k]} {label}' for k,label in [('enriched','complete'),('partial','partly saved'),('unavailable','not available'),('failed','failed'),('deferred','waiting')]),severity,store))
    for store,reason in blocked.items():events.append(LogEntry(f'{store}: {reason}. Try again later with Get missing game details.',Severity.WARNING,store))
    return SummaryMessages(events or [LogEntry('There are no missing Steam, GOG or Epic game details to request.')])
