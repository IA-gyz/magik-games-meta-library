"""Reusable facet picker and lazily loaded, disk-cached cover grid."""

from ui_actions import action_button, set_button_role
from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QPushButton,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QStyledItemDelegate,
    QStyle,
)
from covers import Covers  # noqa: F401 — compatibility import

from visuals import STORE_COLORS, store_background, is_installed
from unknown_style import UnknownItemDelegate, draw_unknown_text, missing_text


class MultiSelect(QPushButton):
    changed = Signal()

    def __init__(self, label, parent=None):
        super().__init__(parent)
        set_button_role(self, "filter")
        self.label = label
        self.options = []
        self.selected = []
        self.update_label()
        self.clicked.connect(self.choose)

    def set_options(self, values):
        self.options = sorted(set(values) | set(self.selected), key=str.casefold)
        self.update_label()

    def set_selected(self, values):
        self.selected = list(dict.fromkeys(values))
        self.set_options(self.options)
        self.changed.emit()

    def update_label(self):
        self.setText(
            self.label
            + (": All" if not self.selected else f": {len(self.selected)} selected")
        )
        self.setToolTip(missing_text(", ".join(self.selected)) if self.selected else "No restriction")

    def choose(self):
        d = QDialog(self)
        d.setWindowTitle(self.label + " — match any selected value")
        d.resize(450, 520)
        layout = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText("Find values…")
        layout.addWidget(search)
        items = QListWidget()
        items.setItemDelegate(UnknownItemDelegate(items))
        layout.addWidget(items)
        for value in self.options:
            item = QListWidgetItem(value)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if value in self.selected else Qt.Unchecked)
            items.addItem(item)
        search.textChanged.connect(
            lambda text: [
                items.item(i).setHidden(
                    text.casefold() not in items.item(i).text().casefold() and text.casefold() not in missing_text(items.item(i).text()).casefold()
                )
                for i in range(items.count())
            ]
        )
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        for title, check in [("Select visible", True), ("Clear all", False)]:
            button = action_button(title, "filter")
            buttons.addWidget(button)

            def set_checks(checked=False, value=check):
                for i in range(items.count()):
                    item = items.item(i)
                    if not value or not item.isHidden():
                        item.setCheckState(Qt.Checked if value else Qt.Unchecked)

            button.clicked.connect(set_checks)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(actions)
        actions.accepted.connect(d.accept)
        actions.rejected.connect(d.reject)
        if d.exec():
            self.set_selected(
                [
                    items.item(i).text()
                    for i in range(items.count())
                    if items.item(i).checkState() == Qt.Checked
                ]
            )


class CoverDelegate(QStyledItemDelegate):
    def __init__(self, covers, parent=None):
        super().__init__(parent)
        self.covers = covers

    def sizeHint(self, option, index):
        return QSize(190, 312)

    def paint(self, painter, option, index):
        proxy = index.model()
        row = proxy.sourceModel().rows[proxy.mapToSource(index).row()]
        painter.save()
        box = option.rect.adjusted(5, 5, -5, -5)
        selected = bool(option.state & QStyle.State_Selected)
        painter.fillRect(
            box,
            option.palette.highlight()
            if selected
            else store_background(row.get("store"), option.palette),
        )
        painter.fillRect(
            QRect(box.left(), box.top(), 4, box.height()),
            QColor(STORE_COLORS.get(row.get("store"), "#8896a8")),
        )
        picture = QRect(box.left() + 8, box.top() + 8, box.width() - 16, 208)
        pix = self.covers.get_cover(row.get("cover"))
        if pix:
            scaled = pix.scaled(
                picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                picture.left() + (picture.width() - scaled.width()) // 2,
                picture.top() + (picture.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            color = {
                "Steam": "#25455e",
                "GOG": "#623b79",
                "Epic": "#414757",
                "Amazon": "#775225",
                "EA": "#71513f",
            }.get(row["store"], "#495057")
            painter.fillRect(picture, QColor(color))
            painter.setPen(Qt.white)
            painter.drawText(
                picture.adjusted(8, 8, -8, -8),
                Qt.AlignCenter | Qt.TextWordWrap,
                row["title"],
            )
        if is_installed(row):
            badge = QRect(picture.left() + 4, picture.top() + 4, 102, 25)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#24764a"))
            painter.drawRoundedRect(badge, 6, 6)
            badge_font = QFont(option.font)
            badge_font.setBold(True)
            badge_font.setPixelSize(13)
            painter.setFont(badge_font)
            painter.setPen(Qt.white)
            painter.drawText(badge, Qt.AlignCenter, "✓ Installed")
        painter.setPen(
            option.palette.highlightedText().color()
            if selected
            else option.palette.text().color()
        )
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRect(box.left() + 8, box.top() + 222, box.width() - 16, 38),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            row["title"],
        )
        font.setBold(False)
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        background = (
            option.palette.highlight().color()
            if selected
            else store_background(row.get("store"), option.palette)
        )
        draw_unknown_text(
            painter,
            QRect(box.left() + 8, box.bottom() - 42, box.width() - 16, 18),
            row["store"] + " · " + str(row.get("type") or "Unknown"),
            background,
        )
        draw_unknown_text(
            painter,
            QRect(box.left() + 8, box.bottom() - 22, box.width() - 16, 18),
            row.get("installation_status") or "Unknown",
            background,
        )
        painter.restore()
