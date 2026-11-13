"""Open a Steam library page; never invoke game launch or installation commands."""

import shutil
from pathlib import Path
from PySide6.QtCore import QUrl, QProcess
from PySide6.QtGui import QDesktopServices


def can_open(row):
    ident = str(row.get("id", "")) if row else ""
    return bool(
        row
        and row.get("store") == "Steam"
        and len(ident) <= 10
        and ident.isascii()
        and ident.isdigit()
        and 0 < int(ident) < 2**32
    )


def library_url(row):
    if not can_open(row):
        raise ValueError("Select a Steam game with a valid app ID first.")
    return "steam://nav/games/details/" + str(int(row["id"]))


def open_in_steam(row, options):
    url = library_url(row)
    configured = options.get("launch_steam_exe") or ""
    executable = (
        shutil.which(str(Path(configured).expanduser()))
        if configured
        else shutil.which("steam")
    )
    if configured and not executable:
        raise ValueError(
            "The configured Steam program was not found. Update it in Installations…"
        )
    if executable:
        started, _pid = QProcess.startDetached(executable, [url])
    else:
        started = QDesktopServices.openUrl(QUrl(url))
    if not started:
        raise ValueError(
            "Could not open Steam. Check that Steam is installed or choose its executable in Installations…"
        )
    return url
