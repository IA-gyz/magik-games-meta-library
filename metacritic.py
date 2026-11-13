"""Conservative title-based reads of public Metacritic game pages. No private API."""

import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from connector_io import Cancelled, FetchError
from contracts import LogEntry, Severity

BASE = "https://www.metacritic.com"
FIELDS = [
    "mc_user_score",
    "mc_critic_count",
    "mc_user_count",
    "mc_sentiment",
    "mc_rating",
    "mc_genre",
    "mc_release",
    "mc_url",
    "mc_checked",
    "mc_status",
]


def title_key(title):
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", title.casefold().replace("™", "").replace("®", ""))


def title_slug(title):
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "__NUXT_DATA__":
            self.capture = True
            self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            self.capture = False
            self.documents.append(json.loads("".join(self.parts)))


def parse_page(html, title, slug, release=None):
    parser = Scripts()
    parser.feed(html)
    for values in parser.documents:
        if not isinstance(values, list):
            continue

        def expand(value, depth=0):
            if depth > 18:
                return None
            if isinstance(value, int) and not isinstance(value, bool):
                if value < 0 or value >= len(values):
                    return None
                return expand_value(values[value], depth + 1)
            return value

        def expand_value(value, depth):
            if isinstance(value, dict):
                return {k: expand(v, depth) for k, v in value.items()}
            if isinstance(value, list):
                return [expand(v, depth) for v in value]
            return value

        products = []
        for item in values:
            if isinstance(item, dict) and all(
                k in item for k in ("title", "slug", "platforms", "production")
            ):
                product = expand_value(item, 0)
                if product.get("slug") == slug and title_key(
                    product.get("title", "")
                ) == title_key(title):
                    products.append(product)
        if len(products) != 1:
            continue
        product = products[0]
        platforms = [
            p
            for p in product.get("platforms", [])
            if isinstance(p, dict) and p.get("name") == "PC"
        ]
        if len(platforms) != 1:
            raise ValueError("No verified PC entry; console scores were not used.")
        pc = platforms[0]
        # Do not silently match a same-name re-release from a different year.
        if release and re.match(r"^\d{4}", str(release)) and pc.get("releaseDate"):
            if abs(int(str(release)[:4]) - int(pc["releaseDate"][:4])) > 1:
                raise ValueError(
                    "Release year differs; this title needs a manual match."
                )
        critic = pc.get("criticScoreSummary") or {}
        score = critic.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= score <= 100
        ):
            score = None
        result = {
            "score": score,
            "mc_critic_count": critic.get("reviewCount"),
            "mc_sentiment": critic.get("sentiment"),
            "mc_rating": product.get("rating"),
            "mc_release": pc.get("releaseDate"),
            "mc_url": BASE + "/game/" + slug + "/?platform=pc",
            "mc_genre": ", ".join(
                g.get("name", "")
                for g in product.get("genres", [])
                if isinstance(g, dict)
            ),
        }
        # User scores must explicitly identify this game's PC page as well.
        for item in values:
            if not isinstance(item, dict) or not all(
                k in item for k in ("max", "score", "reviewCount", "url")
            ):
                continue
            summary = expand_value(item, 0)
            if (
                summary.get("max") == 10
                and summary.get("url") == "/game/" + slug + "/user-reviews/?platform=pc"
            ):
                user = summary.get("score")
                if (
                    isinstance(user, (int, float))
                    and not isinstance(user, bool)
                    and 0 <= user <= 10
                ):
                    result.update(
                        mc_user_score=user, mc_user_count=summary.get("reviewCount")
                    )
        return result
    raise ValueError(
        "No exact title match in the page data. Editions and alternate titles are not guessed."
    )


