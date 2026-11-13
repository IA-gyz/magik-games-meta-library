"""Canonical JSON/CSV export with atomic destination replacement; no Qt dependency."""

import csv
import json
import os
import stat
import tempfile
from pathlib import Path
from catalog_data import FIELDS

NAMES_FORMAT = "magik-library-names-v1"
NAMES_DATES_FORMAT = "magik-library-names-dates-v1"
SCOPES = ("all", "names", "names_dates")
REDUCED_FIELDS = {"names": ["title"], "names_dates": ["title", "date_added"]}


def export_catalog(path, rows, file_format="json", *, scope="all", check_cancel=None):
    check = check_cancel or (lambda: None)
    check()
    if file_format not in ("json", "csv"):
        raise ValueError("Choose JSON or CSV export.")
    if scope not in SCOPES:
        raise ValueError("Choose all fields, names only, or names and dates export.")
    # Follow an existing symlink just as the previous direct writer did.
    destination = Path(path).expanduser().resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix="." + destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            fields = REDUCED_FIELDS.get(scope, FIELDS)
            reduced = (
                [{key: row.get(key) for key in fields} for row in rows]
                if scope != "all"
                else rows
            )
            if file_format == "csv":
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for row in reduced:
                    check()
                    writer.writerow(
                        row
                        if scope != "all"
                        else {key: row.get(key) for key in FIELDS}
                    )
            else:
                if scope == "names":
                    payload = {
                        "format": NAMES_FORMAT,
                        "names": [row["title"] for row in reduced],
                    }
                elif scope == "names_dates":
                    payload = {"format": NAMES_DATES_FORMAT, "games": reduced}
                else:
                    payload = {"format": "magik-library-v1", "games": reduced}
                encoder = json.JSONEncoder(indent=2, ensure_ascii=False)
                for chunk in encoder.iterencode(payload):
                    check()
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists():
            temporary.chmod(stat.S_IMODE(destination.stat().st_mode))
        check()
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
