"""Wait for asynchronous UI reads/imports while continuing to dispatch Qt events."""

import time
from PySide6.QtWidgets import QApplication


def settle(window, timeout=5):
    from unittest.mock import patch
    from connection_checks import ConnectionResult
    with patch("database_connections.probe_database", side_effect=lambda name,*args: ConnectionResult(name,"unknown","Offline UI test")):
        return _settle(window,timeout)

def _settle(window, timeout=5):
    deadline = time.monotonic() + timeout
    def busy():
        return window.catalog_loads.busy or window.import_active or window.local_active or window.connections.busy
    while True:
        QApplication.processEvents()
        if not busy():
            QApplication.processEvents()
            if not busy():
                break
        if time.monotonic() > deadline:
            raise AssertionError("Background library work did not finish")
        time.sleep(0.001)
    return window