def fetch_page(url):
    request = Request(
        url, headers={"User-Agent": "MagikGamesLibrary/0.30", "Accept": "text/html"}
    )
    try:
        with urlopen(request, timeout=25) as response:
            if not response.url.startswith(BASE + "/game/"):
                raise FetchError("Metacritic redirected away from a game page.")
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise FetchError("Metacritic page exceeded the size limit.")
            return body.decode("utf-8")
    except HTTPError as exc:
        raise FetchError(
            "Metacritic returned HTTP " + str(exc.code), status=exc.code
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise FetchError("Metacritic could not be reached. Try again later.") from exc


def run_metacritic(db, cancel, progress, changed, fetch=fetch_page, rows=None, force=False):
    now = datetime.now(timezone.utc)
    cache = {}
    saved = skipped = failed = 0
    with db.connect() as connection:
        paused = connection.execute(
            "SELECT payload FROM local_state WHERE name='metacritic_pause'"
        ).fetchone()
    if paused and datetime.fromisoformat(json.loads(paused[0])) > now:
        return [
            LogEntry(
                "Metacritic is waiting after an access refusal or request limit. Try again tomorrow.",
                Severity.WARNING,
            )
        ]
    rows = [r for r in (db.rows() if rows is None else rows) if r.get("active") and r.get("title")]
    for i, row in enumerate(rows):
        if cancel.is_set():
            raise Cancelled()
        previous = (row.get("raw") or {}).get("metacritic", {})
        lookup_title = (row.get("raw") or {}).get("metadata_matches", {}).get("Metacritic") or row["title"]
        try:
            if (
                not force
                and previous.get("title") == row["title"]
                and previous.get("lookup_title", row["title"]) == lookup_title
                and datetime.fromisoformat(previous["retry_at"]) > now
            ):
                skipped += 1
                continue
        except (KeyError, ValueError, TypeError):
            pass
        title = row["title"]
        slug = title_slug(lookup_title)
        key = (title_key(lookup_title), str(row.get("release")))
        progress(f"Metacritic {i + 1}/{len(rows)} · {title}")
        cached = key in cache
        try:
            if not slug:
                raise ValueError("Title has no usable page name.")
            if cached:
                data = cache[key]
                if isinstance(data, Exception):
                    raise data
            else:
                data = parse_page(
                    fetch(BASE + "/game/" + slug + "/user-reviews/?platform=pc"),
                    lookup_title,
                    slug,
                    row.get("release"),
                )
                cache[key] = data
            outcome = (
                "PC match verified"
                if data.get("score") is not None
                else "PC match verified; no critic score published"
            )
            patch = {k: v for k, v in data.items() if v is not None and v != ""}
            saved += 1
            delay = 7
        except (FetchError, ValueError, json.JSONDecodeError) as exc:
            cache[key] = exc
            data = previous.get("data") or {}
            patch = {}
            outcome = str(exc)
            failed += 1
            delay = 1
            if isinstance(exc, FetchError) and exc.status in (401, 403, 429):
                progress(
                    "Metacritic paused: access was refused or requests were limited. Existing scores were kept."
                )
                with db.connect() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO local_state VALUES (?,?)",
                        (
                            "metacritic_pause",
                            json.dumps((now + timedelta(days=1)).isoformat()),
                        ),
                    )
                break
        patch.update(
            store=row["store"],
            id=row["id"],
            title=title,
            mc_status=outcome,
            mc_checked=now.isoformat(timespec="seconds"),
        )
        patch["raw"] = {
            "metacritic": {
                "title": title,
                "lookup_title": lookup_title,
                "retry_at": (now + timedelta(days=delay)).isoformat(),
                "outcome": outcome,
                "data": data,
                "platform": "PC" if data else None,
            }
        }
        db.save([patch])
        changed()
        if not cached and cancel.wait(3):
            raise Cancelled()
    return [
        LogEntry(
            f"Metacritic: {saved} verified PC entries saved, {skipped} cached entries skipped, {failed} unmatched or unavailable. Existing data was kept for failed matches.",
            Severity.WARNING if failed else Severity.SUCCESS,
        )
    ]
