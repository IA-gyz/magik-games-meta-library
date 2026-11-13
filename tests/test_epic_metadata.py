import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Database,game,normalize
from connectors import FetchError,MetadataUnavailable,Cancelled
from epic_metadata import epic_details, load_heroic_cache, product_page
from enrichment import needs_enrichment

NS='namespace-exact'
def row(**metadata):
    return game('Epic','app','Game',{'metadata':{'namespace':NS,**metadata}},type='Game',developers='Original')
def product():
    return {'namespace':NS,'pages':[{'type':'productHome','data':{
        'meta':{'developer':['New Developer'],'publisher':['Publisher'],'tags':['RPG'],'releaseDate':'2020-01-01','platform':['Windows']},
        'about':{'description':'Long description','image':{'src':'https://example.com/cover.jpg'}},
        'requirements':{'languages':['English','French'],'systems':[{'systemType':'Windows','details':[{'title':'RAM','minimum':'8 GB'}]}]}
    }}]}

class EpicTests(unittest.TestCase):
    def test_content_fields(self):
        with patch('epic_metadata.request',return_value=product()):d=epic_details(row(productSlug='valid-slug'))
        self.assertEqual(d['publishers'],'Publisher');self.assertEqual(d['genres'],'RPG');self.assertEqual(d['languages'],'English, French')
        self.assertIn('systems',d['raw']['epic_product_content']['pages'][0]['data']['requirements'])
        self.assertFalse(needs_enrichment(d))
    def test_mapping_namespace_not_title_guess(self):
        mapping={'data':{'Catalog':{'catalogNs':{'mappings':[{'pageType':'productHome','pageSlug':'real-slug'}]}}}}
        with patch('epic_metadata.request',side_effect=[mapping,product()]) as req:
            d=epic_details(row())
        self.assertEqual(req.call_args_list[0].kwargs['body']['variables'],{'ns':NS})
        self.assertTrue(d['url'].endswith('real-slug'))
    def test_graphql_fallback_on_404(self):
        gql={'data':{'Product':{'sandbox':{'configuration':[{'configs':{'shortDescription':'Fallback','technicalRequirements':{'windows':[{'title':'RAM','minimum':'4 GB'}]}}}]}}}}
        with patch('epic_metadata.request',side_effect=[FetchError('HTTP 404',category='unavailable',status=404),gql]):
            d=epic_details(row(productSlug='slug'))
        self.assertEqual(d['description'],'Fallback');self.assertEqual(d['raw']['epic_enrichment']['method'],'GraphQL fallback')
        self.assertIsNone(d['score'])
    def test_wrong_namespace_not_merged(self):
        data=product();data['namespace']='another-game';self.assertIsNone(product_page(data,NS))
    def test_cache_retained_on_rate_limit(self):
        cache={NS:{'data':{'about':{'shortDescription':'Cached'},'releaseDate':'2021-01-01'},'cache_file':'test-cache'}}
        with patch('epic_metadata.request',side_effect=FetchError('HTTP 429',category='rate_limit',status=429)):
            d=epic_details(row(productSlug='slug'),cache)
        self.assertEqual(d['description'],'Cached');self.assertIn('_metadata_warning',d);self.assertTrue(needs_enrichment(d))
    def test_cache_reader_layout_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'store_cache').mkdir();p=root/'store_cache/legendary_gameinfo.json'
            p.write_text(json.dumps({NS:{'about':{'description':'Cached'}},'__timestamp':{NS:'a date'}}))
            cache,warnings=load_heroic_cache({'epic_heroic_root':tmp});self.assertEqual(list(cache),[NS]);self.assertEqual(warnings,[])
            p.write_text('{broken');cache,warnings=load_heroic_cache({'epic_heroic_root':tmp});self.assertEqual(cache,{});self.assertEqual(len(warnings),1)
    def test_dlc_not_given_parent_data(self):
        r=row(mainGameItem={'id':'parent'})
        with patch('epic_metadata.request') as req:
            with self.assertRaises(MetadataUnavailable):epic_details(r)
            req.assert_not_called()
    def test_refresh_preserves_epic_enrichment(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db')
            with patch('epic_metadata.request',return_value=product()):enriched=epic_details(row(productSlug='slug'))
            db.save([enriched]);fresh=normalize('Epic',[{'app_name':'app','app_title':'Game','metadata':{'namespace':NS,'developer':'Old Name'}}])[0]
            db.save([fresh],'Epic',True);saved=db.rows()[0]
            self.assertEqual(saved['developers'],'New Developer');self.assertEqual(saved['genres'],'RPG');self.assertFalse(needs_enrichment(saved))
    def test_cancel_checked_before_api(self):
        import threading
        event=threading.Event();event.set()
        with patch('epic_metadata.request') as req:
            with self.assertRaises(Cancelled):epic_details(row(),cancel=event)
            req.assert_not_called()
    def test_missing_namespace_no_guess(self):
        with self.assertRaises(MetadataUnavailable):epic_details(game('Epic','app','Title',{}))
    def test_release_info_normalization(self):
        r=normalize('Epic',[{'app_name':'app','app_title':'Title','metadata':{'releaseInfo':[{'date':'2020-01-01','platform':['Windows','Mac']}]}}])[0]
        self.assertEqual(r['release'],'2020-01-01');self.assertEqual(r['platforms'],'Windows, Mac')

if __name__=='__main__':unittest.main()
