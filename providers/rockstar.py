"""Rockstar library and metadata protocol implementation."""

import re
from pathlib import Path
from core import game
from connector_io import FetchError, Cancelled

ROCKSTAR_METADATA = (
    "https://gamedownloads-rockstargames-com.akamaized.net/public/title_metadata.json"
)


def rockstar(options, cancel, progress, *, io):
    path = Path(options.get("rockstar_log", "")).expanduser()
    if not path.is_file():
        raise FetchError(
            "Select a Rockstar launcher.log file in Sources. Ownership recovery is partial."
        )
    owned = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        if cancel.is_set():
            raise Cancelled()
        m = re.search("\\b([a-zA-Z0-9_]+):\\s*.*?(on branch\\s|no branches!)", line)
        if m and m[1] not in ["launcher", "socialclub"]:
            owned[m[1]] = m[2].startswith("on branch")
    ids = [k for k, v in owned.items() if v]
    if not ids:
        raise FetchError(
            "No owned-title branch reports found in this log. Existing cache kept."
        )
    manifest = io.request(ROCKSTAR_METADATA)
    if isinstance(manifest, dict):
        catalog = manifest.get("titles", manifest)
    else:
        catalog = manifest
    if isinstance(catalog, dict):
        catalog = {
            str(x.get("titleId") or k): x
            for k, x in catalog.items()
            if isinstance(x, dict)
        }
    elif isinstance(catalog, list):
        catalog = {str(x.get("titleId") or x.get("id")): x for x in catalog}
    rows = []
    for ident in ids:
        d = catalog.get(ident, {}) if isinstance(catalog, dict) else {}
        rows.append(
            game(
                "Rockstar",
                ident,
                d.get("friendlyName") or d.get("name") or ident,
                {
                    "title_metadata": d,
                    "ownership_evidence": "Launcher log branch report",
                },
                source="Partial ownership recovery from launcher log",
                type="Game",
                languages=d.get("languages"),
            )
        )
    return rows
