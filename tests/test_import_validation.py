import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_import import normalize_import, import_saved_library
from catalog_data import game


class ImportValidationTests(unittest.TestCase):
    def row(self, **changes):
        return {**game("Steam", "1", "A", {}), **changes}

    def test_valid_export_roundtrip_preserves_manual_dates(self):
        row = self.row(
            playtime=0, score=88, date_added="2020-01-02", date_added_source="Manual"
        )
        rows = import_saved_library({"games": [row]})
        for key in [
            "playtime",
            "score",
            "date_added",
            "date_added_source",
            "id",
            "title",
        ]:
            self.assertEqual(rows[0][key], row[key])

    def test_bad_numeric_and_boolean_fields_are_rejected(self):
        for changes in [
            {"playtime": "many"},
            {"playtime": True},
            {"playtime": -1},
            {"score": 101},
            {"score": float("nan")},
            {"playtime": float("inf")},
            {"playtime": 10**1000},
            {"active": "false"},
            {"last_played": []},
            {"description": {}},
            {"title": ["A"]},
            {"id": {}},
            {"raw": []},
        ]:
            with self.subTest(field=next(iter(changes))):
                with self.assertRaises(ValueError):
                    normalize_import("Steam", [self.row(**changes)])

    def test_whole_batch_validates_before_return(self):
        with self.assertRaisesRegex(ValueError, "Game 2"):
            normalize_import("Steam", [self.row(), self.row(id="2", playtime="bad")])

    def test_native_library_rejects_unknown_stores_and_wrong_shapes(self):
        for payload in [
            {"games": {}},
            {"games": [None]},
            {"games": [self.row(store="Other")]},
        ]:
            with self.assertRaises(ValueError):
                import_saved_library(payload)

    def test_provider_formats_still_normalize(self):
        rows = normalize_import("Amazon", [{"product": {"id": "a", "title": "A"}}])
        self.assertEqual(rows[0]["title"], "A")
