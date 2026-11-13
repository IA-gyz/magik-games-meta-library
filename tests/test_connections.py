import os, sys, time, tempfile, threading, unittest, json
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from connection_checks import probe_connection, ConnectionResult
from connector_io import ConnectorIO, FetchError

try:
    from PySide6.QtWidgets import QApplication
    from connection_status import StoreConnections
except ImportError:
    StoreConnections = None


class ConnectionProbeTests(unittest.TestCase):
    def io(self, request=None, helper=None, token=None):
        return ConnectorIO(request or Mock(), helper or Mock(), token or Mock())

    def test_steam_live_empty_library_is_connected(self):
        request = Mock(return_value={"response": {"game_count": 0}})
        result = probe_connection(
            "Steam",
            {"steam_key": "private", "steam_id": "76561198018049642"},
            threading.Event(),
            self.io(request),
        )
        self.assertEqual(result.state, "connected")
        self.assertTrue(result.checked_at)
        self.assertNotIn("private", result.message)
        request.assert_called_once()

    def test_missing_setup_does_not_make_requests(self):
        request = Mock()
        result = probe_connection("Steam", {}, threading.Event(), self.io(request))
        self.assertEqual(result.state, "attention")
        self.assertIn("Sources → Steam", result.message)
        request.assert_not_called()

    def test_gog_reuses_refresh_auth_without_shelf_or_history_requests(self):
        request = Mock(side_effect=[{"access_token": "fresh"}, {"owned": []}])
        token = Mock(return_value={"refresh_token": "private"})
        result = probe_connection(
            "GOG",
            {"gog_auth": "auth.json"},
            threading.Event(),
            self.io(request, token=token),
        )
        self.assertEqual(result.state, "connected")
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("private", result.message)

    def test_epic_checks_live_first_page_from_selected_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "user.json").write_text(json.dumps({"access_token": "private"}))
            request = Mock(return_value={"records": [], "responseMetadata": {}})
            result = probe_connection(
                "Epic", {"epic_config": tmp}, threading.Event(), self.io(request)
            )
        self.assertEqual(result.state, "connected")
        request.assert_called_once()

    def test_amazon_uses_sync_without_importing_games(self):
        helper = Mock(return_value="ok")
        result = probe_connection(
            "Amazon",
            {"amazon_exe": "custom-nile"},
            threading.Event(),
            self.io(helper=helper),
        )
        self.assertEqual(result.state, "connected")
        self.assertEqual(helper.call_args.args[1], ["library", "sync"])
        self.assertIn("app’s game list was not changed", result.message)

    def test_ea_checks_one_library_item_and_reuses_automatic_renewal(self):
        request = Mock(
            return_value={
                "data": {"me": {"ownedGameProducts": {"items": [], "next": None}}}
            }
        )
        with patch("web_sessions.renew_ea", return_value="private") as renew:
            result = probe_connection(
                "EA", {"ea_session_enabled": True}, threading.Event(), self.io(request)
            )
        self.assertEqual(result.state, "connected")
        renew.assert_called_once()
        self.assertIn("limit:1", request.call_args.kwargs["body"]["query"])
        self.assertNotIn("private", result.message)

    def test_error_states_and_rate_limit_deadline(self):
        for status, state in [(401, "failed"), (429, "attention"), (503, "failed")]:
            request = Mock(
                side_effect=FetchError(
                    "HTTP " + str(status), status=status, retry_after=900
                )
            )
            result = probe_connection(
                "Steam",
                {"steam_key": "private", "steam_id": "1"},
                threading.Event(),
                self.io(request),
            )
            self.assertEqual(result.state, state)
            self.assertEqual(result.retry_after, 900)
            self.assertNotIn("private", result.message)

    def test_unexpected_errors_do_not_expose_credentials(self):
        request = Mock(side_effect=RuntimeError("private token"))
        result = probe_connection(
            "Steam",
            {"steam_key": "x", "steam_id": "1"},
            threading.Event(),
            self.io(request),
        )
        self.assertEqual(result.state, "failed")
        self.assertNotIn("private token", result.message)


