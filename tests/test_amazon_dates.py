import json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import normalize,Database
from connectors import amazon

class AmazonDateTests(unittest.TestCase):
 def record(self,**fields):
  return {'id':'entitlement','product':{'id':'product','title':'Game'},**fields}
 def test_documented_entitlement_milliseconds(self):
  row=normalize('Amazon',[self.record(entitlementDateFromEpoch='1640280132019')])[0]
  self.assertEqual(row['date_added'],'2021-12-23T17:22:12+00:00')
  self.assertEqual(row['date_added_source'],'Amazon entitlementDateFromEpoch')
 def test_other_dates_are_not_acquisition(self):
  for value in [None,True,'invalid','0','9999999999999999']:
   raw=self.record(entitlementDateFromEpoch=value,lastModifiedDate=1640280132,releaseDate='2020-01-01',syncpoint=1640280132)
   raw['product']['acquisitionDate']='2020-01-01'
   self.assertIsNone(normalize('Amazon',[raw])[0]['date_added'])
 def test_cached_backfill_and_manual_override(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Database(Path(tmp)/'db');row=normalize('Amazon',[self.record(entitlementDateFromEpoch='1640280132019')])[0]
   row.update(date_added=None,date_added_source=None);db.save([row])
   self.assertEqual(db.rows()[0]['date_added'],'2021-12-23T17:22:12+00:00')
   row.update(date_added='2020-01-01',date_added_source='Manual');db.save([row])
   db.save(normalize('Amazon',[self.record(entitlementDateFromEpoch='1640280132019')]))
   self.assertEqual(db.rows()[0]['date_added'],'2020-01-01')
 def test_sync_report_counts(self):
  records=[self.record(entitlementDateFromEpoch='1640280132019'),self.record(entitlementDateFromEpoch='bad'),self.record()]
  with patch('connectors.helper',side_effect=['',json.dumps(records)]) as helper:
   rows=amazon({},threading.Event(),lambda _:None)
  self.assertEqual(helper.call_args_list[0].args[1],['library','sync'])
  report=rows.acquisition_report
  self.assertEqual((report['matched'],report['unmatched_games'],report['invalid_acquisition_fields']),(1,2,1))
