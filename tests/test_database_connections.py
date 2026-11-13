import os, sys, unittest, threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database_connections import probe_database, ConnectionPanel, SOURCES
from connector_io import FetchError, Cancelled
from PySide6.QtWidgets import QApplication


class DatabaseStatusTests(unittest.TestCase):
    def test_missing_key_never_calls_network(self):
        calls = []
        result = probe_database(
            "OpenCritic", {}, threading.Event(), call=lambda *a, **k: calls.append(a)
        )
        self.assertEqual(result.state, "attention")
        self.assertFalse(calls)

    def test_opencritic_check_has_hourly_limit(self):
        result = probe_database(
            "OpenCritic",
            {"opencritic_api_key": "private"},
            threading.Event(),
            call=lambda *a, **k: {"id": 463},
        )
        self.assertEqual(result.state, "connected")
        self.assertEqual(result.retry_after, 3600)

    def test_rate_limit_is_honored_and_secret_not_displayed(self):
        def call(*args, **kwargs):
            raise FetchError("private key", status=429, retry_after=7200)

        result = probe_database(
            "OpenCritic",
            {"opencritic_api_key": "private"},
            threading.Event(),
            call=call,
        )
        self.assertEqual(result.state, "attention")
        self.assertEqual(result.retry_after, 7200)
        self.assertNotIn("private", result.message)

    def test_proton_live_response_validation(self):
        result = probe_database(
            "ProtonDB",
            {},
            threading.Event(),
            call=lambda *a, **k: {"tier": "gold", "total": 1},
        )
        self.assertEqual(result.state, "connected")

    def test_cancel_propagates(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            probe_database("ProtonDB", {}, cancel)

    def test_two_rows_and_disabled_database(self):
        q = QApplication.instance() or QApplication([])
        panel = ConnectionPanel(can_check=lambda: False)
        panel.set_options({"metadata_ProtonDB": False})
        self.assertEqual(panel.layout().count(), 2)
        self.assertEqual(set(panel.databases.icons), set(SOURCES))
        self.assertEqual(panel.databases.states["ProtonDB"].state, "disabled")
        self.assertEqual(panel.databases.timer.interval(), 3600000)
        panel.stop()
        panel.close()
        q.processEvents()
