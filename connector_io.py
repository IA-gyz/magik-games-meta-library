"""Shared network/helper transport and error types. No provider or Qt imports."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from typing import Callable


class Cancelled(Exception):
    pass


class FetchError(Exception):
    def __init__(self, message, *, category="error", status=None, retry_after=0):
        super().__init__(message)
        self.category = category
        self.status = status
        self.retry_after = retry_after


class MetadataUnavailable(FetchError):
    def __init__(self, message):
        super().__init__(message, category="unavailable")


def request(url, params=None, headers=None, body=None, *, timeout=30):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    payload = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "MagikGamesLibrary/0.1", **(headers or {})}
    if payload:
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=payload, headers=h), timeout=timeout
        ) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        category = (
            "rate_limit"
            if e.code == 429
            else (
                "temporary"
                if e.code in [408, 500, 502, 503, 504]
                else ("unavailable" if e.code in [404, 410] else "http")
            )
        )
        retry_after = 0
        try:
            value = e.headers.get("Retry-After", "0") if e.headers else "0"
            if value.isdigit():
                retry_after = int(value)
            else:
                from email.utils import parsedate_to_datetime

                retry_after = max(
                    0, parsedate_to_datetime(value).timestamp() - time.time()
                )
        except (ValueError, TypeError, AttributeError):
            pass
        raise FetchError(
            f"HTTP {e.code}", category=category, status=e.code, retry_after=retry_after
        ) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise FetchError(
            "Network timeout / connection error / invalid JSON response",
            category="temporary",
        ) from None


def token_file(path):
    p = Path(path).expanduser()
    data = json.loads(p.read_text())
    if "access_token" in data:
        return data
    for value in data.values():
        if isinstance(value, dict) and "access_token" in value:
            return value
    raise FetchError("No access_token found in the selected JSON file")


def helper(executable, args, config, envkey, cancel, *, timeout=600):
    env = os.environ.copy()
    if config:
        env[envkey] = str(Path(config).expanduser())
    try:
        proc = subprocess.Popen(
            [str(Path(executable).expanduser()), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except OSError:
        raise FetchError("Helper executable not found or not executable") from None
    start = time.monotonic()
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if cancel.is_set() or time.monotonic() - start > timeout:
                proc.kill()
                proc.communicate()
                if cancel.is_set():
                    raise Cancelled()
                raise FetchError(
                    "Library query timed out after 10 minutes"
                    if timeout == 600
                    else f"Connection check timed out after {timeout:g} seconds"
                )
    if proc.returncode:
        raise FetchError(
            "Helper query failed. Sign in using the helper or Heroic, then retry. No helper logs were stored."
        )
    return out


@dataclass(frozen=True)
class ConnectorIO:
    request: Callable
    helper: Callable
    token_file: Callable
