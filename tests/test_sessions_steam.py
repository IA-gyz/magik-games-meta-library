import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from web_sessions import WebsiteSession,atomic_json,auth_dir,renew_ea,SessionError,forget_session
from steam_dates import parse_licenses,license_date,steam_dates,fetch_license_page
from core import game,Database
from connectors import ea,FetchError,Cancelled

HTML='''<html><script>g_steamID = "76561198018049642";</script><table>
<tr><th>Date</th><th>Item</th></tr>
<tr><td class="license_date_col"><span class="license_date_col_label">Date acquired</span>Oct 2, 2020</td><td>Game &amp; More</td><td>Steam Store</td></tr>
<tr><td class="license_date_col">3 Oct, 2020</td><td><div class="free_license_remove_link"><a href="javascript:RemoveFreeLicense( 44, 'Other' );">Remove</a></div>Other Game</td></tr>
<tr data-appid="3"><td class="license_date_col">2021-01-01</td><td>Explicit Game</td></tr>
<tr><td class="license_date_col">Jan 1, 2020</td><td>Duplicate Name</td></tr>
</table></html>'''

class SessionTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.options={'auth_dir':self.temp.name}
 def tearDown(self):self.temp.cleanup()
 def cookies(self,service='ea'):
  cookie={'name':'sid' if service=='ea' else 'steamLoginSecure','value':'private' if service=='ea' else '76561198018049642%7C%7CSECRET','domain':'.ea.com' if service=='ea' else '.steampowered.com','path':'/','secure':True,'expires':None,'http_only':True}
  atomic_json(auth_dir(self.options)/(service+'-cookies.json'),{'cookies':[cookie]});return cookie
 def test_session_cookie_roundtrip_domain_scope_and_permissions(self):
  cookie=self.cookies();session=WebsiteSession('ea',self.options);self.assertEqual(len(session.cookies()),1)
  session.save();self.assertEqual(session.cookies()[0]['http_only'],True)
  path=auth_dir(self.options)/'ea-cookies.json';self.assertEqual(path.stat().st_mode&0o777,0o600)
  self.assertEqual(path.parent.stat().st_mode&0o777,0o700)
  with self.assertRaises(SessionError):session.get('https://example.com/')
  with self.assertRaises(SessionError):session.get('http://accounts.ea.com/')
  atomic_json(path,{'cookies':[{**cookie,'domain':'.ea.com.evil.test'},{**cookie,'expires':time.time()-1},{**cookie,'name':'bad\r\nheader'}]})
  self.assertFalse(WebsiteSession('ea',self.options).cookies())
 def test_ea_renews_expired_token_and_persists_expiry(self):
  self.cookies();atomic_json(auth_dir(self.options)/'ea-token.json',{'access_token':'old','expires_at':time.time()-1})
  with patch.object(WebsiteSession,'get',return_value=(json.dumps({'access_token':'new-private','expires_in':14399}),'https://accounts.ea.com/')) as get:
   self.assertEqual(renew_ea(self.options),'new-private');self.assertEqual(renew_ea(self.options),'new-private');self.assertEqual(get.call_count,1)
   self.assertEqual(renew_ea(self.options,force=True),'new-private');self.assertEqual(get.call_count,2)
  data=json.loads((auth_dir(self.options)/'ea-token.json').read_text());self.assertGreater(data['expires_at'],time.time()+14000)
 def test_ea_expired_session_has_actionable_error(self):
  with self.assertRaisesRegex(SessionError,'Connect EA'):renew_ea(self.options)
  self.cookies()
  with patch.object(WebsiteSession,'get',return_value=('{"error":"login_required"}','https://accounts.ea.com')):
   with self.assertRaisesRegex(SessionError,'Connect EA'):renew_ea(self.options)
 def test_forget_session_removes_only_owned_service_files(self):
  self.cookies();self.cookies('steam');atomic_json(auth_dir(self.options)/'ea-token.json',{'access_token':'x'})
  forget_session('ea',self.options);self.assertFalse((auth_dir(self.options)/'ea-token.json').exists());self.assertTrue((auth_dir(self.options)/'steam-cookies.json').exists())
 def test_ea_graphql_401_renews_once(self):
  replies=[FetchError('HTTP 401',status=401),{'data':{'me':{'ownedGameProducts':{'next':None,'items':[{'originOfferId':'a'}]}}}},{'data':{'gameProducts':{'items':[]}}}]
  with patch('web_sessions.renew_ea',side_effect=['old','new']) as renew,patch('connectors.request',side_effect=replies) as request,patch('acquisition.ea_dates',return_value={'matched':0}) as dates:
   rows=ea({**self.options,'ea_session_enabled':True},threading.Event(),lambda _:None)
  self.assertEqual(dates.call_args.args[1],'new');self.assertEqual(len(rows),1);self.assertEqual(renew.call_count,2);self.assertTrue(renew.call_args.kwargs['force']);self.assertEqual(request.call_args.kwargs['headers']['Authorization'],'Bearer new')
 def test_ea_repeated_401_does_not_loop_or_erase_cache(self):
  with patch('web_sessions.renew_ea',return_value='token') as renew,patch('connectors.request',side_effect=FetchError('HTTP 401',status=401)) as request:
   with self.assertRaises(FetchError):ea({**self.options,'ea_session_enabled':True},threading.Event(),lambda _:None)
  self.assertEqual(renew.call_count,2);self.assertEqual(request.call_count,2)
 def test_steam_account_identity_checked(self):
  self.cookies('steam');self.assertEqual(WebsiteSession('steam',self.options).steam_id(),'76561198018049642')
  with self.assertRaisesRegex(SessionError,'another account'):fetch_license_page(self.options,'76561198000000000')

class SteamDateTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'licenses.html';self.path.write_text(HTML);self.options={'auth_dir':str(Path(self.temp.name)/'auth'),'steam_licenses_html':str(self.path),'steam_id':'76561198018049642'}
 def tearDown(self):self.temp.cleanup()
 def rows(self):return [game('Steam',i,title,{}) for i,title in [('1','Game & More'),('2','Other Game'),('3','Explicit Game'),('4','Duplicate Name'),('5','Duplicate Name'),('6','Bundled Game')]]
 def test_parser_formats_ignores_remove_label_and_reads_package(self):
  licenses=parse_licenses(HTML);self.assertEqual(len(licenses),4);self.assertEqual(licenses[0]['date'],'2020-10-02');self.assertEqual(licenses[1]['title'],'Other Game');self.assertEqual(licenses[1]['packages'],['44']);self.assertEqual(licenses[2]['apps'],['3'])
  self.assertEqual(license_date('3 October 2020'),'2020-10-03');self.assertIsNone(license_date('nonsense'))
 def test_exact_names_package_mapping_and_ambiguity(self):
  rows=self.rows();request=Mock(return_value={'44':{'success':True,'data':{'apps':[{'id':2},{'id':6}]}}})
  report=steam_dates(rows,self.options,threading.Event(),lambda _:None,request)
  self.assertEqual(report['matched'],4);self.assertEqual(report['ambiguous_title_rows_skipped'],1);self.assertIsNone(rows[3]['date_added']);self.assertEqual(rows[5]['date_added'],'2020-10-03');self.assertEqual(request.call_count,1)
  steam_dates(self.rows(),self.options,threading.Event(),lambda _:None,request);self.assertEqual(request.call_count,1)
 def test_login_page_or_wrong_account_import_rejected(self):
  self.path.write_text('<html>Sign in</html>')
  with self.assertRaises(SessionError):fetch_license_page(self.options,self.options['steam_id'])
  self.path.write_text(HTML.replace('76561198018049642','76561198000000000'))
  with self.assertRaisesRegex(SessionError,'different account'):fetch_license_page(self.options,self.options['steam_id'])
 def test_missing_connection_is_optional(self):
  report=steam_dates(self.rows(),{},threading.Event(),lambda _:None,Mock());self.assertEqual(report['matched'],0);self.assertIn('Connect Steam dates',report['warnings'][0])
 def test_failed_package_mapping_retains_exact_dates_and_cancels(self):
  rows=self.rows();report=steam_dates(rows,self.options,threading.Event(),lambda _:None,Mock(side_effect=FetchError('HTTP 404',status=404)))
  self.assertTrue(rows[0]['date_added']);self.assertTrue(report['warnings']);self.assertIsNone(rows[-1]['date_added'])
  cancel=threading.Event();cancel.set()
  with self.assertRaises(Cancelled):steam_dates(rows,self.options,cancel,lambda _:None,Mock())
 def test_manual_date_remains_authoritative(self):
  db=Database(Path(self.temp.name)/'db');db.save([game('Steam','1','Game & More',{},date_added='2019-01-01',date_added_source='Manual')]);rows=self.rows()
  steam_dates(rows,self.options,threading.Event(),lambda _:None,Mock(return_value={'44':{'success':False}}));db.save(rows)
  self.assertEqual(next(r for r in db.rows() if r['id']=='1')['date_added'],'2019-01-01')
 def html(self,rows):
  body=''.join('<tr'+(f' data-appid="{app}"' if app else '')+f'><td class="license_date_col">{date}</td><td><a href="/sub/{package}">Item {package}</a></td></tr>' for package,date,app in rows)
  return '<html><script>g_steamID = "76561198018049642";</script><table>'+body+'</table></html>'
 def run_dates(self,html,rows,request):
  path=Path(self.temp.name)/'licenses.html';path.write_text(html)
  return steam_dates(rows,self.options,threading.Event(),lambda _:None,request)
 def test_solo_packages_are_requested_before_attached_ones(self):
  # A license without explicit app IDs can only be dated via its package mapping,
  # so its request must come first while the request budget lasts.
  html=self.html([('300','Jan 1, 2021','5'),('100','Feb 2, 2020',None)])
  seen=[]
  def request(url,params=None,**kw):
   seen.append(params['packageids'])
   return {params['packageids']:{'success':True,'data':{'apps':[{'id':5 if params['packageids']=='300' else 7}]}}}
  rows=[game('Steam','5','Game Five',{})];report=self.run_dates(html,rows,request)
  self.assertEqual(seen,['100','300']);self.assertEqual(rows[0]['date_added'],'2021-01-01')
  self.assertEqual(report['postponed_packages'],0);self.assertFalse(report['date_fetch_incomplete'])
 def test_rate_limit_reports_postponed_lookups(self):
  html=self.html([('100','Feb 2, 2020',None),('200','Mar 3, 2019',None)])
  requested=[]
  def request(url,params=None,**kw):
   requested.append(params['packageids'])
   if params['packageids']=='100':return {'100':{'success':True,'data':{'apps':[{'id':7}]}}}
   raise FetchError('HTTP 429',status=429)
  rows=[game('Steam','7','Game Seven',{})];report=self.run_dates(html,rows,request)
  self.assertEqual(requested,['100','200'])
  self.assertTrue(rows[0]['date_added'])
  self.assertTrue(report['date_fetch_incomplete']);self.assertEqual(report['postponed_packages'],1)
  self.assertTrue(any('rate limited' in warning for warning in report['warnings']))
 def test_cached_mapping_applies_even_when_later_fetch_is_limited(self):
  first=self.html([('100','Feb 2, 2020',None)])
  self.run_dates(first,[game('Steam','7','Game Seven',{})],Mock(return_value={'100':{'success':True,'data':{'apps':[{'id':7}]}}}))
  second=self.html([('100','Feb 2, 2020',None),('200','Mar 3, 2019',None)])
  rows=[game('Steam','7','Game Seven',{})]
  def request(url,params=None,**kw):raise FetchError('HTTP 429',status=429)
  report=self.run_dates(second,rows,request)
  # The cached package 100 mapping was applied before any request, so the game
  # keeps its date even though every package request was rate limited.
  self.assertEqual(rows[0]['date_added'],'2020-02-02');self.assertEqual(report['postponed_packages'],1);self.assertTrue(report['date_fetch_incomplete'])

