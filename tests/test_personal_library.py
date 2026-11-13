import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import game
from storage import Database
from personal_library import save_personal, normalize_tags, annotations
from browsing import matches
from browsing_state import normalize_snapshot
from catalog_export import export_catalog
from catalog_import import import_saved_library


class PersonalLibraryTests(unittest.TestCase):
    def test_refresh_does_not_erase_and_clear_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'db')
            row = game('Steam', '620', 'Portal 2', {})
            db.save([row])
            save_personal(db, row, True, 'With kids, Try next, WITH KIDS')
            db.save([game('Steam', '620', 'Portal 2', {'store_details': True})])
            current = db.rows()[0]
            self.assertEqual(current['personal_tags'], 'With kids, Try next')
            self.assertTrue(current['favorite'])
            self.assertTrue(current['raw']['store_details'])
            save_personal(db, current, False, '')
            current = db.rows()[0]
            self.assertFalse(current['favorite'])
            self.assertEqual(current['personal_tags'], '')
            self.assertTrue(current['raw']['store_details'])

    def test_filter_and_preset(self):
        row = {'favorite': True, 'personal_tags': 'With kids, Try next', 'store': 'GOG'}
        self.assertTrue(matches(row, {'favorites': True, 'personal_tags': ['With kids']}))
        self.assertTrue(matches(row, {'search': 'kids'}))
        self.assertFalse(matches(row, {'personal_tags': ['Finished']}))
        self.assertFalse(matches({}, {'favorites': True}))
        filters = normalize_snapshot({'filters': {'favorites': True, 'personal_tags': ['Try next']}}, 80)['filters']
        self.assertTrue(filters['favorites'])
        self.assertEqual(filters['personal_tags'], ['Try next'])
        self.assertFalse(normalize_snapshot({}, 80)['filters']['favorites'])

    def test_malformed_imported_annotation_and_tag_limits(self):
        self.assertEqual(annotations({'raw': {'personal': []}}), {'favorite': False, 'personal_tags': ''})
        self.assertEqual(normalize_tags(' A ; a | B\nC '), 'A, B, C')
        self.assertEqual(len(normalize_tags(','.join(str(i) for i in range(100))).split(', ')), 40)

    def test_export_import_annotations(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            db = Database(directory / 'db')
            row = game('GOG', '1', 'Game', {})
            db.save([row])
            save_personal(db, row, True, 'Finished')
            path = directory / 'games.json'
            export_catalog(path, db.rows())
            other = Database(directory / 'other')
            other.save(import_saved_library(json.loads(path.read_text())))
            self.assertTrue(other.rows()[0]['favorite'])
            self.assertEqual(other.rows()[0]['personal_tags'], 'Finished')