@unittest.skipIf(StoreConnections is None, "PySide6 required")
class ConnectionStripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            self.q.processEvents()
            if time.monotonic() > deadline:
                raise AssertionError("Connection worker did not finish")
            time.sleep(0.001)
        self.q.processEvents()

    def test_names_states_and_tooltips_are_visible(self):
        strip = StoreConnections()
        strip.set_options({"enabled_Steam": True})
        with patch(
            "connection_status.probe_connection",
            side_effect=lambda store, *args: ConnectionResult(
                store, "connected", "Live test succeeded", "2026-10-18T12:00:00+00:00"
            ),
        ):
            strip.refresh()
            self.wait(lambda: not strip.busy)
        self.assertEqual(strip.states["Steam"].state, "connected")
        self.assertEqual(strip.states["GOG"].state, "disabled")
        self.assertEqual(strip.states["Rockstar"].state, "unsupported")
        self.assertIn("Live test succeeded", strip.labels["Steam"].toolTip())
        self.assertIn("Last check:", strip.labels["Steam"].toolTip())
        self.assertFalse(strip.icons["Steam"].pixmap().isNull())
        strip.stop()
        strip.deleteLater()

    def test_disabled_stores_are_not_queried_and_busy_app_skips_checks(self):
        strip = StoreConnections(can_check=lambda: False)
        strip.set_options({"enabled_Steam": True})
        with patch("connection_status.probe_connection") as probe:
            strip.refresh()
            self.q.processEvents()
            probe.assert_not_called()
        strip.stop()
        strip.deleteLater()

    def test_changed_settings_discard_old_results(self):
        entered = threading.Event()
        release = threading.Event()
        strip = StoreConnections()
        strip.set_options({"enabled_Steam": True})

        def probe(store, *args):
            entered.set()
            release.wait(3)
            return ConnectionResult(store, "connected", "old check")

        with patch("connection_status.probe_connection", side_effect=probe):
            try:
                strip.refresh()
                self.wait(entered.is_set)
                strip.set_options({})
                release.set()
                self.wait(lambda: not strip.busy)
            finally:
                release.set()
                strip.stop()
                self.wait(lambda: not strip.busy)
        self.assertEqual(strip.states["Steam"].state, "disabled")
        strip.deleteLater()

    def test_clicking_a_store_name_rechecks_and_children_have_tooltips(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt

        strip = StoreConnections()
        strip.set_options({"enabled_Steam": True})
        strip.show()
        with patch(
            "connection_status.probe_connection",
            return_value=ConnectionResult("Steam", "connected", "Live check succeeded"),
        ) as probe:
            strip.refresh()
            self.wait(lambda: not strip.busy)
            name = strip.labels["Steam"].findChildren(QLabel)[1]
            self.assertIn("Live check succeeded", name.toolTip())
            before = probe.call_count
            QTest.mouseClick(name, Qt.LeftButton)
            self.wait(lambda: not strip.busy)
            self.assertEqual(probe.call_count, before + 1)
        strip.stop()
        strip.close()
        strip.deleteLater()

    def test_stop_waits_for_inflight_check_without_publishing_result(self):
        entered, release = threading.Event(), threading.Event()
        strip = StoreConnections()
        strip.set_options({"enabled_Steam": True})

        def probe(*args):
            entered.set()
            release.wait(3)
            return ConnectionResult("Steam", "connected", "Late response")

        with patch("connection_status.probe_connection", side_effect=probe):
            try:
                strip.refresh()
                self.wait(entered.is_set)
                strip.stop()
                self.assertTrue(strip.busy)
                release.set()
                self.wait(lambda: not strip.busy)
            finally:
                release.set()
                strip.stop()
                self.wait(lambda: not strip.busy)
        self.assertNotEqual(strip.states["Steam"].state, "connected")
        strip.deleteLater()

    def test_server_wait_is_respected(self):
        strip = StoreConnections()
        strip.set_options({"enabled_Steam": True})
        with patch(
            "connection_status.probe_connection",
            return_value=ConnectionResult(
                "Steam", "attention", "Wait", retry_after=900
            ),
        ) as probe:
            strip.refresh()
            self.wait(lambda: not strip.busy)
            strip.refresh()
            self.q.processEvents()
            self.assertEqual(probe.call_count, 1)
        strip.stop()
        strip.deleteLater()
