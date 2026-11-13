import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QPixmap, QColor
    import main_window as app
    from qt_wait import settle
    from widgets import Covers
except ImportError:
    app = None
from core import game


@unittest.skipIf(app is None, "PySide6 required for UI tests")
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def setUp(self):
        from connection_checks import ConnectionResult

        self.connection_patch = patch(
            "connection_status.probe_connection",
            side_effect=lambda store, *a, **k: ConnectionResult(
                store, "connected", "Test account check"
            ),
        )
        self.connection_patch.start()

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = patch.object(app, "ROOT", self.root)
        self.patch.start()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(self.root))
        self.settings_patch = patch.object(
            app,
            "QSettings",
            lambda *args: QSettings(
                str(self.root / "settings.ini"), QSettings.IniFormat
            ),
        )
        self.settings_patch.start()
        self.w = settle(app.Window())
        self.w.db.save(
            [
                game("Steam", 1, "Alpha", {}, genres="RPG", platforms="Windows"),
                game("GOG", 2, "Beta", {}, genres="Action", platforms="Linux"),
            ]
        )
        self.w.reload()
        settle(self.w)

    def tearDown(self):
        self.w.close()
        self.q.processEvents()
        self.patch.stop()
        self.settings_patch.stop()
        self.connection_patch.stop()
        self.tmp.cleanup()

    def test_ea_and_steam_saved_across_restart(self):
        class Dialog:
            def __init__(self, *args):
                pass

            def exec(self):
                return True

            def values(self):
                return {
                    "steam_key": "dummy-steam",
                    "ea_token": "dummy-ea",
                    "enabled_EA": True,
                }

        with patch.object(app, "Sources", Dialog):
            self.w.sources()
        self.w.settings.sync()
        self.w.close()
        self.w = settle(app.Window())
        self.assertEqual(self.w.options["ea_token"], "dummy-ea")
        self.assertEqual(self.w.options["steam_key"], "dummy-steam")
        self.assertIn("dummy-ea", Path(self.w.settings.fileName()).read_text())

    def test_preset_roundtrip(self):
        self.w.facets["store"].set_selected(["Steam", "GOG"])
        self.w.facets["genres"].set_selected(["RPG"])
        self.w.view_mode.setCurrentIndex(1)
        self.w.sort_key.setCurrentIndex(1)
        self.w.descending.setChecked(True)
        with patch.object(app.QInputDialog, "getText", return_value=("My RPGs", True)):
            self.w.save_preset()
        self.w.clear_filters()
        self.assertEqual(self.w.proxy.rowCount(), 2)
        self.w.apply_preset()
        self.assertEqual(self.w.proxy.rowCount(), 1)
        self.assertEqual(self.w.view_mode.currentIndex(), 1)
        self.w.settings.sync()
        self.w.close()
        self.w = settle(app.Window())
        self.assertIn("My RPGs", self.w.presets)
        self.assertEqual(self.w.facets["genres"].selected, ["RPG"])

    def test_malformed_saved_browsing_recovers_on_restart(self):
        import json

        for value in [
            None,
            [],
            {
                "filters": {
                    "search": [],
                    "score": "bad",
                    "store": [{}, "Steam"],
                    "played": [],
                },
                "sort_key": {},
                "view": True,
            },
        ]:
            self.w.close()
            self.w.settings.setValue("browsing", json.dumps(value))
            self.w.settings.setValue("presets", json.dumps(["not", "a", "mapping"]))
            self.w.settings.sync()
            self.w = settle(app.Window())
            self.assertEqual(self.w.search.text(), "")
            self.assertEqual(self.w.score.value(), 0)
            self.assertEqual(self.w.presets, {})
            self.assertFalse(self.w.restoring)
            self.w.search.setText("recovered")
            self.assertEqual(self.w.snapshot()["filters"]["search"], "recovered")

    def test_cancelled_refresh_does_not_schedule_scan(self):
        from contracts import OperationResult
        from threading import Event
        from types import SimpleNamespace

        worker = SimpleNamespace(mode="sync", cancel=Event(), isRunning=lambda: False)
        self.w.worker = worker
        self.w.finished(OperationResult((), cancelled=True))
        with patch.object(app.QTimer, "singleShot") as timer:
            self.w.idle()
        timer.assert_not_called()
        self.assertEqual(self.w.statusBar().currentMessage(), "Stopped")

    def test_closed_window_refuses_new_work(self):
        self.w.close()
        self.assertTrue(self.w.closing)
        with patch.object(app, "Worker") as worker:
            self.w.start("scan")
        worker.assert_not_called()

    def test_followup_scan_is_guarded(self):
        from contracts import OperationResult
        from threading import Event
        from types import SimpleNamespace

        worker = SimpleNamespace(mode="sync", cancel=Event(), isRunning=lambda: False)
        self.w.worker = worker
        self.w.finished(OperationResult(()))
        callbacks = []
        with patch.object(
            app.QTimer,
            "singleShot",
            side_effect=lambda delay, callback: callbacks.append(callback),
        ):
            self.w.idle()
        self.assertEqual(len(callbacks), 1)
        with patch.object(self.w, "start") as start:
            callbacks[0]()
            start.assert_called_once_with("scan")
            start.reset_mock()
            worker.cancel.set()
            callbacks[0]()
            start.assert_not_called()
            worker.cancel.clear()
            self.w.worker = None
            callbacks[0]()
            start.assert_not_called()
            self.w.worker = worker
            self.w.closing = True
            callbacks[0]()
            start.assert_not_called()
        self.w.closing = False

    def test_malformed_source_and_launch_settings_recover(self):
        import json

        for value in [
            None,
            [],
            {"steam_id": [], "enabled_Steam": "false", "scan_prefix_roots": 42},
        ]:
            self.w.close()
            self.w.settings.setValue("options", json.dumps(value))
            self.w.settings.setValue(
                "launch_links",
                json.dumps({"Steam|1": []} if isinstance(value, dict) else value),
            )
            self.w.settings.setValue(
                "launch_overrides",
                json.dumps(
                    {"Steam|1": {"program": []}} if isinstance(value, dict) else value
                ),
            )
            self.w.settings.sync()
            self.w = settle(app.Window())
            self.assertIsInstance(self.w.options, dict)
            self.assertFalse(self.w.options.get("enabled_Steam", False))
            self.assertNotIn("steam_id", self.w.options)
            self.assertEqual(self.w.launch_links, {})
            self.assertEqual(self.w.launch_overrides, {})
            dialog = app.Sources(self.w.options, self.w)
            dialog.close()

    def test_export_uses_visible_rows_in_display_order(self):
        import json

        path = self.root / "visible.json"
        self.w.descending.setChecked(True)
        with patch.object(
            app.QFileDialog,
            "getSaveFileName",
            return_value=(str(path), "JSON (*.json)"),
        ):
            self.w.export()
            settle(self.w)
        self.assertEqual(
            [r["title"] for r in json.loads(path.read_text())["games"]],
            ["Beta", "Alpha"],
        )
        self.w.search.setText("Alpha")
        with patch.object(
            app.QFileDialog,
            "getSaveFileName",
            return_value=(str(path), "JSON (*.json)"),
        ):
            self.w.export()
            settle(self.w)
        self.assertEqual(
            [r["title"] for r in json.loads(path.read_text())["games"]], ["Alpha"]
        )

    def test_export_names_only_writes_titles_without_other_fields(self):
        import json

        path = self.root / "names.json"
        self.w.descending.setChecked(True)
        with patch.object(
            app.QFileDialog,
            "getSaveFileName",
            return_value=(str(path), "JSON – names only (*.json)"),
        ):
            self.w.export()
            settle(self.w)
        payload = json.loads(path.read_text())
        self.assertEqual(
            payload,
            {"format": "magik-library-names-v1", "names": ["Beta", "Alpha"]},
        )
        self.assertIn("names", self.w.statusBar().currentMessage())

    def test_export_names_only_csv_uses_single_title_column(self):
        import csv

        path = self.root / "names.csv"
        with patch.object(
            app.QFileDialog,
            "getSaveFileName",
            return_value=(str(path), "CSV – names only (*.csv)"),
        ):
            self.w.export()
            settle(self.w)
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, ["title"])
            rows = list(reader)
        self.assertEqual(
            sorted(row["title"] for row in rows), ["Alpha", "Beta"]
        )

    def test_export_names_and_dates_pairs_titles_with_dates_added(self):
        import json

        path = self.root / "dates.json"
        with patch.object(
            app.QFileDialog,
            "getSaveFileName",
            return_value=(str(path), "JSON – names and dates (*.json)"),
        ):
            self.w.export()
            settle(self.w)
        payload = json.loads(path.read_text())
        self.assertEqual(payload["format"], "magik-library-names-dates-v1")
        self.assertEqual(len(payload["games"]), 2)
        self.assertEqual(
            sorted(entry["title"] for entry in payload["games"]),
            ["Alpha", "Beta"],
        )
        for entry in payload["games"]:
            self.assertEqual(set(entry), {"title", "date_added"})
        self.assertIn(
            "names and dates", self.w.statusBar().currentMessage()
        )

    def test_export_failure_is_reported_without_success_event(self):
        count = len(self.w.status.entries)
        with (
            patch.object(
                app.QFileDialog,
                "getSaveFileName",
                return_value=(str(self.root / "out.json"), "JSON (*.json)"),
            ),
            patch(
                "local_tasks.export_catalog", side_effect=TypeError("invalid payload")
            ),
            patch.object(app.QMessageBox, "warning") as warning,
        ):
            self.w.export()
            settle(self.w)
        warning.assert_called_once()
        self.assertEqual(len(self.w.status.entries), count)

    def test_invalid_import_does_not_save_any_rows(self):
        import json

        path = self.root / "invalid.json"
        rows = [
            game("Steam", "new1", "Valid", {}),
            game("Steam", "new2", "Invalid", {}, playtime="bad"),
        ]
        path.write_text(json.dumps({"format": "magik-library-v1", "games": rows}))
        before = self.w.db.rows()
        with (
            patch.object(
                app.QFileDialog, "getOpenFileName", return_value=(str(path), "JSON")
            ),
            patch.object(app.QMessageBox, "warning") as warning,
        ):
            self.w.import_json()
            settle(self.w)
        warning.assert_called_once()
        self.assertEqual(self.w.db.rows(), before)

    def test_first_async_load_keeps_activity_already_logged(self):
        from contracts import LogEntry

        self.w.log_restored = False
        self.w.db.status("Steam", "Saved status")
        self.w.status.append_events([LogEntry("Current session action")])
        self.w.reload()
        settle(self.w)
        text = self.w.status.toPlainText()
        self.assertIn("Saved status", text)
        self.assertIn("Current session action", text)

    def test_prepared_report_opens_on_the_ui_thread(self):
        from PySide6.QtCore import QThread

        threads = []
        with patch.object(
            app,
            "show_prepared_report",
            side_effect=lambda *args: threads.append(QThread.currentThread()),
        ) as show:
            self.w.metadata_report()
            settle(self.w)
        show.assert_called_once()
        self.assertEqual(threads, [self.q.thread()])
        self.assertFalse(self.w.local_active)
        self.assertFalse(self.w.stop.isEnabled())

    def test_stop_suppresses_a_report_even_if_preparation_just_finished(self):
        with patch.object(app, "show_prepared_report") as show:
            self.w.acquisition_report()
            self.w.cancel()
            settle(self.w)
        show.assert_not_called()
        self.assertIn("stopped", self.w.statusBar().currentMessage())

    def test_column_visibility_and_shared_selection(self):
        self.w.table.selectRow(1)
        self.q.processEvents()
        self.assertIn("Beta", self.w.details.toPlainText())
        self.w.view_mode.setCurrentIndex(1)
        self.assertEqual(
            self.w.grid.currentIndex().row(), self.w.table.currentIndex().row()
        )
        self.w.set_column(3, False)
        self.w.close()
        self.w = settle(app.Window())
        self.assertTrue(self.w.table.isColumnHidden(3))

    def test_cover_disk_cache_without_network(self):
        url = "https://example.invalid/test.png"
        covers = Covers(self.root / "test-covers")
        pix = QPixmap(80, 100)
        pix.fill(QColor("blue"))
        pix.save(str(covers.path(url)), "PNG")
        with patch.object(
            covers, "get", side_effect=AssertionError("Should use cache")
        ):
            loaded = covers.get_cover(url)
        self.assertFalse(loaded.isNull())
        self.assertEqual(covers.running, 0)

    def test_disabled_rockstar_and_saved_token_label(self):
        dialog = app.Sources({"enabled_Rockstar": True}, self.w)
        self.assertFalse(dialog.enabled["Rockstar"].isEnabled())
        self.assertFalse(dialog.values()["enabled_Rockstar"])
        self.assertIn("ea_token", dialog.fields)
        dialog.close()

    def test_tools_menu_holds_secondary_actions(self):
        from PySide6.QtWidgets import QPushButton

        button_texts = [b.text() for b in self.w.findChildren(QPushButton)]
        for moved in [
            "Get Metacritic data",
            "Get extra game data",
            "Backups…",
            "Retry missing details",
            "Appearance…",
        ]:
            self.assertNotIn(moved, button_texts)
        tools = next(
            b for b in self.w.findChildren(QPushButton) if b.text() == "Tools"
        )
        menu = tools.menu()
        self.assertIsNotNone(menu)
        labels = [action.text() for action in menu.actions() if action.text()]
        for expected in [
            "Appearance…",
            "Retry missing details",
            "Fetch selected details…",
            "Copies across stores…",
            "Get Metacritic data",
            "Get extra game data",
            "OpenCritic quota…",
            "Date added report…",
            "Game details report…",
            "Installation report…",
            "Save preset…",
            "Delete preset",
            "Backups…",
        ]:
            self.assertIn(expected, labels)

    def test_window_stays_within_screen_through_refresh_like_updates(self):
        self.w.show()
        settle(self.w)
        width_before = self.w.frameGeometry().width()
        self.w.statusBar().showMessage(
            "Steam: 1321 library entries loaded; date added found for 933; date added "
            "warning: Steam package API rate limited the request; remaining package "
            "mappings were postponed. Exact-title and completed ID matches are retained."
        )
        self.w.advanced_button.setText("Advanced filters… (12)")
        self.w.oc_quota_action.setText("OpenCritic quota… (999 left)")
        self.w.apply_filters()
        self.q.processEvents()
        self.assertLessEqual(self.w.frameGeometry().width(), width_before)

    def test_oversized_window_is_clamped_to_the_screen(self):
        avail = self.w.screen().availableGeometry()
        floor = self.w.centralWidget().layout().minimumSize()
        self.w.resize(avail.width() + 1200, avail.height() + 400)
        self.w.hide()
        self.w.show()
        settle(self.w)
        frame = self.w.frameGeometry()
        # The window may keep its content minimum but never its oversized geometry.
        # Frame decorations add a few pixels on top of the clamped client area.
        width_margin = frame.width() - self.w.width()
        height_margin = frame.height() - self.w.height()
        self.assertLessEqual(
            frame.width(), max(avail.width(), floor.width() + 60) + width_margin
        )
        self.assertLessEqual(
            frame.height(), max(avail.height(), floor.height() + 60) + height_margin
        )

    def test_worker_cooldown_and_manual_override(self):
        r = self.w.db.rows()[0]
        self.w.db.metadata_result(r, "unavailable", "No store page")
        seen = []

        def fake(db, rows, *args):
            seen.append([row["id"] for row in rows])
            return []

        with patch("sync_worker.run_enrichment", side_effect=fake):
            app.Worker(self.w.db, {}, "enrich", True).run()
            app.Worker(self.w.db, {}, "retry", True).run()
        self.assertNotIn(r["id"], seen[0])
        self.assertIn(r["id"], seen[1])

    def test_sources_session_controls_and_connect_results(self):
        import signin_process as session_ui

        dialog = app.Sources(
            {
                "auth_dir": str(self.root / "auth"),
                "ea_token": "manual",
                "steam_id": "old",
            },
            self.w,
        )
        self.assertIn("steam_licenses_html", dialog.fields)

        class Login:
            result_data = {"steam_id": "76561198018049642", "licenses": 100}

            def __init__(self, *args):
                pass

            def exec(self):
                return True

        with patch.object(session_ui, "ConnectSession", Login):
            dialog.connect_session("EA")
            self.assertTrue(dialog.values()["ea_session_enabled"])
            self.assertEqual(dialog.fields["ea_token"].text(), "")
            self.assertFalse(dialog.fields["ea_token"].isEnabled())
            dialog.connect_session("Steam")
            self.assertTrue(dialog.values()["steam_dates_enabled"])
            self.assertEqual(dialog.fields["steam_id"].text(), "76561198018049642")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
