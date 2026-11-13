"""Small live account checks using the same transports/profiles as library refreshes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import math
from connector_io import ConnectorIO, FetchError, Cancelled, request, helper, token_file
from error_messages import explain_store_error


@dataclass(frozen=True)
class ConnectionResult:
    store: str
    state: str
    message: str
    checked_at: str | None = None
    retry_after: float = 0


class SetupNeeded(ValueError):
    pass


def probe_connection(store, options, cancel, io=None):
    io = io or ConnectorIO(
        partial(request, timeout=10), partial(helper, timeout=45), token_file
    )

    def check_cancel():
        if cancel.is_set():
            raise Cancelled()

    def need(condition, message):
        if not condition:
            raise SetupNeeded(message)

    try:
        check_cancel()
        if store == "Steam":
            key, ident = (
                options.get("steam_key", "").strip(),
                options.get("steam_id", "").strip(),
            )
            need(
                key and ident,
                "Open Sources → Steam and enter your API key and SteamID64 or profile name.",
            )
            if not ident.isdigit():
                data = io.request(
                    "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
                    {"key": key, "vanityurl": ident},
                )
                ident = data.get("response", {}).get("steamid")
                need(
                    ident,
                    "Steam could not find this profile name. Check it in Sources.",
                )
            data = io.request(
                "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
                {
                    "key": key,
                    "steamid": ident,
                    "include_appinfo": 0,
                    "include_played_free_games": 1,
                },
            )
            need(
                "game_count" in data.get("response", {}),
                "Steam did not expose your library. Check Game details privacy, account ID and API key.",
            )
        elif store == "GOG":
            from providers.gog import authentication_headers

            need(
                options.get("gog_auth"),
                "Open Sources → GOG and select your Heroic/GOGDL sign-in file.",
            )
            headers = authentication_headers(options, io=io)
            data = io.request("https://embed.gog.com/user/data/games", headers=headers)
            need(
                isinstance(data, dict) and isinstance(data.get("owned"), list),
                "GOG did not return an account library. Check the sign-in file in Sources.",
            )
        elif store == "Epic":
            from acquisition import profile, read_json

            session = read_json(profile(options) / "user.json", 4 * 1024 * 1024)
            token = session.get("access_token")
            need(
                isinstance(token, str) and token,
                "Sign in with Legendary or Heroic, then check the selected Legendary settings folder in Sources.",
            )
            data = io.request(
                "https://library-service.live.use1a.on.epicgames.com/library/api/public/items",
                params={"includeMetadata": "true"},
                headers={"Authorization": "Bearer " + token},
            )
            need(
                isinstance(data, dict)
                and isinstance(data.get("records"), list)
                and isinstance(data.get("responseMetadata"), dict),
                "Epic did not return an account library. Refresh your Legendary or Heroic sign-in.",
            )
        elif store == "Amazon":
            io.helper(
                options.get("amazon_exe") or "nile",
                ["library", "sync"],
                options.get("amazon_config"),
                "NILE_CONFIG_PATH",
                cancel,
            )
        elif store == "EA":
            from providers.ea import library_query

            query, _current_token = library_query(options, cancel, lambda _: None, io=io)
            data = query(
                'query Library($next: String) { me { ownedGameProducts(locale:"DEFAULT", entitlementEnabled:true, storefronts:[EA], type:[DIGITAL_FULL_GAME,PACKAGED_FULL_GAME], platforms:[PC], paging:{limit:1,next:$next}) { next items { originOfferId } } } }',
                {"next": None},
            )
            need(
                isinstance(
                    data.get("me", {}).get("ownedGameProducts", {}).get("items"), list
                ),
                "EA did not return an account library. Reconnect EA in Sources.",
            )
        else:
            return ConnectionResult(
                store,
                "unsupported",
                "Connection checks are not supported for this store.",
            )
        check_cancel()
        message = "Live account access succeeded. This does not check acquisition history or game launching."
        if store == "Amazon":
            message += " Nile synced its own library cache; this app’s game list was not changed."
        return ConnectionResult(
            store,
            "connected",
            message,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except Cancelled:
        raise
    except SetupNeeded as exc:
        return ConnectionResult(
            store,
            "attention",
            str(exc),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except (ValueError, FileNotFoundError, IsADirectoryError):
        # Known setup text is produced here, not from arbitrary JSON decoder/request exceptions.
        return ConnectionResult(
            store,
            "attention",
            "Check the account fields and sign-in files in Sources. Sign in through Heroic/Legendary/Nile where applicable, then check again.",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except FetchError as exc:
        delay = (
            exc.retry_after
            if isinstance(exc.retry_after, (int, float))
            and math.isfinite(exc.retry_after)
            and exc.retry_after > 0
            else 0
        )
        state = (
            "attention"
            if exc.status in (403, 429) or exc.category == "rate_limit"
            else "failed"
        )
        return ConnectionResult(
            store,
            state,
            explain_store_error(exc, store),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            delay,
        )
    except Exception as exc:
        return ConnectionResult(
            store,
            "failed",
            "The account check could not finish. Check Sources. Technical error: "
            + type(exc).__name__,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
