import os, sys, unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QStyle
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette, QFont
    from unknown_style import (
        UnknownTextEdit,
        UnknownItemDelegate,
        unknown_color,
        unknown_html,
    )
    from catalog_model import Model
    from core import game
except ImportError:
    UnknownTextEdit = None


@unittest.skipIf(UnknownTextEdit is None, "PySide6 required")
class UnknownStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def test_table_unknown_has_purple_foreground_but_known_values_do_not(self):
        model = Model()
        model.load([game("Steam", "1", "Example", {})])
        index = model.index(0, 2)
        self.assertEqual(model.data(index), "—")
        self.assertIsInstance(model.data(index, Qt.ForegroundRole), QColor)
        self.assertIsNone(model.data(model.index(0, 0), Qt.ForegroundRole))

    def test_text_highlighting_preserves_literal_text_and_handles_emoji(self):
        widget = UnknownTextEdit()
        text = "😀 Unknown, (Unknown), unknown. <b>literal</b> known"
        widget.setPlainText(text)
        widget.unknown_highlighter.rehighlight()
        self.assertEqual(widget.toPlainText(), "😀 —, (—), —. <b>literal</b> known")
        formats = widget.document().firstBlock().layout().formats()
        self.assertEqual(len(formats), 3)
        self.assertEqual(formats[0].start, 3)
        self.assertEqual(
            formats[0].format.foreground().color(),
            unknown_color(widget.palette().base().color()),
        )
        widget.close()

    def test_theme_change_rehighlights_existing_text(self):
        widget = UnknownTextEdit()
        widget.setPlainText("Unknown")
        colors = []
        for background in ["#ffffff", "#191b20"]:
            palette = widget.palette()
            palette.setColor(QPalette.Base, QColor(background))
            widget.setPalette(palette)
            widget.unknown_highlighter.rehighlight()
            formats = widget.document().firstBlock().layout().formats()
            colors.append(formats[0].format.foreground().color().name())
        self.assertNotEqual(*colors)
        widget.close()

    def test_selected_unknown_remains_purple(self):
        model = Model()
        model.load([game("GOG", "1", "Example", {})])
        option = QStyleOptionViewItem()
        option.palette = self.q.palette()
        option.state |= QStyle.State_Selected
        delegate = UnknownItemDelegate()
        delegate.initStyleOption(option, model.index(0, 2))
        self.assertEqual(
            option.palette.color(QPalette.HighlightedText),
            unknown_color(option.palette.highlight().color()),
        )

    def test_label_markup_is_escaped(self):
        text = unknown_html('<img src="private"> Unknown', self.q.palette())
        self.assertIn("&lt;img", text)
        self.assertNotIn("<img", text)
        self.assertIn("color:", text)

    def test_unknown_glyphs_render_purple_in_light_and_dark(self):
        for background in ["#ffffff", "#191b20"]:
            widget = UnknownTextEdit()
            palette = widget.palette()
            palette.setColor(QPalette.Base, QColor(background))
            widget.setPalette(palette)
            widget.setFont(QFont("DejaVu Sans", 18))
            widget.setPlainText("Unknown")
            widget.resize(220, 70)
            widget.show()
            self.q.processEvents()
            widget.unknown_highlighter.rehighlight()
            picture = widget.grab().toImage()
            target = unknown_color(QColor(background))
            near = 0
            for y in range(picture.height()):
                for x in range(picture.width()):
                    color = picture.pixelColor(x, y)
                    if (
                        sum(
                            abs(a - b)
                            for a, b in zip(color.getRgb()[:3], target.getRgb()[:3])
                        )
                        < 30
                    ):
                        near += 1
            self.assertGreater(near, 10)
            widget.close()
