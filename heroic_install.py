"""User-triggered Heroic installation handoff; Heroic owns confirmation and files."""

import shutil
from pathlib import Path
from urllib.parse import urlencode
from PySide6.QtCore import QUrl, QProcess
from PySide6.QtGui import QDesktopServices


def can_install(row):
    return bool(
        row
        and row.get("store") in ("Epic", "GOG")
        and row.get("id")
        and row.get("active", True)
        and row.get("installation_status") != "Installed"
        and not any(
            e.get("state") == "Installed" for e in row.get("_installations", [])
        )
        and str(row.get("type") or "").casefold() not in ("dlc", "movie", "film")
    )


def install_url(row):
    if not can_install(row):
        raise ValueError("Select an uninstalled Epic or GOG game first.")
    ident = str(row["id"])
    if row["store"] == "GOG" and not ident.isdigit():
        raise ValueError("This entry has no valid GOG product ID.")
    if not ident.strip() or any(ord(c) < 32 for c in ident):
        raise ValueError("This entry has no valid game ID.")
    return "heroic://launch?" + urlencode(
        {"appName": ident, "runner": "legendary" if row["store"] == "Epic" else "gog"}
    )


def open_install(row, options):
    url = install_url(row)
    configured = options.get("launch_heroic_exe") or ""
    executable = (
        shutil.which(str(Path(configured).expanduser()))
        if configured
        else shutil.which("heroic")
    )
    if configured and not executable:
        raise ValueError(
            "The configured Heroic program was not found. Update it in Installations…"
        )
    if executable:
        started, _pid = QProcess.startDetached(executable, [url])
    else:
        # The desktop handler also supports Flatpak and registered AppImages.
        started = QDesktopServices.openUrl(QUrl(url))
    if not started:
        raise ValueError(
            "Could not open Heroic. Install Heroic or choose its executable in Installations…"
        )
    return url
