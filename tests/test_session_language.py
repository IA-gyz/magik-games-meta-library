import sys, unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_ui import english_ea_url


class LanguageTests(unittest.TestCase):
    def test_ea_login_and_oauth_redirect_request_english(self):
        for url in [
            "https://www.ea.com/login",
            "https://accounts.ea.com/connect/auth?locale=ar_SA&client_id=client&state=a%2Bb&redirect_uri=https%3A%2F%2Fwww.ea.com%2Flogin#fragment",
        ]:
            result = english_ea_url(url)
            self.assertEqual(parse_qs(urlsplit(result).query)["locale"], ["en_US"])
            if "state=" in url:
                self.assertEqual(parse_qs(urlsplit(result).query)["state"], ["a+b"])
                self.assertEqual(urlsplit(result).fragment, "fragment")
            self.assertEqual(english_ea_url(result), result)

    def test_non_ea_and_non_login_urls_are_untouched(self):
        for url in [
            "https://ea.com.example.org/login?locale=ar_SA",
            "https://store.steampowered.com/login/",
            "https://www.ea.com/games",
            "http://www.ea.com/login",
        ]:
            self.assertEqual(english_ea_url(url), url)
