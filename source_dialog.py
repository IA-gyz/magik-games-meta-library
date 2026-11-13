from provider_registry import PROVIDERS, provider
from ui_actions import action_button
from unknown_style import UnknownTextEdit

"""Store connection settings and credential reveal controls."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QPixmap,
    QDesktopServices,
    QAction,
    QIcon,
    QPainter,
    QPen,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QTabWidget,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QCheckBox,
    QFileDialog,
    QMessageBox,
)


SOURCE_HELP = """Connect each store below, enable it, then choose Save. Refresh libraries reads your account’s game list. Game details include genres, descriptions, release dates and similar information.
Steam: enter your API key and SteamID64 (or profile name) to read your library. Connect Steam dates separately to find when games were added to your account. Your API key stays saved on this computer.
GOG: select the authentication JSON file used by Heroic/GOGDL. This app reads that file without changing it.
Epic: sign in through Heroic or run legendary auth first. The app can reuse saved Heroic game details and request more from Epic. Leave the Heroic folder blank to check the usual locations.
Amazon: sign in through Nile or Heroic first. For a custom Nile setup, choose its program and settings folder (the folder containing nile).
EA: choose Connect EA to save your sign-in and renew access automatically. If the saved sign-in expires, connect again. You can instead disable automatic renewal and supply an access token or a Lutris token JSON file.
Rockstar support is on hold. It cannot be refreshed in this version.
Connecting and refreshing do not install or start games. Heroic, Legendary or Nile may update their own sign-in and library files. Play starts a game through its existing launcher or your chosen script."""


def add_secret_toggle(edit):
    """Trailing reveal control. Visibility is temporary and defaults to masked."""

    def icon(hidden):
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(
                edit.palette().color(edit.foregroundRole()),
                2.3,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        path = QPainterPath()
        path.moveTo(3, 16)
        path.quadTo(16, 2, 29, 16)
        path.quadTo(16, 30, 3, 16)
        painter.drawPath(path)
        painter.drawEllipse(12, 12, 8, 8)
        if hidden:
            painter.drawLine(5, 5, 27, 27)
        painter.end()
        return QIcon(pix)

    show_icon = icon(False)
    hide_icon = icon(True)
    action = QAction(show_icon, "Show value", edit)
    action.setCheckable(True)
    action.setToolTip("Show value")
    action.setObjectName("revealSecret")

    def toggle(visible):
        cursor = edit.cursorPosition()
        start = edit.selectionStart()
        length = len(edit.selectedText())
        edit.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        action.setText("Hide value" if visible else "Show value")
        action.setToolTip(action.text())
        action.setIcon(hide_icon if visible else show_icon)
        if start >= 0:
            edit.setSelection(start, length)
        else:
            edit.setCursorPosition(cursor)

    action.toggled.connect(toggle)
    edit.addAction(action, QLineEdit.TrailingPosition)
    edit.setEchoMode(QLineEdit.Password)
    return action


class Sources(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library sources")
        self.resize(950, 760)
        self.fields = {}
        self.source_options = options.copy()
        self.session_toggles = {}
        self.session_labels = {}
        layout = QVBoxLayout(self)
        helptext = UnknownTextEdit()
        helptext.setReadOnly(True)
        helptext.setPlainText(SOURCE_HELP)
        helptext.setMaximumHeight(205)
        layout.addWidget(helptext)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        definitions = {spec.name: spec.source_fields for spec in PROVIDERS}
        self.enabled = {}
        for store, fields in definitions.items():
            page = QWidget()
            form = QFormLayout(page)
            enabled = QCheckBox("Include in Refresh libraries")
            enabled.setChecked(
                options.get("enabled_" + store, False)
                if provider(store).sync_enabled
                else False
            )
            if not provider(store).sync_enabled:
                enabled.setEnabled(False)
                enabled.setText(store + " on hold")
            self.enabled[store] = enabled
            form.addRow(enabled)
            for key, label, kind in fields:
                edit = QLineEdit(str(options.get(key, "")))
                self.fields[key] = edit
                if key == "steam_licenses_html":
                    edit.setToolTip(
                        "Optional: choose a saved English-language Steam licenses page. When selected, this file is used instead of your saved Steam sign-in to find dates added."
                    )
                if kind == "secret":
                    add_secret_toggle(edit)
                if kind in ["file", "dir"]:
                    wrap = QWidget()
                    row = QHBoxLayout(wrap)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(edit)
                    button = action_button("Browse…", "file")
                    row.addWidget(button)
                    button.clicked.connect(
                        lambda checked=False, e=edit, d=kind == "dir": self.browse(e, d)
                    )
                    form.addRow(label, wrap)
                else:
                    form.addRow(label, edit)
            if store == "Steam":
                b = action_button("Open Steam API key page", "settings")
                b.clicked.connect(
                    lambda: QDesktopServices.openUrl(
                        QUrl("https://steamcommunity.com/dev/apikey")
                    )
                )
                form.addRow(b)
            if store in ["Steam", "EA"]:
                self.session_controls(store, form, options)
            tabs.addTab(page, store)
        from extra_source_ui import add_extra_tabs
        add_extra_tabs(tabs, options, self.fields, self.session_toggles, add_secret_toggle)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def session_controls(self, store, form, options):
        from web_sessions import auth_dir

        key = "ea_session_enabled" if store == "EA" else "steam_dates_enabled"
        enabled = QCheckBox(
            "Keep EA signed in and renew access automatically"
            if store == "EA"
            else "Use saved Steam sign-in to find dates added"
        )
        enabled.setChecked(bool(options.get(key)))
        self.session_toggles[key] = enabled
        form.addRow(enabled)
        if store == "EA":
            for name in ["ea_token", "ea_auth"]:
                self.fields[name].setEnabled(not enabled.isChecked())
                enabled.toggled.connect(
                    lambda checked, n=name: self.fields[n].setEnabled(not checked)
                )
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        connect = action_button(
            "Connect EA…" if store == "EA" else "Connect Steam dates…", "sync"
        )
        connect.clicked.connect(lambda checked=False, s=store: self.connect_session(s))
        row.addWidget(connect)
        forget = action_button("Remove saved sign-in", "danger")
        forget.clicked.connect(lambda checked=False, s=store: self.forget_session(s))
        row.addWidget(forget)
        form.addRow(wrap)
        path = auth_dir(options) / (
            "ea-cookies.json" if store == "EA" else "steam-cookies.json"
        )
        label = QLabel(
            "A saved sign-in is available. It may still need to be renewed."
            if path.exists()
            else "Not connected. Use Connect to to sign in. The saved sign-in stays on this computer."
        )
        label.setWordWrap(True)
        self.session_labels[store] = label
        form.addRow(label)

    def connect_session(self, store):
        from web_sessions import SessionError
        from signin_process import ConnectSession

        options = {**self.source_options, **self.values()}
        try:
            dialog = ConnectSession("ea" if store == "EA" else "steam", options, self)
        except SessionError as exc:
            QMessageBox.information(self, "Sign-in dependency", str(exc))
            return
        if dialog.exec():
            key = "ea_session_enabled" if store == "EA" else "steam_dates_enabled"
            self.session_toggles[key].setChecked(True)
            self.enabled[store].setChecked(True)
            if store == "EA":
                self.fields["ea_token"].clear()
            else:
                self.fields["steam_licenses_html"].clear()
                self.fields["steam_id"].setText(dialog.result_data["steam_id"])
            self.session_labels[store].setText(
                "Sign-in verified. Choose Save to use it when refreshing your library."
            )

    def forget_session(self, store):
        from web_sessions import forget_session

        forget_session("ea" if store == "EA" else "steam", self.source_options)
        self.session_toggles[
            "ea_session_enabled" if store == "EA" else "steam_dates_enabled"
        ].setChecked(False)
        self.session_labels[store].setText(
            "Saved sign-in removed from this computer. Connect again to use it here."
        )

    def browse(self, edit, directory):
        path = (
            QFileDialog.getExistingDirectory(self, "Choose directory", edit.text())
            if directory
            else QFileDialog.getOpenFileName(self, "Choose file", edit.text())[0]
        )
        if path:
            edit.setText(path)

    def values(self):
        return {
            **{k: e.text().strip() for k, e in self.fields.items()},
            **{"enabled_" + k: e.isChecked() for k, e in self.enabled.items()},
            **{k: e.isChecked() for k, e in self.session_toggles.items()},
        }
