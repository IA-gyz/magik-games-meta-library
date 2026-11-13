import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_export import export_catalog
from catalog_data import FIELDS


class CatalogExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "games.json"
        self.rows = [
            {
                "store": "GOG",
                "id": "2",
                "title": 'Été, "Hello"\nWorld',
                "date_added": "2020-01-02",
                "raw": {"x": 1},
            },
            {"store": "Steam", "id": "1", "title": "A", "playtime": 0},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_preserves_format_order_dates_and_input(self):
        before = json.dumps(self.rows)
        export_catalog(self.path, self.rows)
        payload = json.loads(self.path.read_text())
        self.assertEqual(payload, {"format": "magik-library-v1", "games": self.rows})
        self.assertEqual(json.dumps(self.rows), before)
        self.assertIn("Été", self.path.read_text())
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_csv_preserves_fields_escaping_and_order(self):
        export_catalog(self.path, self.rows, "csv")
        with self.path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, FIELDS)
        self.assertEqual(rows[0]["title"], self.rows[0]["title"])
        self.assertEqual(rows[0]["date_added"], "2020-01-02")
        self.assertEqual(rows[1]["playtime"], "0")

    def test_names_only_json_lists_titles_in_order_without_games(self):
        export_catalog(self.path, self.rows, scope="names")
        payload = json.loads(self.path.read_text())
        self.assertEqual(
            payload,
            {
                "format": "magik-library-names-v1",
                "names": ['Été, "Hello"\nWorld', "A"],
            },
        )
        self.assertIn("Été", self.path.read_text())
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_names_only_csv_keeps_escaping_in_single_title_column(self):
        export_catalog(self.path, self.rows, "csv", scope="names")
        with self.path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, ["title"])
        self.assertEqual(
            [row["title"] for row in rows], ['Été, "Hello"\nWorld', "A"]
        )

    def test_names_and_dates_json_pairs_titles_with_dates_added(self):
        export_catalog(self.path, self.rows, scope="names_dates")
        payload = json.loads(self.path.read_text())
        self.assertEqual(
            payload,
            {
                "format": "magik-library-names-dates-v1",
                "games": [
                    {"title": 'Été, "Hello"\nWorld', "date_added": "2020-01-02"},
                    {"title": "A", "date_added": None},
                ],
            },
        )
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_names_and_dates_csv_writes_title_and_date_columns(self):
        export_catalog(self.path, self.rows, "csv", scope="names_dates")
        with self.path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, ["title", "date_added"])
        self.assertEqual(rows[0]["title"], 'Été, "Hello"\nWorld')
        self.assertEqual(rows[0]["date_added"], "2020-01-02")
        self.assertEqual(rows[1]["title"], "A")
        self.assertEqual(rows[1]["date_added"], "")

    def test_reduced_export_does_not_mutate_input_rows(self):
        before = json.dumps(self.rows)
        export_catalog(self.path, self.rows, scope="names")
        export_catalog(self.path, self.rows, scope="names_dates")
        self.assertEqual(json.dumps(self.rows), before)

    def test_names_only_empty_export(self):
        export_catalog(self.path, [], scope="names")
        self.assertEqual(json.loads(self.path.read_text())["names"], [])
        export_catalog(self.path, [], scope="names_dates")
        self.assertEqual(json.loads(self.path.read_text())["games"], [])

    def test_invalid_scope_rejected_without_touching_destination(self):
        self.path.write_text("previous export")
        with self.assertRaises(ValueError):
            export_catalog(self.path, self.rows, scope="bad")
        self.assertEqual(self.path.read_text(), "previous export")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_serialization_failure_preserves_previous_file(self):
        self.path.write_text("previous export")
        with self.assertRaises(TypeError):
            export_catalog(self.path, [{"bad": object()}])
        self.assertEqual(self.path.read_text(), "previous export")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_replace_failure_cleans_temporary_file(self):
        self.path.write_text("previous export")
        with patch("catalog_export.Path.replace", side_effect=OSError("disk problem")):
            with self.assertRaises(OSError):
                export_catalog(self.path, self.rows)
        self.assertEqual(self.path.read_text(), "previous export")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_flush_failure_does_not_publish_partial_file(self):
        with patch("catalog_export.os.fsync", side_effect=OSError("full disk")):
            with self.assertRaises(OSError):
                export_catalog(self.path, self.rows)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_permissions_and_symlink_are_preserved(self):
        self.path.write_text("old")
        self.path.chmod(0o640)
        link = self.root / "link.json"
        link.symlink_to(self.path.name)
        export_catalog(link, self.rows)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(json.loads(link.read_text())["games"], self.rows)

    def test_empty_export_and_invalid_format(self):
        export_catalog(self.path, [])
        self.assertEqual(json.loads(self.path.read_text())["games"], [])
        with self.assertRaises(ValueError):
            export_catalog(self.path, [], "bad")
        self.assertEqual(json.loads(self.path.read_text())["games"], [])