class MoreSessionTests(unittest.TestCase):
 def test_cookie_rotation_is_saved_after_request(self):
  with tempfile.TemporaryDirectory() as tmp:
   options={'auth_dir':tmp};atomic_json(auth_dir(options)/'ea-cookies.json',{'cookies':[{'name':'sid','value':'old','domain':'.ea.com','path':'/','secure':True,'expires':None}]})
   session=WebsiteSession('ea',options)
   def opened(request,timeout):
    next(iter(session.jar)).value='rotated'
    response=Mock();response.read.return_value=b'{}';response.geturl.return_value='https://accounts.ea.com/connect/auth'
    context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False);return context
   session.opener.open=opened;session.get('https://accounts.ea.com/connect/auth')
   self.assertEqual(WebsiteSession('ea',options).cookies()[0]['value'],'rotated')
 def test_invalid_token_error_does_not_echo_value(self):
  secret='PRIVATE\r\nheader'
  with self.assertRaises(FetchError) as error:ea({'ea_token':secret},threading.Event(),lambda _:None)
  self.assertNotIn('PRIVATE',str(error.exception))
 def test_ea_graphql_authorization_error_renews_once(self):
  replies=[{'errors':[{'extensions':{'code':'UNAUTHENTICATED'}}]},{'data':{'me':{'ownedGameProducts':{'next':None,'items':[]}}}}]
  with patch('web_sessions.renew_ea',return_value='token') as renew,patch('connectors.request',side_effect=replies),patch('acquisition.ea_dates',return_value={'matched':0}):
   self.assertEqual(ea({'ea_session_enabled':True},threading.Event(),lambda _:None),[])
  self.assertEqual(renew.call_count,2)
