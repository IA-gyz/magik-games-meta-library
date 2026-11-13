"""Optional, independently cached game data sources. No Qt or account credentials in rows."""

import json
from contextlib import nullcontext
import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from email.utils import parsedate_to_datetime
import time

from connector_io import FetchError, Cancelled
from contracts import LogEntry, Severity
from metacritic import title_key

from extra_schema import SOURCES
from request_budgets import request_limit, BudgetExhausted
from opencritic_quota import Quota, QuotaPaused


def network(url, *, headers=None, data=None, content_type=None, response_headers=None):
    h = {
        "User-Agent": "MagikGamesLibrary/0.31",
        "Accept": "application/json",
        **(headers or {}),
    }
    if content_type:
        h["Content-Type"] = content_type
    try:
        with urlopen(Request(url, data=data, headers=h), timeout=25) as response:
            if response_headers:
                response_headers(response.headers)
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise FetchError("Response exceeded the size limit.")
            return json.loads(body)
    except HTTPError as exc:
        if response_headers and exc.headers:
            response_headers(exc.headers)
        retry = 0
        value = exc.headers.get("Retry-After", "0") if exc.headers else "0"
        try:
            retry = (
                float(value)
                if value.isdigit()
                else max(0, parsedate_to_datetime(value).timestamp() - time.time())
            )
        except (ValueError, TypeError, OverflowError):
            pass
        raise FetchError(
            "HTTP " + str(exc.code), status=exc.code, retry_after=retry
        ) from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise FetchError(
            "Connection failed, timed out, or returned unreadable data."
        ) from None


network.supports_response_headers = True

def number(value, maximum=None):
    if (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
        and (maximum is None or value <= maximum)
    ):
        return value
    return None


def https(value):
    return value if isinstance(value, str) and value.startswith("https://") else None


def names(items):
    return ", ".join(
        item["name"]
        for item in items or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )


def steam_id(row):
    if row.get("store") == "Steam" and str(row.get("id", "")).isdigit():
        return str(row["id"])
    mapping = (row.get("raw") or {}).get("extra_metadata", {}).get("IGDB", {})
    value = (
        mapping.get("steam_id")
        if mapping.get("matched_title") == row.get("title")
        else None
    )
    return str(value) if str(value).isdigit() else None


def exact_match(items, row, name="name", pc=False):
    if not isinstance(items, list):
        raise ValueError("The service returned an unexpected response.")
    found = []
    for item in items:
        if not isinstance(item, dict) or title_key(
            str(item.get(name, ""))
        ) != title_key(row["title"]):
            continue
        if pc and 6 not in item.get("platforms", []):
            continue
        release = row.get("release")
        date = (
            item.get("first_release_date")
            or item.get("firstReleaseDate")
            or item.get("release_date")
        )
        if release and re.match(r"^\d{4}", str(release)) and date:
            try:
                year = (
                    datetime.fromtimestamp(date, timezone.utc).year
                    if isinstance(date, (float, int))
                    else int(str(date)[:4])
                )
                if abs(int(str(release)[:4]) - year) > 1:
                    continue
            except (ValueError, OverflowError, OSError):
                continue
        found.append(item)
    if len(found) != 1:
        raise ValueError(
            "No unique exact title match. Editions and ambiguous titles were not guessed."
        )
    return found[0]


