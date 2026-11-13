"""Amazon library and metadata protocol implementation."""

import json
from datetime import datetime, timezone
from core import normalize, acquisition_date
from contracts import LibraryRows


def amazon(options, cancel, progress, *, io):
    exe = options.get("amazon_exe") or "nile"
    config = options.get("amazon_config")
    io.helper(exe, ["library", "sync"], config, "NILE_CONFIG_PATH", cancel)
    rows = normalize(
        "Amazon",
        json.loads(
            io.helper(
                exe, ["library", "list", "--json"], config, "NILE_CONFIG_PATH", cancel
            )
        ),
    )
    present = sum(("entitlementDateFromEpoch" in r["raw"] for r in rows))
    valid = sum(
        (bool(acquisition_date(r["raw"].get("entitlementDateFromEpoch"))) for r in rows)
    )
    report = {
        "store": "Amazon",
        "source": "Amazon entitlementDateFromEpoch (Nile entitlements)",
        "records": len(rows),
        "records_with_acquisition_field": present,
        "valid_acquisition_fields": valid,
        "invalid_acquisition_fields": present - valid,
        "matched": sum((bool(r["date_added"]) for r in rows)),
        "unmatched_games": sum((not r["date_added"] for r in rows)),
        "warnings": [],
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return LibraryRows(rows, report)
