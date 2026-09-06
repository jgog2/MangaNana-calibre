import os
import sys
import tempfile

from qt.core import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QIcon,
    QSize,
    Qt,
)

ORANGE = "#FF6740"

TABLER_BOOK_SVG = f"""\
<svg xmlns="http://www.w3.org/2000/svg"
     width="24"
     height="24"
     viewBox="0 0 24 24"
     fill="none"
     stroke="{ORANGE}"
     stroke-width="2"
     stroke-linecap="round"
     stroke-linejoin="round">
  <path d="M3 19a9 9 0 0 1 9 0a9 9 0 0 1 9 0" />
  <path d="M3 6a9 9 0 0 1 9 0a9 9 0 0 1 9 0" />
  <path d="M3 6l0 13" />
  <path d="M12 6l0 13" />
  <path d="M21 6l0 13" />
</svg>
"""


def make_svg_file():
    path = os.path.join(
        tempfile.gettempdir(),
        "manganana_tabler_book.svg",
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(TABLER_BOOK_SVG)
    return path


class Window(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MangaNana Tabler Book Test")
        self.resize(700, 300)

        self.setStyleSheet("""
            QWidget {
                background: #111416;
                color: #f2f2f2;
            }

            QPushButton {
                background: #181c1f;
                border: 1px solid #343a3f;
                border-radius: 7px;
                padding: 10px;
                font-size: 12px;
                font-weight: 600;
            }

            QPushButton:hover {
                border: 1px solid #FF6740;
            }

            QLabel {
                color: #aeb3b8;
            }
        """)

        svg_path = make_svg_file()
        icon = QIcon(svg_path)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        title = QLabel("Exact Tabler BOOK icon")
        title.setStyleSheet(
            "font-size:18px; font-weight:700; color:#f2f2f2;"
        )
        root.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)

        for size in (18, 22, 26, 30, 34):
            btn = QPushButton(
                f"  LANDSCAPE\n  Paired Pages"
            )
            btn.setIcon(icon)
            btn.setIconSize(QSize(size, size))
            btn.setMinimumHeight(72)

            row.addWidget(btn)

        root.addLayout(row)

        note = QLabel(
            "Sizes shown: 18, 22, 26, 30, 34 px. "
            "Pick whichever looks best inside MangaNana's layout card."
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(note)


app = QApplication(sys.argv)
window = Window()
window.show()
sys.exit(app.exec())
