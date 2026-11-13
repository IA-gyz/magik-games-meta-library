"""Retry delays for cover requests; independent of Qt and wall-clock scheduling."""

import math
import time
from email.utils import parsedate_to_datetime


def cover_retry_delay(
    attempt, status=None, retry_after="", *, invalid_image=False, now=None
):
    delay = (
        6 * 60 * 60
        if status in (404, 410) or invalid_image
        else min(900, 30 * 2 ** min(max(0, attempt - 1), 5))
    )
    if retry_after:
        try:
            requested = float(retry_after)
        except (TypeError, ValueError):
            try:
                requested = parsedate_to_datetime(retry_after).timestamp() - (
                    time.time() if now is None else now
                )
            except (ValueError, TypeError, OverflowError):
                requested = 0
        if math.isfinite(requested) and requested > 0:
            delay = max(delay, requested)
    return delay
