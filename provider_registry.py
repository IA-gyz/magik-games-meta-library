"""Canonical provider order, configuration fields and capabilities. No Qt/network imports."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    fetch_function: str
    source_fields: tuple[tuple[str, str, str], ...]
    metadata_function: str | None = None
    sync_enabled: bool = True
    launch_enabled: bool = True
    complete_library: bool = True


PROVIDERS = (
    ProviderSpec(
        "Steam",
        "steam",
        (
            ("steam_id", "SteamID64 or profile name", "text"),
            ("steam_key", "Steam API key (saved on this computer)", "secret"),
            (
                "steam_licenses_html",
                "Saved Steam licenses page (optional HTML file)",
                "file",
            ),
        ),
        metadata_function="steam_details",
    ),
    ProviderSpec(
        "GOG",
        "gog",
        (("gog_auth", "Heroic/GOGDL sign-in file (JSON)", "file"),),
        metadata_function="gog_details",
    ),
    ProviderSpec(
        "Epic",
        "epic",
        (
            (
                "epic_exe",
                "Legendary program (leave blank to find automatically)",
                "file",
            ),
            ("epic_config", "Legendary settings folder (optional)", "dir"),
            (
                "epic_heroic_root",
                "Heroic settings folder (optional)",
                "dir",
            ),
        ),
        metadata_function="epic_details",
    ),
    ProviderSpec(
        "Amazon",
        "amazon",
        (
            ("amazon_exe", "Nile program (leave blank to find automatically)", "file"),
            ("amazon_config", "Nile settings folder (optional)", "dir"),
        ),
    ),
    ProviderSpec(
        "EA",
        "ea",
        (
            ("ea_auth", "Lutris sign-in file (JSON)", "file"),
            (
                "ea_token",
                "EA access token (saved locally; used instead of the file)",
                "secret",
            ),
        ),
    ),
    ProviderSpec(
        "Rockstar",
        "rockstar",
        (("rockstar_log", "Launcher log file (may not list all games)", "file"),),
        sync_enabled=False,
        launch_enabled=False,
        complete_library=False,
    ),
)
_INDEX = {spec.name: spec for spec in PROVIDERS}


def provider(name):
    return _INDEX[name]


def selected_providers(options):
    return tuple(
        spec
        for spec in PROVIDERS
        if spec.sync_enabled and options.get("enabled_" + spec.name)
    )


def launch_supported(name):
    return name in _INDEX and _INDEX[name].launch_enabled
