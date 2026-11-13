import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from installations import scan,vdf,decorate,command,validate,check_provider,LaunchError,ScanCancelled,lutris_path
from core import game,Database

class InstallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
  self.env=patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.home/'.config'),'XDG_DATA_HOME':str(self.home/'.local/share')});self.env.start()
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def steam(self,appid='123',flags='4'):
  root=self.home/'.local/share/Steam';(root/'steamapps/common/Game').mkdir(parents=True,exist_ok=True)
  manifest=root/f'steamapps/appmanifest_{appid}.acf';manifest.write_text('"AppState" { "appid" "'+appid+'" "name" "A Game" "installdir" "Game" "StateFlags" "'+flags+'" }')
  return root,manifest
 def heroic(self):
  root=self.home/'.config/heroic';folder=self.home/'Games/Heroic Game';folder.mkdir(parents=True)
  for path,data in [('legendaryConfig/legendary/installed.json',{'epic-id':{'title':'Epic title','install_path':str(folder)}}),('gog_store/installed.json',{'installed':[{'appName':'gog-id','install_path':str(folder)}]}),('nile_config/nile/installed.json',[{'id':'amazon-id','path':str(folder)}])]:
   f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(data))
  return root,folder
 def lutris(self):
  root=self.home/'.local/share/lutris';root.mkdir(parents=True);folder=self.home/'Games/EA';folder.mkdir(parents=True)
  with sqlite3.connect(root/'pga.db') as db:
   db.execute('CREATE TABLE games(id INTEGER,installed INTEGER,name TEXT,service TEXT,service_id TEXT,directory TEXT)')
   db.executemany('INSERT INTO games VALUES(?,?,?,?,?,?)',[(7,1,'EA game','ea_app','content-id',str(folder)),(8,1,'Custom game','lutris',None,str(folder)),(9,0,'Uninstalled','gog','unused',str(folder))])
  return root,folder
 def test_vdf_nested_spaces_and_escapes(self):
  d=vdf('"libraryfolders" {"0" {"path" "/Games/My Games" "apps" {"123" "1"}}}')
  self.assertEqual(d['libraryfolders']['0']['path'],'/Games/My Games')
  with self.assertRaises(ValueError):vdf('"AppState" { "appid" "1"')
 def test_steam_full_and_partial(self):
  root,manifest=self.steam();snapshot=scan({},home=self.home);e=snapshot['entries'][0]
  self.assertEqual(e['state'],'Installed');self.assertEqual(e['id'],'123');validate(e)
  manifest.write_text(manifest.read_text().replace('"4"','"1024"'))
  with self.assertRaises(LaunchError):validate(e)
  self.assertEqual(scan({},home=self.home)['entries'][0]['state'],'Incomplete')
 def test_steam_symlinked_game_folder(self):
  root,manifest=self.steam();target=self.home/'Elsewhere/Game';target.mkdir(parents=True)
  link=root/'steamapps/common/Game';link.rmdir();link.symlink_to(target,target_is_directory=True)
  e=scan({},home=self.home)['entries'][0];self.assertEqual(e['state'],'Installed');self.assertEqual(e['path'],str(target));validate(e)
 def test_steam_extra_library_and_unmounted_cache(self):
  root,manifest=self.steam();library=self.home/'external';(library/'steamapps/common/Other').mkdir(parents=True)
  (library/'steamapps/appmanifest_456.acf').write_text('"AppState" {"appid" "456" "installdir" "Other" "StateFlags" "4"}')
  (root/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" {"1" {"path" "'+str(library)+'" "apps" {"456" "1"}}}')
  first=scan({},home=self.home);self.assertEqual(len(first['entries']),2)
  import shutil;shutil.rmtree(library)
  second=scan({},first,home=self.home);old=next(e for e in second['entries'] if e['id']=='456');self.assertEqual(old['state'],'Unavailable location')
 def test_heroic_formats_and_registry_change(self):
  root,folder=self.heroic();snapshot=scan({},home=self.home)
  self.assertEqual({e['store'] for e in snapshot['entries']},{'GOG','Epic','Amazon'})
  for e in snapshot['entries']:validate(e)
  e=next(e for e in snapshot['entries'] if e['store']=='Epic')
  Path(e['record_file']).write_text('{}')
  with self.assertRaises(LaunchError):validate(e)
 def test_gog_incomplete_resume(self):
  root,folder=self.heroic();(folder/'.gogdl-resume').touch()
  snap=scan({},home=self.home);self.assertEqual(next(e['state'] for e in snap['entries'] if e['store']=='GOG'),'Incomplete')
 def test_missing_install_files_not_called_installed(self):
  root,folder=self.heroic();folder.rmdir();snap=scan({},home=self.home)
  self.assertTrue(all(e['state']!='Installed' for e in snap['entries']))
 def test_corrupt_registry_preserves_evidence(self):
  root,folder=self.heroic();first=scan({},home=self.home);(root/'gog_store/installed.json').write_text('{broken')
  second=scan({},first,home=self.home)
  self.assertEqual(next(e['state'] for e in second['entries'] if e['store']=='GOG'),'Unknown')
  self.assertTrue(second['notes'])
 def test_lutris_exact_id_and_manual_link(self):
  root,folder=self.lutris();before=(root/'pga.db').read_bytes();snap=scan({},home=self.home)
  self.assertEqual(before,(root/'pga.db').read_bytes());self.assertEqual(len(snap['entries']),2)
  row=game('EA','offer-id','Different display name',{'product':{'id':'content-id'}})
  self.assertEqual(decorate([row],snap)[0]['installation_status'],'Installed')
  other=game('Epic','different-id','Custom game',{})
  self.assertEqual(decorate([other],snap)[0]['installation_status'],'Not detected')
  entry=next(e for e in snap['entries'] if e['record_id']=='8')
  self.assertEqual(decorate([other],snap,{'Epic|different-id':entry['key']})[0]['installation_status'],'Installed')
 def test_no_provider_is_unknown(self):
  row=game('Steam',1,'A',{});self.assertEqual(decorate([row],scan({},home=self.home))[0]['installation_status'],'Unknown')
 def test_launch_commands_and_uri_escaping(self):
  root,folder=self.heroic();snap=scan({},home=self.home);e=next(e for e in snap['entries'] if e['store']=='Epic')
  e['record_id']='id with spaces&other=value'
  with patch('installations.shutil.which',return_value='/usr/bin/heroic'):
   cmd=command(e,{})
  self.assertEqual(len(cmd),2);self.assertIn('appName=id+with+spaces%26other%3Dvalue&runner=legendary',cmd[1])
  e['mode']='flatpak'
  with patch('installations.shutil.which',return_value='/usr/bin/flatpak'):self.assertEqual(command(e,{})[:3],['flatpak','run','com.heroicgameslauncher.hgl'])
 def test_custom_root_requires_matching_wrapper(self):
  root,manifest=self.steam();e=scan({},home=self.home)['entries'][0];e['custom_root']=True
  with self.assertRaises(LaunchError):command(e,{})
  with patch('installations.shutil.which',return_value='/custom/wrapper'):
   self.assertEqual(command(e,{'launch_steam_exe':'/custom/wrapper'}),['/custom/wrapper','-applaunch','123'])
 def test_scan_cancel(self):
  event=threading.Event();event.set()
  with self.assertRaises(ScanCancelled):scan({},cancel=event,home=self.home)
 def test_cache_does_not_change_ownership(self):
  db=Database(self.home/'catalog.db');db.save([game('Steam',1,'A',{})]);db.save_installations({'entries':[]})
  self.assertTrue(db.rows()[0]['active']);self.assertEqual(db.installations(),{'entries':[]})
 def test_flatpak_missing_application_rejected(self):
  from types import SimpleNamespace
  with patch('installations.subprocess.run',return_value=SimpleNamespace(returncode=1)):
   with self.assertRaises(LaunchError):check_provider(['flatpak','run','net.lutris.Lutris','lutris:rungameid/1'])
 def test_lutris_executable_path_fallback(self):
  self.assertEqual(lutris_path({'directory':None,'executable':'/Games/game.sh'}),'/Games/game.sh')
  self.assertIsNone(lutris_path({'executable':'relative.exe'}))
 def test_rockstar_remains_on_hold(self):
  r=game('Rockstar','gta5','GTA V',{})
  e={'key':'k','store':'Rockstar','id':'gta5','state':'Installed','provider':'Lutris','path':'/tmp'}
  self.assertEqual(decorate([r],{'entries':[e],'covered':['EA']},{'Rockstar|gta5':'k'})[0]['installation_status'],'Unknown')

if __name__=='__main__':unittest.main()
