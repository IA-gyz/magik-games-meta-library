import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    import main_window as app
    from qt_wait import settle
    from launch_ui import Launches, InstallationSettings
except ImportError:
    app = None
from core import game
from installations import scan, LaunchError


@unittest.skipIf(app is None, "PySide6 required")
class LaunchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = []
        for p in [
            patch.dict(
                "os.environ",
                {
                    "XDG_CONFIG_HOME": str(self.root / ".config"),
                    "XDG_DATA_HOME": str(self.root / ".local/share"),
                },
            ),
            patch.object(app, "ROOT", self.root),
            patch.object(
                app,
                "QSettings",
                lambda *a: QSettings(
                    str(self.root / "settings.ini"), QSettings.IniFormat
                ),
            ),
        ]:
            p.start()
            self.patches.append(p)
        self.w = settle(app.Window())
        folder = self.root / "steam/steamapps/common/Game"
        folder.mkdir(parents=True)
        manifest = self.root / "steam/steamapps/appmanifest_123.acf"
        manifest.write_text(
            '"AppState" {"appid" "123" "name" "A" "installdir" "Game" "StateFlags" "4"}'
        )
        snapshot = scan(
            {"scan_steam_roots": str(self.root / "steam")}, home=self.root / "emptyhome"
        )
        self.entry = snapshot["entries"][0]
        self.entry["custom_root"] = False
        self.w.db.save(
            [game("Steam", "123", "A", {}), game("Epic", "other", "Uninstalled", {})]
        )
        self.w.db.save_installations(snapshot)
        self.w.reload()
        settle(self.w)

    def tearDown(self):
        self.w.close()
        self.q.processEvents()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_play_handoff_is_fixed_argument_vector(self):
        launch = Launches(self.root / "launch.log")
        with (
            patch("installations.shutil.which", return_value="/usr/bin/steam"),
            patch(
                "launch_service.QProcess.startDetached", return_value=(True, 42)
            ) as start,
        ):
            self.assertEqual(launch.launch(self.entry, {}), 42)
            start.assert_called_once_with("steam", ["-applaunch", "123"])
        self.assertIn("does not confirm", (self.root / "launch.log").read_text())

    def test_failed_handoff(self):
        with (
            patch("installations.shutil.which", return_value="/usr/bin/steam"),
            patch("launch_service.QProcess.startDetached", return_value=(False, 0)),
        ):
            with self.assertRaises(LaunchError):
                Launches(self.root / "log").launch(self.entry, {})

    def test_installation_filter_and_play_readiness(self):
        self.w.facets["installation_status"].set_selected(["Installed"])
        self.assertEqual(self.w.proxy.rowCount(), 1)
        self.w.table.setCurrentIndex(self.w.proxy.index(0, 0))
        self.assertTrue(self.w.play_button.isEnabled())
        self.assertIn("Installation details", self.w.details.toPlainText())
        self.w.clear_filters()
        self.w.table.setCurrentIndex(self.w.proxy.index(1, 0))
        self.assertFalse(self.w.play_button.isEnabled())

    def test_scanner_worker_persists_snapshot_without_account_fetch(self):
        self.w.db.save_installations({})
        fake = {"entries": [], "covered": [], "notes": [], "scopes": {}}
        with (
            patch("sync_worker.scan_installations", return_value=fake),
            patch.dict(
                __import__("sync_worker").FETCHERS,
                Steam=lambda *a: (_ for _ in ()).throw(
                    AssertionError("No account query")
                ),
            ),
        ):
            app.Worker(self.w.db, {}, "scan", True).run()
        self.assertEqual(self.w.db.installations(), fake)

    def test_provider_settings_survive_sources_save(self):
        self.w.options["launch_steam_exe"] = "/custom/steam"

        class Dialog:
            def __init__(self, *args):
                pass

            def exec(self):
                return True

            def values(self):
                return {"steam_key": "dummy-key"}

        with patch.object(app, "Sources", Dialog):
            self.w.sources()
        self.assertEqual(self.w.options["launch_steam_exe"], "/custom/steam")

    def test_provider_choice_routes_selected_entry(self):
        snapshot = self.w.db.installations()
        other = {
            **snapshot["entries"][0],
            "key": "second-provider",
            "provider": "Steam (flatpak)",
            "mode": "flatpak",
        }
        snapshot["entries"].append(other)
        self.w.db.save_installations(snapshot)
        self.w.reload()
        settle(self.w)
        self.w.table.setCurrentIndex(self.w.proxy.index(0, 0))
        with (
            patch.object(
                app.QInputDialog,
                "getItem",
                side_effect=lambda parent, title, label, items, *a: (items[1], True),
            ),
            patch.object(self.w.launches, "launch") as launch,
        ):
            self.w.play_selected()
        self.assertEqual(launch.call_args.args[0]["key"], "second-provider")

    def test_manual_lutris_link_persists(self):
        snapshot = self.w.db.installations()
        entry = {
            **snapshot["entries"][0],
            "key": "lutris-existing",
            "kind": "lutris",
            "provider": "Lutris (native)",
            "store": None,
            "id": None,
            "title": "Existing Lutris game",
            "record_id": "7",
        }
        snapshot["entries"].append(entry)
        self.w.db.save_installations(snapshot)
        self.w.reload()
        settle(self.w)
        self.w.table.setCurrentIndex(self.w.proxy.index(1, 0))
        with patch.object(
            app.QInputDialog,
            "getItem",
            side_effect=lambda parent, title, label, items, *a: (items[1], True),
        ):
            self.w.link_lutris()
            settle(self.w)
        self.assertEqual(self.w.selected_game()["installation_status"], "Installed")
        self.w.close()
        self.w = settle(app.Window())
        self.assertEqual(self.w.launch_links["Epic|other"], "lutris-existing")

    def test_prefix_requires_local_override_and_persists(self):
        snapshot = self.w.db.installations()
        entry = {
            **snapshot["entries"][0],
            "key": "prefix-game",
            "kind": "prefix",
            "store": "Epic",
            "id": "other",
            "launch_ready": False,
            "provider": "Epic (Windows prefix)",
        }
        snapshot["entries"] = [entry]
        self.w.db.save_installations(snapshot)
        self.w.reload()
        settle(self.w)
        self.w.table.setCurrentIndex(self.w.proxy.index(1, 0))
        self.assertFalse(self.w.play_button.isEnabled())
        self.assertIn("Launch setup required", self.w.installation_label.text())

        class Dialog:
            value = {"program": sys.executable, "args": [], "env": {}, "cwd": ""}

            def __init__(self, *args):
                pass

            def exec(self):
                return True

        with patch.object(app, "LaunchOverride", Dialog):
            self.w.launch_setup()
            settle(self.w)
        self.assertTrue(self.w.play_button.isEnabled())
        with patch.object(self.w.launches, "launch") as launch:
            self.w.play_selected()
        self.assertEqual(launch.call_args.args[2]["program"], sys.executable)
        self.w.close()
        self.w = settle(app.Window())
        self.assertEqual(
            self.w.launch_overrides["Epic|other"]["program"], sys.executable
        )

    def test_override_process_environment_and_arguments(self):
        from PySide6.QtCore import QProcessEnvironment

        with patch("launch_service.QProcess") as process:
            process.return_value.startDetached.return_value = (True, 99)
            Launches(self.root / "log").launch(
                self.entry,
                {},
                {
                    "program": sys.executable,
                    "args": ["a b", "$(literal)"],
                    "cwd": str(self.root),
                    "env": {"MAGIK_TEST": "value"},
                },
            )
            instance = process.return_value
            instance.setArguments.assert_called_once_with(["a b", "$(literal)"])
            instance.setWorkingDirectory.assert_called_once_with(str(self.root))
            self.assertEqual(
                instance.setProcessEnvironment.call_args.args[0].value("MAGIK_TEST"),
                "value",
            )

    def test_manual_acquisition_date_and_clear(self):
        self.w.table.setCurrentIndex(self.w.proxy.index(0, 0))
        with patch.object(app, "DateAddedDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.value = "2020-05-06"
            self.w.set_date_added()
            settle(self.w)
        self.assertEqual(self.w.selected_game()["date_added"], "2020-05-06")
        self.w.db.save([game("Steam", "123", "A", {})])
        self.w.reload()
        settle(self.w)
        self.assertEqual(self.w.selected_game()["date_added"], "2020-05-06")
        with patch.object(app, "DateAddedDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.value = None
            self.w.set_date_added()
            settle(self.w)
        self.assertIsNone(self.w.selected_game()["date_added"])
        self.assertEqual(self.w.selected_game()["date_added_source"], "Manual")

    def test_old_column_layout_migrates(self):
        from PySide6.QtWidgets import QTableView
        from PySide6.QtGui import QStandardItemModel

        old = QTableView()
        old.setModel(QStandardItemModel(0, 16))
        old.setColumnHidden(3, True)
        saved = old.horizontalHeader().saveState()
        self.w.close()
        self.w.settings.setValue("header", saved)
        self.w.settings.sync()
        self.w = settle(app.Window())
        self.assertEqual(self.w.model.columnCount(), len(app.COLUMNS))
        self.assertTrue(self.w.table.isColumnHidden(3))
        old.close()

    def test_configuration_fields_and_no_real_launch_from_scan(self):
        dialog = InstallationSettings({}, self.w)
        self.assertIn("scan_heroic_roots", dialog.values())
        dialog.close()
        with patch(
            "launch_service.QProcess.startDetached",
            side_effect=AssertionError("Scan must not launch"),
        ):
            scan(
                {"scan_steam_roots": str(self.root / "steam")},
                home=self.root / "emptyhome",
            )

    def test_failed_launch_is_error_in_activity_log(self):
        from contracts import Severity

        self.w.table.setCurrentIndex(self.w.proxy.index(0, 0))
        with (
            patch.object(
                self.w.launches, "launch", side_effect=LaunchError("Test failure")
            ),
            patch.object(app.QMessageBox, "warning"),
        ):
            self.w.play_selected()
        self.assertEqual(self.w.status.entries[-1].severity, Severity.ERROR)
        self.assertIn("Test failure", self.w.status.entries[-1].text)

    def test_launch_events_have_explicit_severity(self):
        from contracts import Severity

        service = Launches(self.root / "events.log")
        events = []
        messages = []
        service.event.connect(events.append)
        service.message.connect(messages.append)
        service.log("information")
        service.log("failed", Severity.ERROR)
        self.assertEqual([e.severity for e in events], [Severity.INFO, Severity.ERROR])
        self.assertEqual(messages, ["information", "failed"])

    def test_shared_readiness_rules(self):
        from launch_commands import ready_installations

        entries = [
            {"state": "Installed", "launch_ready": True},
            {"state": "Installed", "launch_ready": False},
            {"state": "Missing files", "launch_ready": True},
        ]
        row = {"store": "Steam", "_installations": entries}
        self.assertEqual(ready_installations(row), entries[:1])
        self.assertEqual(ready_installations(row, {"program": "script"}), entries[:2])
        self.assertEqual(
            ready_installations({**row, "store": "Rockstar"}, {"program": "script"}), []
        )


if __name__ == "__main__":
    unittest.main()