class Clients:
    def __init__(self, options, cancel, call=network):
        self.options = options
        self.cancel = cancel
        self.call = call
        self.token = None
        self.token_until = 0
        self.requests = 0
        self.source_start = 0
        self.limit = 0
        self.request_progress = lambda: None
        self.quota = Quota(options) if getattr(call, "supports_response_headers", False) is True else None

    def get(self, url, **kwargs):
        if self.cancel.is_set():
            raise Cancelled()
        if self.limit and self.requests - self.source_start >= self.limit:
            raise BudgetExhausted()
        tracked = self.quota is not None and url.startswith("https://opencritic-api.p.rapidapi.com/")
        with self.quota.request(self.cancel) if tracked else nullcontext():
            if tracked:
                kwargs["response_headers"] = self.quota.observe
            self.requests += 1
            self.request_progress()
            try:
                value = self.call(url, **kwargs)
                if tracked:
                    self.quota.access_result(True)
                return value
            except FetchError as exc:
                if tracked:
                    self.quota.access_result(False)
                if tracked and exc.status == 429:
                    self.quota.rate_pause(exc.retry_after or 3600)
                    raise QuotaPaused("OpenCritic reported a request limit; queued work will wait.") from None
                raise

    def igdb(self, row, _renew=True):
        if not self.token or time.monotonic() >= self.token_until:
            response = self.get(
                "https://id.twitch.tv/oauth2/token",
                data=urlencode(
                    {
                        "client_id": self.options["igdb_client_id"],
                        "client_secret": self.options["igdb_client_secret"],
                        "grant_type": "client_credentials",
                    }
                ).encode(),
                content_type="application/x-www-form-urlencoded",
            )
            self.token = response.get("access_token")
            if not isinstance(self.token, str) or not self.token:
                raise FetchError("IGDB authentication failed.")
            self.token_until = time.monotonic() + max(
                0, float(response.get("expires_in", 0)) - 60
            )
        fields = "name,url,platforms,first_release_date,rating,aggregated_rating,genres.name,themes.name,game_modes.name,player_perspectives.name,franchises.name,summary,cover.image_id,external_games.uid,external_games.url,external_games.external_game_source.name,multiplayer_modes.platform,multiplayer_modes.offlinemax,multiplayer_modes.offlinecoopmax"
        query = (
            "search "
            + json.dumps(row["title"])
            + "; fields "
            + fields
            + "; where platforms = (6); limit 50;"
        )

        def query_games():
            return self.get(
                "https://api.igdb.com/v4/games",
                data=query.encode(),
                content_type="text/plain",
                headers={
                    "Client-ID": self.options["igdb_client_id"],
                    "Authorization": "Bearer " + self.token,
                },
            )

        try:
            items = query_games()
        except FetchError as exc:
            if exc.status != 401 or not _renew:
                raise
            self.token = None
            return self.igdb(row, False)
        item = exact_match(items, row, pc=True)
        modes = [m for m in item.get("multiplayer_modes", []) if m.get("platform") == 6]

        def maximum(key):
            values = [number(m.get(key)) for m in modes]
            values = [v for v in values if v is not None]
            return max(values) if values else None

        patch = {
            "igdb_rating": number(item.get("rating"), 100),
            "igdb_critic_rating": number(item.get("aggregated_rating"), 100),
            "igdb_genres": names(item.get("genres")),
            "igdb_themes": names(item.get("themes")),
            "igdb_modes": names(item.get("game_modes")),
            "igdb_perspectives": names(item.get("player_perspectives")),
            "igdb_franchises": names(item.get("franchises")),
            "igdb_summary": item.get("summary"),
            "igdb_local_players": maximum("offlinemax"),
            "igdb_local_coop": maximum("offlinecoopmax"),
            "igdb_url": https(item.get("url")),
        }
        ident = (item.get("cover") or {}).get("image_id")
        if isinstance(ident, str) and re.fullmatch(r"[a-zA-Z0-9_]+", ident):
            patch["igdb_cover"] = (
                "https://images.igdb.com/igdb/image/upload/t_cover_big/"
                + ident
                + ".jpg"
            )
        ids = set()
        for external in item.get("external_games", []):
            url = external.get("url", "")
            matched = re.match(
                r"https?://store\.steampowered\.com/app/(\d+)(?:/|$)", url
            )
            source = (external.get("external_game_source") or {}).get("name", "")
            if matched:
                ids.add(matched[1])
            elif (
                source.casefold() == "steam" and str(external.get("uid", "")).isdigit()
            ):
                ids.add(str(external["uid"]))
        if row.get("store") == "Steam" and ids and str(row["id"]) not in ids:
            raise ValueError(
                "IGDB Steam mapping conflicts with the library app ID; no data was attached."
            )
        return patch, {
            "id": item["id"],
            "steam_id": next(iter(ids)) if len(ids) == 1 else None,
            "matched_title": row["title"],
        }

    def protondb(self, row):
        ident = steam_id(row)
        if not ident:
            raise ValueError(
                "No verified Steam app ID. Fetch IGDB first, or use the Steam library entry."
            )
        item = self.get(
            "https://www.protondb.com/api/v1/reports/summaries/" + ident + ".json"
        )
        tiers = {"borked", "bronze", "silver", "gold", "platinum", "native", "pending"}
        if not isinstance(item, dict) or item.get("tier") not in tiers:
            raise ValueError("No recognized ProtonDB summary was returned.")
        return {
            "proton_tier": item["tier"],
            "proton_trending": item.get("trendingTier")
            if item.get("trendingTier") in tiers
            else None,
            "proton_confidence": item.get("confidence"),
            "proton_reports": number(item.get("total")),
            "proton_url": "https://www.protondb.com/app/" + ident,
        }, {"steam_id": ident}

    def steamgriddb(self, row):
        base = "https://www.steamgriddb.com/api/v2"
        headers = {"Authorization": "Bearer " + self.options["sgdb_api_key"]}
        ident = steam_id(row)
        if ident:
            response = self.get(base + "/games/steam/" + ident, headers=headers)
            item = response.get("data") if isinstance(response, dict) else None
            if not isinstance(item, dict):
                raise ValueError("SteamGridDB has no game mapped to this Steam ID.")
        else:
            response = self.get(
                base + "/search/autocomplete/" + quote(row["title"], safe=""),
                headers=headers,
            )
            item = exact_match(response.get("data"), row)
        ident = item.get("id")
        if type(ident) != int or ident <= 0:
            raise ValueError("SteamGridDB returned no valid game ID.")
        patch = {"sgdb_url": "https://www.steamgriddb.com/game/" + str(ident)}
        artists = []
        credits = {}
        for endpoint, field in [
            ("grids", "grid"),
            ("heroes", "hero"),
            ("logos", "logo"),
            ("icons", "icon"),
        ]:
            if self.cancel.wait(0.3):
                raise Cancelled()
            query = (
                "?dimensions=600x900&types=static"
                if endpoint == "grids"
                else "?types=static"
            )
            query += "&nsfw=false&humor=false&epilepsy=false&limit=20"
            try:
                response = self.get(
                    base + "/" + endpoint + "/game/" + str(ident) + query,
                    headers=headers,
                )
            except FetchError as exc:
                if exc.status == 404:
                    continue
                raise
            if not response.get("success"):
                raise FetchError("SteamGridDB could not return artwork.")
            # Keep artist and asset-page attribution with each selected image.
            for art in response.get("data") or []:
                if (
                    not isinstance(art, dict)
                    or art.get("nsfw")
                    or art.get("humor")
                    or art.get("epilepsy")
                ):
                    continue
                url = https(art.get("url"))
                if not url:
                    continue
                patch["sgdb_" + field] = url
                author = art.get("author") or {}
                if author.get("name"):
                    artists.append(str(author["name"]))
                credits[field] = {
                    "artist": author.get("name"),
                    "profile": https(author.get("url")),
                    "id": art.get("id"),
                }
                break
        patch["sgdb_artists"] = ", ".join(dict.fromkeys(artists))
        return patch, {"id": ident, "credits": credits}

    def opencritic(self, row):
        if self.quota:
            self.quota.preflight_game()
        base = "https://opencritic-api.p.rapidapi.com"
        headers = {
            "X-RapidAPI-Key": self.options["opencritic_api_key"],
            "X-RapidAPI-Host": "opencritic-api.p.rapidapi.com",
        }
        items = self.get(
            base + "/game/search?" + urlencode({"criteria": row["title"]}),
            headers=headers,
        )
        item = exact_match(items, row)
        ident = item.get("id")
        if type(ident) != int or ident <= 0:
            raise ValueError("OpenCritic returned no valid game ID.")
        if self.cancel.wait(0.5):
            raise Cancelled()
        detail = self.get(base + "/game/" + str(ident), headers=headers)
        if (
            not isinstance(detail, dict)
            or detail.get("id") != ident
            or title_key(detail.get("name", "")) != title_key(row["title"])
        ):
            raise ValueError("OpenCritic details did not match the selected game.")
        return {
            "oc_score": number(detail.get("topCriticScore"), 100),
            "oc_recommended": number(detail.get("percentRecommended"), 100),
            "oc_tier": detail.get("tier"),
            "oc_reviews": number(detail.get("numReviews")),
            "oc_url": "https://opencritic.com/game/" + str(ident),
        }, {"id": ident, "scope": "Combined platforms; not a PC-only score"}


