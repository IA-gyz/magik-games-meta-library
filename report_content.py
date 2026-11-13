"""Qt-free report text preparation; widgets are created only by report_dialogs."""

import json
from date_display import friendly_date, friendly_report
from acquisition_report_text import acquisition_summary
from metadata_report_text import metadata_summary, METADATA_HELP, OUTCOME_LABELS
from enrichment import next_retry
from installations import scan_summary

ACQUISITION_HELP = """Date added is the day a game joined your store account. It is not the installation or release date. Unknown means no reliable date was found.

Refresh libraries checks for dates. Get missing game details and Retry missing details do not fetch account history.

Steam: open Sources → Connect Steam dates, or select a saved English-language copy of the Steam licenses page. Uncertain matches are left Unknown.
GOG: dates come from completed orders. Some account items have no matching order. If access is rejected, a GOG website sign-in may be needed; a Galaxy token alone may not work.
Epic: dates come from your library and account ownership records. Games are matched by exact store IDs.
Amazon: dates come from the account records supplied by Nile. Missing or invalid dates stay Unknown.
EA: signing in can load your library even when the separate date-history service is unavailable. A missing date does not mean you do not own the game.

Open Technical details to see counts, matching results and errors from the most recent date check.
"""


def installation_content(snapshot):
    lines = [
        "Last scan: " + friendly_date(snapshot.get("time"), "Not scanned yet"),
        "Stores checked: " + (", ".join(snapshot.get("covered", [])) or "None"),
        scan_summary(snapshot),
        "",
        "Installed means the launcher lists the game and its folder is present; it is not a full check of every game file.",
        "Not detected means the game was not found in the locations checked. It may be installed elsewhere.",
        "Unavailable location means a folder could not be read, for example because its drive is disconnected.",
        "A Wine/Proton prefix is the folder containing a Windows environment for a launcher and its games.",
        "",
    ]
    notes = snapshot.get("notes", [])
    lines += ["Scan warnings:"] + notes if notes else ["No scan warnings."]
    lines += ["Windows environment found: " + p for p in snapshot.get("prefixes", [])]
    for entry in snapshot.get("entries", []):
        lines += [
            "",
            entry["title"],
            f"Launcher: {entry['provider']} · Store: {entry.get('store') or 'Not linked to a store game'}",
            "Status: " + entry["state"],
            "Folder: " + (entry.get("path") or "Not provided"),
            "Details: " + entry["detail"],
            "Launcher game ID: " + str(entry["record_id"]),
        ]
    if not snapshot.get("entries"):
        lines += [
            "",
            "No installed-game records to show. Try Rescan installations. Add a custom launcher folder in Installations if needed.",
        ]
    return dict(title="Installed games report", content="\n".join(lines))


def acquisition_content(reports):
    details = "\n\n".join(
        json.dumps(friendly_report(report), indent=2, ensure_ascii=False)
        for report in reports
    )
    return dict(
        title="Date added report",
        content=acquisition_summary(reports),
        technical=details or "No saved technical details yet.",
        help_text=ACQUISITION_HELP,
    )


def metadata_content(results, rows):
    titles = {(row["store"], row["id"]): row["title"] for row in rows}
    problems = [result for result in results if result["outcome"] != "enriched"]
    labels = OUTCOME_LABELS
    lines = [
        "Game details include descriptions, genres, release dates and similar information. These requests do not change your account library or dates added.",
        "Only the most recent saved result for each game is shown. Older attempts may have no saved report.",
        f"Results saved for {len(results)} games. {len(problems)} still have missing details.",
        "The entries below include every saved result, including successes. Store errors are included to help troubleshoot.",
        "Choose Get missing game details to retry when the waiting period ends, or Retry missing details to try now.",
    ]
    for result in results:
        lines += [
            "",
            titles.get((result["store"], result["id"]), result["title"]),
            f"Store: {result['store']} · Game ID: {result['id']}",
            "Result: " + labels.get(result["outcome"], result["outcome"]),
            "Details: " + result["reason"],
            "Last attempt: " + friendly_date(result["time"]),
            "Can retry after: "
            + (
                "Not needed for this saved successful result"
                if result["outcome"] == "enriched"
                else friendly_date(next_retry(result), "No waiting period recorded")
            ),
        ]
    if not results:
        lines += ["", "No game-detail requests have been recorded yet."]
    elif not problems:
        lines += [
            "",
            "No missing details were reported in the saved results. Stores may still leave individual fields blank.",
        ]
    return dict(
        title="Game details report",
        content=metadata_summary(results),
        technical="\n".join(lines),
        help_text=METADATA_HELP,
    )
