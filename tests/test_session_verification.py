import json, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_verification import verify_candidate
from web_sessions import WebsiteSession, atomic_json, renew_ea, SessionError


class SessionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.options = {"auth_dir": str(self.root)}
        self.cookie = {
            "name": "sid",
            "value": "old",
            "domain": ".ea.com",
            "path": "/",
            "secure": True,
            "expires": None,
            "http_only": True,
        }
        self.path = self.root / "ea-cookies.json"
        atomic_json(self.path, {"cookies": [self.cookie]})
        self.token = self.root / "ea-token.json"
        atomic_json(
            self.token, {"access_token": "old-token", "expires_at": time.time() + 10000}
        )
        self.before = {p.name: p.read_bytes() for p in self.root.iterdir()}

    def tearDown(self):
        self.tmp.cleanup()

    def candidate(self):
        return {"cookies": [{**self.cookie, "value": "new"}]}

    def assert_old_files(self):
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.root.iterdir()}, self.before
        )

    def test_failed_check_preserves_previous_session_and_token(self):
        staged = []

        def fail(options, force):
            staged.append(Path(options["auth_dir"]))
            self.assertNotEqual(staged[-1], self.root)
            raise SessionError("rejected")

        with patch("session_verification.renew_ea", side_effect=fail):
            with self.assertRaises(SessionError):
                verify_candidate("ea", self.options, self.candidate())
        self.assert_old_files()
        self.assertFalse(staged[0].exists())

    def test_success_promotes_rotated_verified_cookies_only(self):
        def succeed(options, force):
            path = Path(options["auth_dir"]) / "ea-cookies.json"
            atomic_json(path, {"cookies": [{**self.cookie, "value": "rotated"}]})
            return "temporary-token"

        with patch("session_verification.renew_ea", side_effect=succeed):
            self.assertEqual(verify_candidate("ea", self.options, self.candidate()), {})
        self.assertEqual(
            WebsiteSession("ea", self.options).cookies()[0]["value"], "rotated"
        )
        self.assertEqual(self.token.read_bytes(), self.before["ea-token.json"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_failed_publication_preserves_previous_files(self):
        from session_verification import atomic_json as real_write

        def write(path, value):
            if Path(path) == self.path:
                raise OSError("cannot publish")
            return real_write(path, value)

        with (
            patch("session_verification.renew_ea", return_value="verified"),
            patch("session_verification.atomic_json", side_effect=write),
        ):
            with self.assertRaises(OSError):
                verify_candidate("ea", self.options, self.candidate())
        self.assert_old_files()

    def test_token_cache_cannot_cross_sign_in_changes(self):
        with patch.object(
            WebsiteSession,
            "get",
            return_value=(
                json.dumps({"access_token": "first", "expires_in": 10000}),
                "https://accounts.ea.com",
            ),
        ) as get:
            self.assertEqual(renew_ea(self.options), "first")
            self.assertEqual(renew_ea(self.options), "first")
            self.assertEqual(get.call_count, 1)
        atomic_json(self.path, self.candidate())
        with patch.object(
            WebsiteSession,
            "get",
            return_value=(
                json.dumps({"access_token": "second", "expires_in": 10000}),
                "https://accounts.ea.com",
            ),
        ) as get:
            self.assertEqual(renew_ea(self.options), "second")
            get.assert_called_once()

    def test_steam_verification_preserves_old_login_on_failure(self):
        path = self.root / "steam-cookies.json"
        atomic_json(path, {"cookies": []})
        before = path.read_bytes()
        cookie = {
            **self.cookie,
            "domain": ".steampowered.com",
            "name": "steamLoginSecure",
            "value": "76561198018049642%7C%7Cprivate",
        }
        with patch(
            "steam_dates.fetch_license_page", side_effect=SessionError("no access")
        ):
            with self.assertRaises(SessionError):
                verify_candidate("steam", self.options, {"cookies": [cookie]})
        self.assertEqual(path.read_bytes(), before)

    def test_steam_success_returns_identity_and_preserves_other_service(self):
        cookie = {
            **self.cookie,
            "domain": ".steampowered.com",
            "name": "steamLoginSecure",
            "value": "76561198018049642%7C%7Cprivate",
        }
        with patch(
            "steam_dates.fetch_license_page", return_value=([{}, {}], "website")
        ):
            result = verify_candidate("steam", self.options, {"cookies": [cookie]})
        self.assertEqual(result, {"steam_id": "76561198018049642", "licenses": 2})
        self.assertEqual(self.path.read_bytes(), self.before["ea-cookies.json"])
