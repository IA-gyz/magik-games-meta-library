"""Steam library and metadata protocol implementation."""

from core import game
from connector_io import FetchError, MetadataUnavailable


def steam(options, cancel, progress, *, io):
    key = options.get("steam_key", "").strip()
    ident = options.get("steam_id", "").strip()
    if not key or not ident:
        raise FetchError("Enter a Steam API key and SteamID64 in Sources")
    if not ident.isdigit():
        ident = io.request(
            "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
            {"key": key, "vanityurl": ident},
        )["response"].get("steamid")
        if not ident:
            raise FetchError("Steam vanity name could not be resolved")
    response = io.request(
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
        {
            "key": key,
            "steamid": ident,
            "include_appinfo": 1,
            "include_played_free_games": 1,
        },
    )
    data = response.get("response", {})
    if "game_count" not in data:
        raise FetchError(
            "Steam did not expose a library. Check Game Details privacy and account/key."
        )
    rows = [
        game(
            "Steam",
            p["appid"],
            p.get("name") or f"Steam App {p['appid']}",
            p,
            type="Game",
            playtime=p.get("playtime_forever"),
            last_played=p.get("rtime_last_played"),
            url=f"https://store.steampowered.com/app/{p['appid']}/",
        )
        for p in data.get("games", [])
    ]
    from steam_dates import steam_dates
    from acquisition import optional_dates

    return optional_dates(
        "Steam",
        rows,
        progress,
        lambda: steam_dates(
            rows, {**options, "steam_id": ident}, cancel, progress, io.request
        ),
    )


def steam_details(row, *, io):
    data = io.request(
        "https://store.steampowered.com/api/appdetails",
        {"appids": row["id"], "l": "english", "cc": "fr"},
    )
    result = data.get(row["id"], {})
    if not result.get("success"):
        raise MetadataUnavailable(
            "Steam returned success=false: this app may be delisted, region-restricted, or lack a public store page"
        )
    d = result["data"]
    platforms = [k for k, v in (d.get("platforms") or {}).items() if v]
    enriched = game(
        "Steam",
        row["id"],
        row["title"],
        {**row["raw"], "store_details": d},
        type=d.get("type"),
        genres=d.get("genres"),
        developers=d.get("developers"),
        publishers=d.get("publishers"),
        release=(d.get("release_date") or {}).get("date"),
        platforms=platforms,
        languages=d.get("supported_languages"),
        controller=d.get("controller_support"),
        score=(d.get("metacritic") or {}).get("score"),
        description=d.get("detailed_description") or d.get("short_description"),
        cover=d.get("header_image"),
    )
    enriched.update(
        playtime=row.get("playtime"),
        last_played=row.get("last_played"),
        url=row.get("url"),
        active=row.get("active", True),
    )
    return enriched
