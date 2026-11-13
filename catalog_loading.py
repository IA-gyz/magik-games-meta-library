"""Coalesced background catalog reads; Qt models remain on the UI thread."""

from copy import deepcopy
from PySide6.QtCore import QObject, QThread, Signal
from browsing import FACETS, facet_tokens
from installations import decorate
from store_copies import find_copies


def prepare_catalog(db, links):
    rows, snapshot, statuses = db.view_snapshot()
    rows = decorate(rows, snapshot, links)
    facets = {
        key: sorted(
            {v for row in rows for v in facet_tokens(row, key)}, key=str.casefold
        )
        for key in FACETS
    }
    return {
        "rows": rows,
        "installations": snapshot,
        "statuses": statuses,
        "facets": facets,
        "copies": find_copies(rows),
    }


class CatalogRead(QThread):
    def __init__(self, db, links, generation, parent):
        super().__init__(parent)
        self.db, self.links, self.generation = db, links, generation
        self.value, self.error = None, None

    def run(self):
        try:
            self.value = prepare_catalog(self.db, self.links)
        except Exception as exc:
            self.error = (
                "Could not reload the library. The previous view was kept. Technical error: "
                + type(exc).__name__
            )


class CatalogLoads(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    idle = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.worker = db, None
        self.generation = 0
        self.pending = None
        self.accepting = True

    @property
    def busy(self):
        return self.worker is not None

    def request(self, links):
        if not self.accepting:
            return
        self.generation += 1
        self.pending = (deepcopy(links), self.generation)
        if not self.busy:
            self.start_pending()

    def start_pending(self):
        links, generation = self.pending
        self.pending = None
        self.worker = CatalogRead(self.db, links, generation, self)
        self.worker.finished.connect(self.read_finished)
        self.worker.start()

    def read_finished(self):
        completed, self.worker = self.worker, None
        if self.accepting and completed.generation == self.generation:
            if completed.error:
                self.failed.emit(completed.error)
            else:
                self.loaded.emit(completed.value)
        completed.deleteLater()
        if self.busy:
            return
        if self.accepting and self.pending is not None:
            self.start_pending()
        else:
            self.idle.emit()

    def stop(self):
        self.accepting = False
        self.pending = None
