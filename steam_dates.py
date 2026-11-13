"""Steam license-page dates: explicit IDs first, unique exact titles second."""
import html
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit,urljoin,parse_qs,urlencode,urlunsplit
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from core import acquisition_date
from web_sessions import WebsiteSession,SessionError,STEAM_LICENSES,auth_dir,read_json,atomic_json

class LicenseParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None;self.ignore=0;self.depth=0;self.row_attrs={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag not in ['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']:self.depth+=1
        if tag=='tr':self.row=[];self.row_attrs=attrs
        if self.row is None:return
        if tag=='td':self.cell={'class':attrs.get('class',''),'text':[],'attrs':[self.row_attrs]};self.row.append(self.cell)
        if self.cell is not None:
            self.cell['attrs'].append(attrs)
            if not self.ignore and any(word in attrs.get('class','').split() for word in ['free_license_remove_link','license_date_col_label']):self.ignore=self.depth
    def handle_endtag(self,tag):
        if tag in ['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']:return
        if self.ignore and self.depth<=self.ignore:self.ignore=0
        if tag=='td':self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None;self.cell=None
        self.depth=max(0,self.depth-1)
    def handle_data(self,data):
        if self.cell is not None and not self.ignore:self.cell['text'].append(data)

MONTHS={name:index+1 for index,name in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'])}
def license_date(text):
    text=' '.join(text.replace(',',' ').split());match=re.fullmatch(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',text)
    if match:day,month,year=match.groups()
    else:
        match=re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})',text)
        if not match:return acquisition_date(text)
        month,day,year=match.groups()
    try:return acquisition_date(datetime(int(year),MONTHS[month[:3].lower()],int(day)).date().isoformat())
    except (ValueError,KeyError):return None

def title_key(value):
    text=unicodedata.normalize('NFKC',html.unescape(str(value)).replace('™','').replace('®',''))
    return ' '.join(text.casefold().split())

def parse_licenses(source):
    parser=LicenseParser();parser.feed(source);result=[]
    for cells in parser.rows:
        date_index=next((i for i,c in enumerate(cells) if 'license_date_col' in c['class'].split()),None)
        if date_index is None or date_index+1>=len(cells):continue
        date=license_date(''.join(cells[date_index]['text']));cell=cells[date_index+1];title=' '.join(''.join(cell['text']).split())
        if not date or not title:continue
        apps=set();packages=set()
        for c in cells:
            for attrs in c['attrs']:
                if str(attrs.get('data-appid','')).isdigit():apps.add(str(attrs['data-appid']))
                for key in ['data-packageid','data-subid']:
                    if str(attrs.get(key,'')).isdigit():packages.add(str(attrs[key]))
                href=attrs.get('href','')
                if re.match(r'^/(?:app|sub)/\d+(?:/|$)',href):
                    match=re.match(r'^/(app|sub)/(\d+)',href)
                    (apps if match[1]=='app' else packages).add(match[2])
                for value in attrs.values():
                    apps.update(re.findall(r'https?://store\.steampowered\.com/app/(\d+)(?:/|\b)',value))
                    packages.update(re.findall(r'https?://store\.steampowered\.com/sub/(\d+)(?:/|\b)',value))
                    packages.update(re.findall(r'RemoveFreeLicense\s*\(\s*(\d+)\s*,',value))
        result.append({'date':date,'title':title,'apps':sorted(apps),'packages':sorted(packages)})
    return result

class ContinuationLinks(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href')
            if href:self.links.append(href)

def next_license_page(text,current_url):
    """Follow only Steam's own license links, without inventing continuation values."""
    parser=ContinuationLinks();parser.feed(text)
    current_query=parse_qs(urlsplit(current_url).query)
    current_offset=int(current_query.get('offset',['0'])[0])
    candidates=[]
    for href in parser.links:
        url=urljoin(current_url,href);parts=urlsplit(url)
        if parts.scheme!='https' or parts.netloc!='store.steampowered.com' or parts.path.rstrip('/')!='/account/licenses':continue
        query=parse_qs(parts.query)
        if len(query.get('continuationToken',[]))!=1 or len(query.get('offset',[]))!=1:continue
        token=query['continuationToken'][0];offset=query['offset'][0]
        if not token or not offset.isdigit() or int(offset)<=current_offset:continue
        # Keep account-page language deterministic. Tokens are opaque and never logged.
        query={'continuationToken':token,'offset':offset,'l':'english'}
        candidates.append((int(offset),urlunsplit(('https','store.steampowered.com','/account/licenses/',urlencode(query),''))))
    return min(candidates,key=lambda item:item[0])[1] if candidates else None

def fetch_license_page(options,expected_id,cancel=None,progress=None,diagnostics=None):
    from connectors import Cancelled
    imported=options.get('steam_licenses_html','').strip()
    url=STEAM_LICENSES
    if imported:
        file=Path(imported).expanduser()
        if file.stat().st_size>16*1024*1024:raise SessionError('Imported Steam license page is too large.')
        text=file.read_text(encoding='utf-8-sig');source='Steam imported license page'
    else:
        session=WebsiteSession('steam',options)
        if session.steam_id()!=str(expected_id):raise SessionError('Steam dates session belongs to another account. Sources → Connect Steam dates with the same account as your SteamID64.')
        text,url=session.get(url);source='Steam account license page'
    details=diagnostics if diagnostics is not None else {}
    details.update(license_pages=0,license_history_complete=True,license_warnings=[])
    licenses=[];seen_urls=set();seen_pages=set()
    while True:
        if cancel is not None and cancel.is_set():raise Cancelled()
        parts=urlsplit(url)
        if parts.scheme!='https' or parts.netloc!='store.steampowered.com' or parts.path.rstrip('/')!='/account/licenses':raise SessionError('Steam website session expired. Open Sources → Connect Steam dates.')
        page_ids=set(re.findall(r"g_steamID\s*=\s*['\"](\d{17})['\"]",text))
        if page_ids and str(expected_id) not in page_ids:raise SessionError('Steam license page belongs to a different account.')
        page=parse_licenses(text)
        if not page:raise SessionError('No dated Steam licenses found on a requested page; no partial date history was applied.')
        signature=json.dumps(page,sort_keys=True)
        if signature in seen_pages:raise SessionError('Steam repeated a license page; no partial date history was applied.')
        seen_pages.add(signature);seen_urls.add(url);licenses.extend(page);details['license_pages']+=1
        next_url=next_license_page(text,url)
        suspicious=bool(re.search(r'load_more_licenses|btn_load_more|LoadMoreLicenses',text,re.I)) or len(page)==100
        if imported:
            if next_url or suspicious:
                details['license_history_complete']=False
                details['license_warnings'].append('Imported HTML may contain only one license page. Connect Steam dates to retrieve remaining pages.')
            break
        if not next_url:
            if suspicious:
                details['license_history_complete']=False
                details['license_warnings'].append('Steam returned a full page but no advancing continuation link. Only the retrieved pages were matched; completeness is unverified.')
            break
        if next_url in seen_urls or details['license_pages']>=200:raise SessionError('Steam license pagination did not advance or exceeded 200 pages; no partial date history was applied.')
        if cancel is not None and cancel.wait(.25):raise Cancelled()
        if progress:progress('Steam acquisition dates: loading license page '+str(details['license_pages']+1))
        text,url=session.get(next_url)
    return licenses,source

def steam_dates(rows,options,cancel,progress,request):
    from connectors import Cancelled,FetchError
    if cancel.is_set():raise Cancelled()
    expected=options.get('steam_id','').strip()
    if not options.get('steam_dates_enabled') and not options.get('steam_licenses_html'):
        return {'store':'Steam','source':'Steam account license page','matched':0,'unmatched_games':len(rows),'warnings':['Steam dates are not connected. Sources → Steam → Connect Steam dates.']}
    diagnostics={}
    licenses,source=fetch_license_page(options,expected,cancel,progress,diagnostics)
    wanted={r['id'] for r in rows};titles={}
    for row in rows:titles.setdefault(title_key(row['title']),set()).add(row['id'])
    dates={};methods={};packages={};ambiguous=0;unmatched=[];package_failures=0;rate_limited=False;failure_reasons={};failure_samples=[]
    cache_path=auth_dir(options)/'steam-packages.json';cache=read_json(cache_path,{})
    if not isinstance(cache,dict):cache={}
    def put(ident,date,method):
        if ident not in wanted:return
        if ident not in dates or date<dates[ident]:dates[ident]=date;methods[ident]=method
    for license in licenses:
        if cancel.is_set():raise Cancelled()
        for ident in license['apps']:put(ident,license['date'],'explicit app ID')
        for ident in license['packages']:
            if ident not in packages or license['date']<packages[ident]:packages[ident]=license['date']
        matches=titles.get(title_key(license['title']),set())
        if len(matches)==1:put(next(iter(matches)),license['date'],'unique exact license title')
        elif len(matches)>1:ambiguous+=1
    # Package IDs are authenticated license evidence; public package details only map them to apps.
    # Mappings already in the cache cost no request and are applied first, so completed
    # matches always fill in dates even if a later request is rate limited.
    cached=[];uncached=[]
    for ident,date in packages.items():
        entry=cache.get(ident,{})
        apps=entry.get('apps') if isinstance(entry,dict) and entry.get('time',0)>time.time()-30*86400 else None
        if isinstance(apps,list):cached.append((ident,date,apps))
        else:uncached.append((ident,date))
    for ident,date,apps in cached:
        for app in apps:put(str(app),date,'explicit license package → app ID')
    # Licenses without explicit app IDs can only be dated through their package mapping,
    # so those requests come first while the request budget lasts.
    solo_packages={ident for license in licenses if not license['apps'] for ident in license['packages']}
    uncached.sort(key=lambda item:item[0] not in solo_packages)
    fetched=0;postponed=len(uncached)
    for ident,date in uncached:
        if cancel.is_set():raise Cancelled()
        progress(f'Steam acquisition dates: package {fetched+1}/{len(uncached)}')
        try:
            data=request('https://store.steampowered.com/api/packagedetails',params={'packageids':ident,'l':'english'})
            value=data.get(ident,{}) if isinstance(data,dict) else {}
            if not value.get('success') or not isinstance(value.get('data'),dict) or not isinstance(value['data'].get('apps'),list):raise ValueError('No public app mapping returned')
            apps=[str(a['id']) for a in value['data']['apps'] if isinstance(a,dict) and str(a.get('id','')).isdigit()]
            cache[ident]={'time':time.time(),'apps':apps};atomic_json(cache_path,cache)
        except (FetchError,ValueError) as exc:
            package_failures+=1
            reason=str(exc) if isinstance(exc,FetchError) else 'No public app mapping returned'
            failure_reasons[reason]=failure_reasons.get(reason,0)+1
            if len(failure_samples)<10:failure_samples.append({'package_id':ident,'reason':reason})
            if isinstance(exc,FetchError) and exc.status==429:
                rate_limited=True;break
            if cancel.wait(.25):raise Cancelled()
            continue
        fetched+=1;postponed=len(uncached)-fetched
        for app in apps:put(str(app),date,'explicit license package → app ID')
        if cancel.wait(.25):raise Cancelled()
    for row in rows:
        ident=row['id']
        if ident in dates:
            origin=source+' ('+methods[ident]+')';row.update(date_added=dates[ident],date_added_source=origin)
            row.setdefault('raw',{})['acquisition_record']={'date':dates[ident],'source':origin}
        elif len(unmatched)<30:unmatched.append({'id':ident,'title':row['title']})
    warnings=list(diagnostics['license_warnings'])
    if rate_limited:warnings.append('Steam package API rate limited the request; remaining package mappings were postponed. Exact-title and completed ID matches are retained.')
    if package_failures:warnings.append(str(package_failures)+' package mappings unavailable; those dates remain unknown unless matched independently.')
    return {'store':'Steam','source':source,'licenses':len(licenses),'license_pages':diagnostics['license_pages'],'license_history_complete':diagnostics['license_history_complete'],'package_mapping_failures':failure_reasons,'package_failure_samples':failure_samples,'package_ids':len(packages),'postponed_packages':postponed if rate_limited else 0,'date_fetch_incomplete':rate_limited,'matched':len(dates),'matched_by_method':{m:sum(v==m for v in methods.values()) for m in set(methods.values())},'ambiguous_title_rows_skipped':ambiguous,'unmatched_games':len(rows)-len(dates),'unmatched_samples':unmatched,'warnings':warnings}
