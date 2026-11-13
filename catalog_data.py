"""Catalog fields, normalization and acquisition-date handling. No storage or Qt."""

import re
from datetime import datetime, timezone

from provider_registry import PROVIDERS

STORES = [spec.name for spec in PROVIDERS]
FIELDS = [
    "store",
    "id",
    "title",
    "type",
    "genres",
    "developers",
    "publishers",
    "release",
    "platforms",
    "languages",
    "controller",
    "score",
    "playtime",
    "last_played",
    "description",
    "cover",
    "url",
    "source",
    "updated",
    "active",
    "installation_status",
    "launch_provider",
    "installation_path",
    "date_added",
    "date_added_source",
    "mc_user_score", "mc_critic_count", "mc_user_count", "mc_sentiment",
    "mc_rating", "mc_genre", "mc_release", "mc_url", "mc_checked", "mc_status",
]
from extra_schema import FIELDS as EXTRA_FIELDS
FIELDS += EXTRA_FIELDS
FIELDS += ["favorite", "personal_tags"]

SECRET = re.compile(
    r"(^|_)(access_token|refresh_token|authorization|password|cookie|secret|api_key|certificate)($|_)",
    re.I,
)


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not SECRET.search(k)}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def words(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return ", ".join(
            str(k) if isinstance(v, bool) else str(v)
            for k, v in value.items()
            if v is not False and v is not None
        )
    if isinstance(value, list):
        return ", ".join(
            str(
                v.get("description")
                or v.get("name")
                or v.get("title")
                or v.get("id")
                or ""
            )
            if isinstance(v, dict)
            else str(v)
            for v in value
        )
    return str(value)


def acquisition_date(value):
    """UTC timestamp or ISO calendar date; never substitute a catalog release date."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and value.isdigit()
        ):
            number = float(value)
            if number > 100000000000:
                number /= 1000
            if number <= 0:
                return None
            result = datetime.fromtimestamp(number, timezone.utc)
        else:
            text = str(value).strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                day = datetime.strptime(text, "%Y-%m-%d").date()
                return (
                    day.isoformat()
                    if day <= datetime.now(timezone.utc).date()
                    else None
                )
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if result.tzinfo is None:
                return None
        if result.year < 1970 or result > datetime.now(timezone.utc):
            return None
        return result.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def account_added(store, raw):
    # Only explicit acquisition fields on account objects, not product metadata dates.
    record = raw.get("acquisition_record") or {}
    if acquisition_date(record.get("date")):
        return acquisition_date(record["date"]), record.get(
            "source"
        ) or "Account acquisition record"
    sources = []
    if store == "GOG":
        sources = [raw.get("account_shelf") or {}]
    elif store == "EA":
        sources = raw.get("entitlements") or []
    elif store == "Epic":
        sources = [
            raw,
            raw.get("acquisition_entitlement") or {},
            raw.get("entitlement") or {},
        ]
    elif store == "Amazon":
        result = acquisition_date(raw.get("entitlementDateFromEpoch"))
        if result:
            return result, "Amazon entitlementDateFromEpoch"
        sources = [raw]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ["datePurchased", "purchaseDate", "acquisitionDate", "grantDate"]:
            result = acquisition_date(source.get(key))
            if result:
                return result, store + " account: " + key
    return None, None


def game(store, ident, title, raw, **values):
    if ident is None or not str(ident).strip() or not title:
        raise ValueError("Game requires a stable ID and title")
    row = dict.fromkeys(FIELDS, None)
    row.update(
        store=store,
        id=str(ident),
        title=title,
        source="Account API",
        active=True,
        updated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        raw=clean(raw),
    )
    added, origin = account_added(store, raw)
    row.update(date_added=added, date_added_source=origin)
    row.update(values)
    row["date_added"] = acquisition_date(row.get("date_added"))
    from personal_library import annotations
    row.update(annotations(row))
    for key in ["genres", "developers", "publishers", "platforms", "languages"]:
        row[key] = words(row[key])
    return row


def normalize(store, data):
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of games")
    rows = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each game must be an object")
        if "raw" in item and "title" in item and "id" in item:
            row = game(
                store,
                item["id"],
                item["title"],
                item["raw"],
                **{
                    k: v
                    for k, v in item.items()
                    if k in FIELDS and k not in ["store", "id", "title"]
                },
            )
            rows.append(row)
            continue
        if store == "Epic":
            m = item.get("metadata") or {}
            cats = m.get("categories") or []
            releases = m.get("releaseInfo") or []
            release = next(
                (
                    v.get("date") or v.get("releaseDate")
                    for v in releases
                    if v.get("date") or v.get("releaseDate")
                ),
                None,
            )
            platforms = list((item.get("asset_infos") or {}).keys()) or list(
                dict.fromkeys(p for v in releases for p in v.get("platform", []) or [])
            )
            row = game(
                store,
                item.get("app_name"),
                item.get("app_title"),
                item,
                type="DLC"
                if m.get("mainGameItem") or any("dlc" in str(c).lower() for c in cats)
                else "Game",
                developers=m.get("developer"),
                publishers=m.get("publisher"),
                description=m.get("description"),
                release=m.get("releaseDate") or release,
                platforms=platforms,
            )
            images = m.get("keyImages") or []
            row["cover"] = next(
                (i.get("url") for i in images if "tall" in i.get("type", "").lower()),
                next((i.get("url") for i in images), None),
            )
            rows.append(row)
            for dlc in item.get("dlcs") or []:
                child = normalize(store, [dlc])[0]
                child["type"] = "DLC"
                rows.append(child)
        elif store == "Amazon":
            p = item.get("product") or item
            detail = (p.get("productDetail") or {}).get("details") or {}
            rows.append(
                game(
                    store,
                    p.get("id") or item.get("id"),
                    p.get("title"),
                    item,
                    type="Game",
                    genres=detail.get("genres"),
                    developers=detail.get("developer"),
                    publishers=detail.get("publisher"),
                    description=detail.get("description"),
                    release=detail.get("releaseDate"),
                    languages=detail.get("languages"),
                )
            )
        else:
            rows.append(
                game(
                    store,
                    item.get("id") or item.get("offerId") or item.get("app_name"),
                    item.get("title") or item.get("name") or item.get("app_title"),
                    item,
                    **{
                        k: item[k]
                        for k in FIELDS
                        if k in item and k not in ["store", "id", "title"]
                    },
                )
            )
    return rows
