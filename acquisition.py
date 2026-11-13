"""Read-only acquisition sources. Never infer dates from release or filesystem timestamps."""
from contracts import LibraryRows
import json
import os
from pathlib import Path
from urllib.parse import quote
from core import acquisition_date

class DateSourceError(Exception):pass

def profile(options):
    return Path(options.get('epic_config') or os.environ.get('LEGENDARY_CONFIG_PATH') or str(Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'legendary')).expanduser()

def read_json(path,limit=64*1024*1024):
    if path.stat().st_size>limit:raise ValueError('File too large')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def earliest(index,key,value):
    date=acquisition_date(value)
    if date and (key not in index or date<index[key]):index[key]=date

def apply_dates(rows,index,source):
    count=0
    for row in rows:
        date=index.get(row['id'])
        if date:
            row.update(date_added=date,date_added_source=source)
            row.setdefault('raw',{})['acquisition_record']={'date':date,'source':source}
            count+=1
    return count

def epic_library_records(token,cancel,request):
    from connectors import Cancelled
    records=[];cursor=None;seen=set()
    for page in range(100):
        if cancel.is_set():raise Cancelled()
        params={'includeMetadata':'true'}
        if cursor:params['cursor']=cursor
        data=request('https://library-service.live.use1a.on.epicgames.com/library/api/public/items',params=params,headers={'Authorization':'Bearer '+token})
        if not isinstance(data,dict) or not isinstance(data.get('records'),list) or not isinstance(data.get('responseMetadata'),dict):raise DateSourceError('Epic library-items response has an unsupported shape.')
        records.extend(data['records']);cursor=data['responseMetadata'].get('nextCursor')
        if not cursor:return records
        if not isinstance(cursor,str) or cursor in seen:raise DateSourceError('Epic library-items cursor repeated or is invalid.')
        seen.add(cursor)
    raise DateSourceError('Epic library-items pagination limit reached.')

def epic_dates(rows,options,cancel,progress,request,network=True):
    from connectors import FetchError,Cancelled
    if cancel.is_set():raise Cancelled()
    report={'store':'Epic','source':'Legendary entitlements cache','warnings':[]};root=profile(options);cached=[]
    report['selected_profile']=str(root)
    try:
        cached=read_json(root/'entitlements.json')
        if not isinstance(cached,list):raise ValueError()
    except (OSError,ValueError):cached=[];report['warnings'].append('Selected profile has no readable entitlements.json.')
    report['cached_records']=len(cached)
    entitlements=cached;token=None
    if network:
        try:
            session=read_json(root/'user.json',4*1024*1024)
            token=session.get('access_token');account=session.get('account_id')
            if not isinstance(token,str) or not token or not isinstance(account,str) or not account:raise DateSourceError('Selected Legendary profile has no usable session; using cache.')
            fresh=[];seen=set()
            for page in range(100):
                if cancel.is_set():raise Cancelled()
                response=request('https://entitlement-public-service-prod08.ol.epicgames.com/entitlement/api/account/'+quote(account,safe='')+'/entitlements',params={'start':len(fresh),'count':1000},headers={'Authorization':'Bearer '+token})
                if not isinstance(response,list):raise DateSourceError('Epic entitlement response was not a list.')
                fingerprint=json.dumps(response,sort_keys=True)
                if response and fingerprint in seen:raise DateSourceError('Epic repeated an entitlement page.')
                seen.add(fingerprint);fresh.extend(response)
                if len(response)<1000:break
            else:raise DateSourceError('Epic entitlement pagination limit reached.')
            entitlements=fresh;report['source']='Epic live entitlements (same Legendary session)';report['warnings']=[]
        except (OSError,ValueError,FetchError,DateSourceError) as exc:
            report['warnings'].append('Live entitlement query unavailable; using cache. '+(str(exc) if isinstance(exc,(FetchError,DateSourceError)) else 'Session file missing or invalid.'))
    library=[];library_apps={};library_items={};report['library_query']='not requested (offline or missing session)'
    if network and isinstance(token,str) and token:
        try:
            library=epic_library_records(token,cancel,request);report['library_query']='succeeded'
        except (FetchError,DateSourceError) as exc:
            report['library_query']='failed';report['warnings'].append('Epic library acquisition dates unavailable: '+str(exc))
    dated_library=0
    for record in library:
        if cancel.is_set():raise Cancelled()
        if not isinstance(record,dict):continue
        namespace=record.get('namespace');date=acquisition_date(record.get('acquisitionDate'))
        if not namespace or not date:continue
        dated_library+=1
        if record.get('appName'):earliest(library_apps,(str(namespace),str(record['appName'])),date)
        if record.get('catalogItemId'):earliest(library_items,(str(namespace),str(record['catalogItemId'])),date)
    by_id={};by_name={};namespaces=set();valid=0;skipped=0
    for e in entitlements:
        if cancel.is_set():raise Cancelled()
        if not isinstance(e,dict) or e.get('active') is False or e.get('status','ACTIVE')!='ACTIVE' or e.get('consumable'):
            skipped+=1;continue
        namespace=e.get('namespace');date=acquisition_date(e.get('grantDate'))
        if not namespace or not date:skipped+=1;continue
        valid+=1;namespaces.add(str(namespace))
        if e.get('catalogItemId'):earliest(by_id,(str(namespace),str(e['catalogItemId'])),date)
        if e.get('entitlementName'):earliest(by_name,(str(namespace),str(e['entitlementName'])),date)
    matched_id=matched_name=matched_library=0;unmatched=[];index={};sources={}
    for row in rows:
        m=(row.get('raw') or {}).get('metadata') or {};ns=str(m.get('namespace') or '')
        date=library_apps.get((ns,row['id'])) or library_items.get((ns,str(m.get('id'))));method='library acquisitionDate'
        if date:matched_library+=1
        else:
            date=by_id.get((ns,str(m.get('id'))));method='catalogItemId'
            if date:matched_id+=1
            else:
                date=by_name.get((ns,str(m.get('entitlementName'))));method='entitlementName'
                if date:matched_name+=1
        if date:
            index[row['id']]=date;sources[row['id']]='Epic library acquisitionDate' if method=='library acquisitionDate' else 'Epic entitlement grantDate'
            row.setdefault('raw',{})['acquisition_match']={'namespace':ns,'catalogItemId':m.get('id'),'entitlementName':m.get('entitlementName'),'method':method}
        elif len(unmatched)<30:
            unmatched.append({'app_id':row['id'],'namespace':ns,'catalog_item_id':m.get('id'),'entitlement_name':m.get('entitlementName'),'namespace_has_dated_entitlements':ns in namespaces})
    matched=apply_dates(rows,index,'Epic acquisition date')
    for row in rows:
        if row['id'] in sources:
            row['date_added_source']=sources[row['id']];row['raw']['acquisition_record']['source']=sources[row['id']]
    report.update(library_records=len(library),library_records_with_dates=dated_library,matched_library=matched_library,records=len(entitlements),valid_dated_entitlements=valid,skipped_entitlements=skipped,matched=matched,matched_catalog_id=matched_id,matched_entitlement_name=matched_name,unmatched_games=len(rows)-matched,unmatched_samples=unmatched)
    progress(f'Epic dates: {len(entitlements)} entitlements, {valid} dated, {matched_library} library-date matches, {matched_id} catalog-ID matches, {matched_name} entitlement-name matches, {len(rows)-matched} unmatched games.')
    return report