def missing_credentials(source, options):
    required = {
        "IGDB": ["igdb_client_id", "igdb_client_secret"],
        "SteamGridDB": ["sgdb_api_key"],
        "OpenCritic": ["opencritic_api_key"],
    }
    return any(
        not isinstance(options.get(key), str) or not options[key].strip()
        for key in required.get(source, [])
    )


def run_extra(db, options, cancel, progress, changed, call=network, rows=None, force=False):
    selected_rows = rows
    clients = Clients(options, cancel, call)
    now = datetime.now(timezone.utc)
    events = []
    selected = [s for s in SOURCES if options.get("metadata_" + s, True)]
    if not selected:
        return [
            LogEntry(
                "No extra sources are enabled. Enable them in Sources.",
                Severity.WARNING,
            )
        ]
    for source in selected:
        if cancel.is_set():
            raise Cancelled()
        if missing_credentials(source, options):
            events.append(
                LogEntry(
                    source + ": add API credentials in Sources before fetching.",
                    Severity.WARNING,
                    source,
                )
            )
            continue
        with db.connect() as connection:
            pause = connection.execute(
                "SELECT payload FROM local_state WHERE name=?",
                ("extra_pause|" + source,),
            ).fetchone()
        credential_keys = {
            "IGDB": ("igdb_client_id", "igdb_client_secret"),
            "SteamGridDB": ("sgdb_api_key",),
            "OpenCritic": ("opencritic_api_key",),
        }.get(source, ())
        fingerprint = hashlib.sha256(
            json.dumps([options.get(k, "") for k in credential_keys]).encode()
        ).hexdigest()
        paused = json.loads(pause[0]) if pause else {}
        if (
            isinstance(paused, dict)
            and paused.get("credentials") == fingerprint
            and datetime.fromisoformat(paused["until"]) > now
        ):
            events.append(
                LogEntry(
                    source
                    + ": waiting after a previous service error; try again later.",
                    Severity.WARNING,
                    source,
                )
            )
            continue
        clients.source_start = clients.requests
        clients.limit = request_limit(options, source)
        counts = Counter()
        cache = {}
        failures = 0
        rows = [r for r in (db.rows() if selected_rows is None else selected_rows) if r.get("active")]
        for i, row in enumerate(rows):
            if cancel.is_set():
                raise Cancelled()
            lookup_title = (row.get("raw") or {}).get("metadata_matches", {}).get(source) or row["title"]
            key = (
                steam_id(row) if source in ("ProtonDB", "SteamGridDB") else None,
                title_key(lookup_title),
                str(row.get("release")),
                fingerprint,
            )
            previous = (row.get("raw") or {}).get("extra_metadata", {}).get(source, {})
            try:
                if (
                    not force
                    and previous.get("title") == row["title"]
                    and previous.get("lookup") == list(key)
                    and datetime.fromisoformat(previous["retry_at"]) > now
                ):
                    counts["cached"] += 1
                    if source == "OpenCritic" and clients.quota:
                        clients.quota.completed(row)
                    continue
            except (KeyError, ValueError, TypeError):
                pass
            def request_progress():
                used = clients.requests - clients.source_start
                cap = str(clients.limit) if clients.limit else "no local cap"
                progress(f"{source} · game {i + 1}/{len(rows)} · {used} requests / {cap} · {row['title']}")
            clients.request_progress = request_progress
            request_progress()
            requests_before = clients.requests
            cached = key in cache
            patch = {}
            details = {}
            outcome = "Saved"
            wait = 7
            stop = False
            try:
                if cached:
                    value = cache[key]
                    if isinstance(value, Exception):
                        raise value
                    patch, details = value
                    patch = patch.copy()
                else:
                    patch, details = getattr(clients, source.lower())({**row, "title": lookup_title})
                    if source == "IGDB":
                        details["lookup_title"] = lookup_title
                        details["matched_title"] = row["title"]
                    cache[key] = (patch, details)
                failures = 0
                counts["saved"] += 1
                if source == "OpenCritic":
                    outcome = "Saved; combined platform scores"
            except Cancelled:
                raise
            except QuotaPaused as exc:
                if cancel.is_set():
                    raise Cancelled()
                counts["quota_paused"] = 1
                if clients.quota:
                    clients.quota.enqueue(rows[i:])
                events.append(LogEntry(str(exc) + " Remaining games are queued; see OpenCritic quota for details.", Severity.WARNING, source))
                break
            except BudgetExhausted:
                counts["budget_reached"] = 1
                if source == "OpenCritic" and clients.quota:
                    clients.quota.enqueue(rows[i:], for_budget=True)
                events.append(LogEntry(
                    f"{source}: stopped at the local cap of {clients.limit} HTTP requests. The unfinished game and remaining entries were not marked unavailable. Other sources can continue. OpenCritic can queue another batch when reported quota permits; other sources need another fetch.",
                    Severity.WARNING, source))
                break
            except (FetchError, ValueError, KeyError, TypeError, AttributeError) as exc:
                cache[key] = exc
                counts["unavailable"] += 1
                wait = 1
                failures = failures + 1 if isinstance(exc, FetchError) else 0
                outcome = (
                    str(exc)
                    if isinstance(exc, (FetchError, ValueError))
                    else "Unexpected response format; existing values kept."
                )
                stop = (
                    isinstance(exc, FetchError) and exc.status in (401, 403, 429)
                ) or (isinstance(exc, FetchError) and failures >= 3)
                if stop:
                    delay = max(
                        getattr(exc, "retry_after", 0),
                        3600 if getattr(exc, "status", None) == 429 else 86400,
                    )
                    with db.connect() as connection:
                        connection.execute(
                            "INSERT OR REPLACE INTO local_state VALUES (?,?)",
                            (
                                "extra_pause|" + source,
                                json.dumps(
                                    {
                                        "until": (
                                            now + timedelta(seconds=delay)
                                        ).isoformat(),
                                        "credentials": fingerprint,
                                    }
                                ),
                            ),
                        )
            prefix = source.lower()
            patch = {k: v for k, v in patch.items() if v is not None and v != ""}
            if source in ("IGDB", "SteamGridDB") and not row.get("cover"):
                cover = patch.get("sgdb_grid") or patch.get("igdb_cover")
                if cover:
                    patch["cover"] = cover
            state = {
                **previous,
                **details,
                "title": row["title"],
                "lookup_title": lookup_title,
                "lookup": list(key),
                "outcome": outcome,
                "retry_at": (now + timedelta(days=wait)).isoformat(),
            }
            raw = {**(row.get("raw") or {}).get("extra_metadata", {}), source: state}
            patch.update(
                store=row["store"],
                id=row["id"],
                title=row["title"],
                raw={"extra_metadata": raw},
                **{
                    prefix + "_checked": now.isoformat(timespec="seconds"),
                    prefix + "_status": outcome,
                },
            )
            db.save([patch])
            if source == "OpenCritic" and clients.quota:
                clients.quota.completed(row)
            if i % 10 == 0:
                changed()
            if stop:
                events.append(
                    LogEntry(
                        source
                        + ": requests paused after a service error. Existing values were kept.",
                        Severity.WARNING,
                        source,
                    )
                )
                break
            if clients.requests > requests_before and cancel.wait(1):
                raise Cancelled()
        changed()
        events.append(
            LogEntry(
                source
                + ": "
                + ", ".join(
                    f"{counts[k]} {k}" for k in ("saved", "cached", "unavailable")
                )
                + f" · {clients.requests - clients.source_start} HTTP requests"
                + (f" / {clients.limit} allowed this fetch" if clients.limit else " (no local cap)"),
                Severity.WARNING if counts["unavailable"] or counts["budget_reached"] or counts["quota_paused"] else Severity.SUCCESS,
                source,
            )
        )
    return events
