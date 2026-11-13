import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heroic_install import can_install, install_url, open_install
from browsing import matches
from browsing_state import normalize_snapshot


class HeroicInstallTests(unittest.TestCase):
    def test_exact_runner_id_and_encoding(self):
        row = {
            "store": "Epic",
            "id": "app &id/=a",
            "title": "Example",
            "installation_status": "Not detected",
        }
        query = parse_qs(urlsplit(install_url(row)).query)
        self.assertEqual(query, {"appName": ["app &id/=a"], "runner": ["legendary"]})
        self.assertIn("runner=gog", install_url({"store": "GOG", "id": "123"}))

    def test_no_install_for_installed_or_other_stores(self):
        for row in (
            {"store": "Steam", "id": "1"},
            {"store": "GOG", "id": "1", "installation_status": "Installed"},
            {"store": "Epic", "id": "app", "_installations": [{"state": "Installed"}]},
            {"store": "GOG", "id": "1", "type": "DLC"},
        ):
            self.assertFalse(can_install(row))
            with self.assertRaises(ValueError):
                install_url(row)

    def test_native_handoff_is_argv_without_shell(self):
        row = {"store": "Epic", "id": "app"}
        with (
            patch("heroic_install.shutil.which", return_value="/usr/bin/heroic"),
            patch(
                "heroic_install.QProcess.startDetached", return_value=(True, 123)
            ) as start,
        ):
            open_install(row, {})
            start.assert_called_once_with("/usr/bin/heroic", [install_url(row)])

    def test_flatpak_desktop_handler_fallback(self):
        with (
            patch("heroic_install.shutil.which", return_value=None),
            patch(
                "heroic_install.QDesktopServices.openUrl", return_value=True
            ) as opened,
        ):
            open_install({"store": "GOG", "id": "123"}, {})
            self.assertEqual(opened.call_args.args[0].scheme(), "heroic")

    def test_failed_handoff_reports_failure(self):
        with (
            patch("heroic_install.shutil.which", return_value=None),
            patch("heroic_install.QDesktopServices.openUrl", return_value=False),
        ):
            with self.assertRaises(ValueError):
                open_install({"store": "GOG", "id": "123"}, {})

    def test_empty_store_selection_shows_nothing(self):
        self.assertFalse(matches({"store": "Steam"}, {"visible_stores": []}))
        self.assertTrue(matches({"store": "Steam"}, {"visible_stores": ["Steam"]}))
        self.assertFalse(matches({"store": "GOG"}, {"visible_stores": ["Steam"]}))
        self.assertEqual(
            normalize_snapshot({"filters": {"visible_stores": []}}, 67)["filters"][
                "visible_stores"
            ],
            [],
        )

    def test_window_checkboxes_persist_and_button_tracks_selection(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings
        import main_window as app
        from qt_wait import settle
        from core import game

        q = QApplication.instance() or QApplication([])
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(app, "ROOT", Path(root)),
            patch.object(
                app,
                "QSettings",
                lambda *a: QSettings(root + "/settings.ini", QSettings.IniFormat),
            ),
        ):
            w = settle(app.Window())
            try:
                w.model.load(
                    [
                        game(
                            "GOG",
                            "123",
                            "Example",
                            {},
                            installation_status="Not detected",
                        ),
                        game(
                            "Steam",
                            "1",
                            "Steam Example",
                            {},
                            installation_status="Installed",
                        ),
                    ]
                )
                w.apply_filters()
                self.assertEqual(w.proxy.rowCount(), 2)
                w.connections.stores.store_checks["GOG"].setChecked(False)
                self.assertEqual(w.proxy.rowCount(), 1)
                saved = w.snapshot()
                w.clear_filters()
                self.assertEqual(w.proxy.rowCount(), 2)
                w.restore_snapshot(saved)
                self.assertEqual(w.proxy.rowCount(), 1)
                w.connections.set_visible_stores([])
                w.apply_filters()
                self.assertEqual(w.proxy.rowCount(), 0)
                w.clear_filters()
                for i in range(w.proxy.rowCount()):
                    if w.proxy.index(i, 1).data() == "GOG":
                        w.table.setCurrentIndex(w.proxy.index(i, 0))
                        self.assertFalse(w.install_button.isHidden())
                        self.assertTrue(w.steam_button.isHidden())
                    else:
                        w.table.setCurrentIndex(w.proxy.index(i, 0))
                        self.assertTrue(w.install_button.isHidden())
                        self.assertFalse(w.steam_button.isHidden())
            finally:
                w.close()
                q.processEvents()
