"""Stable public connector API; store protocols live in providers/."""

from connector_io import (
    Cancelled,
    FetchError,
    MetadataUnavailable,
    request,
    token_file,
    helper,
    ConnectorIO,
)
from providers import (
    steam as steam_provider,
    gog as gog_provider,
    epic as epic_provider,
    amazon as amazon_provider,
    ea as ea_provider,
    rockstar as rockstar_provider,
)
from providers.ea import EA_ENDPOINT
from providers.rockstar import ROCKSTAR_METADATA
from provider_registry import PROVIDERS


def _io():
    # Late binding preserves the public transport injection point for tests and callers.
    return ConnectorIO(request, helper, token_file)


def steam(options, cancel, progress):
    return steam_provider.steam(options, cancel, progress, io=_io())


def steam_details(row):
    return steam_provider.steam_details(row, io=_io())


def gog_shelf(headers, cancel, progress):
    return gog_provider.gog_shelf(headers, cancel, progress, io=_io())


def gog(options, cancel, progress):
    return gog_provider.gog(options, cancel, progress, io=_io())


def gog_details(row):
    return gog_provider.gog_details(row, io=_io())


def epic_acquisition_dates(rows, options, cancel, progress):
    return epic_provider.epic_acquisition_dates(
        rows, options, cancel, progress, io=_io()
    )


def epic(options, cancel, progress):
    return epic_provider.epic(options, cancel, progress, io=_io())


def amazon(options, cancel, progress):
    return amazon_provider.amazon(options, cancel, progress, io=_io())


def ea(options, cancel, progress):
    return ea_provider.ea(options, cancel, progress, io=_io())


def rockstar(options, cancel, progress):
    return rockstar_provider.rockstar(options, cancel, progress, io=_io())


FETCHERS = {provider.name: globals()[provider.fetch_function] for provider in PROVIDERS}

__all__ = [
    "Cancelled",
    "FetchError",
    "MetadataUnavailable",
    "request",
    "token_file",
    "helper",
    "ConnectorIO",
    "EA_ENDPOINT",
    "ROCKSTAR_METADATA",
    "steam",
    "steam_details",
    "gog_shelf",
    "gog",
    "gog_details",
    "epic_acquisition_dates",
    "epic",
    "amazon",
    "ea",
    "rockstar",
    "FETCHERS",
]
