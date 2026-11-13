"""Readable summaries of saved acquisition checks; no Qt or account requests."""

from date_display import friendly_date

INTRO = """Date added is when a game joined your store account, not the installation or release date.
These are results from the last saved check for each store, not a live check. Manual dates and previously saved dates may make the current library's date coverage different.
Refresh libraries checks account dates. Get missing game details and Retry missing details do not fetch account history.
"""


def count(report, key):
    value = report.get(key)
    return value if type(value) is int and value >= 0 else None


def acquisition_summary(reports):
    lines = [INTRO]
    if not reports:
        return (
            INTRO
            + "\nNo date checks have been saved yet. Connect your accounts in Sources, then choose Refresh libraries."
        )
    for report in reports:
        store = report.get("store") or "Unknown store"
        found, missing = count(report, "matched"), count(report, "unmatched_games")
        warnings = report.get("warnings") or []
        lines += [
            str(store),
            "Last checked: " + friendly_date(report.get("time"), "Not recorded"),
            "Entries matched to a date: "
            + (f"{found:,}" if found is not None else "Not reported"),
            "Entries without a date match: "
            + (f"{missing:,}" if missing is not None else "Not reported"),
        ]
        if found is not None and missing is not None:
            lines.append(f"Library entries in this check: {found + missing:,}")
        if warnings:
            lines.append(
                "Result: The check reported a problem. Counts may be incomplete; see Technical details."
            )
        elif found is None or missing is None:
            lines.append(
                "Result: This saved report does not include enough counts to measure date coverage."
            )
        elif found + missing == 0:
            lines.append("Result: There were no library entries in this check.")
        elif missing == 0:
            lines.append("Result: Every entry in this check was matched to a date.")
        elif found == 0:
            lines.append("Result: No account dates were matched in this check.")
        else:
            lines.append(
                "Result: Dates were found for some entries. Others are still unmatched."
            )
        if store == "Steam" and report.get("license_history_complete") is False:
            lines.append(
                "History coverage: Only part of the Steam license history was read. More dates may be missing."
            )
        if warnings or (missing is not None and missing > 0):
            advice = {
                "Steam": "Check Sources → Connect Steam dates, or your saved licenses-page file. Some licenses cannot be matched with certainty.",
                "GOG": "Check the order-history warnings in Technical details. Some account items may have no matching completed order.",
                "Epic": "Check your Heroic or Legendary sign-in if the report shows access errors. Some account records may not provide a usable date.",
                "Amazon": "Check your Heroic or Nile sign-in if the report shows access errors. Some account records may not provide a usable date.",
                "EA": "Check the service errors in Technical details. EA date history can be unavailable even when your game library loads correctly.",
            }.get(store, "Review Technical details for the source and any errors.")
            lines.append("What to check: " + advice)
        lines += [
            "Open Help for store-specific instructions. Refresh libraries runs the next check.",
            "",
        ]
    return "\n".join(lines)
