"""Validated, Qt-free persisted browsing state. Existing setting keys stay stable."""

from browsing import FACETS
from advanced_filters import normalize as normalize_advanced
from provider_registry import PROVIDERS

STORE_NAMES = [p.name for p in PROVIDERS]

PLAYED_OPTIONS = ("All", "Played", "Unplayed (known)", "Unknown playtime")


def normalize_snapshot(value, column_count):
    state = value if isinstance(value, dict) else {}
    raw = state.get("filters")
    raw = raw if isinstance(raw, dict) else {}
    filters = {
        "search": raw.get("search") if isinstance(raw.get("search"), str) else "",
        "played": raw.get("played") if raw.get("played") in PLAYED_OPTIONS else "All",
        "score": max(0, min(100, raw["score"])) if type(raw.get("score")) is int else 0,
        "current": raw.get("current") is True,
        "favorites": raw.get("favorites") is True,
        "advanced": normalize_advanced(raw.get("advanced")),
    }
    for key in FACETS:
        selected = raw.get(key, [])
        if isinstance(selected, str):
            selected = [selected]
        filters[key] = (
            list(dict.fromkeys(v for v in selected if isinstance(v, str) and v))
            if isinstance(selected, list)
            else []
        )
    visible = raw.get("visible_stores", STORE_NAMES)
    filters["visible_stores"] = (
        [name for name in STORE_NAMES if name in visible]
        if isinstance(visible, list)
        else STORE_NAMES[:]
    )
    sort_key = state.get("sort_key", 0)
    return {
        "filters": filters,
        "sort_key": max(0, min(max(0, column_count - 1), sort_key))
        if type(sort_key) is int
        else 0,
        "descending": state.get("descending") is True,
        "view": 1 if type(state.get("view")) is int and state["view"] == 1 else 0,
    }


def normalize_presets(value, column_count):
    if not isinstance(value, dict):
        return {}
    return {
        name: normalize_snapshot(state, column_count)
        for name, state in value.items()
        if isinstance(name, str) and name.strip() and isinstance(state, dict)
    }
