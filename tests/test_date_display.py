import os,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from date_display import friendly_date,date_sort_key,friendly_report
class DateDisplayTests(unittest.TestCase):
 def setUp(self):self.previous=os.environ.get('TZ');os.environ['TZ']='Europe/Paris';time.tzset()
 def tearDown(self):
  if self.previous is None:os.environ.pop('TZ',None)
  else:os.environ['TZ']=self.previous
  time.tzset()
 def test_system_timezone_and_day_precision(self):
  self.assertEqual(friendly_date('2026-10-16T22:21:25+00:00'),'17 Oct 2026, 00:21:25')
  self.assertEqual(friendly_date('2026-10-16'),'16 Oct 2026')
  self.assertEqual(friendly_date('2026-01-16T22:21:25Z'),'16 Jan 2026, 23:21:25')
 def test_epoch_milliseconds_and_partial_release_dates(self):
  self.assertEqual(friendly_date(1609459200),'1 Jan 2021, 01:00:00')
  self.assertEqual(friendly_date(1609459200000),'1 Jan 2021, 01:00:00')
  self.assertEqual(friendly_date('Oct 2020'),'Oct 2020');self.assertEqual(friendly_date('2020'),'2020')
  self.assertEqual(friendly_date('28 Feb, 2020'),'28 Feb 2020')
 def test_unknown_dates_and_immutable_diagnostics(self):
  self.assertEqual(friendly_date(None),'—');self.assertEqual(friendly_date(0),'—');self.assertEqual(friendly_date('Coming soon'),'Coming soon')
  report={'time':'2026-10-16T22:21:25+00:00','records':1609459200,'nested':[{'grantDate':'2020-01-01'}]}
  view=friendly_report(report);self.assertEqual(view['time'],'17 Oct 2026, 00:21:25');self.assertEqual(view['records'],1609459200);self.assertEqual(report['time'],'2026-10-16T22:21:25+00:00')
 def test_sort_order_uses_instant_not_formatted_label(self):
  self.assertLess(date_sort_key('2020-02-28'),date_sort_key('2020-03-01'))
  self.assertEqual(date_sort_key('2021-01-01T01:00:00+01:00'),date_sort_key(1609459200));self.assertIsNone(date_sort_key('Coming soon'))
