"""Theme-aware feature colours and escaped, semantic log rendering."""

from log_view import ColorLog
from app_config import SETTINGS_ORG, SETTINGS_APP
from ui_actions import ROLES
from PySide6.QtCore import QObject, QEvent, QSettings, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QDialog,
    QFormLayout,
    QComboBox,
    QDialogButtonBox,
)

PALETTES = {
    "Ocean": {
        "sync": "#248fc5",
        "metadata": "#9270d0",
        "filter": "#358d93",
        "file": "#b58632",
        "settings": "#6679a7",
        "launch": "#31925b",
        "danger": "#ce5d68",
    },
    "Forest": {
        "sync": "#468d80",
        "metadata": "#9b78ad",
        "filter": "#6d963c",
        "file": "#b88b48",
        "settings": "#6e8297",
        "launch": "#268c58",
        "danger": "#c45b57",
    },
    "Ember": {
        "sync": "#418fba",
        "metadata": "#b26eaa",
        "filter": "#829642",
        "file": "#c68738",
        "settings": "#9b7d69",
        "launch": "#4a955a",
        "danger": "#cf5e46",
    },
    "Orchid": {
        "sync": "#678cce",
        "metadata": "#a66bc6",
        "filter": "#459b95",
        "file": "#c3974a",
        "settings": "#897cb4",
        "launch": "#4b995c",
        "danger": "#cd6384",
    },
}


def blend(base, accent, amount):
    return QColor(
        *(
            round(a * (1 - amount) + b * amount)
            for a, b in zip(base.getRgb()[:3], accent.getRgb()[:3])
        )
    )


def readable(color, base):
    # Adjust the accent for WCAG text contrast against the actual background.
    def lum(c):
        channels = [v / 255 for v in c.getRgb()[:3]]
        values = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in channels
        ]
        return sum(v * w for v, w in zip(values, [0.2126, 0.7152, 0.0722]))

    target = QColor("white" if lum(base) < 0.4 else "black")
    result = QColor(color)
    for _ in range(24):
        a, b = sorted([lum(result), lum(base)])
        if (b + 0.05) / (a + 0.05) >= 4.5:
            break
        result = blend(result, target, 0.12)
    return result


class Appearance(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.system_palette = QPalette(app.palette())
        self.busy = False
        self.theme = self.settings.value("appearance/theme", "System")
        self.scheme = self.settings.value("appearance/palette", "Ocean")
        if self.theme not in ["System", "Light", "Dark"]:
            self.theme = "System"
        if self.scheme not in PALETTES:
            self.scheme = "Ocean"
        app.installEventFilter(self)
        self.apply()

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and event.type() in [
            QEvent.Polish,
            QEvent.Show,
        ]:
            if obj.property("actionRole") not in ROLES:
                obj.setProperty("actionRole", "settings")
            self.style_button(obj)
        if (
            obj is self.app
            and event.type() == QEvent.ApplicationPaletteChange
            and not self.busy
            and self.theme == "System"
        ):
            self.system_palette = QPalette(self.app.palette())
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        if self.busy:
            return
        self.busy = True
        try:
            palette = QPalette(self.system_palette)
            if self.theme != "System":
                dark = self.theme == "Dark"
                for role, value in [
                    (QPalette.Window, "#24262c" if dark else "#f2f3f6"),
                    (QPalette.Base, "#191b20" if dark else "#ffffff"),
                    (QPalette.AlternateBase, "#2c3037" if dark else "#e9edf3"),
                    (QPalette.Text, "#eeeeee" if dark else "#20232b"),
                    (QPalette.WindowText, "#eeeeee" if dark else "#20232b"),
                    (QPalette.ButtonText, "#eeeeee" if dark else "#20232b"),
                    (QPalette.Button, "#32363f" if dark else "#e6eaf0"),
                    (QPalette.Highlight, "#466eab"),
                    (QPalette.HighlightedText, "#ffffff"),
                    (QPalette.PlaceholderText, "#aeb6c6" if dark else "#586273"),
                    (QPalette.ToolTipBase, "#32363f" if dark else "#ffffff"),
                    (QPalette.ToolTipText, "#eeeeee" if dark else "#20232b"),
                ]:
                    palette.setColor(role, QColor(value))
            self.app.setPalette(palette)
            for widget in self.app.allWidgets():
                widget.setPalette(palette)
                if isinstance(widget, QPushButton):
                    self.style_button(widget)
                if (
                    isinstance(widget, ColorLog)
                    and getattr(self.app, "magik_appearance", None) is self
                ):
                    widget.setPalette(palette)
                    widget.render()
            self.settings.setValue("appearance/theme", self.theme)
            self.settings.setValue("appearance/palette", self.scheme)
        finally:
            self.busy = False

    def style_button(self, button):
        role = button.property("actionRole") or "settings"
        if role not in ROLES:
            role = "settings"
        palette = self.app.palette()
        accent = QColor(PALETTES[self.scheme][role])
        dark = palette.window().color().lightness() < 128
        # Per-widget styles override native style painting, without property-selector timing.
        background = blend(palette.button().color(), accent, 0.65 if dark else 0.48)
        foreground = readable(palette.buttonText().color(), background)
        hover = blend(background, accent, 0.25)
        pressed = blend(background, accent, 0.5)
        css = (
            f"QPushButton {{background:{background.name()};background-image:none;color:{foreground.name()};border:1px solid {accent.name()};border-radius:5px;padding:5px 9px;}}"
            f"QPushButton:hover {{background:{hover.name()};}} QPushButton:pressed {{background:{pressed.name()};}}"
            "QPushButton:disabled {color:palette(mid);background:palette(button);border-color:palette(mid);border-style:dotted;} QPushButton:focus {border-width:2px;}"
        )
        if button.styleSheet() != css:
            button.setStyleSheet(css)
            button.update()

    def choose(self, parent):
        dialog = QDialog(parent)
        dialog.setWindowTitle("Appearance")
        layout = QFormLayout(dialog)
        theme = QComboBox()
        theme.addItems(["System", "Light", "Dark"])
        theme.setCurrentText(self.theme)
        layout.addRow("Global theme", theme)
        scheme = QComboBox()
        scheme.addItems(list(PALETTES))
        scheme.setCurrentText(self.scheme)
        layout.addRow("Colour palette", scheme)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        def update():
            self.theme = theme.currentText()
            self.scheme = scheme.currentText()
            self.apply()

        theme.currentTextChanged.connect(update)
        scheme.currentTextChanged.connect(update)
        dialog.exec()


def appearance():
    app = QApplication.instance()
    if not hasattr(app, "magik_appearance"):
        app.magik_appearance = Appearance(app)
    return app.magik_appearance
