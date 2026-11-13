"""Background file parsing, import validation and transactional persistence."""

import json
from pathlib import Path
from PySide6.QtCore import QThread
from catalog_import import normalize_import, import_saved_library
from connectors import Cancelled


class ImportWorker(QThread):
    def __init__(self, db, cancel, *, path=None, payload=None, store=None, parent=None):
        super().__init__(parent)
        self.db, self.cancel = db, cancel
        self.path, self.payload, self.store = path, payload, store
        self.outcome, self.value = None, None

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def run(self):
        try:
            self.check_cancel()
            payload = (
                json.loads(Path(self.path).read_text(encoding="utf-8"))
                if self.path is not None
                else self.payload
            )
            self.check_cancel()
            if (
                isinstance(payload, dict)
                and payload.get("format") == "magik-library-v1"
            ):
                rows = import_saved_library(payload)
            elif self.store is None:
                self.outcome, self.value = "choose_store", payload
                return
            else:
                rows = normalize_import(self.store, payload)
            self.check_cancel()
            from database_backups import ensure_daily
            ensure_daily(self.db, self.check_cancel)
            self.db.save(rows, before_commit=self.check_cancel)
            self.outcome, self.value = "saved", len(rows)
        except Cancelled:
            self.outcome = "cancelled"
        except (ValueError, OSError) as exc:
            self.outcome, self.value = "error", str(exc)
        except Exception as exc:
            self.outcome, self.value = (
                "error",
                "The import could not finish. Technical error: " + type(exc).__name__,
            )
