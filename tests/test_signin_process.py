import os, sys, time, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QDialog
from signin_process import ConnectSession, browser_environment


def wait(condition):
    deadline = time.monotonic() + 7
    while not condition():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Sign-in child did not finish")
        time.sleep(0.01)
    QApplication.processEvents()


class SigninProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_child_crash_keeps_parent_and_saved_login(self):
        with tempfile.TemporaryDirectory() as root:
            cookies = Path(root) / "ea-cookies.json"
            cookies.write_text("previous verified login")
            script = "import resource,os,signal;resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.kill(os.getpid(),signal.SIGABRT)"
            with patch(
                "signin_process.browser_command",
                return_value=(sys.executable, ["-c", script]),
            ):
                dialog = ConnectSession(
                    "ea", {"auth_dir": root, "steam_key": "not-for-child"}
                )
                dialog.show()
                wait(lambda: dialog.finished_handled)
                self.assertIsNone(dialog.process)
                self.assertTrue(dialog.retry.isEnabled())
                self.assertTrue(dialog.isVisible())
                self.assertIn("unexpectedly", dialog.hint.text())
                self.assertEqual(cookies.read_text(), "previous verified login")
                self.assertIsNone(dialog.temporary)
                dialog.reject()

    def test_verified_child_returns_result(self):
        script = 'import json,sys;open(sys.argv[1],"w").write(json.dumps({"status":"verified","result":{"steam_id":"123"}}))'
        with patch(
            "signin_process.browser_command",
            side_effect=lambda req, out: (sys.executable, ["-c", script, str(out)]),
        ):
            dialog = ConnectSession("steam", {})
            wait(lambda: dialog.finished_handled)
            self.assertEqual(dialog.result(), QDialog.Accepted)
            self.assertEqual(dialog.result_data, {"steam_id": "123"})
            self.assertIsNone(dialog.temporary)

    def test_dependency_failure_can_retry_and_does_not_import_webengine(self):
        script = 'import json,sys;open(sys.argv[1],"w").write(json.dumps({"status":"dependency"}))'
        with patch(
            "signin_process.browser_command",
            side_effect=lambda req, out: (sys.executable, ["-c", script, str(out)]),
        ):
            dialog = ConnectSession("ea", {})
            wait(lambda: dialog.finished_handled)
            self.assertIn("qt6-webengine", dialog.hint.text())
            self.assertTrue(dialog.retry.isEnabled())
            dialog.reject()

    def test_request_contains_only_service_and_auth_location(self):
        captured = []

        def command(req, out):
            import json

            captured.append(json.loads(req.read_text()))
            self.assertEqual(req.stat().st_mode & 0o777, 0o600)
            self.assertEqual(req.parent.stat().st_mode & 0o777, 0o700)
            return sys.executable, ["-c", "pass"]

        with (
            tempfile.TemporaryDirectory() as root,
            patch("signin_process.browser_command", side_effect=command),
        ):
            dialog = ConnectSession(
                "ea",
                {
                    "auth_dir": root,
                    "ea_token": "private",
                    "igdb_client_secret": "private",
                },
            )
            wait(lambda: dialog.finished_handled)
            self.assertEqual(captured, [{"service": "ea", "auth_dir": root}])
            dialog.reject()

    def test_cancel_waits_for_child_exit(self):
        with patch(
            "signin_process.browser_command",
            return_value=(sys.executable, ["-c", "import time;time.sleep(30)"]),
        ):
            dialog = ConnectSession("ea", {})
            dialog.show()
            wait(lambda: dialog.process is not None)
            dialog.reject()
            wait(lambda: dialog.finished_handled)
            self.assertEqual(dialog.result(), QDialog.Rejected)
            self.assertIsNone(dialog.process)
            self.assertIsNone(dialog.temporary)

    def test_compatibility_flags_are_child_only(self):
        original = dict(os.environ)
        env = browser_environment(True, False)
        self.assertIn("--disable-gpu", env.value("QTWEBENGINE_CHROMIUM_FLAGS"))
        self.assertEqual(env.value("QT_QUICK_BACKEND"), "software")
        self.assertEqual(dict(os.environ), original)
