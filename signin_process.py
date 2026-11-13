"""Isolate native WebEngine failures from the library's Qt process."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox
from ui_actions import action_button
from web_sessions import auth_dir, atomic_json


def browser_environment(software=True, x11=False):
    env = QProcessEnvironment.systemEnvironment()
    if software:
        env.insert(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            (env.value("QTWEBENGINE_CHROMIUM_FLAGS") + " --disable-gpu").strip(),
        )
        env.insert("QT_QUICK_BACKEND", "software")
        env.insert("QT_OPENGL", "software")
    if x11 and env.value("DISPLAY"):
        env.insert("QT_QPA_PLATFORM", "xcb")
    return env


def browser_command(request, output):
    return sys.executable, [
        str(Path(__file__).with_name("session_browser.py")),
        str(request),
        str(output),
    ]


class ConnectSession(QDialog):
    def __init__(self, service, options, parent=None):
        super().__init__(parent)
        if service not in ("ea", "steam"):
            raise ValueError("Unsupported sign-in service")
        self.service = service
        self.options = options.copy()
        self.result_data = {}
        self.process = None
        self.temporary = None
        self.closing_result = None
        self.finished_handled = False
        self.setWindowTitle(
            "Connect " + ("EA" if service == "ea" else "Steam dates added")
        )
        self.resize(620, 280)
        layout = QVBoxLayout(self)
        self.hint = QLabel(
            "Opening a separate sign-in window. Sign in there and choose Use this session. This library stays open if the browser fails."
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.software = QCheckBox("Use software rendering for the sign-in window")
        self.software.setChecked(True)
        layout.addWidget(self.software)
        self.x11 = QCheckBox("Use X11 compatibility (XWayland) for the sign-in window")
        layout.addWidget(self.x11)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.retry = action_button("Retry sign-in", "sync")
        self.retry.setEnabled(False)
        self.retry.clicked.connect(self.start)
        row.addWidget(self.retry)
        cancel = action_button("Cancel", "settings")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.kill_browser)
        QTimer.singleShot(0, self.start)

    def start(self):
        if (
            self.closing_result is not None
            or self.process
            and self.process.state() != QProcess.NotRunning
        ):
            return
        self.cleanup_files()
        self.temporary = TemporaryDirectory(prefix="magik-browser-")
        root = Path(self.temporary.name)
        atomic_json(
            root / "request.json",
            {"service": self.service, "auth_dir": str(auth_dir(self.options))},
        )
        self.output = root / "result.json"
        process = QProcess(self)
        self.process = process
        self.finished_handled = False
        process.setProcessEnvironment(
            browser_environment(self.software.isChecked(), self.x11.isChecked())
        )
        process.setStandardOutputFile(QProcess.nullDevice())
        process.setStandardErrorFile(QProcess.nullDevice())
        process.finished.connect(self.browser_finished)
        process.errorOccurred.connect(self.browser_error)
        self.retry.setEnabled(False)
        self.software.setEnabled(False)
        self.x11.setEnabled(False)
        self.hint.setText(
            "Sign-in is open in a separate window. Complete sign-in there, then choose Use this session. You can cancel here to close that window."
        )
        program, arguments = browser_command(root / "request.json", self.output)
        process.start(program, arguments)

    def browser_error(self, error):
        if error == QProcess.FailedToStart:
            self.browser_finished(-1, QProcess.NormalExit)

    def browser_finished(self, code, status):
        if self.finished_handled:
            return
        self.finished_handled = True
        self.kill_timer.stop()
        completed, self.process = self.process, None
        if completed:
            completed.deleteLater()
        value = {}
        try:
            if self.output.stat().st_size <= 8192:
                value = json.loads(self.output.read_text())
        except (OSError, ValueError):
            pass
        if not isinstance(value, dict):
            value = {}
        self.cleanup_files()
        self.retry.setEnabled(True)
        self.software.setEnabled(True)
        self.x11.setEnabled(True)
        if self.closing_result is not None:
            super().done(self.closing_result)
            return
        if (
            code == 0
            and status == QProcess.NormalExit
            and value.get("status") == "verified"
            and isinstance(value.get("result"), dict)
        ):
            self.result_data = value["result"]
            super().done(QDialog.Accepted)
            return
        if value.get("status") == "cancelled":
            self.hint.setText(
                "Sign-in was cancelled. Your previously saved sign-in was kept. Choose Retry sign-in to start again."
            )
        elif value.get("status") == "dependency":
            self.hint.setText(
                "The sign-in browser needs Qt WebEngine. On CachyOS/Arch: sudo pacman -S --needed pyside6 qt6-webengine. Restart the app after installation."
            )
        else:
            self.hint.setText(
                f"The sign-in browser stopped unexpectedly (exit {code}). The library is still open. Try software rendering; on Wayland, also try X11 compatibility. Then choose Retry sign-in. Previously saved sign-in files are kept unless a new sign-in was verified successfully."
            )

    def cleanup_files(self):
        if self.temporary:
            self.temporary.cleanup()
            self.temporary = None

    def kill_browser(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def done(self, result):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.closing_result = result
            self.process.terminate()
            self.kill_timer.start(2000)
            return
        self.closing_result = result
        self.cleanup_files()
        super().done(result)

    def closeEvent(self, event):
        self.reject()
        if self.process and self.process.state() != QProcess.NotRunning:
            event.ignore()
        else:
            event.accept()