def ea_dates(rows,token,cancel,progress,request):
    from connectors import Cancelled,FetchError
    if cancel.is_set():raise Cancelled()
    accept='application/vnd.origin.v3+json; x-cache/force-write'
    try:identity=request('https://gateway.ea.com/proxy/identity/pids/me',headers={'Authorization':'Bearer '+token,'Accept':accept})
    except FetchError as exc:raise DateSourceError('EA identity endpoint: '+str(exc)) from None
    pid_object=identity.get('pid') if isinstance(identity,dict) else None
    pid=pid_object.get('pidId') if isinstance(pid_object,dict) else None
    if not pid:raise DateSourceError('EA identity response contains no pidId.')
    attempts=[];response=None
    for host in ['api2.origin.com','api1.origin.com']:
        if cancel.is_set():raise Cancelled()
        try:
            response=request('https://'+host+'/ecommerce2/consolidatedentitlements/'+quote(str(pid),safe=''),params={'machine_hash':1},headers={'authtoken':token,'Accept':accept})
            attempts.append({'host':host,'result':'response received'});break
        except FetchError as exc:
            attempts.append({'host':host,'result':str(exc)})
            # Only route-not-found errors justify trying the known alternative host.
            if exc.status not in [404,410]:
                raise DateSourceError('EA consolidated-entitlements '+host+': '+str(exc)) from None
    if response is None:
        raise DateSourceError('EA consolidated-entitlements routes unavailable: '+'; '.join(a['host']+' '+a['result'] for a in attempts))
    values=response.get('entitlements') if isinstance(response,dict) else None
    if not isinstance(values,list):raise DateSourceError('EA entitlement response has an unsupported shape.')
    index={};status_counts={};dated_records=0;identifiers=set()
    for e in values:
        if cancel.is_set():raise Cancelled()
        if not isinstance(e,dict):continue
        status=str(e.get('status','ACTIVE')).upper();status_counts[status]=status_counts.get(status,0)+1
        if status not in ['ACTIVE','ENABLED']:continue
        ident=e.get('offerId') or e.get('productId')
        if ident:
            identifiers.add(str(ident))
            if acquisition_date(e.get('grantDate')):dated_records+=1
            earliest(index,str(ident),e.get('grantDate'))
    matched=apply_dates(rows,index,'EA entitlement grantDate')
    return {'store':'EA','source':'EA consolidated entitlements','route_attempts':attempts,'records':len(values),'records_with_dates':dated_records,'status_counts':status_counts,'matched':matched,'unmatched_games':len(rows)-matched,'unmatched_samples':[{'id':r['id'],'title':r['title'],'offer_seen_without_date':r['id'] in identifiers} for r in rows if r['id'] not in index][:30],'warnings':[]}

