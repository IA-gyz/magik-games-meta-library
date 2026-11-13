"""Verify candidate sign-ins in isolation before replacing saved cookies."""

from tempfile import TemporaryDirectory
from pathlib import Path
from web_sessions import atomic_json, auth_dir, WebsiteSession, renew_ea, SessionError


def verify_candidate(service, options, candidate):
    if service not in ("ea", "steam"):
        raise SessionError("Unsupported sign-in service.")
    destination = auth_dir(options) / (service + "-cookies.json")
    with TemporaryDirectory(prefix="magik-signin-") as temporary:
        staged = {**options, "auth_dir": temporary}
        atomic_json(Path(temporary) / (service + "-cookies.json"), candidate)
        if service == "ea":
            renew_ea(staged, force=True)
            result = {}
        else:
            from steam_dates import fetch_license_page

            identity = WebsiteSession("steam", staged).steam_id()
            licenses, _source = fetch_license_page(
                {**staged, "steam_licenses_html": ""}, identity
            )
            result = {"steam_id": identity, "licenses": len(licenses)}
        verified = WebsiteSession(service, staged)
        if not verified.cookies():
            raise SessionError(
                "The verified sign-in has no usable cookies. Please sign in again."
            )
        # Only this atomic write publishes the verified login. Temporary tokens are not promoted.
        atomic_json(
            destination,
            {"cookies": verified.cookies(), "user_agent": verified.user_agent},
        )
        return result
