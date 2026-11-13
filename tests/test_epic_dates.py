import json,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from connectors import epic_acquisition_dates,Cancelled
from core import game
class EpicDateTests(unittest.TestCase):
 def test_exact_product_not_shared_namespace(self):
  with tempfile.TemporaryDirectory() as tmp:
   cache=[{'namespace':'ns','catalogItemId':'base','grantDate':'2021-03-01T00:00:00Z'}, {'namespace':'ns','catalogItemId':'base','grantDate':'2020-03-01T00:00:00Z'},{'namespace':'ns','catalogItemId':'dlc','grantDate':'2022-03-01T00:00:00Z'},{'namespace':'ns','catalogItemId':'base','grantDate':'2010-03-01T00:00:00Z','active':False}]
   Path(tmp,'entitlements.json').write_text(json.dumps(cache))
   rows=[game('Epic',i,i,{'metadata':{'namespace':'ns','id':i,'creationDate':'2000-01-01'}}) for i in ['base','dlc','unknown']]
   epic_acquisition_dates(rows,{'epic_config':tmp},threading.Event(),lambda _:None)
   self.assertEqual(rows[0]['date_added'],'2020-03-01T00:00:00+00:00');self.assertEqual(rows[1]['date_added'],'2022-03-01T00:00:00+00:00');self.assertIsNone(rows[2]['date_added'])
   self.assertNotIn('accountId',rows[0]['raw']['acquisition_match'])
 def test_bad_cache_does_not_fail_library(self):
  with tempfile.TemporaryDirectory() as tmp:
   rows=[game('Epic','a','Game',{})];notes=[]
   self.assertEqual(epic_acquisition_dates(rows,{'epic_config':tmp},threading.Event(),notes.append),rows)
   self.assertTrue(notes)
   Path(tmp,'entitlements.json').write_text('{broken');epic_acquisition_dates(rows,{'epic_config':tmp},threading.Event(),notes.append)
 def test_cancellation(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'entitlements.json').write_text('[{}]');cancel=threading.Event();cancel.set()
   with self.assertRaises(Cancelled):epic_acquisition_dates([],{'epic_config':tmp},cancel,lambda _:None)
