import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from connector_io import FetchError
from error_messages import explain_store_error


class ErrorMessageTests(unittest.TestCase):
    def test_ea_sign_in_has_action_and_retains_code(self):
        text = explain_store_error(FetchError("HTTP 401", status=401), "EA")
        self.assertIn("Sources → Connect EA", text)
        self.assertIn("manual token", text)
        self.assertIn("HTTP 401", text)

    def test_steam_and_helper_connections_have_specific_actions(self):
        for store, expected in [
            ("Steam", "API key"),
            ("Epic", "Legendary"),
            ("Amazon", "Nile"),
            ("GOG", "Sources"),
        ]:
            self.assertIn(
                expected, explain_store_error(FetchError("HTTP 401", status=401), store)
            )

    def test_forbidden_does_not_claim_token_expired(self):
        text = explain_store_error(FetchError("HTTP 403", status=403), "EA")
        self.assertIn("refused access", text)
        self.assertNotIn("expired", text)

    def test_rate_limit_uses_structured_delay_only(self):
        text = explain_store_error(
            FetchError("HTTP 429", category="rate_limit", status=429, retry_after=61.2)
        )
        self.assertIn("62 seconds", text)
        for delay in [0, None, "secret", float("inf")]:
            text = explain_store_error(
                FetchError("HTTP 429", category="rate_limit", retry_after=delay)
            )
            self.assertIn("Wait a while", text)

    def test_missing_details_are_different_from_missing_library_service(self):
        exc = FetchError("HTTP 404", category="unavailable", status=404)
        self.assertIn("no public details", explain_store_error(exc, game_details=True))
        self.assertIn("store service was not found", explain_store_error(exc))
        self.assertIn("HTTP 404", explain_store_error(exc, game_details=True))

    def test_connection_failure_does_not_assign_blame(self):
        text = explain_store_error(FetchError("connection error", category="temporary"))
        self.assertIn("connection, store service or response", text)

    def test_unknown_fetch_error_keeps_diagnostic(self):
        text = explain_store_error(FetchError("Helper query failed"))
        self.assertIn("Sources", text)
        self.assertIn("Helper query failed", text)

    def test_unexpected_exception_text_is_not_exposed(self):
        for details in [False, True]:
            text = explain_store_error(
                ValueError("https://host/?token=private"), game_details=details
            )
            self.assertIn("ValueError", text)
            self.assertNotIn("private", text)
