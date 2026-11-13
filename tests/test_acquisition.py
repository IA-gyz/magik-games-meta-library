import json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from acquisition import epic_dates,ea_dates,gog_dates,optional_dates,DateSourceError
from core import game,Database
from connectors import FetchError,Cancelled
class AcquisitionTests(unittest.TestCase):
 def setUp(self):self.cancel=threading.Event()
 def test_epic_entitlement_name_matches_when_catalog_id_differs(self):
  with tempfile.TemporaryDirectory() as tmp:
   ent=[{'namespace':'n','catalogItemId':'audience','entitlementName':'access','grantDate':'2020-01-01T00:00:00Z'}]
   Path(tmp,'entitlements.json').write_text(json.dumps(ent))
   rows=[game('Epic','app','Game',{'metadata':{'namespace':'n','id':'executable','entitlementName':'access'}}),game('Epic','dlc','DLC',{'metadata':{'namespace':'n','id':'other'}})]
   report=epic_dates(rows,{'epic_config':tmp},self.cancel,lambda _:None,Mock(),network=False)
   self.assertEqual(report['matched_entitlement_name'],1);self.assertEqual(report['matched'],1);self.assertIsNone(rows[1]['date_added'])
   self.assertTrue(report['unmatched_samples'][0]['namespace_has_dated_entitlements'])
 def test_epic_live_pagination_and_no_session_persistence(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'user.json').write_text(json.dumps({'access_token':'SECRET','account_id':'PRIVATE'}))
   record={'namespace':'n','catalogItemId':'id','grantDate':'2021-01-01T00:00:00Z'}
   request=Mock(side_effect=[[record]*1000,[],{'records':[],'responseMetadata':{}}]);rows=[game('Epic','a','A',{'metadata':{'namespace':'n','id':'id'}})]
   report=epic_dates(rows,{'epic_config':tmp},self.cancel,lambda _:None,request)
   self.assertEqual(request.call_count,3);self.assertEqual(request.call_args_list[1].kwargs['params']['start'],1000)
   self.assertEqual(report['records'],1000);self.assertEqual(report['matched'],1)
   self.assertNotIn('SECRET',json.dumps(rows)+json.dumps(report));self.assertNotIn('PRIVATE',json.dumps(report))
 def test_epic_live_failure_uses_cache(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'user.json').write_text('{"access_token":"secret","account_id":"account"}')
   Path(tmp,'entitlements.json').write_text('[{"namespace":"n","catalogItemId":"id","grantDate":"2020-01-01T00:00:00Z"}]')
   rows=[game('Epic','a','A',{'metadata':{'namespace':'n','id':'id'}})]
   report=epic_dates(rows,{'epic_config':tmp},self.cancel,lambda _:None,Mock(side_effect=FetchError('HTTP 401')))
   self.assertEqual(report['matched'],1);self.assertTrue(report['warnings'])
 def test_ea_offer_id_and_vendor_headers(self):
  request=Mock(side_effect=[{'pid':{'pidId':'123'}},{'entitlements':[{'offerId':'offer','grantDate':'2020-01-01T00:00:00Z'},{'offerId':'offer','grantDate':'2022-01-01T00:00:00Z'}]}])
  rows=[game('EA','offer','Game',{})];report=ea_dates(rows,'secret',self.cancel,lambda _:None,request)
  self.assertEqual(report['matched'],1);self.assertTrue(rows[0]['date_added'].startswith('2020'))
  self.assertNotIn('Authorization',request.call_args.kwargs['headers']);self.assertEqual(request.call_args.kwargs['headers']['authtoken'],'secret')
 def test_gog_pages_refunds_gifts_and_earliest(self):
  request=Mock(side_effect=[{'totalPages':2,'orders':[{'status':'completed','date':1609459200,'products':[{'id':1},{'id':2,'isRefunded':True}]}]}, {'totalPages':2,'orders':[{'status':'completed','date':1577836800,'products':[{'id':1}]},{'status':'pending','date':1577836800,'products':[{'id':3}]},{'status':'completed','date':1577836800,'giftRecipient':'someone','products':[{'id':4}]}]}])
  rows=[game('GOG',str(i),str(i),{}) for i in range(1,5)]
  report=gog_dates(rows,{},self.cancel,lambda _:None,request)
  self.assertEqual(report['matched'],1);self.assertTrue(rows[0]['date_added'].startswith('2020'))
  self.assertTrue(all(not r['date_added'] for r in rows[1:]));self.assertEqual(request.call_count,2)
 def test_date_failure_keeps_library_and_cancel_propagates(self):
  rows=[game('EA','a','A',{})]
  rows=optional_dates('EA',rows,lambda _:None,Mock(side_effect=FetchError('HTTP 401')))
  self.assertEqual(rows[0]['title'],'A');self.assertEqual(rows.acquisition_report['warnings'],['HTTP 401'])
  with self.assertRaises(Cancelled):optional_dates('EA',rows,lambda _:None,Mock(side_effect=Cancelled()))
 def test_gog_repeated_pages_are_not_silently_applied(self):
  response={'totalPages':3,'orders':[{'status':'completed','date':1609459200,'products':[{'id':1}]}]}
  rows=[game('GOG','1','A',{})]
  with self.assertRaises(DateSourceError):gog_dates(rows,{},self.cancel,lambda _:None,Mock(return_value=response))
  self.assertIsNone(rows[0]['date_added'])
 def test_manual_date_and_report_persistence(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Database(Path(tmp)/'db');db.save([game('EA','offer','Game',{},date_added='2019-01-01',date_added_source='Manual')])
   rows=[game('EA','offer','Game',{},date_added='2020-01-01',date_added_source='EA entitlement grantDate')];db.save(rows)
   db.save_acquisition_report('EA',{'matched':1,'warnings':[]})
   self.assertEqual(Database(Path(tmp)/'db').acquisition_reports()[0]['matched'],1);self.assertEqual(db.rows()[0]['date_added'],'2019-01-01')

class ReportRegressionTests(unittest.TestCase):
 def test_gog_purchase_status_from_user_report(self):
  rows=[game('GOG','123','Game',{}),game('GOG','gift','Other',{})]
  request=Mock(return_value={'totalPages':1,'orders':[{'status':'purchase','date':1609459200,'products':[{'id':'123'}]},{'status':'gift_by_me','date':1609459200,'products':[{'id':'gift'}]}]})
  report=gog_dates(rows,{},threading.Event(),lambda _:None,request)
  self.assertEqual(report['matched'],1);self.assertEqual(report['order_status_counts'],{'purchase':1,'gift_by_me':1});self.assertIsNone(rows[1]['date_added'])
 def test_epic_library_dates_handle_different_entitlement_products(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'user.json').write_text('{"access_token":"secret","account_id":"private"}')
   request=Mock(side_effect=[ [{'namespace':'shared','catalogItemId':'audience','grantDate':'2020-01-01T00:00:00Z'}],
    {'records':[{'namespace':'shared','appName':'app','catalogItemId':'game','acquisitionDate':'2021-02-03T04:05:06Z'}],'responseMetadata':{'nextCursor':'next'}},
    {'records':[{'namespace':'shared','appName':'dlc','catalogItemId':'addon','acquisitionDate':'2022-03-04T04:05:06Z'}],'responseMetadata':{}}])
   rows=[game('Epic',i,i,{'metadata':{'namespace':'shared','id':ident}}) for i,ident in [('app','game'),('dlc','addon'),('other','unmatched')]]
   report=epic_dates(rows,{'epic_config':tmp},threading.Event(),lambda _:None,request)
   self.assertEqual(report['matched_library'],2);self.assertEqual(report['matched'],2)
   self.assertEqual(rows[0]['date_added'],'2021-02-03T04:05:06+00:00');self.assertEqual(rows[1]['date_added'],'2022-03-04T04:05:06+00:00');self.assertIsNone(rows[2]['date_added'])
   self.assertEqual(rows[0]['date_added_source'],'Epic library acquisitionDate');self.assertEqual(request.call_args.kwargs['params']['cursor'],'next')
 def test_library_repeated_cursor_does_not_apply_partial_results(self):
  from acquisition import epic_library_records
  request=Mock(return_value={'records':[{'appName':'app'}],'responseMetadata':{'nextCursor':'same'}})
  with self.assertRaises(DateSourceError):epic_library_records('token',threading.Event(),request)
 def test_ea_failure_identifies_endpoint(self):
  with self.assertRaisesRegex(DateSourceError,'identity endpoint: HTTP 404'):
   ea_dates([],'token',threading.Event(),lambda _:None,Mock(side_effect=FetchError('HTTP 404')))
  with self.assertRaisesRegex(DateSourceError,'consolidated-entitlements routes unavailable'):
   ea_dates([],'token',threading.Event(),lambda _:None,Mock(side_effect=[{'pid':{'pidId':'123'}},FetchError('HTTP 404',status=404),FetchError('HTTP 404',status=404)]))

class AcquisitionRouteTests(unittest.TestCase):
 def test_ea_uses_api2_primary(self):
  request=Mock(side_effect=[{'pid':{'pidId':'123'}},{'entitlements':[{'offerId':'owned','grantDate':'2020-01-01T00:00:00Z'}]}])
  rows=[game('EA','owned','Owned',{})];report=ea_dates(rows,'private',threading.Event(),lambda _:None,request)
  self.assertTrue(request.call_args.args[0].startswith('https://api2.origin.com/'));self.assertEqual(report['matched'],1)
  self.assertNotIn('private',json.dumps(report)+json.dumps(rows));self.assertEqual(len(report['route_attempts']),1)
 def test_ea_falls_back_only_for_missing_route(self):
  request=Mock(side_effect=[{'pid':{'pidId':'123'}},FetchError('HTTP 404',status=404),{'entitlements':[]}])
  report=ea_dates([],'token',threading.Event(),lambda _:None,request)
  self.assertEqual(request.call_count,3);self.assertTrue(request.call_args.args[0].startswith('https://api1.origin.com/'))
  self.assertEqual(report['route_attempts'][0]['result'],'HTTP 404')
 def test_ea_does_not_retry_authentication_failure_on_other_host(self):
  request=Mock(side_effect=[{'pid':{'pidId':'123'}},FetchError('HTTP 401',status=401)])
  with self.assertRaisesRegex(DateSourceError,'api2.origin.com: HTTP 401'):ea_dates([],'token',threading.Event(),lambda _:None,request)
  self.assertEqual(request.call_count,2)
 def test_gog_unmatched_diagnostics_without_financial_data(self):
  rows=[game('GOG','paid','Paid',{'account_shelf':{'id':'paid'}}),game('GOG','shelf','Shelf game',{'account_shelf':{'id':'shelf'}}),game('GOG','owned-only','GOG product owned-only',{}),game('GOG','refund','Refund',{})]
  response={'totalPages':1,'orders':[{'status':'purchase','date':1609459200,'publicId':'PRIVATE_ORDER','total':{'amount':123},'products':[{'id':'paid'},{'id':'refund','isRefunded':True},{'id':'outside','title':'Other product'}]}]}
  report=gog_dates(rows,{},threading.Event(),lambda _:None,Mock(return_value=response))
  self.assertEqual(report['matched'],1);self.assertEqual(report['unmatched_on_account_shelf'],1);self.assertEqual(report['unmatched_without_account_shelf'],2)
  self.assertEqual(report['unmatched_seen_in_orders'],1);self.assertEqual(report['unmatched_not_seen_in_orders'],2)
  self.assertEqual(report['order_product_ids_outside_library'],1);self.assertEqual(report['unmatched_samples'][0]['id'],'shelf')
  refund=next(s for s in report['unmatched_samples'] if s['id']=='refund');self.assertIn('refunded product',refund['skip_reasons'])
  self.assertNotIn('PRIVATE_ORDER',json.dumps(report));self.assertNotIn('amount',json.dumps(report))
