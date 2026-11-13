import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opencritic_quota import Quota, QuotaPaused, parse_headers, describe
from extra_metadata import Clients, run_extra
from test_extra_metadata import FastCancel, options
from storage import Database
from core import game
from connector_io import FetchError


def headers(remaining, reset=60, limit=100):
    return {'X-RateLimit-Requests-Remaining': str(remaining), 'X-RateLimit-Requests-Limit': str(limit), 'X-RateLimit-Requests-Reset': str(reset)}


class OpenCriticQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.options = {**options('OpenCritic'), 'opencritic_api_key': 'never-saved-test-key', 'auth_dir': self.tmp.name}
        self.quota = Quota(self.options)

    def test_header_units_case_and_allowlist(self):
        parsed = parse_headers({**headers(8, 60), 'Authorization': 'never-store'}, now=1000)
        self.assertEqual(parsed['x-ratelimit-requests']['reset_at'], 1065)
        self.assertEqual(parsed['x-ratelimit-requests']['remaining'], 8)
        self.assertNotIn('authorization', parsed)
        self.assertEqual(parse_headers({'x-ratelimit-requests-remaining': 'NaN'}), {})
        self.assertNotIn('reset_at', parse_headers(headers(8, 999999999999), now=1000)['x-ratelimit-requests'])

    def test_persistent_reservations_and_credential_separation(self):
        self.quota.observe(headers(4))
        self.quota.reserve()
        self.quota.reserve()
        with self.assertRaises(QuotaPaused):
            Quota(self.options).reserve()
        self.assertNotIn('never-saved-test-key', self.quota.path.read_text())
        self.assertEqual(Quota({**self.options, 'opencritic_api_key': 'different'}).snapshot(), {})

    def test_reset_allows_only_one_verification_without_new_headers(self):
        with patch('opencritic_quota.time.time', return_value=1000):
            self.quota.observe(headers(2, 10))
            self.quota.enqueue([{'store': 'Steam', 'id': '620'}])
        with patch('opencritic_quota.time.time', return_value=1016):
            self.assertTrue(self.quota.take_ready())
            self.quota.reserve()
            with self.assertRaises(QuotaPaused):
                self.quota.reserve()
            self.quota.observe(headers(100, 60))
            self.quota.reserve()
            self.assertEqual(self.quota.snapshot()['buckets']['x-ratelimit-requests']['remaining'], 99)

    def test_multiple_buckets_and_missing_reset_do_not_guess(self):
        self.quota.observe({**headers(90), 'x-rate-limit-rapid-free-plans-hard-limit-remaining': '2'})
        with self.assertRaises(QuotaPaused):
            self.quota.reserve()
        self.quota.enqueue([{'store': 'GOG', 'id': '1'}])
        self.assertIsNone(self.quota.snapshot()['queue_after'])
        self.assertFalse(self.quota.take_ready())
        self.quota.clear_queue()
        self.assertFalse(self.quota.snapshot().get('queue'))

    def test_two_call_preflight_and_final_remaining_headers(self):
        self.quota.observe(headers(3))
        calls = []
        def call(url, response_headers=None, **kwargs):
            calls.append(url)
            response_headers(headers(2))
            return []
        call.supports_response_headers = True
        clients = Clients(self.options, FastCancel(), call)
        with self.assertRaises(QuotaPaused):
            clients.opencritic({'title': 'Game'})
        self.assertFalse(calls)
        self.quota.observe(headers(10))
        clients.get('https://opencritic-api.p.rapidapi.com/game/1')
        self.assertEqual(self.quota.snapshot()['buckets']['x-ratelimit-requests']['remaining'], 2)

    def test_run_pauses_without_negative_cache_and_resumes_queue(self):
        db = Database(Path(self.tmp.name) / 'db')
        row = game('Steam', '620', 'Portal 2', {})
        db.save([row])
        calls = []
        def call(url, response_headers=None, **kwargs):
            calls.append(url)
            response_headers(headers(10 - len(calls)))
            if '/search?' in url:
                return [{'id': 1, 'name': 'Portal 2'}]
            return {'id': 1, 'name': 'Portal 2', 'topCriticScore': 95}
        call.supports_response_headers = True
        self.quota.observe(headers(2))
        run_extra(db, self.options, FastCancel(), lambda _: None, lambda: None, call)
        self.assertFalse(calls)
        self.assertFalse(db.rows()[0].get('opencritic_checked'))
        self.assertEqual(self.quota.snapshot()['queue'], [['Steam', '620']])
        self.quota.observe(headers(10))
        run_extra(db, self.options, FastCancel(), lambda _: None, lambda: None, call)
        self.assertEqual(len(calls), 2)
        self.assertEqual(db.rows()[0]['oc_score'], 95)
        self.assertFalse(self.quota.snapshot().get('queue'))

    def test_429_headers_and_retry_after_stop_further_calls(self):
        def call(url, response_headers=None, **kwargs):
            response_headers(headers(90))
            raise FetchError('HTTP 429', status=429, retry_after=120)
        call.supports_response_headers = True
        client = Clients(self.options, FastCancel(), call)
        with self.assertRaises(QuotaPaused):
            client.get('https://opencritic-api.p.rapidapi.com/game/1')
        self.assertEqual(client.requests, 1)
        with self.assertRaises(QuotaPaused):
            client.get('https://opencritic-api.p.rapidapi.com/game/1')
        self.assertEqual(client.requests, 1)
        self.assertIn('90 remaining', describe(self.quota.snapshot()))

    def test_connection_check_uses_recent_snapshot_without_network(self):
        from database_connections import probe_database
        self.quota.observe(headers(2))
        def call(*args, **kwargs):
            self.fail('A quota-exhausted check contacted the API')
        call.supports_response_headers = True
        result = probe_database('OpenCritic', self.options, FastCancel(), call)
        self.assertEqual(result.state, 'attention')
        self.assertIn('2 remaining', result.message)

    def test_real_transport_observes_success_and_error_headers(self):
        import io
        from urllib.error import HTTPError
        from unittest.mock import MagicMock
        from extra_metadata import network
        response = MagicMock()
        response.headers = headers(12)
        response.read.return_value = b'{"id": 1}'
        response.__enter__.return_value = response
        with patch('extra_metadata.urlopen', return_value=response):
            self.assertEqual(network('https://example.invalid', response_headers=self.quota.observe), {'id': 1})
        self.assertEqual(self.quota.snapshot()['buckets']['x-ratelimit-requests']['remaining'], 12)
        error = HTTPError('https://example.invalid', 429, 'limit', headers(3), io.BytesIO(b'{}'))
        with patch('extra_metadata.urlopen', side_effect=error):
            with self.assertRaises(FetchError):
                network('https://example.invalid', response_headers=self.quota.observe)
        self.assertEqual(self.quota.snapshot()['buckets']['x-ratelimit-requests']['remaining'], 3)

    def test_auto_resume_ui_checks_due_queue_and_respects_disable(self):
        import main_window as app
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from qt_wait import settle
        q = QApplication.instance() or QApplication([])
        with patch.object(app, 'ROOT', Path(self.tmp.name)), patch.object(app, 'QSettings', lambda *args: QSettings(self.tmp.name + '/settings.ini', QSettings.IniFormat)):
            window = settle(app.Window())
            try:
                window.options.update(self.options)
                with patch('opencritic_quota.time.time', return_value=1000):
                    self.quota.observe(headers(2, 60))
                    self.quota.enqueue([{'store': 'Steam', 'id': '620'}])
                with patch('opencritic_quota.time.time', return_value=1100), patch.object(window, 'start') as start:
                    window.options['opencritic_auto_resume'] = False
                    window.resume_opencritic_queue()
                    start.assert_not_called()
                    window.options['opencritic_auto_resume'] = True
                    window.resume_opencritic_queue()
                    start.assert_called_once_with('selected', selected={('Steam', '620')}, sources=['OpenCritic'])
            finally:
                window.close()
                q.processEvents()

    def test_batch_cap_queues_a_paced_continuation_only_with_known_quota(self):
        with patch('opencritic_quota.time.time', return_value=1000):
            self.quota.observe(headers(90, 3600))
            self.quota.enqueue([{'store': 'GOG', 'id': '1'}], for_budget=True)
            self.assertEqual(self.quota.snapshot()['queue_after'], 1060)
            self.assertFalse(self.quota.take_ready())
        with patch('opencritic_quota.time.time', return_value=1061):
            self.assertEqual(self.quota.take_ready(), [['GOG', '1']])
        unknown = Quota({**self.options, 'opencritic_api_key': 'unknown'})
        unknown.enqueue([{'store': 'GOG', 'id': '2'}], for_budget=True)
        self.assertIsNone(unknown.snapshot()['queue_after'])

    def test_failed_access_headers_do_not_imply_connected(self):
        from database_connections import probe_database
        def call(url, response_headers=None, **kwargs):
            response_headers(headers(90))
            raise FetchError('HTTP 401', status=401)
        call.supports_response_headers = True
        client = Clients(self.options, FastCancel(), call)
        with self.assertRaises(FetchError):
            client.get('https://opencritic-api.p.rapidapi.com/game/1')
        self.assertFalse(self.quota.snapshot()['access_ok'])
        with patch('builtins.print'):
            result = probe_database('OpenCritic', self.options, FastCancel(), call)
        self.assertEqual(result.state, 'attention')
