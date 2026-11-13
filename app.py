#!/usr/bin/env python3
"""Application entry point. UI and background work live in dedicated modules."""

import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from app_config import APP_ID, DISPLAY_NAME, SETTINGS_ORG, ASSETS
from main_window import Window


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from kde_integration import register

    try:
        register(quiet=True, refresh=False)
    except OSError:
        pass  # Direct launch remains usable if desktop registration is not writable.
    app = QApplication(sys.argv + ["-name", APP_ID])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setOrganizationName(SETTINGS_ORG)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon(str(ASSETS / (APP_ID + ".svg"))))
    window = Window()
    window.show()
    QTimer.singleShot(0, lambda: window.start("scan"))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
