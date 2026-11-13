"""Epic library and metadata protocol implementation."""

import json
from core import normalize


def epic_acquisition_dates(rows, options, cancel, progress, *, io):
    from acquisition import epic_dates, optional_dates

    return optional_dates(
        "Epic",
        rows,
        progress,
        lambda: epic_dates(rows, options, cancel, progress, io.request),
    )


def epic(options, cancel, progress, *, io):
    data = json.loads(
        io.helper(
            options.get("epic_exe") or "legendary",
            ["list", "--json", "--include-non-installable", "--force-refresh"],
            options.get("epic_config"),
            "LEGENDARY_CONFIG_PATH",
            cancel,
        )
    )
    return epic_acquisition_dates(
        normalize("Epic", data), options, cancel, progress, io=io
    )
