import json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from steam_dates import fetch_license_page,next_license_page,steam_dates
from web_sessions import SessionError,STEAM_LICENSES,WebsiteSession
from core import game
from connectors import FetchError,Cancelled
SID='76561198018049642'
def page(ident,title='Game'):
 return f'<tr><td class="license_date_col">2 Oct, 2020</td><td><a href="/app/{ident}/">{title}</a></td></tr>'
def link(offset,token='1700000000:123456789'):
 return f'<a href="/account/licenses/?continuationToken={token}&amp;offset={offset}">Next</a>'
class SteamPaginationTests(unittest.TestCase):
 def session(self,responses):
  session=Mock();session.steam_id.return_value=SID;session.get.side_effect=responses;return session
 def test_captured_get_route_token_offset_and_all_pages(self):
  url=next_license_page(link(100),STEAM_LICENSES);url2=next_license_page(link(200,'next'),url)
  session=self.session([(page('1')+link(100),STEAM_LICENSES),(page('2')+link(200,'next'),url),(page('3'),url2)]);details={}
  with patch('steam_dates.WebsiteSession',return_value=session):rows,_=fetch_license_page({},SID,threading.Event(),Mock(),details)
  self.assertEqual([r['apps'] for r in rows],[['1'],['2'],['3']]);self.assertEqual(details['license_pages'],3);self.assertTrue(details['license_history_complete'])
  self.assertEqual(session.get.call_args_list[1].args,(url,));self.assertNotIn('continuationToken',json.dumps(details))
  self.assertEqual(parse_qs(urlsplit(url).query)['offset'],['100'])
 def test_links_are_scoped_and_next_offset_advances(self):
  current='https://store.steampowered.com/account/licenses/?offset=100'
  text=link(100)+link(200)+'<a href="https://evil.test/account/licenses/?continuationToken=x&offset=101">Next</a>'+link(50)
  self.assertEqual(parse_qs(urlsplit(next_license_page(text,current)).query)['offset'],['200'])
  self.assertIsNone(next_license_page(link(100),current))
 def test_repeated_page_rejected_without_mutating_games(self):
  url=next_license_page(link(100),STEAM_LICENSES);session=self.session([(page('1')+link(100),STEAM_LICENSES),(page('1')+link(200),url)])
  rows=[game('Steam','1','Game',{})]
  with tempfile.TemporaryDirectory() as tmp,patch('steam_dates.WebsiteSession',return_value=session),self.assertRaises(SessionError):
   steam_dates(rows,{'steam_dates_enabled':True,'steam_id':SID,'auth_dir':tmp},threading.Event(),Mock(),Mock())
  self.assertIsNone(rows[0]['date_added'])
 def test_failed_or_redirected_page_rejected(self):
  for response,url in [('Sign in','https://store.steampowered.com/login/'),('invalid',STEAM_LICENSES),(page('2')+'<script>g_steamID="76561198000000000";</script>',STEAM_LICENSES)]:
   session=self.session([(page('1')+link(100),STEAM_LICENSES),(response,url)])
   with patch('steam_dates.WebsiteSession',return_value=session),self.assertRaises(SessionError):fetch_license_page({},SID)
 def test_http_failure_and_cancel_propagate(self):
  session=self.session([(page('1')+link(100),STEAM_LICENSES),FetchError('HTTP 429',status=429)])
  with patch('steam_dates.WebsiteSession',return_value=session),self.assertRaises(FetchError):fetch_license_page({},SID)
  cancel=threading.Event();cancel.set();session=self.session([(page('1'),STEAM_LICENSES)])
  with patch('steam_dates.WebsiteSession',return_value=session),self.assertRaises(Cancelled):fetch_license_page({},SID,cancel)
 def test_import_stays_offline_and_reports_partial(self):
  with tempfile.TemporaryDirectory() as tmp:
   file=Path(tmp)/'licenses.html';file.write_text(page('1')+link(100));details={}
   with patch('steam_dates.WebsiteSession') as session:rows,_=fetch_license_page({'steam_licenses_html':str(file)},SID,diagnostics=details)
   session.assert_not_called();self.assertEqual(len(rows),1);self.assertFalse(details['license_history_complete'])
 def test_full_page_without_link_is_not_claimed_complete(self):
  session=self.session([(''.join(page(str(n)) for n in range(100)),STEAM_LICENSES)]);details={}
  with patch('steam_dates.WebsiteSession',return_value=session):rows,_=fetch_license_page({},SID,diagnostics=details)
  self.assertEqual(len(rows),100);self.assertFalse(details['license_history_complete']);self.assertTrue(details['license_warnings']);session.get.assert_called_once()
 def test_package_failure_report_is_specific(self):
  raw=page('1')+'<tr><td class="license_date_col">2 Oct, 2020</td><td><a href="/sub/44/">Bundle</a></td></tr>'
  with tempfile.TemporaryDirectory() as tmp:
   file=Path(tmp)/'licenses.html';file.write_text(raw)
   report=steam_dates([game('Steam','1','Game',{})],{'auth_dir':tmp,'steam_licenses_html':str(file)},threading.Event(),Mock(),Mock(return_value={'44':{'success':False}}))
  self.assertEqual(report['package_mapping_failures'],{'No public app mapping returned':1});self.assertEqual(report['matched'],1)
