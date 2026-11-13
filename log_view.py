"""Render typed activity events; message wording never determines severity."""

import html
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTextEdit
from contracts import LogEntry, Severity
from visuals import STORE_COLORS
from unknown_style import highlight_unknown, missing_text

SEVERITY_ROLES = {
    Severity.INFO: "sync",
    Severity.SUCCESS: "launch",
    Severity.WARNING: "file",
    Severity.ERROR: "danger",
}


class ColorLog(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        highlight_unknown(self)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(1500)

    @property
    def lines(self):
        return [entry.text for entry in self.entries]

    def append_events(self, events):
        self.entries.extend(
            LogEntry(line, event.severity, event.source)
            for event in events
            for line in event.text.splitlines()
        )
        self.entries = self.entries[-1500:]
        self.render()

    def set_events(self, events):
        self.entries = []
        self.append_events(events)

    def append(self, text):
        self.append_events([LogEntry(str(text))])

    def setPlainText(self, text):
        self.set_events([LogEntry(str(text))])

    def render(self):
        from appearance import appearance, PALETTES, readable

        base = self.palette().base().color()
        colors = PALETTES[appearance().scheme]
        output = []
        for entry in self.entries:
            color = readable(
                QColor(colors[SEVERITY_ROLES[entry.severity]]), base
            ).name()
            content = html.escape(missing_text(entry.text)) or "&nbsp;"
            if entry.source in STORE_COLORS and entry.text.startswith(
                entry.source + ":"
            ):
                label = entry.source + ":"
                store_color = readable(QColor(STORE_COLORS[entry.source]), base).name()
                content = f'<b style="color:{store_color}">{label}</b>' + html.escape(
                    missing_text(entry.text[len(label) :])
                )
            output.append(
                f'<div style="color:{color};white-space:pre-wrap">{content}</div>'
            )
        bar = self.verticalScrollBar()
        bottom = bar.value() >= bar.maximum() - 3
        position = bar.value()
        self.setHtml("".join(output))
        bar.setValue(bar.maximum() if bottom else position)
