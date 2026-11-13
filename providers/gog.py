"""Gog library and metadata protocol implementation."""

import urllib.parse
from pathlib import Path
from core import game
from connector_io import FetchError, Cancelled


def gog_shelf(headers, cancel, progress, *, io):
    """Read authenticated account shelf, including hidden games and movies."""
    products = {}
    warnings = []
    for media in [1, 2]:
        for hidden in [0, 1]:
            page = 1
            while True:
                if cancel.is_set():
                    raise Cancelled()
                progress(
                    f"GOG: account titles, media {media}, hidden {hidden}, page {page}"
                )
                try:
                    data = io.request(
                        "https://embed.gog.com/account/getFilteredProducts",
                        {
                            "mediaType": media,
                            "hiddenFlag": hidden,
                            "sortBy": "title",
                            "page": page,
                        },
                        headers=headers,
                    )
                    if (
                        not isinstance(data, dict)
                        or not isinstance(data.get("products"), list)
                        or "totalPages" not in data
                    ):
                        raise FetchError(
                            "GOG account shelf returned an unexpected response"
                        )
                    if int(data.get("page", page)) != page:
                        raise FetchError("GOG account shelf repeated a page")
                    for product in data["products"]:
                        if isinstance(product, dict) and product.get("id") is not None:
                            products[str(product["id"])] = product
                    total = int(data["totalPages"])
                    if page >= total:
                        break
                    if page >= 1000:
                        raise FetchError("GOG account shelf exceeded pagination limit")
                    page += 1
                except FetchError as exc:
                    warnings.append(f"media {media}, hidden {hidden}: {exc}")
                    if exc.category in ["rate_limit", "temporary"] or exc.status in [
                        401,
                        403,
                    ]:
                        return (products, warnings)
                    break
                except (ValueError, TypeError):
                    warnings.append(
                        f"media {media}, hidden {hidden}: invalid shelf pagination"
                    )
                    break
    return (products, warnings)


def authentication_headers(options, *, io):
    creds = io.token_file(options.get("gog_auth", ""))
    if creds.get("refresh_token"):
        creds = io.request(
            "https://auth.gog.com/token",
            {
                "client_id": "46899977096215655",
                "client_secret": "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9",
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
            },
        )
    return {"Authorization": "Bearer " + creds["access_token"]}


def gog(options, cancel, progress, *, io):
    headers = authentication_headers(options, io=io)
    data = io.request("https://embed.gog.com/user/data/games", headers=headers)
    if "owned" not in data:
        raise FetchError("GOG did not return an owned library")
    shelf, warnings = gog_shelf(headers, cancel, progress, io=io)
    ids = list(dict.fromkeys([str(i) for i in data["owned"]] + list(shelf)))
    rows = []
    for ident in ids:
        item = shelf.get(ident, {})
        image = item.get("image")
        url = item.get("url")
        if image and image.startswith("//"):
            image = "https:" + image
        if image and (not Path(urllib.parse.urlsplit(image).path).suffix):
            image += "_product_630.jpg"
        if url and url.startswith("/"):
            url = "https://www.gog.com" + url
        release = item.get("releaseDate")
        if isinstance(release, dict):
            release = release.get("date")
        raw = {"owned_product_id": ident}
        if item:
            raw["account_shelf"] = item
        if warnings:
            raw["account_shelf_warnings"] = warnings
        rows.append(
            game(
                "GOG",
                ident,
                item.get("title") or f"GOG product {ident}",
                raw,
                type="Movie" if item.get("isMovie") else "Game" if item else None,
                genres=item.get("category"),
                platforms=item.get("worksOn"),
                release=release,
                cover=image,
                url=url,
                source="GOG account shelf" if item else "GOG account API",
            )
        )
    from acquisition import gog_dates, optional_dates

    return optional_dates(
        "GOG",
        rows,
        progress,
        lambda: gog_dates(rows, headers, cancel, progress, io.request),
    )


def gog_details(row, *, io):
    d = row["raw"].get("product") or io.request(
        "https://api.gog.com/products/" + urllib.parse.quote(row["id"], safe=""),
        {
            "expand": "description,downloads,expanded_dlcs,screenshots,videos,related_products",
            "locale": "en-US",
        },
    )
    rich = row["raw"].get("v2") or {}
    warning = None
    try:
        rich = rich or io.request(
            "https://api.gog.com/v2/games/" + urllib.parse.quote(row["id"], safe=""),
            {"locale": "en-US"},
        )
    except FetchError as exc:
        warning = exc
    embedded = rich.get("_embedded") or {}
    product = embedded.get("product") or {}
    row = game(
        "GOG",
        row["id"],
        d.get("title") or row["title"],
        {**row["raw"], "product": d, "v2": rich},
        type=product.get("category") or d.get("game_type"),
        genres=embedded.get("tags") or d.get("genres"),
        developers=embedded.get("developers"),
        publishers=embedded.get("publishers"),
        release=product.get("globalReleaseDate") or d.get("release_date"),
        platforms=[
            x["operatingSystem"]["name"]
            for x in embedded.get("supportedOperatingSystems", [])
        ]
        or d.get("content_system_compatibility"),
        languages=d.get("languages"),
        description=(d.get("description") or {}).get("full")
        if isinstance(d.get("description"), dict)
        else d.get("description"),
        url=(d.get("links") or {}).get("product_card"),
        source="GOG account + product API",
        active=row.get("active", True),
    )
    image = (d.get("images") or {}).get("logo2x") or (d.get("images") or {}).get("logo")
    row["cover"] = "https:" + image if image and image.startswith("//") else image
    if warning:
        row["_metadata_warning"] = {
            "message": str(warning),
            "category": warning.category,
            "status": warning.status,
        }
    return row
