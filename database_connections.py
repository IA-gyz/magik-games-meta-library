"""Live enrichment access checks and a second row below store indicators."""

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
from connector_io import FetchError, Cancelled
from connection_checks import ConnectionResult
from connection_status import StoreConnections
from extra_metadata import Clients, missing_credentials, network
from metacritic import fetch_page, parse_page
from opencritic_quota import describe as describe_quota, QuotaPaused

SOURCES = ("Metacritic", "IGDB", "ProtonDB", "SteamGridDB", "OpenCritic")


def probe_database(name, options, cancel, call=None, page=None):
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    retry = 0
    try:
        if cancel.is_set():
            raise Cancelled()
        if missing_credentials(name, options):
            return ConnectionResult(
                name,
                "attention",
                "Add the required API credentials in Sources.",
                checked,
            )
        client = Clients(options, cancel, call or network)
        if name == "Metacritic":
            parse_page(
                (page or fetch_page)(
                    "https://www.metacritic.com/game/portal-2/user-reviews/?platform=pc"
                ),
                "Portal 2",
                "portal-2",
            )
        elif name == "ProtonDB":
            client.protondb({"store": "Steam", "id": "620", "title": "Portal 2"})
        elif name == "IGDB":
            # Authenticates and checks API access without fetching library metadata.
            token = client.get(
                "https://id.twitch.tv/oauth2/token",
                data=urlencode(
                    {
                        "client_id": options["igdb_client_id"],
                        "client_secret": options["igdb_client_secret"],
                        "grant_type": "client_credentials",
                    }
                ).encode(),
                content_type="application/x-www-form-urlencoded",
            )
            value = client.get(
                "https://api.igdb.com/v4/games",
                data=b"fields id; limit 1;",
                content_type="text/plain",
                headers={
                    "Client-ID": options["igdb_client_id"],
                    "Authorization": "Bearer " + token["access_token"],
                },
            )
            if not isinstance(value, list):
                raise ValueError()
        elif name == "SteamGridDB":
            value = client.get(
                "https://www.steamgriddb.com/api/v2/games/steam/620",
                headers={"Authorization": "Bearer " + options["sgdb_api_key"]},
            )
            if not isinstance(value, dict) or not value.get("success"):
                raise ValueError()
        elif name == "OpenCritic":
            if client.quota:
                state = client.quota.snapshot()
                import time
                if state.get("checked", 0) > time.time() - 3600:
                    blocked = client.quota.blocked(state, time.time()) or state.get("blocked_until", 0) > time.time() or state.get("verification_pending") or state.get("access_ok") is not True
                    return ConnectionResult(name, "attention" if blocked else "connected", "Using the recent quota observation; no new check request was sent.\n\n" + describe_quota(state), checked, 3600)
            value = client.get(
                "https://opencritic-api.p.rapidapi.com/game/463",
                headers={
                    "X-RapidAPI-Key": options["opencritic_api_key"],
                    "X-RapidAPI-Host": "opencritic-api.p.rapidapi.com",
                },
            )
            if not isinstance(value, dict) or value.get("id") != 463:
                raise ValueError()
            retry = 3600
        if cancel.is_set():
            raise Cancelled()
        return ConnectionResult(
            name,
            "connected",
            "Live data access verified. Checks do not change game records."
            + (
                " This check uses one request from your RapidAPI plan; checks are limited to once per hour." + ("\n\n" + describe_quota(client.quota.snapshot()) if client.quota else "")
                if name == "OpenCritic"
                else ""
            ),
            checked,
            retry,
        )
    except Cancelled:
        raise
    except QuotaPaused as exc:
        return ConnectionResult(name, "attention", str(exc), checked, 300)
    except FetchError as exc:
        retry = max(exc.retry_after, 3600 if name == "OpenCritic" else 300)
        if exc.status in (401, 403):
            message = "Access refused. Check your API key and any required subscription in Sources."
        elif exc.status == 429:
            message = "Request limit reached. Waiting before checking again."
        else:
            message = "The service could not be reached or returned an error. Try again later."
        return ConnectionResult(
            name,
            "attention" if exc.status in (401, 403, 429) else "failed",
            message,
            checked,
            retry,
        )
    except (ValueError, KeyError, TypeError):
        return ConnectionResult(
            name,
            "failed",
            "The response did not contain the expected game data. The service may have changed.",
            checked,
            3600,
        )


class DatabaseConnections(StoreConnections):
    def __init__(self, parent=None, can_check=None):
        super().__init__(
            parent,
            can_check,
            specs=[SimpleNamespace(name=n, sync_enabled=True) for n in SOURCES],
            probe=lambda *args: probe_database(*args),
            interval=60 * 60 * 1000,
        )

    def set_options(self, options):
        old_wait = dict(getattr(self, "not_before", {}))
        old_options = dict(getattr(self, "options", {}))
        mapped = dict(options)
        for name in SOURCES:
            mapped["enabled_" + name] = options.get("metadata_" + name, True) is True
        super().set_options(mapped)
        keys = {
            "IGDB": ("igdb_client_id", "igdb_client_secret"),
            "SteamGridDB": ("sgdb_api_key",),
            "OpenCritic": ("opencritic_api_key",),
        }
        for name, deadline in old_wait.items():
            if all(
                old_options.get(key) == mapped.get(key) for key in keys.get(name, ())
            ):
                self.not_before[name] = deadline
        for name in SOURCES:
            if not mapped["enabled_" + name]:
                self.update_state(
                    ConnectionResult(
                        name,
                        "disabled",
                        "Enable this database in Sources to check access.",
                    )
                )


class ConnectionPanel(QWidget):
    idle = Signal()
    store_filter_changed = Signal(object)

    def __init__(self, parent=None, can_check=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.stores = StoreConnections(self, can_check, store_filters=True)
        self.stores.store_filter_changed.connect(self.store_filter_changed.emit)
        self.databases = DatabaseConnections(self, can_check)
        for strip in (self.stores, self.databases):
            layout.addWidget(strip)
            strip.idle.connect(self.idle.emit)

    def visible_stores(self):
        return self.stores.visible_stores()

    def set_visible_stores(self, stores):
        self.stores.set_visible_stores(stores)

    @property
    def busy(self):
        return self.stores.busy or self.databases.busy

    def set_options(self, options):
        self.stores.set_options(options)
        self.databases.set_options(options)

    def refresh(self):
        self.stores.refresh()
        self.databases.refresh()

    def pause(self):
        self.stores.pause()
        self.databases.pause()

    def stop(self):
        self.stores.stop()
        self.databases.stop()
