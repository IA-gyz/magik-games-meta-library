import os, sys, time, threading, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from catalog_loading import CatalogLoads, prepare_catalog
    from import_worker import ImportWorker
except ImportError:
    CatalogLoads = None
from core import Database, game
import json


def wait_until(condition, timeout=5):
    end = time.monotonic() + timeout
    while not condition():
        QApplication.processEvents()
        if time.monotonic() > end:
            raise AssertionError("Background work timed out")
        time.sleep(0.001)
    QApplication.processEvents()


@unittest.skipIf(CatalogLoads is None, "PySide6 required")
class BackgroundCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def test_reads_are_background_coalesced_and_stale_results_are_discarded(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def prepare(db, links):
            self.assertNotEqual(QThread.currentThread(), self.q.thread())
            calls.append(links)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            return links

        loads = CatalogLoads(None)
        results = []
        loads.loaded.connect(results.append)
        with patch("catalog_loading.prepare_catalog", side_effect=prepare):
            try:
                loads.request({"value": 1})
                wait_until(entered.is_set)
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                wait_until(lambda: bool(heartbeat))
                self.assertTrue(loads.busy)
                loads.request({"value": 2})
                latest = {"value": 3}
                loads.request(latest)
                latest["value"] = 99
                release.set()
                wait_until(lambda: not loads.busy)
            finally:
                release.set()
                wait_until(lambda: not loads.busy)
        self.assertEqual(calls, [{"value": 1}, {"value": 3}])
        self.assertEqual(results, [{"value": 3}])

    def test_stop_finishes_read_without_publishing_or_starting_pending_work(self):
        entered = threading.Event()
        release = threading.Event()

        def prepare(*args):
            entered.set()
            release.wait(3)
            return {}

        loads = CatalogLoads(None)
        results = []
        loads.loaded.connect(results.append)
        with patch("catalog_loading.prepare_catalog", side_effect=prepare) as read:
            try:
                loads.request({})
                wait_until(entered.is_set)
                loads.request({})
                loads.stop()
                release.set()
                wait_until(lambda: not loads.busy)
            finally:
                release.set()
                wait_until(lambda: not loads.busy)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(results, [])

    def test_read_failure_is_reported_without_replacing_the_view(self):
        loads = CatalogLoads(None)
        results = []
        errors = []
        loads.loaded.connect(results.append)
        loads.failed.connect(errors.append)
        with patch(
            "catalog_loading.prepare_catalog", side_effect=ValueError("private data")
        ):
            loads.request({})
            wait_until(lambda: not loads.busy)
        self.assertEqual(results, [])
        self.assertIn("previous view was kept", errors[0])
        self.assertNotIn("private data", errors[0])

    def test_window_defers_close_until_background_read_finishes(self):
        import main_window as app
        from PySide6.QtCore import QSettings

        entered, release = threading.Event(), threading.Event()

        def prepare(*args):
            entered.set()
            release.wait(3)
            return {"rows": [], "installations": {}, "statuses": {}, "facets": {}}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(app, "ROOT", Path(tmp)),
            patch.object(
                app,
                "QSettings",
                lambda *args: QSettings(tmp + "/settings.ini", QSettings.IniFormat),
            ),
            patch("catalog_loading.prepare_catalog", side_effect=prepare),
            patch("database_connections.probe_database", side_effect=__import__("connector_io").Cancelled),
        ):
            window = app.Window()
            window.show()
            try:
                wait_until(entered.is_set)
                window.close()
                self.assertTrue(window.closing)
                self.assertTrue(window.catalog_loads.busy)
                release.set()
                wait_until(lambda: not window.catalog_loads.busy)
                wait_until(lambda: not window.isVisible())
            finally:
                release.set()
                wait_until(lambda: not window.catalog_loads.busy)
                window.close()

    def test_real_snapshot_and_facets_match_saved_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            db.save(
                [
                    game(
                        "Steam",
                        "1",
                        "A",
                        {},
                        genres="RPG",
                        date_added="2020-01-01",
                        date_added_source="Manual",
                    )
                ]
            )
            db.status("Steam", "Ready")
            db.save_installations({"entries": []})
            value = prepare_catalog(db, {})
            self.assertEqual(value["rows"][0]["date_added"], "2020-01-01")
            self.assertEqual(value["facets"]["genres"], ["RPG"])
            self.assertEqual(value["statuses"]["Steam"]["message"], "Ready")

    def test_import_commit_cancellation_rolls_back_actual_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            original = game("Steam", "1", "Original", {})
            db.save([original])
            cancel = threading.Event()
            write = db._write_rows

            def cancel_after_write(*args):
                write(*args)
                cancel.set()

            worker = ImportWorker(
                db,
                cancel,
                payload={
                    "format": "magik-library-v1",
                    "games": [game("Steam", "2", "New", {})],
                },
            )
            with patch.object(db, "_write_rows", side_effect=cancel_after_write):
                worker.run()
            self.assertEqual(worker.outcome, "cancelled")
            self.assertEqual(db.rows(), [original])

    def test_import_file_runs_in_background_and_keeps_qt_event_loop_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            path = Path(tmp) / "games.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "magik-library-v1",
                        "games": [game("Steam", "1", "A", {})],
                    }
                )
            )
            entered = threading.Event()
            release = threading.Event()
            from import_worker import import_saved_library

            def normalize(payload):
                self.assertNotEqual(QThread.currentThread(), self.q.thread())
                entered.set()
                release.wait(3)
                return import_saved_library(payload)

            worker = ImportWorker(db, threading.Event(), path=path)
            with patch("import_worker.import_saved_library", side_effect=normalize):
                try:
                    worker.start()
                    wait_until(entered.is_set)
                    heartbeat = []
                    QTimer.singleShot(0, lambda: heartbeat.append(True))
                    wait_until(lambda: bool(heartbeat))
                    self.assertTrue(worker.isRunning())
                    release.set()
                    wait_until(lambda: not worker.isRunning())
                finally:
                    release.set()
                    worker.wait(5000)
            self.assertEqual(worker.outcome, "saved")
            self.assertEqual(worker.value, 1)

    def test_raw_import_requests_store_before_any_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            worker = ImportWorker(
                db, threading.Event(), payload=[{"id": "1", "title": "A"}]
            )
            worker.run()
            self.assertEqual(worker.outcome, "choose_store")
            self.assertEqual(db.rows(), [])
