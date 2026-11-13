"""Per-user desktop registration; application files remain in their current folder."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

from app_config import APP_ID
ROOT=Path(__file__).resolve().parent

def desktop_string(value):
    return str(value).replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r').replace('\t','\\t')

def exec_argument(value):
    value=str(value).replace('%','%%')
    for char in ('\\','"','`','$'):value=value.replace(char,'\\'+char)
    return desktop_string('"'+value+'"')

def register(remove=False,quiet=False,refresh=True):
    data=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
    if not data.is_absolute():raise ValueError('XDG_DATA_HOME must be an absolute path')
    desktop=data/'applications'/f'{APP_ID}.desktop'
    icon=data/'icons/hicolor/scalable/apps'/f'{APP_ID}.svg'
    if remove:
        desktop.unlink(missing_ok=True);icon.unlink(missing_ok=True)
    else:
        if not (ROOT/'app.py').is_file():raise ValueError('Keep the complete application folder together')
        desktop.parent.mkdir(parents=True,exist_ok=True);icon.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'assets'/f'{APP_ID}.svg',icon)
        desktop.write_text('\n'.join([
            '[Desktop Entry]','Type=Application','Version=1.0',
            'Name=Magik Games Library','GenericName=Games Library',
            'Comment=Browse your games and launch installed titles',
            'Exec='+exec_argument('/usr/bin/bash')+' '+exec_argument(ROOT/'run.sh'),
            'Path='+desktop_string(ROOT),'Icon='+desktop_string(icon),'Terminal=false',
            'Categories=Game;','Keywords=Steam;GOG;Epic;Amazon;EA;games;library;',
            'StartupNotify=true','StartupWMClass='+APP_ID,'\n']),encoding='utf-8')
        desktop.chmod(0o644)
    for command in (['update-desktop-database',str(desktop.parent)],['gtk-update-icon-cache','-f','-t',str(data/'icons/hicolor')],['kbuildsycoca6','--noincremental']):
        if refresh and shutil.which(command[0]):
            try:subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=False)
            except (OSError,subprocess.TimeoutExpired):pass
    if not quiet:print('KDE launcher removed. Your library and credentials were kept.' if remove else
          'KDE launcher installed. Open Magik Games Library from the application menu, then pin it to the taskbar.')
    if not quiet and not remove:print('Keep this application folder in place. Rerun setup after moving it: '+str(ROOT))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--remove',action='store_true')
    args=parser.parse_args();register(args.remove)
