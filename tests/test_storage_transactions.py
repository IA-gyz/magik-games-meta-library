import threading
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Database, game
from connectors import Cancelled
import storage, catalog_data, core


class RefreshTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db")
        self.db.save(
            [
                game(
                    "Steam",
                    "1",
                    "Original",
                    {"store_details": {"type": "game"}},
                    date_added="2019-01-01",
                    date_added_source="Manual",
                    genres="RPG",
                ),
                game("Steam", "2", "Cached only", {}),
            ]
        )
        self.db.save_acquisition_report(
            "Steam", {"store": "Steam", "matched": 7, "warnings": ["previous"]}
        )
        self.db.status("Steam", "Previous result", 2)
        self.before = self.snapshot()

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        with self.db.connect() as connection:
            return {
                name: connection.execute(
                    "SELECT * FROM " + name + " ORDER BY 1,2"
                ).fetchall()
                for name in ["games", "status", "local_state", "metadata_results"]
            }

    def rows(self):
        return [
            game(
                "Steam",
                "1",
                "Refreshed",
                {},
                date_added="2020-01-01",
                date_added_source="Account",
            ),
            game("Steam", "3", "New", {}),
        ]

    def commit(self, **kwargs):
        self.db.save_refresh(
            "Steam",
            self.rows(),
            {"store": "Steam", "matched": 1, "warnings": []},
            "New result",
            severity="success",
            **kwargs,
        )

    def test_refresh_commits_report_status_and_reconciliation_with_existing_merges(
        self,
    ):
        self.commit()
        rows = {row["id"]: row for row in self.db.rows()}
        self.assertEqual(set(rows), {"1", "2", "3"})
        self.assertTrue(rows["1"]["active"])
        self.assertFalse(rows["2"]["active"])
        self.assertTrue(rows["3"]["active"])
        self.assertEqual(rows["1"]["date_added"], "2019-01-01")
        self.assertEqual(rows["1"]["date_added_source"], "Manual")
        self.assertEqual(rows["1"]["genres"], "RPG")
        self.assertIn("store_details", rows["1"]["raw"])
        status = self.db.statuses()["Steam"]
        report = self.db.acquisition_reports()[0]
        self.assertEqual(status["count"], 2)
        self.assertEqual(status["severity"], "success")
        self.assertEqual(status["time"], report["time"])
        self.assertEqual(report["matched"], 1)

    def test_failure_after_report_sql_rolls_back_rows_reconciliation_and_report(self):
        write = self.db._write_acquisition_report

        def fail(*args, **kwargs):
            write(*args, **kwargs)
            raise RuntimeError("injected report write failure")

        with (
            patch.object(self.db, "_write_acquisition_report", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            self.commit()
        self.assertEqual(self.snapshot(), self.before)

    def test_failure_after_status_sql_rolls_back_every_write(self):
        write = self.db._write_status

        def fail(*args, **kwargs):
            write(*args, **kwargs)
            raise RuntimeError("injected status write failure")

        with (
            patch.object(self.db, "_write_status", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            self.commit()
        self.assertEqual(self.snapshot(), self.before)

    def test_cancel_before_commit_rolls_back_all_parts(self):
        def stop():
            raise Cancelled()

        with self.assertRaises(Cancelled):
            self.commit(before_commit=stop)
        self.assertEqual(self.snapshot(), self.before)

    def test_row_serialization_failure_rolls_back_earlier_row_writes(self):
        rows = self.rows()
        rows[-1]["description"] = object()
        with self.assertRaises(TypeError):
            self.db.save_refresh("Steam", rows, {}, "Bad")
        self.assertEqual(self.snapshot(), self.before)

    def test_empty_complete_and_partial_results_keep_original_semantics(self):
        self.db.save_refresh("Steam", [], {"matched": 0}, "Empty", complete=False)
        self.assertTrue(all(row["active"] for row in self.db.rows()))
        self.db.save_refresh("Steam", [], None, "Empty complete", complete=True)
        self.assertTrue(all(not row["active"] for row in self.db.rows()))
        self.assertEqual(self.db.statuses()["Steam"]["count"], 0)
        self.assertEqual(self.db.acquisition_reports()[0]["matched"], 0)

    def test_cross_store_batch_cannot_reconcile_selected_store(self):
        with self.assertRaises(ValueError):
            self.db.save_refresh(
                "Steam", [game("EA", "1", "Wrong store", {})], None, "Bad"
            )
        self.assertEqual(self.snapshot(), self.before)

    def test_readers_only_see_previous_snapshot_until_commit(self):
        observed = []
        write = self.db._write_status

        def inspect(*args, **kwargs):
            write(*args, **kwargs)
            observed.append(self.snapshot())

        with patch.object(self.db, "_write_status", side_effect=inspect):
            self.commit()
        self.assertEqual(observed, [self.before])
        self.assertNotEqual(self.snapshot(), self.before)

    def test_manual_date_clear_and_missing_row(self):
        self.assertTrue(self.db.set_manual_date("Steam", "1", None))
        row = next(row for row in self.db.rows() if row["id"] == "1")
        self.assertIsNone(row["date_added"])
        self.assertEqual(row["date_added_source"], "Manual")
        self.assertFalse(self.db.set_manual_date("Steam", "missing", "2020-01-01"))

    def test_manual_edit_waits_for_refresh_then_keeps_fresh_metadata(self):
        written = threading.Event()
        release = threading.Event()
        editing = threading.Event()
        done = threading.Event()
        errors = []
        write = self.db._write_status

        def pause(*args, **kwargs):
            write(*args, **kwargs)
            written.set()
            if not release.wait(3):
                raise RuntimeError("Test timed out waiting for release")

        def refresh():
            try:
                self.commit()
            except Exception as exc:
                errors.append(exc)

        def edit():
            editing.set()
            try:
                self.db.set_manual_date("Steam", "1", "2021-02-03")
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()

        writer = threading.Thread(target=refresh)
        editor = threading.Thread(target=edit)
        with patch.object(self.db, "_write_status", side_effect=pause):
            writer.start()
            try:
                self.assertTrue(written.wait(2))
                editor.start()
                self.assertTrue(editing.wait(1))
                self.assertFalse(done.wait(0.05))
            finally:
                release.set()
                writer.join(4)
                if editor.ident is not None:
                    editor.join(4)
        self.assertFalse(writer.is_alive())
        self.assertFalse(editor.is_alive())
        self.assertEqual(errors, [])
        row = next(row for row in self.db.rows() if row["id"] == "1")
        self.assertEqual(row["title"], "Refreshed")
        self.assertEqual(row["date_added"], "2021-02-03")
        self.assertIn("store_details", row["raw"])

    def test_compatibility_facade_preserves_catalog_and_database_imports(self):
        self.assertIs(core.Database, storage.Database)
        self.assertIs(core.game, catalog_data.game)
        self.assertIs(core.normalize, catalog_data.normalize)
