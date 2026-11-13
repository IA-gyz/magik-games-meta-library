"""Validate a complete import before it reaches persistent storage."""

import math
from catalog_data import normalize, STORES, FIELDS
from extra_schema import NUMERIC

TEXT_FIELDS = set(FIELDS) - set(NUMERIC) - {"score", "playtime", "active", "favorite", "last_played", "release", "mc_user_score", "mc_critic_count", "mc_user_count"}


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def validate_import_row(row, number):
    def fail(field, expected):
        raise ValueError(
            f"Game {number}: {field} must be {expected}. No games were imported."
        )

    for key in TEXT_FIELDS:
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            fail(key, "text or null")
    if not row.get("title", "").strip():
        fail("title", "non-empty text")
    if not isinstance(row.get("raw"), dict):
        fail("raw", "a JSON object")
    for key in ("score", "playtime", "mc_user_score", "mc_critic_count", "mc_user_count"):
        value = row.get(key)
        if value is not None and (not finite_number(value)):
            fail(key, "a finite non-negative number or null")
    if row.get("score") is not None and row["score"] > 100:
        fail("score", "a number from 0 to 100 or null")
    if row.get("mc_user_score") is not None and row["mc_user_score"] > 10:
        fail("mc_user_score", "a number from 0 to 10 or null")
    for key, maximum in NUMERIC.items():
        value = row.get(key)
        if value is not None and (not finite_number(value) or (maximum is not None and value > maximum)):
            fail(key, "a valid finite non-negative number or null")
    if row.get("favorite") is not None and type(row["favorite"]) is not bool:
        fail("favorite", "true, false or null")
    if row.get("active") is not None and type(row["active"]) is not bool:
        fail("active", "true, false or null")
    for key in ("release", "last_played"):
        value = row.get(key)
        if (
            value is not None
            and not isinstance(value, str)
            and (not finite_number(value))
        ):
            fail(key, "a date string, non-negative timestamp or null")
    return row


def normalize_import(store, payload):
    if store not in STORES:
        raise ValueError("Choose a supported store. No games were imported.")
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON list of games. No games were imported.")
    rows = []
    for number, item in enumerate(payload, 1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Game {number}: expected a JSON object. No games were imported."
            )
        if all(key in item for key in ("raw", "title", "id")) and (
            type(item["id"]) not in (str, int) or not str(item["id"]).strip()
        ):
            raise ValueError(
                f"Game {number}: id must be non-empty text or an integer. No games were imported."
            )
        try:
            normalized = normalize(store, [item])
        except (TypeError, ValueError, KeyError, AttributeError, IndexError):
            raise ValueError(
                f"Game {number}: the game data has an invalid structure. No games were imported."
            ) from None
        rows.extend(validate_import_row(row, number) for row in normalized)
    return rows


def import_saved_library(payload):
    games = payload.get("games")
    if not isinstance(games, list):
        raise ValueError(
            "The saved library must contain a list named games. No games were imported."
        )
    # Validate all store identities before normalization; never silently skip unknown stores.
    if any(
        not isinstance(item, dict) or item.get("store") not in STORES for item in games
    ):
        raise ValueError(
            "Every saved game must name a supported store. No games were imported."
        )
    rows = []
    for store in STORES:
        rows.extend(
            normalize_import(store, [item for item in games if item["store"] == store])
        )
    return rows
