"""Compact live store indicators with periodic, cancellable background checks."""

from copy import deepcopy
import threading
import time
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QCheckBox
from provider_registry import PROVIDERS
from connection_checks import ConnectionResult, probe_connection
from connector_io import Cancelled
from date_display import friendly_date

COLORS = {
    "connected": "#26965a",
    "checking": "#3989d7",
    "attention": "#d99a18",
    "failed": "#d74545",
    "disabled": "#84909b",
    "unsupported": "#84909b",
    "unknown": "#84909b",
}
LABELS = {
    "connected": "Connected",
    "checking": "Checking…",
    "attention": "Needs attention",
    "failed": "Connection failed",
    "disabled": "Disabled",
    "unsupported": "On hold",
    "unknown": "Not checked yet",
}


class ConnectionChecks(QThread):
    result = Signal(object)
    checking = Signal(str)

    def __init__(self, options, stores, parent, probe=None):
        super().__init__(parent)
        self.options = deepcopy(options)
        self.probe = probe
        self.stores = stores
        self.cancel = threading.Event()

    def run(self):
        for store in self.stores:
            if self.cancel.is_set():
                break
            self.checking.emit(store)
            try:
                result = (self.probe or probe_connection)(
                    store, self.options, self.cancel
                )
            except Cancelled:
                break
            if not self.cancel.is_set():
                self.result.emit(result)


class StoreConnections(QWidget):
    idle = Signal()
    store_filter_changed = Signal(object)

    def __init__(
        self,
        parent=None,
        can_check=None,
        *,
        specs=None,
        probe=None,
        interval=5 * 60 * 1000,
        store_filters=False,
    ):
        super().__init__(parent)
        self.specs = specs if specs is not None else PROVIDERS
        self.probe = probe
        self.interval = interval
        self.can_check = can_check or (lambda: True)
        self.worker = None
        self.options = {}
        self.revision = 0
        self.worker_revision = 0
        self.stopping = False
        self.not_before = {}
        self.states = {}
        self.last_known = {}
        self.labels = {}
        self.icons = {}
        self.store_checks = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for spec in self.specs:
            item = QWidget(self)
            row = QHBoxLayout(item)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            if store_filters:
                check = QCheckBox()
                check.setChecked(True)
                check.setObjectName("filterStore" + spec.name)
                check.setAccessibleName("Show " + spec.name + " games")
                check.setToolTip(
                    "Show "
                    + spec.name
                    + " games in the library. This does not enable or disable account refreshes."
                )
                self.store_checks[spec.name] = check
                check.toggled.connect(
                    lambda checked: self.store_filter_changed.emit(
                        self.visible_stores()
                    )
                )
                row.addWidget(check)
            icon = QLabel()
            icon.setFixedSize(16, 16)
            name = QLabel(spec.name)
            name.setTextFormat(Qt.PlainText)
            row.addWidget(icon)
            row.addWidget(name)
            layout.addWidget(item)
            self.labels[spec.name] = item
            self.icons[spec.name] = icon
        self.timer = QTimer(self)
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.set_options({})

    def visible_stores(self):
        return [name for name, check in self.store_checks.items() if check.isChecked()]

    def set_visible_stores(self, stores):
        for name, check in self.store_checks.items():
            check.blockSignals(True)
            check.setChecked(name in stores)
            check.blockSignals(False)

    @property
    def busy(self):
        return self.worker is not None

    def set_options(self, options):
        self.options = deepcopy(options)
        self.revision += 1
        self.not_before = {}
        if self.worker:
            self.worker.cancel.set()
        for spec in self.specs:
            state = (
                "unsupported"
                if not spec.sync_enabled
                else "unknown"
                if options.get("enabled_" + spec.name)
                else "disabled"
            )
            message = (
                "Rockstar support is on hold; no request is made."
                if state == "unsupported"
                else "Enable this store in Sources to check its connection."
                if state == "disabled"
                else "Waiting for a live account check."
            )
            self.update_state(ConnectionResult(spec.name, state, message))
        QTimer.singleShot(0, self.refresh)

    def update_state(self, result):
        self.states[result.store] = result
        if result.state != "checking":
            self.last_known[result.store] = result
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(COLORS[result.state]).darker(125), 1))
        p.setBrush(QColor(COLORS[result.state]))
        p.drawEllipse(2, 2, 12, 12)
        p.end()
        self.icons[result.store].setPixmap(pix)
        tooltip = f"{result.store} — {LABELS[result.state]}\n{result.message}\nLast check: {friendly_date(result.checked_at, 'Not checked yet')}\nChecks run every {self.interval // 60000} minutes when the app is idle. Click this strip to check again."
        self.labels[result.store].setToolTip(tooltip)
        self.labels[result.store].setAccessibleName(
            f"{result.store}: {LABELS[result.state]}"
        )
        self.labels[result.store].setAccessibleDescription(result.message)
        for label in self.labels[result.store].findChildren(QLabel):
            label.setToolTip(tooltip)
        self.labels[result.store].setProperty("connectionState", result.state)

    def refresh(self):
        if self.stopping or self.busy or not self.can_check():
            return
        stores = [
            spec.name
            for spec in self.specs
            if spec.sync_enabled
            and self.options.get("enabled_" + spec.name)
            and time.monotonic() >= self.not_before.get(spec.name, 0)
        ]
        if not stores:
            return
        self.worker_revision = self.revision
        self.worker = ConnectionChecks(self.options, stores, self, self.probe)
        self.worker.checking.connect(self.checking)
        self.worker.result.connect(self.result)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def checking(self, store):
        if not self.stopping and self.worker_revision == self.revision:
            prior = self.states[store]
            self.update_state(
                ConnectionResult(
                    store,
                    "checking",
                    (
                        "Checking live database/API access in the background."
                        if self.probe
                        else "Checking live account access in the background."
                    ),
                    prior.checked_at,
                )
            )

    def result(self, result):
        if not self.stopping and self.worker_revision == self.revision:
            self.update_state(result)
            if result.retry_after:
                self.not_before[result.store] = time.monotonic() + result.retry_after

    def finished(self):
        completed, self.worker = self.worker, None
        completed.deleteLater()
        self.idle.emit()
        if not self.stopping and self.worker_revision != self.revision:
            QTimer.singleShot(0, self.refresh)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.refresh()
        super().mousePressEvent(event)

    def pause(self):
        self.revision += 1
        if self.worker:
            self.worker.cancel.set()
        for store, result in list(self.states.items()):
            if result.state == "checking":
                self.update_state(self.last_known[store])

    def stop(self):
        self.stopping = True
        self.timer.stop()
        if self.worker:
            self.worker.cancel.set()
