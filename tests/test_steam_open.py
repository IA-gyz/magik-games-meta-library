import sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from steam_open import library_url, can_open, open_in_steam


class SteamOpenTests(unittest.TestCase):
    def test_library_navigation_only(self):
        row = {"store": "Steam", "id": "620", "installation_status": "Not detected"}
        with (
            patch("steam_open.shutil.which", return_value="/usr/bin/steam"),
            patch("steam_open.QProcess.startDetached", return_value=(True, 1)) as start,
        ):
            self.assertEqual(open_in_steam(row, {}), "steam://nav/games/details/620")
            start.assert_called_once_with(
                "/usr/bin/steam", ["steam://nav/games/details/620"]
            )

    def test_bad_id_or_store_never_opens(self):
        for row in [{"store": "GOG", "id": "620"}] + [
            {"store": "Steam", "id": v}
            for v in ("0", "-1", "620?launch=1", "9" * 5000, "١٢٣")
        ]:
            self.assertFalse(can_open(row))
            with self.assertRaises(ValueError):
                library_url(row)

    def test_desktop_handler_supports_flatpak_and_reports_failure(self):
        with (
            patch("steam_open.shutil.which", return_value=None),
            patch("steam_open.QDesktopServices.openUrl", return_value=True) as opened,
        ):
            open_in_steam({"store": "Steam", "id": "620"}, {})
            self.assertEqual(
                opened.call_args.args[0].toString(), "steam://nav/games/details/620"
            )
        with (
            patch("steam_open.shutil.which", return_value=None),
            patch("steam_open.QDesktopServices.openUrl", return_value=False),
        ):
            with self.assertRaises(ValueError):
                open_in_steam({"store": "Steam", "id": "620"}, {})
