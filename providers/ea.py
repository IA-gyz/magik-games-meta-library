"""Ea library and metadata protocol implementation."""

from core import game
from connector_io import FetchError, Cancelled

EA_ENDPOINT = "https://service-aggregation-layer.juno.ea.com/graphql"


def library_query(options, cancel, progress, *, io):
    from web_sessions import renew_ea, SessionError, valid_token

    automatic = bool(options.get("ea_session_enabled"))
    renewed = False
    try:
        token = renew_ea(options) if automatic else options.get("ea_token", "").strip()
        if not token:
            token = io.token_file(options.get("ea_auth", ""))["access_token"]
        if not valid_token(token):
            raise SessionError(
                "EA token format is invalid. Connect EA or paste only the access_token value."
            )
    except SessionError as exc:
        raise FetchError(str(exc), category="http", status=401) from None

    def query(q, variables):
        nonlocal token, renewed

        def run():
            h = {
                k: "Bearer " + token if k == "Authorization" else token
                for k in ["Authorization", "AuthToken", "X-AuthToken"]
            }
            response = io.request(
                EA_ENDPOINT, headers=h, body={"query": q, "variables": variables}
            )
            errors = response.get("errors") or []
            codes = {
                str((e.get("extensions") or {}).get("code", "")).upper()
                for e in errors
                if isinstance(e, dict)
            }
            if codes & {
                "UNAUTHENTICATED",
                "AUTHENTICATION_ERROR",
                "INVALID_ACCESS_TOKEN",
                "TOKEN_EXPIRED",
            }:
                raise FetchError(
                    "EA authorization rejected", category="http", status=401
                )
            if errors:
                raise FetchError(
                    "EA GraphQL query rejected. Reconnect EA if your session is no longer accepted."
                )
            return response["data"]

        try:
            return run()
        except FetchError as exc:
            if exc.status != 401 or not automatic or renewed:
                raise
            if cancel.is_set():
                raise Cancelled()
            renewed = True
            progress("EA: renewing the saved session and retrying once…")
            try:
                token = renew_ea(options, force=True)
            except SessionError as error:
                raise FetchError(str(error), category="http", status=401) from None
            return run()

    return query, lambda: token


def ea(options, cancel, progress, *, io):
    query, current_token = library_query(options, cancel, progress, io=io)
    q = 'query Library($next: String) { me { ownedGameProducts(locale:"DEFAULT", entitlementEnabled:true, storefronts:[EA], type:[DIGITAL_FULL_GAME,PACKAGED_FULL_GAME], platforms:[PC], paging:{limit:100,next:$next}) { next items { originOfferId product { baseItem { gameType } } } } } }'
    entries = []
    cursor = None
    seen = set()
    while True:
        if cancel.is_set():
            raise Cancelled()
        page = query(q, {"next": cursor})["me"]["ownedGameProducts"]
        entries += page["items"]
        cursor = page.get("next")
        if not cursor:
            break
        if cursor in seen:
            raise FetchError("EA returned a repeated page token")
        seen.add(cursor)
    offers = list(
        dict.fromkeys((e["originOfferId"] for e in entries if e.get("originOfferId")))
    )
    rows = []
    for offset in range(0, len(offers), 50):
        if cancel.is_set():
            raise Cancelled()
        progress(f"EA: fetching products {offset + 1}–{min(offset + 50, len(offers))}")
        ids = offers[offset : offset + 50]
        details = query(
            'query Products($ids:[String!]!) { gameProducts(offerIds:$ids,locale:"DEFAULT") { items { id originOfferId gameSlug baseItem { title gameType keyArt { largestImage { path } } packArt { largestImage { path } } } } } }',
            {"ids": ids},
        )
        products = {
            p.get("originOfferId"): p
            for p in (details.get("gameProducts") or {}).get("items", []) or []
        }
        for ident in ids:
            p = products.get(ident) or {}
            b = p.get("baseItem") or {}
            ent = [e for e in entries if e.get("originOfferId") == ident]
            rows.append(
                game(
                    "EA",
                    ident,
                    b.get("title") or ident,
                    {"entitlements": ent, "product": p},
                    type=b.get("gameType"),
                    cover=((b.get("packArt") or {}).get("largestImage") or {}).get(
                        "path"
                    ),
                    source="EA account API (experimental)",
                )
            )
    from acquisition import ea_dates, optional_dates

    return optional_dates(
        "EA",
        rows,
        progress,
        lambda: ea_dates(rows, current_token(), cancel, progress, io.request),
    )
