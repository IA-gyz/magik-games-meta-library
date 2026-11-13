#!/usr/bin/env python3
"""Private child-process entry point for EA/Steam website sign-in."""

import json
import sys
from pathlib import Path


def main():
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text())
    service = request["service"]
    if service not in ("ea", "steam"):
        return 2
    from web_sessions import atomic_json, SessionError
    from PySide6.QtCore import Qt, QLocale
    from PySide6.QtWidgets import QApplication, QDialog

    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    # Import WebEngine before creating QApplication, in this child process only.
    try:
        from PySide6 import QtWebEngineCore, QtWebEngineWidgets  # noqa: F401 — initialize before QApplication
    except ImportError:
        atomic_json(result_path, {"status": "dependency"})
        return 3
    QLocale.setDefault(QLocale("en_US"))
    app = QApplication([sys.argv[0], "--lang=en-US"])
    app.setApplicationName("magik-games-library-signin")
    app.setApplicationDisplayName("Magik Games Library — Sign in")
    app.setQuitOnLastWindowClosed(False)
    from session_ui import ConnectSession

    try:
        dialog = ConnectSession(service, {"auth_dir": request["auth_dir"]})
    except SessionError:
        atomic_json(result_path, {"status": "dependency"})
        return 3
    code = dialog.exec()
    atomic_json(
        result_path,
        {"status": "verified", "result": dialog.result_data}
        if code == QDialog.Accepted
        else {"status": "cancelled"},
    )
    # Deliver deferred page/profile deletion before the child exits.
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(4)
