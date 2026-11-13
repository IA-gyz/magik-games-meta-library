"""Local command validation and shared launch eligibility; no Qt dependency."""

import shutil
from pathlib import Path
from installations import LaunchError
from configuration import override_values
from provider_registry import launch_supported


def ready_installations(row, override=None):
    if not row or not launch_supported(row["store"]):
        return []
    return [
        entry
        for entry in row.get("_installations", [])
        if entry["state"] == "Installed"
        and (entry.get("launch_ready", True) or override)
    ]


def override_command(value):
    try:
        value = override_values(value)
    except ValueError as exc:
        raise LaunchError(str(exc)) from exc
    program, args, env, cwd = (value[k] for k in ("program", "args", "env", "cwd"))
    executable = shutil.which(str(Path(program).expanduser()))
    if not executable:
        raise LaunchError("Executable not found or not executable: " + program)
    if not isinstance(cwd, str) or (cwd and not Path(cwd).expanduser().is_dir()):
        raise LaunchError("Working directory does not exist.")
    return executable, args, str(Path(cwd).expanduser()) if cwd else "", env
