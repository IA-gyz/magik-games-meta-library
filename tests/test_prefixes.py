import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from installations import scan,validate,windows_path,decorate,LaunchError
from core import game

class PrefixTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.prefix=self.home/'compat/pfx';(self.prefix/'drive_c').mkdir(parents=True)
  self.options={'scan_prefix_roots':str(self.prefix.parent)}
 def tearDown(self):self.temp.cleanup()
 def epic(self):
  target=self.prefix/'drive_c/Games/My Game';target.mkdir(parents=True)
  file=self.prefix/'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/test.item';file.parent.mkdir(parents=True)
  file.write_text(json.dumps({'AppName':'exact-id','InstallLocation':r'C:\Games\My Game','DisplayName':'Game','bIsIncompleteInstall':False}));return target,file
 def test_epic_exact_match_and_revalidate(self):
  target,file=self.epic();snapshot=scan(self.options,home=self.home);entry=next(e for e in snapshot['entries'] if e['kind']=='prefix')
  self.assertEqual(entry['path'],str(target));self.assertEqual(entry['state'],'Installed');self.assertFalse(entry['launch_ready']);validate(entry)
  rows=decorate([game('Epic','exact-id','Game',{}),game('Epic','other-id','Game',{})],snapshot)
  self.assertEqual(rows[0]['installation_status'],'Installed');self.assertFalse(rows[1]['_installations'])
  data=json.loads(file.read_text());data['bIsIncompleteInstall']=True;file.write_text(json.dumps(data))
  with self.assertRaises(LaunchError):validate(entry)
 def test_missing_prefix_preserves_evidence(self):
  self.epic();first=scan(self.options,home=self.home)
  (self.home/'compat').rename(self.home/'disconnected');second=scan(self.options,first,home=self.home)
  self.assertTrue(any(e['state']=='Unavailable location' for e in second['entries']))
 def test_windows_drives_and_case(self):
  target,_=self.epic();self.assertEqual(windows_path(self.prefix,'c:/games/my game'),target)
  self.assertIsNone(windows_path(self.prefix,'D:/Game'));self.assertIsNone(windows_path(self.prefix,'C:/../escape'))
  other=self.home/'drive';other.mkdir();(self.prefix/'dosdevices').mkdir();(self.prefix/'dosdevices/d:').symlink_to(other)
  self.assertEqual(windows_path(self.prefix,'D:/Game'),other/'Game')
 def test_ea_ids_and_manual_association(self):
  file=self.prefix/'drive_c/Program Files/EA Games/Test/__Installer/installerdata.xml';file.parent.mkdir(parents=True)
  file.write_text('<DiPManifest><contentIDs><contentID>content-1</contentID><contentID>content-2</contentID></contentIDs></DiPManifest>')
  snapshot=scan(self.options,home=self.home);entries=[e for e in snapshot['entries'] if e.get('store')=='EA'];self.assertEqual(len(entries),2);validate(entries[0])
  row=game('EA','offer-id','Test',{});decorate([row],snapshot,{'EA|offer-id':entries[0]['key']});self.assertEqual(row['installation_status'],'Installed')
  file.write_text('<broken>')
  with self.assertRaises(LaunchError):validate(entries[0])

try:
 from launch_ui import override_command
 HAS_QT=True
except ImportError:HAS_QT=False
@unittest.skipUnless(HAS_QT,'PySide6 missing')
class OverrideTests(unittest.TestCase):
 def test_literal_arguments(self):
  executable,args,cwd,env=override_command({'program':sys.executable,'args':['a b','$(touch nope)',';'],'env':{'WINEPREFIX':'/some prefix'}})
  self.assertEqual(args,['a b','$(touch nope)',';']);self.assertEqual(env['WINEPREFIX'],'/some prefix')
 def test_invalid_configuration(self):
  for extra in [{'args':'shell command'},{'env':{'BAD=NAME':'x'}},{'env':{'X':1}},{'cwd':'/not/a/real/magik-folder'}]:
   with self.assertRaises(LaunchError):override_command({'program':sys.executable,**extra})

class ScanRecoveryTests(unittest.TestCase):
 def test_changed_device_does_not_hide_accessible_steam_library(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);root=home/'steam';folder=root/'steamapps/common/Game';folder.mkdir(parents=True)
   (root/'steamapps/appmanifest_123.acf').write_text('"AppState" {"appid" "123" "name" "Game" "installdir" "Game" "StateFlags" "4"}')
   options={'scan_steam_roots':str(root)};first=scan(options,home=home/'empty')
   for scope in first['scopes'].values():scope['device']=-123
   for e in first['entries']:e['device']=-123;e['state']='Unavailable location'
   second=scan(options,first,home=home/'empty')
   entry=next(e for e in second['entries'] if e['id']=='123')
   self.assertEqual(entry['state'],'Installed');validate(entry)
   folder.rmdir();third=scan(options,second,home=home/'empty')
   self.assertEqual(next(e for e in third['entries'] if e['id']=='123')['state'],'Not detected')
 def test_missing_library_warns_and_retains_evidence(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'steam';folder=root/'steamapps/common/Game';folder.mkdir(parents=True)
   (root/'steamapps/appmanifest_123.acf').write_text('"AppState" {"appid" "123" "installdir" "Game" "StateFlags" "4"}')
   options={'scan_steam_roots':str(root)};first=scan(options,home=Path(tmp)/'empty')
   (root/'steamapps').rename(root/'offline');second=scan(options,first,home=Path(tmp)/'empty')
   self.assertEqual(next(e for e in second['entries'] if e['id']=='123')['state'],'Unavailable location')
   self.assertTrue(any(str(root/'steamapps') in note for note in second['notes']))
 def test_summary_does_not_claim_launch_ready(self):
  from installations import scan_summary
  text=scan_summary({'entries':[{'state':'Installed','launch_ready':False},{'state':'Unavailable location'}],'notes':['missing library']})
  self.assertIn('1 installed',text);self.assertIn('1 unavailable',text);self.assertIn('Scan warnings: 1',text);self.assertNotIn(' ready.',text)
