import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtWidgets import QApplication
    from sync_worker import Worker
except ImportError:
    Worker = None
from contracts import LibraryRows, Severity, OperationResult
from core import Database, game
from connectors import FetchError, Cancelled


@unittest.skipIf(Worker is None, "PySide6 required")
class WorkerResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def execute(self, db, mode="sync", enrich=False):
        worker = Worker(db, {"enabled_Steam": True, "enabled_Epic": True}, mode, enrich)
        results = []
        worker.result.connect(results.append)
        worker.run()
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], OperationResult)
        return results[0]

    def test_store_failure_isolated_and_results_typed(self):
        def steam(*args):
            return LibraryRows(
                [game("Steam", "1", "A", {})],
                {"store": "Steam", "warnings": ["date history unavailable"]},
            )

        def epic(*args):
            raise FetchError("HTTP 401", status=401)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("sync_worker.FETCHERS", Steam=steam, Epic=epic),
        ):
            db = Database(Path(tmp) / "db")
            result = self.execute(db)
            self.assertEqual(
                [event.severity for event in result.events],
                [Severity.WARNING, Severity.ERROR],
            )
            self.assertIn("Heroic or Legendary", result.text)
            self.assertIn("HTTP 401", result.text)
            self.assertTrue(result.failed)
            self.assertFalse(result.cancelled)
            self.assertEqual(len(db.rows()), 1)
            self.assertNotIn("_acquisition_report", db.rows()[0])
            self.assertEqual(db.statuses()["Epic"]["severity"], "error")

    def test_cancellation_retains_completed_source_and_no_false_failure(self):
        def steam(*args):
            return [game("Steam", "1", "A", {})]

        def epic(*args):
            raise Cancelled()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("sync_worker.FETCHERS", Steam=steam, Epic=epic),
        ):
            db = Database(Path(tmp) / "db")
            result = self.execute(db)
            self.assertTrue(result.cancelled)
            self.assertFalse(result.failed)
            self.assertEqual(result.events[0].severity, Severity.SUCCESS)
            self.assertEqual(len(db.rows()), 1)
            self.assertNotIn("Epic", db.statuses())

    def test_successful_scan_is_not_warning_because_summary_contains_unknown(self):
        snapshot = {"entries": [], "notes": [], "covered": []}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("sync_worker.scan_installations", return_value=snapshot),
        ):
            result = self.execute(Database(Path(tmp) / "db"), "scan")
            self.assertIn("0 unknown", result.text)
            self.assertEqual(result.events[0].severity, Severity.SUCCESS)

    def test_details_wait_while_date_lookups_are_postponed(self):
        report = {
            "store": "Steam",
            "warnings": [],
            "date_fetch_incomplete": True,
            "postponed_packages": 2,
        }

        def steam(*args):
            return LibraryRows([game("Steam", "1", "A", {})], report)

        def epic(*args):
            return []

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("sync_worker.FETCHERS", Steam=steam, Epic=epic),
            patch("sync_worker.select_candidates", return_value=([], 0)) as select,
            patch("sync_worker.run_enrichment", return_value=[]) as run,
        ):
            result = self.execute(Database(Path(tmp) / "db"), enrich=True)
        run.assert_not_called()
        select.assert_not_called()
        self.assertTrue(any("Date added" in event.text for event in result.events))

    def test_details_run_when_date_lookups_are_complete(self):
        report = {"store": "Steam", "warnings": []}

        def steam(*args):
            return LibraryRows([game("Steam", "1", "A", {})], report)

        def epic(*args):
            return []

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("sync_worker.FETCHERS", Steam=steam, Epic=epic),
            patch("sync_worker.select_candidates", return_value=([], 0)) as select,
            patch("sync_worker.run_enrichment", return_value=[]) as run,
        ):
            result = self.execute(Database(Path(tmp) / "db"), enrich=True)
        run.assert_called_once()
        self.assertFalse(any(event.text.startswith("Date added:") for event in result.events))
