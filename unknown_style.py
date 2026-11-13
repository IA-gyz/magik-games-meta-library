"""Theme-aware purple for Unknown text without changing stored or copied values."""

import html
import re
from PySide6.QtCore import Qt, QEvent, QPointF, QObject
from PySide6.QtGui import (
    QColor,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextLayout,
)
from PySide6.QtWidgets import (
    QTextEdit,
    QStyledItemDelegate,
    QComboBox,
    QStylePainter,
    QStyleOptionComboBox,
    QStyle,
)

UNKNOWN_WORD = re.compile(r"\bUnknown\b", re.IGNORECASE)
UNKNOWN = re.compile(r"\bUnknown\b|—", re.IGNORECASE)

def missing_text(text):
    return UNKNOWN_WORD.sub("—", str(text))


def unknown_color(background):
    def luminance(color):
        values = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in color.getRgbF()[:3]
        ]
        return sum(a * b for a, b in zip(values, (0.2126, 0.7152, 0.0722)))

    base = luminance(background)
    choices = [QColor("#7424a8"), QColor("#dfb0ff")]

    def contrast(color):
        value = luminance(color)
        return (max(base, value) + 0.05) / (min(base, value) + 0.05)

    best = max(choices, key=contrast)
    if contrast(best) >= 4.5:
        return best
    return max([QColor("#310046"), QColor("#fbf1ff")], key=contrast)


class UnknownHighlighter(QSyntaxHighlighter):
    def __init__(self, widget):
        super().__init__(widget.document())
        self.widget = widget
        widget.installEventFilter(self)

    def highlightBlock(self, text):
        format = QTextCharFormat()
        format.setForeground(unknown_color(self.widget.palette().base().color()))
        for match in UNKNOWN.finditer(text):
            # Qt positions count UTF-16 units, not Python Unicode code points.
            start = len(text[: match.start()].encode("utf-16-le")) // 2
            length = len(match.group().encode("utf-16-le")) // 2
            self.setFormat(start, length, format)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.PaletteChange:
            self.rehighlight()
        return False


def highlight_unknown(widget):
    if not hasattr(widget, "unknown_highlighter"):
        widget.unknown_highlighter = UnknownHighlighter(widget)
    return widget.unknown_highlighter


class UnknownTextEdit(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        highlight_unknown(self)

    def setPlainText(self, text):
        super().setPlainText(missing_text(text))


class UnknownItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = missing_text(option.text)
        if UNKNOWN.search(option.text):
            background = (
                option.palette.highlight().color()
                if option.state & QStyle.State_Selected
                else option.backgroundBrush.color()
                if option.backgroundBrush.style() != Qt.NoBrush
                else option.palette.base().color()
            )
            color = unknown_color(background)
            option.palette.setColor(QPalette.Text, color)
            option.palette.setColor(QPalette.HighlightedText, color)
            option.palette.setColor(QPalette.Disabled, QPalette.Text, color)
            option.palette.setColor(QPalette.Disabled, QPalette.HighlightedText, color)


def draw_unknown_text(painter, rect, text, background):
    text = missing_text(text)
    layout = QTextLayout(text, painter.font())
    ranges = []
    for match in UNKNOWN.finditer(text):
        item = QTextLayout.FormatRange()
        item.start = len(text[: match.start()].encode("utf-16-le")) // 2
        item.length = len(match.group().encode("utf-16-le")) // 2
        item.format.setForeground(unknown_color(background))
        ranges.append(item)
    layout.setFormats(ranges)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(rect.width())
    layout.endLayout()
    painter.save()
    painter.setClipRect(rect)
    layout.draw(
        painter,
        QPointF(rect.left(), rect.top() + max(0, (rect.height() - line.height()) / 2)),
    )
    painter.restore()


class UnknownComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setItemDelegate(UnknownItemDelegate(self))

    def paintEvent(self, event):
        if not UNKNOWN.search(self.currentText()):
            return super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        rect = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        painter.setPen(option.palette.buttonText().color())
        draw_unknown_text(
            painter, rect, self.currentText(), option.palette.button().color()
        )


def unknown_html(text, palette):
    escaped = html.escape(missing_text(text))
    color = unknown_color(palette.window().color()).name()
    return (
        "<span>"
        + UNKNOWN.sub(
            lambda match: f'<span style="color:{color}">{match.group()}</span>', escaped
        ).replace("\n", "<br>")
        + "</span>"
    )


class UnknownLabelFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.PaletteChange:
            obj.setText(unknown_html(obj.unknown_text, obj.palette()))
        return False


def set_unknown_label(label, text):
    label.unknown_text = text
    if not hasattr(label, "unknown_label_filter"):
        label.unknown_label_filter = UnknownLabelFilter(label)
        label.installEventFilter(label.unknown_label_filter)
    label.setText(unknown_html(text, label.palette()))
