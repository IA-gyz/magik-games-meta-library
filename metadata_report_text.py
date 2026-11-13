"""Plain-language overview of the latest saved game-detail results."""

from collections import Counter

OUTCOME_LABELS = {
    "enriched": "Details retrieved",
    "partial": "Some details retrieved",
    "unavailable": "Not available from the store",
    "failed": "Request failed",
    "deferred": "Waiting: store requests were paused",
}

METADATA_HELP = """What is checked?
Game details include descriptions, genres, release dates and similar information. Extra detail requests are supported for Steam, GOG and Epic. They do not update account ownership, dates added or installed-game detection.

What do the results mean?
Details retrieved: the request succeeded and its details were saved. The store may still leave some fields blank.
Some details retrieved: basic or previously saved details were kept, but additional details could not be loaded.
Not available from the store: no usable public details were available. A game may be delisted, restricted or missing a public page. This does not mean you no longer own it.
Request failed: the request or its response could not be processed. Open Technical details for the error and retry time.
Waiting: requests to that store were paused, so this game was not attempted during that run. This is not a failure of the game itself.

What should I do next?
Get missing game details requests eligible missing details. Entries still in a waiting period are skipped.
Retry missing details tries eligible missing entries now, including those waiting after an error. It does not force the store to return unavailable information.
If a report says to reconnect, open Sources and check that store’s sign-in. If the store asks you to wait, retry later.

How current is this report?
It shows only the most recent saved result per game, not a complete history or a live check. Games with no saved result are not counted. Saved results may include older or imported entries. The current request may still be running, and stores may leave individual fields unknown even after a successful request.
"""


def metadata_summary(results):
    lines = [
        "These are the latest saved game-detail request results, not a live check.",
        "Each game has at most one saved result here. Games with no saved result are not counted.",
        f"Library entries with a saved result: {len(results):,}",
        "A successful request does not mean every field is known. Stores may leave information blank.",
        "",
    ]
    if not results:
        lines += [
            "No game-detail requests have been recorded yet.",
            "Choose Get missing game details to request descriptions, genres and other details for Steam, GOG and Epic.",
        ]
        return "\n".join(lines)
    stores = {}
    for result in results:
        store = result.get("store") or "Unknown store"
        stores.setdefault(store, Counter())[result.get("outcome")] += 1
    for store, counts in stores.items():
        lines += [str(store), f"Saved results: {sum(counts.values()):,}"]
        lines += [
            f"{label}: {counts[outcome]:,}" for outcome, label in OUTCOME_LABELS.items()
        ]
        other = sum(
            number
            for outcome, number in counts.items()
            if outcome not in OUTCOME_LABELS
        )
        if other:
            lines.append(
                f"Other or unrecognized results: {other:,}. See Technical details."
            )
        if other:
            lines.append(
                "Next step: Open Technical details to inspect the unrecognized result."
            )
        elif counts["failed"] or counts["partial"]:
            lines.append(
                "Next step: Open Technical details for the affected games, errors and retry times."
            )
        elif counts["deferred"]:
            lines.append(
                "Next step: Try again later. This store was paused during the previous run."
            )
        elif counts["unavailable"]:
            lines.append(
                "Next step: No immediate action is required. These details may remain unavailable from the store."
            )
        else:
            lines.append(
                "No request failures are recorded for this store in these results."
            )
        lines.append("")
    lines += [
        "Get missing game details respects waiting periods. Retry missing details tries waiting entries now.",
        "Neither action fetches account history. Use Refresh libraries for dates added.",
        "Open Help for result definitions and retry instructions.",
    ]
    return "\n".join(lines)
