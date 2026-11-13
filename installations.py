"""Read-only installation discovery and fixed provider launch handoffs.
No installation, import into another manager, Wine configuration or title guessing.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode,quote

STATES=['Installed','Incomplete','Unavailable location','Not detected','Unknown']
SERVICE_STORES={'steam':'Steam','gog':'GOG','egs':'Epic','epic':'Epic','amazon':'Amazon','amazon_games':'Amazon','ea_app':'EA','origin':'EA'}
class ScanCancelled(Exception):pass
class LaunchError(Exception):pass

def vdf(text):
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|[{}]',re.sub(r'(?m)^\s*//.*$','',text));position=0
    def parse(nested=False):
        nonlocal position
        result={}
        while position<len(tokens):
            token=tokens[position];position+=1
            if token=='}':
                if not nested:raise ValueError('Unexpected closing VDF brace')
                return result
            if not token.startswith('"') or position>=len(tokens):raise ValueError('Invalid VDF key')
            key=re.sub(r'\\(["\\])',r'\1',token[1:-1]);value=tokens[position];position+=1
            if value=='{':result[key]=parse(True)
            elif value.startswith('"'):result[key]=re.sub(r'\\(["\\])',r'\1',value[1:-1])
            else:raise ValueError('Invalid VDF value')
        if nested:raise ValueError('Unclosed VDF object')
        return result
    result=parse()
    if not result:raise ValueError('Empty VDF')
    return result

def json_file(path):
    if path.stat().st_size>32*1024*1024:raise ValueError('Installation registry exceeds 32 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def records(data,kind):
    if kind=='gog':
        values=data.get('installed') if isinstance(data,dict) else data
        if not isinstance(values,list):raise ValueError('Invalid GOG installed registry')
        return [(str(r.get('appName') or r.get('app_name') or r.get('id')),r) for r in values if isinstance(r,dict)]
    if kind=='epic':
        if not isinstance(data,dict):raise ValueError('Invalid Legendary installed registry')
        return [(str(k),r) for k,r in data.items() if isinstance(r,dict)]
    if kind=='nile':
        if not isinstance(data,list):raise ValueError('Invalid Nile installed registry')
        return [(str(r.get('id')),r) for r in data if isinstance(r,dict)]
    raise ValueError('Unknown registry format')

def root_paths(options,home=None):
    home=Path(home or Path.home());config=Path(os.environ.get('XDG_CONFIG_HOME',str(home/'.config')));data=Path(os.environ.get('XDG_DATA_HOME',str(home/'.local/share')))
    roots={
      'steam':[(data/'Steam','native'),(home/'.steam/steam','native'),(home/'.steam/root','native'),(home/'.var/app/com.valvesoftware.Steam/data/Steam','flatpak'),(home/'.var/app/com.valvesoftware.Steam/.local/share/Steam','flatpak')],
      'heroic':[(config/'heroic','native'),(home/'.var/app/com.heroicgameslauncher.hgl/config/heroic','flatpak')],
      'lutris':[(data/'lutris','native'),(home/'.var/app/net.lutris.Lutris/data/lutris','flatpak')]}
    extra_heroic=options.get('epic_heroic_root')
    if extra_heroic:roots['heroic'].append((Path(extra_heroic).expanduser(),'native'))
    for kind in roots:
        for value in options.get('scan_'+kind+'_roots','').splitlines():
            value=value.strip()
            if value:roots[kind].append((Path(value).expanduser(),'flatpak' if '/.var/app/' in value else 'native'))
        unique={}
        for path,mode in roots[kind]:
            resolved=str(path.resolve());unique.setdefault(resolved,(Path(resolved),mode))
        roots[kind]=list(unique.values())
    return roots

def anchor(path):
    path=Path(path);parts=path.parts
    for prefix,count in [(('/','run','media'),5),(('/','media'),4),(('/','mnt'),3)]:
        if parts[:len(prefix)]==prefix and len(parts)>=count:return Path(*parts[:count])
    return path.parent

def classify(entry):
    path=entry.get('path')
    if not path:return 'Unknown','Provider did not record an installation path'
    p=Path(path)
    try:
        if p.exists():
            if not entry.get('complete',True):return 'Incomplete','Manager reports an incomplete installation'
            return 'Installed','The launcher lists this game, and its installation folder exists.'
        base=Path(entry.get('library_root') or anchor(p))
        if not base.exists():return 'Unavailable location','Installation location or drive is unavailable'
        return 'Not detected','Installation record exists, but its files are missing'
    except OSError:return 'Unavailable location','Could not access installation location'

def lutris_path(info):
    path=info.get('directory')
    if not path:
        executable=info.get('executable')
        if isinstance(executable,str) and Path(executable).expanduser().is_absolute():path=executable
    return str(Path(path).expanduser()) if path else None

def finish_entry(entry,previous_by_key):
    if entry.get('path') and not Path(entry['path']).is_absolute():
        entry['state']='Unknown';entry['detail']='Manager recorded a relative installation path';return entry
    entry.pop('device',None)  # Discard obsolete runtime device numbers from old snapshots.
    entry['state'],entry['detail']=classify(entry)
    return entry

def windows_path(prefix,value):
    """Resolve explicit Windows drive mappings without executing anything."""
    parts=str(value).replace('\\','/').split('/')
    if not re.fullmatch('[A-Za-z]:',parts[0]) or '..' in parts:return None
    drive=parts.pop(0).lower();base=prefix/'dosdevices'/drive
    if not base.exists():
        if drive!='c:':return None
        base=prefix/'drive_c'
    current=base.resolve()
    for part in filter(None,parts):
        target=current/part
        if not target.exists() and current.is_dir():
            found=next((p for p in current.iterdir() if p.name.casefold()==part.casefold()),None)
            if found:target=found
        current=target
    return current

def discover_prefixes(options,steam_libraries,entries,home,check,notes):
    """Bounded discovery in manager locations; never walk the whole home or disks."""
    home=Path(home or Path.home());candidates=[]
    def children(folder):
        if not folder.is_dir():return []
        try:
            result=[]
            for item in folder.iterdir():
                check()
                if len(result)>=2048:
                    notes.append('Prefix discovery limit reached: '+str(folder));break
                if item.is_dir():result.append(item)
            return result
        except OSError:
            notes.append('Could not inspect prefix location: '+str(folder));return []
    for library in steam_libraries:candidates.extend(children(Path(library)/'steamapps/compatdata'))
    games=home/'Games';candidates.append(games)
    for folder in children(games):
        candidates.append(folder);candidates.extend(children(folder))
    candidates.append(home/'.wine')
    for entry in entries:
        if entry.get('kind')!='lutris' or not entry.get('path'):continue
        folder=Path(entry['path'])
        candidates.extend([folder,*list(folder.parents)[:8]])
    for value in options.get('scan_prefix_roots','').splitlines():
        if value.strip():candidates.append(Path(value.strip()).expanduser())
    result={}
    for folder in candidates:
        check()
        try:
            if (folder/'pfx/drive_c').is_dir():folder=folder/'pfx'
            if (folder/'drive_c').is_dir():result[str(folder.resolve())]=None
        except OSError:notes.append('Could not access candidate prefix: '+str(folder))
    # Preserve explicitly requested missing paths for diagnostics and cached evidence.
    for value in options.get('scan_prefix_roots','').splitlines():
        if value.strip():
            folder=Path(value.strip()).expanduser().resolve()
            if (folder/'pfx/drive_c').is_dir():folder=folder/'pfx'
            result.setdefault(str(folder),None)
    return list(result)

def prefix_records(options,check,notes):
    entries=[];scopes={}
    for value in options.get('scan_prefix_roots','').splitlines():
        if not value.strip():continue
        prefix=Path(value.strip()).expanduser().resolve()
        if (prefix/'pfx/drive_c').is_dir():prefix=prefix/'pfx'
        scope='Windows prefix|'+str(prefix)
        if not (prefix/'drive_c').is_dir():
            scopes[scope]={'status':'unavailable'};notes.append('Wine prefix unavailable: '+str(prefix));continue
        scopes[scope]={'status':'ok'}
        manifests=windows_path(prefix,'C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests')
        files=list(manifests.glob('*.item')) if manifests and manifests.is_dir() else []
        for file in files:
            check()
            try:
                info=json_file(file);ident=str(info['AppName']);path=windows_path(prefix,info['InstallLocation'])
                if not path:raise ValueError('Unmapped Windows drive')
                entries.append(dict(key=scope+'|Epic|'+str(file),scope=scope,store='Epic',id=ident,title=info.get('DisplayName') or ident,
                    provider='Epic (Windows prefix)',kind='prefix',mode='wine',root=str(prefix),library_root=str(anchor(path)),path=str(path),
                    record_file=str(file),record_id=ident,record_format='epic-item',complete=not info.get('bIsIncompleteInstall',False),launch_ready=False))
            except (OSError,ValueError,KeyError,TypeError):
                scopes[scope]={'status':'error'};notes.append('Unreadable Epic manifest or unmapped drive: '+str(file))
        folders=[windows_path(prefix,'C:/Program Files/EA Games'),windows_path(prefix,'C:/Program Files/Origin Games')]
        folders += [Path(v.strip()).expanduser().resolve() for v in options.get('scan_ea_game_roots','').splitlines() if v.strip()]
        for folder in dict.fromkeys(folders):
            if not folder or not folder.is_dir():continue
            for file in folder.glob('*/__Installer/installerdata.xml'):
                check()
                try:
                    if file.stat().st_size>4*1024*1024:raise ValueError()
                    xml=ET.parse(file);ids=list(dict.fromkeys(n.text.strip() for n in xml.iter('contentID') if n.text and n.text.strip()))
                    if not ids:continue
                    path=file.parent.parent
                    for ident in ids:
                        entries.append(dict(key=scope+'|EA|'+str(file)+'|'+ident,scope=scope,store='EA',id=ident,title=path.name,
                            provider='EA (Windows prefix)',kind='prefix',mode='wine',root=str(prefix),library_root=str(anchor(path)),path=str(path),
                            record_file=str(file),record_id=ident,record_format='ea-xml',complete=True,launch_ready=False))
                except (OSError,ValueError,ET.ParseError):
                    scopes[scope]={'status':'error'};notes.append('Unreadable EA installation record: '+str(file))
    return entries,scopes

def scan(options,previous=None,cancel=None,progress=lambda _:None,home=None):
    previous=previous or {};old={e['key']:e for e in previous.get('entries',[])}
    entries=[];scopes={};covered=set();notes=[];steam_libraries=set()
    def check():
        if cancel and cancel.is_set():raise ScanCancelled()
    def scope_id(provider,root):return provider+'|'+str(root)
    roots=root_paths(options,home)
    standard_roots={kind:{str(path) for path,_ in values} for kind,values in root_paths({},home).items()}
    for root,mode in roots['steam']:
        check();progress('Scanning Steam: '+str(root))
        if not root.exists():
            if str(root) not in standard_roots['steam']:notes.append('Configured Steam data root is missing or inaccessible: '+str(root))
            continue
        libraries={str(root):{}}
        folder_file=root/'steamapps/libraryfolders.vdf'
        if not folder_file.exists():folder_file=root/'config/libraryfolders.vdf'
        try:
            if folder_file.is_file():
                folder_data=vdf(folder_file.read_text())
                folder_data=folder_data.get('libraryfolders') or folder_data.get('LibraryFolders') or {}
                for key,value in folder_data.items():
                    if not str(key).isdigit():continue
                    if isinstance(value,dict) and value.get('path'):libraries[str(Path(value['path']).expanduser())]=value.get('apps') or {}
                    elif isinstance(value,str):libraries[value]={}
        except (OSError,ValueError) as exc:notes.append('Steam libraryfolders could not be read: '+str(root))
        for library,apps in libraries.items():
            steam_libraries.add(library)
            check();base=Path(library);scope=scope_id('Steam '+mode,base)
            steamapps=base/'steamapps'
            # st_dev is a runtime device number, not a persistent filesystem identity.
            # Re-read accessible manifests even if an earlier scan recorded another number.
            if not steamapps.is_dir():
                scopes[scope]={'status':'unavailable','detail':'Steam library folder is missing or inaccessible: '+str(steamapps)}
                notes.append(scopes[scope]['detail'])
                for appid in apps:
                    if not str(appid).isdigit():continue
                    key=scope+'|'+str(appid)
                    if key in old:continue
                    entries.append({'key':key,'scope':scope,'store':'Steam','id':str(appid),'title':f'Steam app {appid}',
                        'provider':'Steam ('+mode+')','kind':'steam','mode':mode,'root':str(root),'library_root':str(base),
                        'path':None,'record_file':str(steamapps/f'appmanifest_{appid}.acf'),'record_id':str(appid),
                        'state':'Unavailable location','detail':'Library is registered with Steam but is unavailable','complete':True})
                continue
            scopes[scope]={'status':'ok'};covered.add('Steam')
            for manifest in steamapps.glob('appmanifest_*.acf'):
                check()
                try:
                    info=vdf(manifest.read_text())['AppState'];appid=str(info['appid']);folder=info.get('installdir')
                    if not appid.isdigit() or not folder:raise ValueError()
                    relative=Path(folder)
                    if relative.is_absolute() or '..' in relative.parts:raise ValueError()
                    path=(steamapps/'common'/relative).resolve()
                    entry={'key':scope+'|'+appid,'scope':scope,'store':'Steam','id':appid,'title':info.get('name',appid),
                        'provider':'Steam ('+mode+')','kind':'steam','mode':mode,'root':str(root),'library_root':str(base),
                        'path':str(path),'record_file':str(manifest),'record_id':appid,'complete':bool(int(info.get('StateFlags','0'))&4)}
                    entries.append(finish_entry(entry,old))
                except (OSError,ValueError,KeyError):
                    notes.append('Unreadable Steam manifest: '+str(manifest))
                    for cached in old.values():
                        if cached.get('record_file')==str(manifest):entries.append({**cached,'state':'Unknown','detail':'Steam manifest is unreadable; rescan after fixing it'})
    for root,mode in roots['heroic']:
        check();progress('Scanning Heroic: '+str(root))
        if not root.is_dir():continue
        for kind,store,relative in [('epic','Epic','legendaryConfig/legendary/installed.json'),('gog','GOG','gog_store/installed.json'),('nile','Amazon','nile_config/nile/installed.json')]:
            check();file=root/relative;scope=scope_id('Heroic '+mode+' '+kind,root)
            if not file.exists():scopes[scope]={'status':'ok'};covered.add(store);continue
            try:
                data=records(json_file(file),kind);scopes[scope]={'status':'ok'};covered.add(store)
                for ident,info in data:
                    if ident in ['None','']:continue
                    path=info.get('install_path') or info.get('path')
                    if path:path=str(Path(path).expanduser())
                    entry={'key':scope+'|'+ident,'scope':scope,'store':store,'id':ident,'title':info.get('title') or info.get('app_title') or ident,
                        'provider':'Heroic ('+mode+')','kind':'heroic','mode':mode,'runner':{'epic':'legendary','gog':'gog','nile':'nile'}[kind],
                        'root':str(root),'library_root':str(anchor(path)) if path else None,'path':path,
                        'record_file':str(file),'record_id':ident,'record_format':kind,'complete':not bool(info.get('is_incomplete_install') or info.get('is_installing'))}
                    if kind=='gog' and path and (Path(path)/'.gogdl-resume').exists():entry['complete']=False
                    entries.append(finish_entry(entry,old))
            except (OSError,ValueError,TypeError):scopes[scope]={'status':'error'};notes.append('Unreadable Heroic registry: '+str(file))
    for root,mode in roots['lutris']:
        check();dbpath=root/'pga.db';scope=scope_id('Lutris '+mode,root)
        if not dbpath.is_file():continue
        progress('Scanning Lutris: '+str(dbpath))
        try:
            with sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
                db.row_factory=sqlite3.Row
                columns={r[1] for r in db.execute('PRAGMA table_info(games)')}
                if not {'id','installed'}.issubset(columns):raise ValueError()
                games=[dict(r) for r in db.execute('SELECT * FROM games WHERE installed=1')]
            scopes[scope]={'status':'ok'};covered.update(['Steam','GOG','Epic','Amazon','EA'])
            for info in games:
                check();ident=str(info['id'])
                if not ident.isdigit():continue
                service=str(info.get('service') or '').lower();store=SERVICE_STORES.get(service)
                service_id=info.get('service_id');path=lutris_path(info)
                entry={'key':scope+'|'+ident,'scope':scope,'store':store,'id':str(service_id) if service_id else None,
                    'title':info.get('name') or info.get('slug') or ident,'provider':'Lutris ('+mode+')','kind':'lutris','mode':mode,
                    'root':str(root),'library_root':str(anchor(path)) if path else None,'path':str(Path(path).expanduser()) if path else None,
                    'record_file':str(dbpath),'record_id':ident,'complete':True}
                entries.append(finish_entry(entry,old))
        except (OSError,sqlite3.Error,ValueError):scopes[scope]={'status':'error'};notes.append('Could not read Lutris database: '+str(dbpath))
    discovered=discover_prefixes(options,steam_libraries,entries,home,check,notes)
    prefix_entries,prefix_scopes=prefix_records({**options,'scan_prefix_roots':'\n'.join(discovered)},check,notes)
    entries.extend(finish_entry(e,old) for e in prefix_entries);scopes.update(prefix_scopes)
    # Preserve evidence on an unavailable/corrupt source instead of claiming an uninstall.
    keys={e['key'] for e in entries}
    for key,entry in old.items():
        if key in keys:continue
        state=scopes.get(entry['scope'],{}).get('status')
        if state in ['unavailable','error'] or entry['scope'] not in scopes:
            detail=(scopes.get(entry['scope']) or {}).get('detail') or ('Previous installation source is unreadable: ' if state=='error' else 'Previous installation source was not accessible in this scan: ')+str(entry.get('root') or entry['scope'])
            if detail not in notes:notes.append(detail)
            entries.append({**entry,'state':'Unavailable location' if state!='error' else 'Unknown','detail':detail})
    unique={}
    for entry in entries:
        group=entry['kind']
        entry['custom_root']=entry['root'] not in standard_roots.get(group,set())
        previous_entry=unique.get(entry['key'])
        if not previous_entry or (previous_entry.get('custom_root') and not entry['custom_root']):unique[entry['key']]=entry
    entries=list(unique.values())
    return {'entries':entries,'scopes':scopes,'covered':sorted(covered),'notes':notes,'prefixes':discovered,'time':datetime.now(timezone.utc).isoformat(timespec='seconds')}

def matches_game(row,entry,links=None):
    if row['store']=='Rockstar':return False
    if (links or {}).get(row['store']+'|'+row['id'])==entry['key']:return True
    if entry.get('store')!=row['store'] or not entry.get('id'):return False
    ids={row['id']}
    if row['store']=='EA':
        product=(row.get('raw') or {}).get('product') or {}
        ids.update(str(product[k]) for k in ['id','contentId','originOfferId'] if product.get(k))
    return entry['id'] in ids

def decorate(rows,snapshot,links=None):
    entries=snapshot.get('entries',[]);covered=snapshot.get('covered',[]);index={};by_key={e['key']:e for e in entries}
    for entry in entries:
        if entry.get('store') and entry.get('id'):index.setdefault((entry['store'],entry['id']),[]).append(entry)
    for row in rows:
        ids={row['id']}
        if row['store']=='EA':
            product=(row.get('raw') or {}).get('product') or {}
            ids.update(str(product[k]) for k in ['id','contentId','originOfferId'] if product.get(k))
        candidates=[]
        if row['store']!='Rockstar':
            candidates=[e for ident in ids for e in index.get((row['store'],ident),[])]
            linked=by_key.get((links or {}).get(row['store']+'|'+row['id']))
            if linked:candidates.append(linked)
        candidates=list({e['key']:e for e in candidates}.values())
        state=next((s for s in STATES if any(e['state']==s for e in candidates)),None)
        row['installation_status']=state or ('Not detected' if row['store'] in covered and str(row.get('type') or '').casefold()!='dlc' else 'Unknown')
        row['launch_provider']=', '.join(dict.fromkeys(e['provider'] for e in candidates))
        row['installation_path']='; '.join(dict.fromkeys(e['path'] for e in candidates if e.get('path')))
        row['_installations']=candidates
    return rows

def validate(entry):
    state,reason=classify(entry)
    if entry.get('state')!='Installed' or state!='Installed':raise LaunchError(reason)
    path=Path(entry['record_file']);ident=entry['record_id']
    try:
        if entry['kind']=='steam':
            info=vdf(path.read_text())['AppState']
            if str(info.get('appid'))!=ident or not int(info.get('StateFlags',0))&4:raise ValueError()
            current=(path.parent/'common'/info.get('installdir','')).resolve()
            if str(current)!=str(Path(entry['path']).resolve()):raise ValueError()
        elif entry['kind']=='heroic':
            current=next((r for i,r in records(json_file(path),entry['record_format']) if i==ident),None)
            if not current or str(Path(current.get('install_path') or current.get('path') or '').expanduser())!=entry['path'] or current.get('is_incomplete_install') or current.get('is_installing'):raise ValueError()
            if entry['record_format']=='gog' and (Path(entry['path'])/'.gogdl-resume').exists():raise ValueError()
        elif entry['kind']=='lutris':
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                db.row_factory=sqlite3.Row
                current=db.execute('SELECT * FROM games WHERE id=? AND installed=1',(ident,)).fetchone()
                if not current or lutris_path(dict(current))!=entry['path']:raise ValueError()
        elif entry['kind']=='prefix':
            if entry['record_format']=='epic-item':
                info=json_file(path);current=windows_path(Path(entry['root']),info['InstallLocation'])
                if str(info['AppName'])!=ident or str(current)!=entry['path'] or info.get('bIsIncompleteInstall'):raise ValueError()
            else:
                if path.stat().st_size>4*1024*1024:raise ValueError()
                if ident not in [n.text.strip() for n in ET.parse(path).iter('contentID') if n.text]:raise ValueError()
        else:raise ValueError()
    except (OSError,ValueError,sqlite3.Error,KeyError,ET.ParseError):raise LaunchError('The launcher’s installation record changed or could not be read. Choose Rescan installations, then try Play again.') from None

def command(entry,options):
    """Argument vector, never shell text; provider is responsible for compatibility settings."""
    kind=entry['kind'];flatpak=entry['mode']=='flatpak'
    override=options.get('launch_'+{'steam':'steam','heroic':'heroic','lutris':'lutris'}.get(kind,'')+'_exe')
    if entry.get('custom_root') and not override:
        raise LaunchError('This game uses a custom launcher data folder. Open Installations and select a script that starts the launcher with that folder.')
    if kind=='steam':
        if not entry['record_id'].isdigit():raise LaunchError('Invalid Steam app ID')
        args=['-applaunch',entry['record_id']]
        cmd=['flatpak','run','com.valvesoftware.Steam'] if flatpak else [options.get('launch_steam_exe') or 'steam']
    elif kind=='heroic':
        if entry.get('runner') not in ['legendary','gog','nile']:raise LaunchError('Invalid Heroic runner')
        args=['heroic://launch?'+urlencode({'appName':entry['record_id'],'runner':entry['runner']})]
        cmd=['flatpak','run','com.heroicgameslauncher.hgl'] if flatpak else [options.get('launch_heroic_exe') or 'heroic']
    elif kind=='lutris':
        if not entry['record_id'].isdigit():raise LaunchError('Invalid Lutris game ID')
        args=['lutris:rungameid/'+entry['record_id']]
        cmd=['flatpak','run','net.lutris.Lutris'] if flatpak else [options.get('launch_lutris_exe') or 'lutris']
    else:raise LaunchError('Unsupported launch provider')
    if entry.get('custom_root') and override:cmd=[override]
    cmd=[str(Path(cmd[0]).expanduser()),*cmd[1:],*args]
    if not shutil.which(cmd[0]):raise LaunchError(f'Launcher executable not found: {cmd[0]}. Configure it in Installations.')
    return cmd


def check_provider(args):
    if len(args)>=3 and args[1]=='run' and args[2] in ['com.valvesoftware.Steam','com.heroicgameslauncher.hgl','net.lutris.Lutris']:
        try:
            result=subprocess.run([args[0],'info',args[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            if result.returncode:raise LaunchError('Flatpak launcher is not installed for the current user: '+args[2])
        except (OSError,subprocess.TimeoutExpired):raise LaunchError('Could not check the Flatpak launcher. Verify it is installed and accessible.') from None


def scan_summary(snapshot):
    entries=snapshot.get('entries',[])
    counts={state:sum(e.get('state')==state for e in entries) for state in STATES}
    setup=sum(e.get('state')=='Installed' and not e.get('launch_ready',True) for e in entries)
    parts=[f"{counts['Installed']} installed",f"{counts['Incomplete']} incomplete",f"{counts['Unavailable location']} unavailable",f"{counts['Not detected']} missing files",f"{counts['Unknown']} unknown"]
    message=f"Installation scan: {len(entries)} installation records found — "+', '.join(parts)+f". Windows games that may need Launch setup: {setup}. Scan warnings: {len(snapshot.get('notes',[]))}."
    if not snapshot.get('covered') and not entries:message+=' No supported launcher data was found. Open Installations to add a custom launcher data folder.'
    return message
