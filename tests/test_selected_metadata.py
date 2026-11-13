import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import game
from storage import Database
from extra_metadata import run_extra
from test_extra_metadata import FastCancel, options
from metacritic import run_metacritic
from test_metacritic import page


class SelectedMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'db')
        self.first = game('GOG', '1', 'Portal Two', {}, release='2011-04-19')
        self.other = game('GOG', '2', 'Other game', {})
        self.db.save([self.first, self.other])
        self.cancel = FastCancel()

    def test_corrected_metacritic_title_scoped_and_cache_invalidated(self):
        from metadata_review import save_matches
        save_matches(self.db, self.first, {'Metacritic': 'Portal 2'})
        row = next(r for r in self.db.rows() if r['id'] == '1')
        urls = []
        def fetch(url):
            urls.append(url)
            return page()
        run_metacritic(self.db, self.cancel, lambda _: None, lambda: None, fetch, rows=[row])
        self.assertEqual(len(urls), 1)
        rows = {r['id']: r for r in self.db.rows()}
        self.assertEqual(rows['1']['title'], 'Portal Two')
        self.assertEqual(rows['1']['score'], 95)
        self.assertFalse(rows['2'].get('mc_checked'))
        run_metacritic(self.db, self.cancel, lambda _: None, lambda: None, fetch, rows=[rows['1']])
        self.assertEqual(len(urls), 1)
        run_metacritic(self.db, self.cancel, lambda _: None, lambda: None, fetch, rows=[rows['1']], force=True)
        self.assertEqual(len(urls), 2)
        save_matches(self.db, rows['1'], {})
        self.assertEqual(next(r for r in self.db.rows() if r['id'] == '1')['raw']['metadata_matches']['Metacritic'], '')

    def test_extra_override_preserves_catalog_and_other_rows(self):
        from metadata_review import save_matches
        save_matches(self.db, self.first, {'OpenCritic': 'Portal 2'})
        row = next(r for r in self.db.rows() if r['id'] == '1')
        seen = []
        def oc(client, request):
            seen.append(request['title'])
            return {'oc_score': 90}, {'id': 123}
        with patch('extra_metadata.Clients.opencritic', oc):
            run_extra(self.db, {**options('OpenCritic'), 'opencritic_api_key': 'test'}, self.cancel, lambda _: None, lambda: None, rows=[row])
        self.assertEqual(seen, ['Portal 2'])
        rows = {r['id']: r for r in self.db.rows()}
        self.assertEqual(rows['1']['oc_score'], 90)
        self.assertEqual(rows['1']['title'], 'Portal Two')
        self.assertFalse(rows['2'].get('opencritic_checked'))

    def test_worker_limits_all_phases_and_reloads_between_sources(self):
        from sync_worker import Worker
        seen = []
        def extra(db, options, *args, rows=None, **kwargs):
            seen.extend((r['store'], str(r['id'])) for r in rows)
            return []
        with patch('extra_metadata.run_extra', extra):
            worker = Worker(self.db, {}, 'selected', False, selected={('GOG', '1')}, sources=['ProtonDB'])
            worker.run()
        self.assertEqual(seen, [('GOG', '1')])

    def test_review_ui_plain_text_and_sources(self):
        from PySide6.QtWidgets import QApplication
        from metadata_review import MatchReview, FetchSelected
        app = QApplication.instance() or QApplication([])
        dialog = MatchReview(self.first)
        self.assertEqual(dialog.values(), {})
        dialog.edits['IGDB'].setText(' Portal 2 ')
        self.assertEqual(dialog.values(), {'IGDB': 'Portal 2'})
        fetch = FetchSelected(2, {})
        self.assertEqual(fetch.sources(), ['Store details'])
        dialog.close()
        fetch.close()
        app.processEvents()
