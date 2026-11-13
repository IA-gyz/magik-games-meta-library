import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import game
from storage import Database
from extra_metadata import Clients, run_extra
from request_budgets import request_limit, BudgetExhausted
from test_extra_metadata import FastCancel, options
from configuration import normalize_options


class RequestBudgetTests(unittest.TestCase):
    def test_defaults_and_configuration_validation(self):
        self.assertEqual(request_limit({}, 'OpenCritic'), 50)
        self.assertEqual(request_limit({}, 'SteamGridDB'), 0)
        self.assertEqual(request_limit({'request_budget_OpenCritic': '12'}, 'OpenCritic'), 12)
        for value in (True, -4, 'invalid', float('nan')):
            self.assertEqual(request_limit({'request_budget_OpenCritic': value}, 'OpenCritic'), 50)
        self.assertEqual(normalize_options({'request_budget_OpenCritic': '6'})['request_budget_OpenCritic'], 6)

    def test_requests_are_counted_before_failed_call_and_gate_retries(self):
        calls = []
        def call(url):
            calls.append(url)
            raise ValueError('failed')
        clients = Clients({}, FastCancel(), call)
        clients.limit = 1
        with self.assertRaises(ValueError):
            clients.get('https://example.invalid/first')
        with self.assertRaises(BudgetExhausted):
            clients.get('https://example.invalid/second')
        self.assertEqual(len(calls), 1)
        self.assertEqual(clients.requests, 1)

    def test_partial_opencritic_game_is_not_negative_cached_and_other_source_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'db')
            row = game('Steam', '620', 'Portal 2', {})
            db.save([row])
            calls = []
            def call(url, **kwargs):
                calls.append(url)
                if 'protondb' in url:
                    return {'tier': 'gold', 'total': 10, 'confidence': 'strong'}
                if '/game/search?' in url:
                    return [{'id': 123, 'name': 'Portal 2'}]
                self.fail('Budget allowed an extra OpenCritic request')
            events = run_extra(db, {**options('ProtonDB', 'OpenCritic'), 'opencritic_api_key': 'test', 'request_budget_OpenCritic': 1}, FastCancel(), lambda _: None, lambda: None, call)
            current = db.rows()[0]
            self.assertEqual(current['proton_tier'], 'gold')
            self.assertFalse(current.get('opencritic_checked'))
            self.assertNotIn('OpenCritic', current['raw'].get('extra_metadata', {}))
            self.assertTrue(any('local cap of 1' in e.text for e in events))
            self.assertEqual(len(calls), 2)

    def test_multiple_games_stop_at_cap_and_completed_results_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'db')
            db.save([game('Steam', str(i), 'Game ' + str(i), {}) for i in (1, 2, 3)])
            calls = []
            messages = []
            def call(url, **kwargs):
                calls.append(url)
                return {'tier': 'gold', 'total': 2}
            settings = {**options('ProtonDB'), 'request_budget_ProtonDB': 1}
            run_extra(db, settings, FastCancel(), messages.append, lambda: None, call)
            self.assertEqual(len(calls), 1)
            self.assertEqual(sum(bool(r.get('protondb_checked')) for r in db.rows()), 1)
            self.assertTrue(any('1 requests / 1' in message for message in messages))
            run_extra(db, settings, FastCancel(), messages.append, lambda: None, call)
            self.assertEqual(len(calls), 2)
            self.assertEqual(sum(bool(r.get('protondb_checked')) for r in db.rows()), 2)

    def test_budget_stop_does_not_block_a_later_source(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'db')
            db.save([game('Steam', '620', 'Portal 2', {})])
            calls = []
            def call(url, **kwargs):
                calls.append(url)
                if 'steamgriddb' in url:
                    return {'success': True, 'data': {'id': 1}}
                if '/game/search?' in url:
                    return [{'id': 2, 'name': 'Portal 2'}]
                return {'id': 2, 'name': 'Portal 2', 'topCriticScore': 95}
            run_extra(db, {**options('SteamGridDB', 'OpenCritic'), 'sgdb_api_key': 'test', 'opencritic_api_key': 'test', 'request_budget_SteamGridDB': 1, 'request_budget_OpenCritic': 2}, FastCancel(), lambda _: None, lambda: None, call)
            current = db.rows()[0]
            self.assertFalse(current.get('steamgriddb_checked'))
            self.assertEqual(current['oc_score'], 95)
            self.assertEqual(len(calls), 3)
