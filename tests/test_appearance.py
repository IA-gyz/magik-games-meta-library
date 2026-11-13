import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QPushButton,
        QWidget,
        QHBoxLayout,
    )
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtCore import QSettings, QTimer
    from appearance import appearance, PALETTES, readable
    from log_view import ColorLog
    from ui_actions import action_button, set_button_role
    import main_window as app
    from qt_wait import settle
except ImportError:
    app = None
import kde_integration as kde


class DesktopIntegrationTests(unittest.TestCase):
    def test_persistent_icon_and_entry_survive_window_close(self):
        with (
            tempfile.TemporaryDirectory(prefix="magik kde ") as tmp,
            patch.dict(os.environ, {"XDG_DATA_HOME": tmp}),
        ):
            kde.register(quiet=True, refresh=False)
            entry = Path(tmp) / "applications" / f"{kde.APP_ID}.desktop"
            text = entry.read_text()
            self.assertIn("StartupWMClass=" + kde.APP_ID, text)
            iconline = next(
                line[5:] for line in text.splitlines() if line.startswith("Icon=")
            )
            self.assertTrue(Path(iconline).is_file())
            self.assertTrue(Path(iconline).is_absolute())
            kde.register(quiet=True, refresh=False)
            self.assertEqual(entry.read_text(), text)
            kde.register(remove=True, quiet=True, refresh=False)
            self.assertFalse(entry.exists())


@unittest.skipIf(app is None, "PySide6 required")
class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def test_explicit_role_survives_label_changes(self):
        button = action_button("Refresh libraries", "sync")
        button.setText("A different label")
        manager = appearance()
        manager.apply()
        self.assertEqual(button.property("actionRole"), "sync")
        self.assertTrue(button.styleSheet())
        with self.assertRaises(ValueError):
            set_button_role(button, "invalid")
        button.deleteLater()

    def test_palette_changes_rendered_button_pixels(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)
        buttons = [
            action_button("Action", role)
            for role in [
                "sync",
                "metadata",
                "filter",
                "file",
                "settings",
                "launch",
                "danger",
            ]
        ]
        for button in buttons:
            layout.addWidget(button)
        panel.show()
        self.q.processEvents()
        manager = appearance()
        old = (manager.theme, manager.scheme)
        try:
            for theme in ["System", "Light", "Dark"]:
                samples = []
                for scheme in PALETTES:
                    manager.theme = theme
                    manager.scheme = scheme
                    manager.apply()
                    self.q.processEvents()
                    samples.append(
                        tuple(
                            button.grab()
                            .toImage()
                            .pixelColor(12, button.height() // 2)
                            .name()
                            for button in buttons
                        )
                    )
                self.assertEqual(len(set(samples)), len(PALETTES), theme)
                self.assertGreater(len(set(samples[0])), 1, theme)
        finally:
            manager.theme, manager.scheme = old
            manager.apply()
            panel.close()
            panel.deleteLater()

    def test_log_severity_is_not_inferred_and_reload_retains_history(self):
        from contracts import LogEntry, Severity, OperationResult

        log = ColorLog()
        log.append_events(
            [
                LogEntry("0 errors and 0 unknown", Severity.SUCCESS),
                LogEntry("Ordinary text", Severity.ERROR),
            ]
        )
        self.assertEqual(
            [entry.severity for entry in log.entries],
            [Severity.SUCCESS, Severity.ERROR],
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(app, "ROOT", Path(tmp)),
            patch.object(
                app,
                "QSettings",
                lambda *args: QSettings(
                    str(Path(tmp) / "settings.ini"), QSettings.IniFormat
                ),
            ),
        ):
            window = settle(app.Window())
            window.finished(
                OperationResult((LogEntry("Kept event", Severity.WARNING),))
            )
            before = window.status.toPlainText()
            window.reload()
            settle(window)
            self.assertEqual(window.status.toPlainText(), before)
            window.close()
        log.deleteLater()

    def test_logs_are_literal_and_recolor_without_changing_content(self):
        log = ColorLog()
        log.setPlainText("EA: Failed <b>literal</b>\nSteam: 10 records fetched")
        before = log.toPlainText()
        manager = appearance()
        old = (manager.theme, manager.scheme)
        for theme in ["Light", "Dark"]:
            for scheme in PALETTES:
                manager.theme = theme
                manager.scheme = scheme
                manager.apply()
                self.assertEqual(log.toPlainText(), before)
        self.assertIn("&lt;b&gt;", log.toHtml())
        manager.theme, manager.scheme = old
        manager.apply()
        log.deleteLater()

    def test_column_dialog_stays_open_for_multiple_changes(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(app, "ROOT", Path(tmp)),
            patch.object(
                app,
                "QSettings",
                lambda *args: QSettings(
                    str(Path(tmp) / "settings.ini"), QSettings.IniFormat
                ),
            ),
        ):
            window = settle(app.Window())
            results = []

            def click():
                dialog = next(
                    d
                    for d in self.q.topLevelWidgets()
                    if isinstance(d, QDialog) and d.windowTitle() == "Visible columns"
                )
                checks = dialog.findChildren(QCheckBox)
                checks[1].setChecked(False)
                checks[2].setChecked(False)
                results.append(
                    dialog.isVisible()
                    and window.table.isColumnHidden(1)
                    and window.table.isColumnHidden(2)
                )
                checks[1].setChecked(True)
                results.append(
                    dialog.isVisible() and not window.table.isColumnHidden(1)
                )
                dialog.reject()

            QTimer.singleShot(20, click)
            window.columns_menu()
            self.assertEqual(results, [True, True])
            window.close()
