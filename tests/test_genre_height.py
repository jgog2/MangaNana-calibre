"""Genre rows must preserve complete chip rectangles under height pressure."""
import unittest
from qt.core import QApplication, QWidget, QVBoxLayout, QPoint
from calibre_plugins.manganana.presentation.hero_readability import GenreStrip


class GenreHeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_complete_chips(self, strip):
        self.app.processEvents()
        chips = [w for w in [*strip.chips, strip.overflow] if w.isVisible()]
        self.assertTrue(chips)
        for chip in chips:
            self.assertGreaterEqual(chip.height(), chip.sizeHint().height())
            self.assertGreaterEqual(chip.mapTo(strip, QPoint()).y(), 0)
            self.assertLessEqual(chip.mapTo(strip, QPoint()).y() + chip.height(), strip.height())
            self.assertEqual(chip.height(), chip.visibleRegion().boundingRect().height())

    def test_compact_row_cannot_clip_chips_after_late_metadata(self):
        strip = GenreStrip()
        try:
            strip.resize(440, 16); strip.show(); self.app.processEvents()
            strip.set_tags(['Action', 'Comedy', 'Drama', 'Horror', 'Supernatural'])
            strip.resize(440, 16)
            self.assert_complete_chips(strip)
        finally:
            strip.close(); strip.deleteLater(); self.app.processEvents()

    def test_font_growth_reallocates_height_without_window_resize(self):
        panel = QWidget(); layout = QVBoxLayout(panel)
        strip = GenreStrip(); layout.addWidget(strip)
        try:
            strip.set_tags(['Action', 'Comedy', 'Supernatural', 'Science Fiction'])
            panel.resize(310, 55); panel.show(); self.app.processEvents()
            for font_size in (11, 19, 13):
                for chip in [*strip.chips, strip.overflow]:
                    chip.setStyleSheet(f'font-size:{font_size}px;padding:4px 9px;border:1px solid gray;')
                self.app.processEvents()
                strip.resize(strip.width(), 16)
                self.assert_complete_chips(strip)
        finally:
            panel.close(); panel.deleteLater(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
