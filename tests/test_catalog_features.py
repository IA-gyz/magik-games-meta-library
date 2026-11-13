import sys
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from connectors import gog_shelf,gog,FetchError,Cancelled
from core import Database,game
from browsing import matches,facet_tokens,UNKNOWN
from enrichment import select_candidates,next_retry

class CatalogTests(unittest.TestCase):
    def test_gog_shelf_pagination_and_hidden_movies(self):
        calls=[]
        def fake(url,params,headers=None):
            calls.append(params.copy());page=params['page'];ident=f"{params['mediaType']}{params['hiddenFlag']}{page}"
            return {'products':[{'id':ident,'title':'Recovered '+ident}],'page':page,'totalPages':2 if params['mediaType']==1 and params['hiddenFlag']==0 else 1}
        with patch('connectors.request',side_effect=fake):products,warnings=gog_shelf({},threading.Event(),lambda _:None)
        self.assertEqual(len(products),5);self.assertEqual(warnings,[])
        self.assertTrue(any(c['mediaType']==2 and c['hiddenFlag']==1 for c in calls))
    def test_gog_preserves_owned_ids_if_shelf_unavailable(self):
        with patch('connectors.token_file',return_value={'access_token':'dummy'}),patch('connectors.request',return_value={'owned':[123]}),patch('providers.gog.gog_shelf',return_value=({},['HTTP 403'])):
            rows=gog({'gog_auth':'unused'},threading.Event(),lambda _:None)
        self.assertEqual(rows[0]['id'],'123');self.assertIn('account_shelf_warnings',rows[0]['raw'])
    def test_gog_recovers_name_without_public_product(self):
        shelf={'123':{'id':123,'title':'Recovered Movie','isMovie':True,'image':'//images.example/hash','url':'/movie/example','releaseDate':{'date':'2020-01-01'}}}
        with patch('connectors.token_file',return_value={'access_token':'dummy'}),patch('connectors.request',return_value={'owned':[123]}),patch('providers.gog.gog_shelf',return_value=(shelf,[])):
            rows=gog({},threading.Event(),lambda _:None)
        self.assertEqual(rows[0]['title'],'Recovered Movie');self.assertEqual(rows[0]['type'],'Movie');self.assertEqual(rows[0]['release'],'2020-01-01')
    def test_gog_repeated_page_stops(self):
        def fake(url,params,headers=None):return {'products':[{'id':'123'}],'page':1,'totalPages':2}
        with patch('connectors.request',side_effect=fake):products,warnings=gog_shelf({},threading.Event(),lambda _:None)
        self.assertEqual(len(warnings),4)
    def test_or_within_and_between_facets(self):
        row=game('Steam',1,'A',{},genres='RPG, Adventure',platforms='windows',languages='English, French')
        self.assertTrue(matches(row,{'store':['Steam','GOG'],'genres':['Action','RPG'],'platforms':['Windows']}))
        self.assertFalse(matches(row,{'genres':['RPG'],'platforms':['Linux']}))
        self.assertFalse(matches(row,{'genres':['PG']}))
    def test_unknown_and_language_normalization(self):
        self.assertEqual(facet_tokens({'type':'BASE_GAME'},'type'),['Game'])
        self.assertEqual(facet_tokens({'languages':'English<strong>*</strong>, French<br>* full audio'},'languages'),['English','French'])
        self.assertEqual(facet_tokens({'platforms':'osx'},'platforms'),['Mac'])
        self.assertTrue(matches({'title':'x'},{'genres':[UNKNOWN]}))
    def test_playtime_unknown_not_unplayed(self):
        self.assertFalse(matches({'title':'x'},{'played':'Unplayed (known)'}))
        self.assertTrue(matches({'title':'x','playtime':0},{'played':'Unplayed (known)'}))
    def test_retry_dates_migrate_old_results(self):
        now=datetime(2026,10,16,tzinfo=timezone.utc);row=game('Steam',1,'A',{})
        result={'store':'Steam','id':'1','outcome':'unavailable','time':now.isoformat(),'reason':'No store page'}
        self.assertEqual(datetime.fromisoformat(next_retry(result)),now+timedelta(days=7))
        candidates,skipped=select_candidates([row],[result],now=now+timedelta(days=1));self.assertEqual(candidates,[]);self.assertEqual(skipped,1)
        self.assertEqual(len(select_candidates([row],[result],force=True,now=now)[0]),1)
        self.assertEqual(len(select_candidates([row],[result],now=now+timedelta(days=8))[0]),1)
    def test_retry_scope_and_completed_cache(self):
        rows=[game('Steam',1,'A',{'store_details':{'name':'A'}}),game('GOG',2,'B',{}),game('Epic',3,'C',{})]
        ready,_=select_candidates(rows,[],enabled=['Steam','GOG']);self.assertEqual([r['id'] for r in ready],['2'])
    def test_result_retry_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');r=game('Steam',1,'A',{})
            db.metadata_result(r,'failed','HTTP 503','2026-10-17T00:00:00+00:00')
            self.assertEqual(db.metadata_results()[0]['retry_after'],'2026-10-17T00:00:00+00:00')

if __name__=='__main__':unittest.main()
