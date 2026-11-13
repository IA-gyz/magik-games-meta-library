import json, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import LibraryRows, LibraryResult, LogEntry, Severity, OperationResult
from core import game, Database
from library_service import refresh_store
from connectors import Cancelled, FetchError
from acquisition import optional_dates


class ContractsTests(unittest.TestCase):
    def test_batch_report_is_not_a_game_field_and_legacy_input_not_mutated(self):
        report = {"store": "Steam", "warnings": [], "matched": 1}
        row = game("Steam", "1", "A", {})
        row["_acquisition_report"] = report
        payload = [row]
        batch = LibraryResult.from_provider("Steam", payload)
        self.assertIn("_acquisition_report", row)
        self.assertNotIn("_acquisition_report", batch.rows[0])
        batch.acquisition_report["warnings"].append("changed")
        self.assertEqual(report["warnings"], [])

    def test_malformed_cross_store_and_conflicting_batches_rejected(self):
        for payload in [
            {},
            [game("Epic", "1", "A", {})],
            LibraryRows([], {"store": "GOG"}),
            [{"store": "Steam", "id": ""}],
        ]:
            with self.assertRaises(ValueError):
                LibraryResult.from_provider("Steam", payload)
        report = {"warnings": []}
        row = game("Steam", "1", "A", {})
        row["_acquisition_report"] = {"warnings": ["other"]}
        with self.assertRaises(ValueError):
            LibraryResult.from_provider("Steam", LibraryRows([row], report))

    def test_empty_library_still_persists_acquisition_failure(self):
        rows = optional_dates(
            "EA", [], Mock(), Mock(side_effect=FetchError("HTTP 404"))
        )
        self.assertEqual(rows, [])
        self.assertEqual(rows.acquisition_report["warnings"], ["HTTP 404"])
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            event = refresh_store(
                db, "EA", {}, threading.Event(), Mock(), Mock(return_value=rows)
            )
            self.assertEqual(event.severity, Severity.WARNING)
            self.assertEqual(db.acquisition_reports()[0]["warnings"], ["HTTP 404"])
            self.assertEqual(db.statuses()["EA"]["severity"], "warning")

    def test_refresh_store_collects_this_runs_acquisition_reports(self):
        rows = optional_dates(
            "EA", [], Mock(), Mock(side_effect=FetchError("HTTP 404"))
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            collected = {}
            refresh_store(
                db, "EA", {}, threading.Event(), Mock(),
                Mock(return_value=rows), reports=collected,
            )
        self.assertEqual(collected["EA"]["warnings"], ["HTTP 404"])

    def test_cancel_after_query_does_not_write_rows_or_report(self):
        cancel = threading.Event()
        db = Mock()

        def fetch(*args):
            cancel.set()
            return LibraryRows([game("Steam", "1", "A", {})], {"warnings": []})

        with self.assertRaises(Cancelled):
            refresh_store(db, "Steam", {}, cancel, Mock(), fetch)
        db.save_refresh.assert_not_called()
        db.save.assert_not_called()
        db.save_acquisition_report.assert_not_called()
        db.status.assert_not_called()

    def test_old_status_payload_and_new_severity_can_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db")
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO status VALUES (?,?)",
                    (
                        "Steam",
                        json.dumps(
                            {"message": "old", "count": 1, "time": "2020-01-01"}
                        ),
                    ),
                )
            db.status("EA", "Failed", severity="error")
            self.assertNotIn("severity", db.statuses()["Steam"])
            self.assertEqual(db.statuses()["EA"]["severity"], "error")

    def test_log_severity_is_explicit_even_with_misleading_words(self):
        event = LogEntry("0 failed, 0 unknown, 2 installed", "success", "Steam")
        self.assertEqual(event.severity, Severity.SUCCESS)
        with self.assertRaises(ValueError):
            LogEntry("A", "arbitrary")
