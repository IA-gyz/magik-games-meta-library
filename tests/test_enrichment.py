import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Database, game
from connectors import FetchError, MetadataUnavailable, Cancelled
import connectors
import enrichment as e

class Cancel:
    def is_set(self): return False
    def wait(self,seconds): return False

class EnrichmentTests(unittest.TestCase):
    def test_retry_transient(self):
        row=game('Steam',1,'One',{})
        fn=Mock(side_effect=[FetchError('HTTP 503',category='temporary'),row])
        with patch.dict(e.FETCHERS,Steam=fn):
            self.assertEqual(e.fetch_with_retry(row,Cancel(),lambda _:None),row)
        self.assertEqual(fn.call_count,2)
    def test_unavailable_not_retried(self):
        fn=Mock(side_effect=MetadataUnavailable('No public store page'))
        with patch.dict(e.FETCHERS,Steam=fn):
            with self.assertRaises(MetadataUnavailable): e.fetch_with_retry(game('Steam',1,'One',{}),Cancel(),lambda _:None)
        self.assertEqual(fn.call_count,1)
    def test_rate_limit_defers_provider_but_keeps_other_store(self):
        rows=[game('Steam',1,'One',{}),game('Steam',2,'Two',{}),game('GOG',3,'Three',{})]
        steam=Mock(side_effect=FetchError('HTTP 429',category='rate_limit',status=429,retry_after=120))
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');db.save(rows)
            with patch.dict(e.FETCHERS,Steam=steam,GOG=lambda r:r):
                messages=e.run_enrichment(db,rows,Cancel(),lambda _:None,lambda:None)
            results={r['id']:r for r in db.metadata_results()}
            self.assertEqual(results['1']['outcome'],'failed')
            self.assertEqual(results['2']['outcome'],'deferred')
            self.assertEqual(results['3']['outcome'],'enriched')
            self.assertEqual(len(db.rows()),3)
            self.assertTrue(any('waiting' in x for x in messages))
        self.assertEqual(steam.call_count,1)
    def test_gog_partial_saved_and_rate_limit_deferred(self):
        rows=[game('GOG',1,'One',{}),game('GOG',2,'Two',{})]
        partial={**rows[0],'raw':{'product':{'title':'One'}},'_metadata_warning':{'message':'HTTP 429','status':429,'category':'rate_limit'}}
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');db.save(rows)
            with patch.dict(e.FETCHERS,GOG=lambda r:partial): e.run_enrichment(db,rows,Cancel(),lambda _:None,lambda:None)
            self.assertEqual([r['outcome'] for r in db.metadata_results()],['partial','deferred'])
            self.assertIn('product',next(r for r in db.rows() if r['id']=='1')['raw'])
    def test_unknown_exception_redacts_message(self):
        self.assertEqual(e.safe_error(ValueError('secret token in request URL')),'ValueError while parsing metadata')
    def test_http_status_categorized(self):
        import urllib.error
        from email.message import Message
        headers=Message();headers['Retry-After']='90'
        exc=urllib.error.HTTPError('https://host/?key=private',429,'limited',headers,None)
        with patch('connector_io.urllib.request.urlopen',side_effect=exc):
            with self.assertRaises(FetchError) as caught: connectors.request('https://host/?key=private')
        self.assertEqual(caught.exception.category,'rate_limit');self.assertEqual(caught.exception.retry_after,90)
        self.assertNotIn('private',str(caught.exception))
