"""Plain-language explanations from structured store errors, without guessing causes."""

import math
from connector_io import FetchError


def explain_store_error(error, store=None, *, game_details=False):
    if not isinstance(error, FetchError):
        # Unexpected exception text can contain request URLs or credentials.
        return (
            type(error).__name__ + " while reading game details"
            if game_details
            else type(error).__name__ + " while reading the library"
        )
    status, category = error.status, error.category
    if status == 401:
        if store == "EA":
            explanation = "EA did not accept the sign-in. Open Sources → Connect EA and sign in again. If you use a manual token, replace it in Sources."
        elif store == "Steam":
            explanation = "Steam did not accept this request. Check the API key in Sources. If you are fetching dates added, reconnect Steam dates."
        elif store in ("Epic", "Amazon"):
            explanation = (
                f"{store} did not accept the sign-in. Sign in again through Heroic or "
                + ("Legendary" if store == "Epic" else "Nile")
                + ", then refresh."
            )
        else:
            explanation = "The store did not accept the sign-in. Check the account connection in Sources, then try again."
    elif status == 403:
        explanation = "The store refused access. This can be an account-permission or service restriction. Check your account access and try again later."
    elif status == 429 or category == "rate_limit":
        delay = error.retry_after
        wait = (
            f" Wait at least {math.ceil(delay)} seconds before trying again."
            if isinstance(delay, (int, float)) and math.isfinite(delay) and delay > 0
            else " Wait a while before trying again."
        )
        explanation = (
            "The store asked the app to slow down."
            + wait
            + " Other stores can still be checked."
        )
    elif status in (404, 410) or category == "unavailable":
        explanation = (
            "The store has no public details available for this game. Your saved library entry is kept; this does not mean you no longer own it."
            if game_details
            else "The requested store service was not found or is no longer available. Your saved library is kept; this does not mean your account has no games. Try again later."
        )
    elif category == "temporary" or status in (408, 500, 502, 503, 504):
        explanation = "The request could not be completed. The connection, store service or response may have a temporary problem. Try again later."
    else:
        explanation = "The store request could not be completed. Check the details below and your connection settings in Sources."
    return explanation + " Details: " + str(error)
