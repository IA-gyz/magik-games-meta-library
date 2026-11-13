"""Selected-game requests and explicit per-source title corrections."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox,
    QFormLayout, QLineEdit, QTabWidget, QWidget, QTextBrowser,
)
from PySide6.QtCore import Qt
from extra_schema import SOURCES
from date_display import friendly_date

MATCH_SOURCES = ("Metacritic", "IGDB", "SteamGridDB", "OpenCritic", "HLTB")


def selected_keys(view, proxy, model):
    return frozenset(
        (row["store"], str(row["id"]))
        for index in view.selectionModel().selectedRows()
        for row in [model.rows[proxy.mapToSource(index).row()]]
    )


class FetchSelected(QDialog):
    def __init__(self, count, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fetch selected game details")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Request details for {count} selected game(s). Choose the sources to contact."))
        self.checks = {}
        for source in ("Store details", "Metacritic", *SOURCES):
            check = QCheckBox(source)
            check.setChecked(source == "Store details")
            self.checks[source] = check
            layout.addWidget(check)
            if source in SOURCES:
                from request_budgets import request_limit
                limit = request_limit(options, source)
                layout.addWidget(QLabel(f"    HTTP cap this fetch: {limit}" if limit else "    HTTP cap this fetch: unlimited"))
        self.force = QCheckBox("Retry cached results now")
        self.force.setToolTip("Skip each game's cache. Service-wide pauses and request limits still apply.")
        layout.addWidget(self.force)
        layout.addWidget(QLabel("API subscriptions may count these requests against your quota."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Fetch details")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sources(self):
        return [name for name, check in self.checks.items() if check.isChecked()]


class MatchReview(QDialog):
    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review metadata matches")
        self.resize(700, 540)
        layout = QVBoxLayout(self)
        title = QLabel(f'{row["title"]} · {row["store"]}')
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        help_text = QLabel("Enter the exact title used by a website to correct a missing match. Leave blank for the store title. PC, edition and release-year checks still apply. Saving does not fetch data or erase existing values; fetch selected details afterwards.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.edits = {}
        raw = row.get("raw") or {}
        overrides = raw.get("metadata_matches") or {}
        for source in MATCH_SOURCES:
            page = QWidget()
            form = QFormLayout(page)
            edit = QLineEdit(overrides.get(source, ""))
            edit.setMaxLength(300)
            edit.setPlaceholderText(row["title"])
            self.edits[source] = edit
            form.addRow("Lookup title", edit)
            state = raw.get("metacritic", {}) if source == "Metacritic" else raw.get("extra_metadata", {}).get(source, {})
            prefix = {"Metacritic": "mc", "OpenCritic": "oc", "SteamGridDB": "sgdb", "IGDB": "igdb", "HLTB": "hltb"}[source]
            details = QTextBrowser()
            details.setOpenExternalLinks(False)
            data = state.get("data") or {}
            status_prefix = "mc" if source == "Metacritic" else source.lower()
            lines = [
                "Last result: " + str(row.get(status_prefix + "_status") or state.get("outcome") or "No request yet"),
                "Last checked: " + friendly_date(row.get(status_prefix + "_checked")),
                "Last lookup title: " + str(state.get("lookup_title") or state.get("matched_title") or state.get("title") or "—"),
                "Website entry: " + str(row.get(prefix + "_url") or data.get("mc_url") or "—"),
                "Website ID: " + str(state.get("id") or "—"),
            ]
            details.setPlainText("\n\n".join(lines))
            form.addRow(details)
            tabs.addTab(page, source)
        note = QLabel("ProtonDB uses an exact Steam app ID, not a title match. SteamGridDB also prefers a known Steam app ID.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {source: edit.text().strip() for source, edit in self.edits.items() if edit.text().strip()}


def save_matches(db, row, values):
    """Empty values restore automatic matching; merge persistence keeps other raw data."""
    db.save([{"store": row["store"], "id": row["id"], "title": row["title"],
              "raw": {"metadata_matches": {s: values.get(s, "") for s in MATCH_SOURCES}}}])
