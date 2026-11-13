import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from installations import scan,discover_prefixes
from core import game,Database,acquisition_date,normalize
class AddedTests(unittest.TestCase):
 def test_no_release_or_refresh_date_as_acquisition(self):
  for store in ['Steam','GOG','Epic','Amazon','EA']:
   row=game(store,'1','Game',{'releaseDate':'2020-01-01','created':'2021-01-01'},release='2020-01-01')
   self.assertIsNone(row['date_added'])
 def test_account_dates(self):
  row=game('GOG','1','Game',{'account_shelf':{'datePurchased':1609459200}})
  self.assertEqual(row['date_added'],'2021-01-01T00:00:00+00:00')
  self.assertEqual(game('Epic','1','Game',{'metadata':{'grantDate':'2020-01-01'}})['date_added'],None)
  self.assertEqual(game('EA','1','Game',{'entitlements':[{'grantDate':'2021-04-03T12:00:00Z'}]})['date_added'],'2021-04-03T12:00:00+00:00')
 def test_date_validation(self):
  for value in ['bad','2020-99-01','2021-01-01T00:00:00',True,0,'2999-01-01']:
   self.assertIsNone(acquisition_date(value))
  self.assertEqual(acquisition_date('2021-01-02'),'2021-01-02')
 def test_manual_date_survives_refresh_export_import(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Database(Path(tmp)/'db');db.save([game('GOG','1','Game',{},date_added='2020-02-03',date_added_source='Manual')])
   db.save([game('GOG','1','Game',{'account_shelf':{'datePurchased':'2021-01-01'}})])
   row=db.rows()[0];self.assertEqual(row['date_added'],'2020-02-03')
   self.assertEqual(normalize('GOG',[row])[0]['date_added'],'2020-02-03')
 def test_old_raw_dates_backfilled(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Database(Path(tmp)/'db');row=game('GOG','1','Game',{'account_shelf':{'datePurchased':'2021-01-02'}});row.pop('date_added');row.pop('date_added_source')
   with db.connect() as connection:connection.execute('INSERT INTO games VALUES (?,?,?)',('GOG','1',json.dumps(row)))
   self.assertEqual(db.rows()[0]['date_added'],'2021-01-02')
class DiscoveryTests(unittest.TestCase):
 def test_automatic_steam_library_prefix_and_symlink_dedup(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);root=home/'steam';prefix=root/'steamapps/compatdata/999/pfx';target=prefix/'drive_c/Games/Game';target.mkdir(parents=True)
   manifest=prefix/'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/one.item';manifest.parent.mkdir(parents=True);manifest.write_text(json.dumps({'AppName':'abc','InstallLocation':'C:/Games/Game'}))
   (home/'Games').mkdir();(home/'Games/Epic').symlink_to(prefix.parent)
   snapshot=scan({'scan_steam_roots':str(root)},home=home)
   self.assertEqual(len([e for e in snapshot['entries'] if e['kind']=='prefix']),1)
   self.assertEqual(snapshot['prefixes'],[str(prefix.resolve())])
 def test_lutris_prefix_ancestor_discovery(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);prefix=home/'custom/prefix';(prefix/'drive_c/Games/Game').mkdir(parents=True)
   found=discover_prefixes({},[],[{'kind':'lutris','path':str(prefix/'drive_c/Games/Game')}],home,lambda:None,[])
   self.assertIn(str(prefix),found)
 def test_no_recursive_home_scan(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);(home/'Documents/hidden/prefix/drive_c').mkdir(parents=True)
   self.assertEqual(discover_prefixes({},[],[],home,lambda:None,[]),[])
