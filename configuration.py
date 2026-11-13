"""Validate saved configuration shapes without checking files or exposing secrets."""

from copy import deepcopy
from provider_registry import PROVIDERS
from extra_schema import OPTIONS as EXTRA_OPTIONS, SOURCES as EXTRA_SOURCES

TEXT_OPTIONS = frozenset(
    key for spec in PROVIDERS for key, _label, _kind in spec.source_fields
) | frozenset(
    {
        "auth_dir",
        "scan_steam_roots",
        "scan_heroic_roots",
        "scan_lutris_roots",
        "scan_prefix_roots",
        "scan_ea_game_roots",
        "launch_steam_exe",
        "launch_heroic_exe",
        "launch_lutris_exe",
    }
)
TEXT_OPTIONS |= frozenset(EXTRA_OPTIONS)
BOOLEAN_OPTIONS = frozenset("enabled_" + spec.name for spec in PROVIDERS) | frozenset(
    {
        "ea_session_enabled",
        "opencritic_auto_resume",
        "steam_dates_enabled",
    }
)

BOOLEAN_OPTIONS |= frozenset("metadata_" + source for source in EXTRA_SOURCES)

def normalize_options(value):
    options = deepcopy(value) if isinstance(value, dict) else {}
    for key in TEXT_OPTIONS:
        if key in options and not isinstance(options[key], str):
            options.pop(key)
    for key in BOOLEAN_OPTIONS:
        if key in options:
            options[key] = options[key] is True
    from request_budgets import request_limit, option_key
    for source in EXTRA_SOURCES:
        if option_key(source) in options:
            options[option_key(source)] = request_limit(options, source)
    for spec in PROVIDERS:
        if not spec.sync_enabled:
            options["enabled_" + spec.name] = False
    return options


def normalize_links(value):
    if not isinstance(value, dict):
        return {}
    return {
        key: target
        for key, target in value.items()
        if isinstance(key, str) and key and isinstance(target, str) and target
    }


def override_values(value):
    """Validate structure only; missing/unmounted executables remain editable."""
    if not isinstance(value, dict):
        raise ValueError("Launch setup must be an object.")
    program, args = value.get("program"), value.get("args", [])
    env, cwd = value.get("env", {}), value.get("cwd", "")
    if not isinstance(program, str) or not program.strip() or "\0" in program:
        raise ValueError("Choose a launch executable or script.")
    if not isinstance(args, list) or any(
        not isinstance(a, str) or "\0" in a for a in args
    ):
        raise ValueError("Arguments must be a JSON array of strings.")
    if not isinstance(env, dict) or any(
        not isinstance(k, str)
        or not k
        or "=" in k
        or "\0" in k
        or not isinstance(v, str)
        or "\0" in v
        for k, v in env.items()
    ):
        raise ValueError("Environment must map variable names to strings.")
    if not isinstance(cwd, str) or "\0" in cwd:
        raise ValueError("Working directory must be a path string.")
    return {"program": program, "args": args[:], "cwd": cwd, "env": env.copy()}


def normalize_overrides(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, override in value.items():
        if not isinstance(key, str) or not key:
            continue
        try:
            result[key] = override_values(override)
        except ValueError:
            continue
    return result
