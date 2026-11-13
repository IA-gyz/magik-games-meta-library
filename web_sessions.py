"""App-owned website sessions and EA token renewal; never read browser profiles."""
import http.cookiejar
import hashlib
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from app_config import data_root

ALLOWED={'ea':('ea.com',),'steam':('steampowered.com','steamcommunity.com')}
EA_AUTH='https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus%3Arest&prompt=none'
STEAM_LICENSES='https://store.steampowered.com/account/licenses/?l=english'
class SessionError(Exception):pass

def auth_dir(options=None):
    options=options or {}
    return Path(options.get('auth_dir') or data_root()/'auth').expanduser()

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(path.parent,0o700)
    fd,temp=tempfile.mkstemp(prefix='.session-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def read_json(path,default=None):
    try:
        if Path(path).stat().st_size>8*1024*1024:raise ValueError()
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def allowed_domain(service,domain):
    domain=str(domain).lower().lstrip('.')
    return any(domain==root or domain.endswith('.'+root) for root in ALLOWED[service])

def valid_cookie(service,cookie):
    return isinstance(cookie,dict) and allowed_domain(service,cookie.get('domain','')) and all(isinstance(cookie.get(k),str) and not any(c in cookie[k] for c in '\r\n\0') for k in ['name','value','domain','path']) and bool(cookie['name'])

class WebsiteSession:
    def __init__(self,service,options=None):
        self.service=service;self.root=auth_dir(options);self.path=self.root/(service+'-cookies.json')
        data=read_json(self.path,{})
        if not isinstance(data,dict):data={}
        self.user_agent=data.get('user_agent') or 'Mozilla/5.0 MagikGamesLibrary/0.8'
        if not isinstance(self.user_agent,str) or '\n' in self.user_agent or '\r' in self.user_agent:self.user_agent='Mozilla/5.0 MagikGamesLibrary/0.8'
        self.jar=http.cookiejar.CookieJar()
        for c in data.get('cookies',[]) if isinstance(data.get('cookies'),list) else []:
            if not valid_cookie(service,c):continue
            expiration=c.get('expires')
            if expiration is not None and (not isinstance(expiration,(int,float)) or not math.isfinite(expiration) or expiration<=time.time()):continue
            self.jar.set_cookie(http.cookiejar.Cookie(0,c['name'],c['value'],None,False,c['domain'],bool(c['domain'].startswith('.')),c['domain'].startswith('.'),c['path'],True,bool(c.get('secure')),int(expiration) if expiration else None,expiration is None,None,None,{'HttpOnly':None} if c.get('http_only') else {},False))
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def cookies(self):
        return [{'name':c.name,'value':c.value,'domain':c.domain,'path':c.path,'secure':c.secure,'expires':c.expires,'http_only':c.has_nonstandard_attr('HttpOnly')} for c in self.jar if allowed_domain(self.service,c.domain) and not c.is_expired()]
    def save(self):atomic_json(self.path,{'cookies':self.cookies(),'user_agent':self.user_agent})
    def get(self,url):
        from connectors import FetchError
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not allowed_domain(self.service,parsed.hostname or ''):raise SessionError('Refusing a session request outside its service.')
        try:
            with self.opener.open(urllib.request.Request(url,headers={'User-Agent':self.user_agent,'Accept-Language':'en-US,en;q=0.9'}),timeout=30) as response:
                body=response.read(16*1024*1024+1)
                if len(body)>16*1024*1024:raise SessionError('Session response exceeded the size limit.')
                return body.decode('utf-8',errors='replace'),response.geturl()
        except urllib.error.HTTPError as exc:raise FetchError('Session request HTTP '+str(exc.code),status=exc.code,category='http') from None
        except (urllib.error.URLError,TimeoutError):raise SessionError('Session request timed out or could not connect.') from None
        finally:self.save()  # Persist server-side cookie rotation, including session cookies.
    def steam_id(self):
        ids=set()
        for c in self.jar:
            if c.name=='steamLoginSecure' and allowed_domain('steam',c.domain):
                ident=urllib.parse.unquote(c.value).split('||',1)[0]
                if ident.isdigit() and len(ident)==17:ids.add(ident)
        if len(ids)!=1:raise SessionError('Connect Steam dates again: no unambiguous Steam account session was found.')
        return ids.pop()

def valid_token(value):return isinstance(value,str) and bool(value) and len(value)<1024*1024 and all(32<ord(c)<127 for c in value)

def cookie_fingerprint(cookies):
    ordered = sorted(cookies, key=lambda c: (c['domain'], c['path'], c['name']))
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()

def renew_ea(options=None,force=False):
    from connectors import FetchError
    path=auth_dir(options)/'ea-token.json';saved=read_json(path,{})
    if not isinstance(saved,dict):saved={}
    session=WebsiteSession('ea',options)
    if not force and saved.get('session_fingerprint') == cookie_fingerprint(session.cookies()) and valid_token(saved.get('access_token')) and isinstance(saved.get('expires_at'),(int,float)) and saved['expires_at']>time.time()+90:return saved['access_token']
    if not session.cookies():raise SessionError('EA session is missing or expired. Open Sources → Connect EA and sign in again.')
    try:
        text,url=session.get(EA_AUTH);data=json.loads(text)
        token=data.get('access_token') if isinstance(data,dict) else None
        lifetime=float(data.get('expires_in',0)) if isinstance(data,dict) else 0
        if not valid_token(token) or not math.isfinite(lifetime) or lifetime<=0:raise ValueError()
    except (FetchError,ValueError,TypeError):raise SessionError('EA could not renew this login session. Open Sources → Connect EA and sign in again.') from None
    atomic_json(path,{'access_token':token,'expires_at':time.time()+lifetime,'expires_in':lifetime,'session_fingerprint':cookie_fingerprint(session.cookies())})
    return token

def forget_session(service,options=None):
    root=auth_dir(options)
    for suffix in ['cookies','token']:
        (root/(service+'-'+suffix+'.json')).unlink(missing_ok=True)