def gog_dates(rows,headers,cancel,progress,request):
    from connectors import Cancelled
    index={};records=0;seen=set();status_counts={};observed={}
    for page in range(1,101):
        if cancel.is_set():raise Cancelled()
        response=request('https://www.gog.com/account/settings/orders/data',params={'canceled':0,'completed':1,'in_progress':0,'not_redeemed':1,'page':page,'pending':0,'redeemed':1},headers=headers)
        if not isinstance(response,dict) or not isinstance(response.get('orders'),list):raise DateSourceError('GOG order history requires website authentication or returned an unsupported response.')
        orders=response['orders'];fingerprint=json.dumps(orders,sort_keys=True)
        if orders and fingerprint in seen:raise DateSourceError('GOG repeated an order page.')
        seen.add(fingerprint);records+=len(orders)
        for order in orders:
            if not isinstance(order,dict):continue
            status=str(order.get('status','')).lower();status_counts[status]=status_counts.get(status,0)+1
            for product in order.get('products') or []:
                if not isinstance(product,dict) or product.get('id') is None:continue
                ident=str(product['id']);evidence=observed.setdefault(ident,{'statuses':set(),'skip_reasons':set(),'title':product.get('title')})
                evidence['statuses'].add(status);reasons=[]
                if status not in ['purchase','completed','complete','redeemed']:reasons.append('order status not eligible')
                if order.get('giftRecipient'):reasons.append('gift sent to another person')
                if product.get('isRefunded'):reasons.append('refunded product')
                if not acquisition_date(order.get('date')):reasons.append('missing or invalid order date')
                evidence['skip_reasons'].update(reasons)
                if not reasons:earliest(index,ident,order.get('date'))
        try:total=int(response['totalPages'])
        except (ValueError,KeyError,TypeError):raise DateSourceError('GOG order response contains no valid page count.')
        if page>=total:break
    else:raise DateSourceError('GOG order pagination limit reached.')
    matched=apply_dates(rows,index,'GOG completed order date')
    unmatched=[r for r in rows if r['id'] not in index];library_ids={r['id'] for r in rows}
    samples=[]
    # Prioritize shelf-confirmed records, whose known titles help interpret missing order evidence.
    for row in sorted(unmatched,key=lambda r:not bool((r.get('raw') or {}).get('account_shelf')))[:50]:
        evidence=observed.get(row['id'],{})
        samples.append({'id':row['id'],'title':row['title'],'type':row.get('type'),
            'on_account_shelf':bool((row.get('raw') or {}).get('account_shelf')),
            'seen_in_order_history':bool(evidence),'order_statuses':sorted(evidence.get('statuses',[])),
            'skip_reasons':sorted(evidence.get('skip_reasons',[]))})
    return {'store':'GOG','source':'GOG completed order history','order_status_counts':status_counts,'records':records,
        'matched':matched,'unmatched_games':len(unmatched),
        'unmatched_on_account_shelf':sum(bool((r.get('raw') or {}).get('account_shelf')) for r in unmatched),
        'unmatched_without_account_shelf':sum(not bool((r.get('raw') or {}).get('account_shelf')) for r in unmatched),
        'unmatched_seen_in_orders':sum(r['id'] in observed for r in unmatched),
        'unmatched_not_seen_in_orders':sum(r['id'] not in observed for r in unmatched),
        'dated_order_product_ids':len(index),'order_product_ids_outside_library':len(set(observed)-library_ids),
        'unmatched_samples':samples,
        'outside_library_samples':[{'id':ident,'title':observed[ident].get('title'),'has_eligible_date':ident in index} for ident in sorted(set(observed)-library_ids)[:20]],
        'warnings':[]}

def optional_dates(store,rows,progress,run):
    from connectors import FetchError
    from web_sessions import SessionError
    try:report=run()
    except (FetchError,DateSourceError,SessionError,OSError) as exc:
        report={'store':store,'source':'Acquisition service','matched':0,'warnings':[str(exc)],'unmatched_games':len(rows)}
        progress(store+' acquisition dates unavailable: '+str(exc)+'; library refresh retained.')
    return LibraryRows(rows,report)
