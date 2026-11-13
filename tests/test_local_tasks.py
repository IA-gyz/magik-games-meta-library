import os, sys, time, json, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Database, game
from catalog_export import export_catalog
from connectors import Cancelled

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QThread, QTimer
    from local_tasks import LocalTask
except ImportError:
    LocalTask = None


def wait_until(condition):
    end = time.monotonic() + 5
    while not condition():
        QApplication.processEvents()
        if time.monotonic() > end:
            raise AssertionError("Task did not finish")
        time.sleep(0.001)
    QApplication.processEvents()


class ExportCancellationTests(unittest.TestCase):
    def test_cancel_during_json_encoding_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text("previous")
            checks = 0

            def cancel():
                nonlocal checks
                checks += 1
                if checks == 8:
                    raise Cancelled()

            with self.assertRaises(Cancelled):
                export_catalog(path, [game("Steam", "1", "A", {})], check_cancel=cancel)
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_cancel_at_final_publication_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.csv"
            path.write_text("previous")
            checks = 0

            def cancel():
                nonlocal checks
                checks += 1
                if checks == 3:
                    raise Cancelled()  # Initial, row, final replacement.

            with self.assertRaises(Cancelled):
                export_catalog(
                    path, [game("Steam", "1", "A", {})], "csv", check_cancel=cancel
                )
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(list(Path(tmp).iterdir()), [path])


@unittest.skipIf(LocalTask is None, "PySide6 required")
class LocalTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "db")
        self.db.save([game("Steam", "1", "A", {})])

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_runs_off_ui_thread_and_stays_responsive(self):
        entered = threading.Event()
        release = threading.Event()

        def writer(*args, **kwargs):
            self.assertNotEqual(QThread.currentThread(), self.q.thread())
            entered.set()
            release.wait(3)
            return export_catalog(*args, **kwargs)

        task = LocalTask(
            "export",
            self.db,
            threading.Event(),
            rows=self.db.rows(),
            path=self.root / "export.json",
        )
        with patch("local_tasks.export_catalog", side_effect=writer):
            try:
                task.start()
                wait_until(entered.is_set)
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                wait_until(lambda: bool(heartbeat))
                self.assertTrue(task.isRunning())
                release.set()
                wait_until(lambda: not task.isRunning())
            finally:
                release.set()
                task.wait(5000)
        self.assertEqual(task.outcome, "saved")
        self.assertEqual(
            json.loads((self.root / "export.json").read_text())["games"][0]["title"],
            "A",
        )

    def test_report_read_and_format_run_off_ui_thread(self):
        entered = threading.Event()
        release = threading.Event()
        original = self.db.report_snapshot

        def read(kind):
            self.assertNotEqual(QThread.currentThread(), self.q.thread())
            entered.set()
            release.wait(3)
            return original(kind)

        task = LocalTask("metadata", self.db, threading.Event())
        with patch.object(self.db, "report_snapshot", side_effect=read):
            try:
                task.start()
                wait_until(entered.is_set)
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                wait_until(lambda: bool(heartbeat))
                release.set()
                wait_until(lambda: not task.isRunning())
            finally:
                release.set()
                task.wait(5000)
        self.assertEqual(task.outcome, "report")
        self.assertEqual(task.value["title"], "Game details report")

    def test_cancelled_report_does_not_publish_a_result(self):
        cancel = threading.Event()

        def read(kind):
            cancel.set()
            return []

        task = LocalTask("acquisition", self.db, cancel)
        with patch.object(self.db, "report_snapshot", side_effect=read):
            task.run()
        self.assertEqual(task.outcome, "cancelled")
        self.assertIsNone(task.value)

    def test_late_stop_after_published_export_still_reports_saved(self):
        cancel = threading.Event()
        path = self.root / "export.json"

        def writer(*args, **kwargs):
            export_catalog(*args, **kwargs)
            cancel.set()

        task = LocalTask("export", self.db, cancel, rows=self.db.rows(), path=path)
        with patch("local_tasks.export_catalog", side_effect=writer):
            task.run()
        self.assertEqual(task.outcome, "saved")
        self.assertTrue(path.exists())

    def test_export_names_only_passes_scope_to_writer(self):
        seen = {}

        def writer(path, rows, file_format, **kwargs):
            seen.update(kwargs)
            return export_catalog(path, rows, file_format, **kwargs)

        path = self.root / "names.json"
        task = LocalTask(
            "export",
            self.db,
            threading.Event(),
            rows=self.db.rows(),
            path=path,
            scope="names",
        )
        with patch("local_tasks.export_catalog", side_effect=writer):
            task.run()
        self.assertEqual(task.outcome, "saved")
        self.assertEqual(seen.get("scope"), "names")
        self.assertEqual(json.loads(path.read_text())["names"], ["A"])

    def test_export_names_and_dates_task_writes_pairs(self):
        path = self.root / "dates.json"
        task = LocalTask(
            "export",
            self.db,
            threading.Event(),
            rows=self.db.rows(),
            path=path,
            scope="names_dates",
        )
        task.run()
        self.assertEqual(task.outcome, "saved")
        payload = json.loads(path.read_text())
        self.assertEqual(payload["format"], "magik-library-names-dates-v1")
        self.assertEqual(
            payload["games"], [{"title": "A", "date_added": None}]
        )

    def test_all_report_kinds_build_from_real_snapshots(self):
        self.db.save_acquisition_report(
            "Steam", {"store": "Steam", "matched": 1, "unmatched_games": 0}
        )
        for kind, title in [
            ("installations", "Installed games report"),
            ("acquisition", "Date added report"),
            ("metadata", "Game details report"),
        ]:
            task = LocalTask(kind, self.db, threading.Event())
            task.run()
            self.assertEqual(task.outcome, "report")
            self.assertEqual(task.value["title"], title)
