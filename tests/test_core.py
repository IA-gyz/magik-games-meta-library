import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Database,game,normalize,clean
import connectors as c

class CoreTests(unittest.TestCase):
    def test_reconciliation_and_failure_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'test.db')
            a=game('Steam','1','A',{},playtime=0); b=game('Steam','2','B',{})
            db.save([a,b],'Steam',True); db.save([a],'Steam',True)
            self.assertEqual({r['id']:r['active'] for r in db.rows()},{'1':True,'2':False})
            db.status('Steam','Failed'); self.assertEqual(len(db.rows()),2)
    def test_metadata_survives_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'test.db')
            db.save([game('GOG',1,'Real title',{'product':{'title':'Real title'}},genres='RPG')])
            db.save([game('GOG',1,'GOG product 1',{'owned_product_id':1})],'GOG',True)
            row=db.rows()[0]; self.assertEqual(row['title'],'Real title'); self.assertIn('product',row['raw']); self.assertEqual(row['genres'],'RPG')
    def test_epic_dlc(self):
        rows=normalize('Epic',[{'app_name':'a','app_title':'A','metadata':{},'dlcs':[{'app_name':'b','app_title':'B'}]}])
        self.assertEqual(len(rows),2); self.assertEqual(rows[1]['type'],'DLC')
    def test_amazon(self):
        r=normalize('Amazon',[{'product':{'id':'a','title':'A','productDetail':{'details':{'genres':['RPG']}}}}])[0]
        self.assertEqual(r['genres'],'RPG')
    def test_invalid_import(self):
        with self.assertRaises(ValueError): normalize('EA',[{'title':'missing ID'}])
    def test_redaction(self):
        self.assertEqual(clean({'nested':{'access_token':'private','name':'a'},'refresh_token':'x'}),{'nested':{'name':'a'}})
    def test_steam_private_not_empty_success(self):
        with patch.object(c,'request',return_value={'response':{}}):
            with self.assertRaises(c.FetchError): c.steam({'steam_key':'x','steam_id':'123'},threading.Event(),lambda _:None)
    def test_ea_pagination_and_missing_metadata(self):
        replies=[{'data':{'me':{'ownedGameProducts':{'next':'p2','items':[{'originOfferId':'a'}]}}}},
                 {'data':{'me':{'ownedGameProducts':{'next':None,'items':[{'originOfferId':'b'}]}}}},
                 {'data':{'gameProducts':{'items':[{'originOfferId':'a','baseItem':{'title':'A'}}]}}}]
        with patch.object(c,'request',side_effect=replies+[c.FetchError('HTTP 403')]):
            rows=c.ea({'ea_token':'private'},threading.Event(),lambda _:None)
        self.assertEqual([r['title'] for r in rows],['A','b'])
        self.assertNotIn('private',json.dumps(rows))
    def test_rockstar_latest_log_report_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'launcher.log'; path.write_text('test gta5: on branch public\ntest rdr2: on branch public\ntest gta5: no branches!\n')
            with patch.object(c,'request',return_value={'titles':{'1':{'titleId':'rdr2','friendlyName':'Red Dead Redemption 2'}}}):
                rows=c.rockstar({'rockstar_log':str(path)},threading.Event(),lambda _:None)
            self.assertEqual([r['title'] for r in rows],['Red Dead Redemption 2'])

if __name__=='__main__': unittest.main()
