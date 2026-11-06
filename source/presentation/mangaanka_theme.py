"""Judgement presentation tokens and QSS. No workflow or preference dependencies.

Values mirror docs/ui/mangaanka.tokens.json; parity is checked by the test suite.
Qt logical pixels are scaled by Qt, never multiplied by the device pixel ratio.
"""

DEEP_OCEAN = '#08131D'
MIDNIGHT_BLUE = '#10253A'
STORM_BLUE = '#1C3A52'
SEA_GREEN = '#3E7C72'
BRIGHT_SEAFOAM = '#66B7A8'
DEEP_TEAL = '#285A58'
INDIGO_DEPTH = '#242A46'
OFF_WHITE = '#EEF3F1'
MIST_GRAY = '#AAB8BD'
LIGHTHOUSE_RED = '#C94B4B'
SOFT_BEACON_WHITE = '#F6F1E7'
DISABLED_BG = '#33383B'
DISABLED_TEXT = '#7F878B'
SPACING = (4, 8, 12, 16, 24, 32)
RADII = (6, 8, 12, 16)


def text_style(size=12, weight=400, color=MIST_GRAY):
    return f'color:{color}; font-size:{size}px; font-weight:{weight};'


SECTION_STYLE = text_style(16, 600, OFF_WHITE)
HELPER_STYLE = text_style()
COVER_PLACEHOLDER_STYLE = f'background:{DEEP_OCEAN}; color:{BRIGHT_SEAFOAM}; border:1px solid {DEEP_TEAL}; border-radius:6px; font-size:11px; font-weight:700;'
ROUND_SELECTOR_STYLE = f'''
    QPushButton {{ background:{DEEP_OCEAN}; color:{BRIGHT_SEAFOAM}; border:1px solid {DEEP_TEAL}; border-radius:11px; padding:0; font-weight:700; }}
    QPushButton:checked {{ background:{BRIGHT_SEAFOAM}; color:{DEEP_OCEAN}; }}
    QPushButton:hover, QPushButton:focus {{ border:1px solid {SOFT_BEACON_WHITE}; }}
    QPushButton:pressed {{ background:{DEEP_TEAL}; color:{OFF_WHITE}; }}
    QPushButton:disabled {{ background:{DISABLED_BG}; color:{DISABLED_TEXT}; border-color:{DISABLED_BG}; }}
'''
RESULT_ROW_STYLE = f'''
    QFrame#volumeRow {{ background:{DEEP_OCEAN}; border:1px solid transparent; border-radius:6px; }}
    QFrame#volumeRow:hover {{ background:{MIDNIGHT_BLUE}; border-color:{DEEP_TEAL}; }}
    QFrame#volumeRow[selected="true"] {{ background:{DEEP_TEAL}; border-color:{BRIGHT_SEAFOAM}; }}
'''


def set_role(widget, role):
    """Repolish only the widget whose semantic role has changed."""
    widget.setProperty('ankaRole', role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def stylesheet():
    """Shared component states; legacy object names keep current signal wiring."""
    return f'''
    QDialog, QWidget#mangananaShell {{ background:{DEEP_OCEAN}; }}
    QWidget {{ color:{OFF_WHITE}; font-size:12px; }}
    QLabel {{ background:transparent; }}
    QWidget#customizationSection {{ background:{DEEP_OCEAN}; border:1px solid {DEEP_TEAL}; border-radius:8px; }}
    QPushButton#sectionHeader {{ text-align:left; border:0; background:transparent; padding:5px 0; }}
    QPushButton#sectionHeader:hover, QPushButton#sectionHeader:focus {{ color:{BRIGHT_SEAFOAM}; }}
    QFrame#card, QGroupBox, QFrame[ankaRole="panel"] {{
        background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {MIDNIGHT_BLUE},stop:1 {DEEP_OCEAN});
        border:1px solid {DEEP_TEAL}; border-radius:16px;
    }}
    QWidget#selectedMangaCard, QFrame[ankaRole="nested"], QFrame#sourceManagerRow {{
        background:{STORM_BLUE}; border:1px solid {DEEP_TEAL}; border-radius:12px;
    }}
    QGroupBox {{ margin-top:16px; padding:16px 12px 12px; font-weight:600; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 4px; }}
    QLabel[ankaRole="heading"] {{ color:{OFF_WHITE}; font-size:16px; font-weight:600; }}
    QLabel[ankaRole="helper"] {{ color:{MIST_GRAY}; }}
    QLabel[ankaRole="empty"] {{ background:{DEEP_OCEAN}; color:{MIST_GRAY}; border:1px solid {DEEP_TEAL}; border-radius:12px; padding:12px; }}
    QLabel[ankaRole="status"] {{ background:{STORM_BLUE}; color:{OFF_WHITE}; border:1px solid {DEEP_TEAL}; border-radius:6px; padding:4px 8px; }}
    QLabel[ankaRole="ready"] {{ background:{DEEP_TEAL}; color:{OFF_WHITE}; border-radius:6px; padding:4px 8px; }}
    QLabel[ankaRole="error"] {{ color:{LIGHTHOUSE_RED}; }}
    QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit {{
        background:{DEEP_OCEAN}; color:{OFF_WHITE}; border:1px solid {DEEP_TEAL}; border-radius:8px;
        padding:6px; selection-background-color:{DEEP_TEAL}; selection-color:{OFF_WHITE};
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color:{BRIGHT_SEAFOAM}; }}
    QComboBox {{ padding-right:28px; }}
    QComboBox::drop-down {{ width:24px; border:0; border-left:1px solid {DEEP_TEAL}; }}
    QComboBox::down-arrow {{ image:none; width:0; height:0; }}
    QComboBox QAbstractItemView {{ background:{MIDNIGHT_BLUE}; color:{OFF_WHITE}; selection-background-color:{DEEP_TEAL}; selection-color:{OFF_WHITE}; border:1px solid {BRIGHT_SEAFOAM}; }}
    QPushButton, QToolButton {{ background:{MIDNIGHT_BLUE}; color:{OFF_WHITE}; border:1px solid {DEEP_TEAL}; border-radius:8px; padding:7px 12px; font-weight:600; }}
    QPushButton:hover, QToolButton:hover {{ background:{DEEP_TEAL}; border-color:{BRIGHT_SEAFOAM}; }}
    QPushButton:pressed, QToolButton:pressed {{ background:{STORM_BLUE}; border-color:{SOFT_BEACON_WHITE}; }}
    QPushButton:focus, QToolButton:focus {{ border-color:{SOFT_BEACON_WHITE}; }}
    QPushButton#primaryAction, QPushButton[ankaRole="primary"] {{ background:{BRIGHT_SEAFOAM}; color:{DEEP_OCEAN}; border:1px solid {BRIGHT_SEAFOAM}; padding:9px 16px; font-weight:700; }}
    QPushButton#primaryAction:hover, QPushButton#primaryAction:focus, QPushButton[ankaRole="primary"]:hover, QPushButton[ankaRole="primary"]:focus {{ border-color:{SOFT_BEACON_WHITE}; }}
    QPushButton#primaryAction:pressed, QPushButton[ankaRole="primary"]:pressed {{ background:{DEEP_TEAL}; color:{OFF_WHITE}; }}
    QPushButton#secondaryAction {{ padding:7px 12px; }}
    QPushButton[ankaRole="destructive"] {{ color:{OFF_WHITE}; border-color:{LIGHTHOUSE_RED}; }}
    QPushButton[ankaRole="destructive"]:hover {{ background:{LIGHTHOUSE_RED}; color:{DEEP_OCEAN}; }}
    QPushButton#modeChoice:checked, QPushButton#processingChoice:checked, QPushButton#layoutChoice:checked, QPushButton[ankaRole="segment"]:checked {{ background:{BRIGHT_SEAFOAM}; color:{DEEP_OCEAN}; border-color:{BRIGHT_SEAFOAM}; }}
    QPushButton#modeChoice:focus, QPushButton#processingChoice:focus, QPushButton#layoutChoice:focus {{ border-color:{SOFT_BEACON_WHITE}; }}
    QPushButton#layoutChoice {{ min-width:118px; min-height:62px; padding:5px 7px; }}
    QPushButton:disabled, QToolButton:disabled, QPushButton#primaryAction:disabled, QPushButton#secondaryAction:disabled,
    QPushButton#modeChoice:disabled, QPushButton#layoutChoice:disabled, QPushButton#processingChoice:disabled,
    QPushButton[ankaRole="primary"]:disabled, QPushButton[ankaRole="destructive"]:disabled, QPushButton[ankaRole="segment"]:disabled,
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{ background:{DISABLED_BG}; color:{DISABLED_TEXT}; border-color:{DISABLED_BG}; }}
    QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color:{DISABLED_TEXT}; }}
    QCheckBox, QRadioButton {{ spacing:8px; padding:2px; border:1px solid transparent; border-radius:6px; }}
    QCheckBox:focus, QRadioButton:focus {{ border-color:{BRIGHT_SEAFOAM}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width:16px; height:16px; background:{DEEP_OCEAN}; border:1px solid {DEEP_TEAL}; }}
    QCheckBox::indicator {{ border-radius:4px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color:{BRIGHT_SEAFOAM}; }}
    QCheckBox::indicator:checked {{ background:{BRIGHT_SEAFOAM}; border-color:{BRIGHT_SEAFOAM}; image:none; }}
    QCheckBox::indicator:indeterminate {{ background:{SEA_GREEN}; border:3px solid {BRIGHT_SEAFOAM}; }}
    QRadioButton::indicator {{ border-radius:9px; }}
    QRadioButton::indicator:checked {{ background:{BRIGHT_SEAFOAM}; border:4px solid {DEEP_TEAL}; width:10px; height:10px; }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background:{DISABLED_BG}; border-color:{DISABLED_TEXT}; }}
    QCheckBox#importUseCheckbox {{ background:transparent; padding:0; spacing:0; border:0; }}
    QSlider:horizontal {{ min-height:20px; padding:2px 3px; }}
    QSlider::groove:horizontal {{ height:4px; background:{STORM_BLUE}; border-radius:2px; }}
    QSlider::sub-page:horizontal {{ background:{BRIGHT_SEAFOAM}; border-radius:2px; }}
    QSlider::handle:horizontal {{ width:14px; margin:-6px 0; background:{BRIGHT_SEAFOAM}; border:1px solid {BRIGHT_SEAFOAM}; border-radius:7px; }}
    QSlider::handle:horizontal:hover, QSlider::handle:horizontal:focus {{ border-color:{SOFT_BEACON_WHITE}; }}
    QSlider::handle:horizontal:pressed {{ background:{OFF_WHITE}; }}
    QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled {{ background:{DISABLED_TEXT}; border-color:{DISABLED_TEXT}; }}
    QProgressBar {{ border:1px solid {DEEP_TEAL}; border-radius:6px; background:{DEEP_OCEAN}; min-height:11px; }}
    QProgressBar::chunk {{ background:{BRIGHT_SEAFOAM}; border-radius:4px; }}
    QAbstractItemView {{ background:{DEEP_OCEAN}; color:{OFF_WHITE}; alternate-background-color:{MIDNIGHT_BLUE}; border:1px solid {DEEP_TEAL}; border-radius:8px; padding:4px; selection-background-color:{DEEP_TEAL}; selection-color:{OFF_WHITE}; }}
    QAbstractItemView:focus {{ border-color:{BRIGHT_SEAFOAM}; }}
    QAbstractItemView::item:selected {{ background:{DEEP_TEAL}; color:{OFF_WHITE}; }}
    QTableWidget {{ gridline-color:{MIDNIGHT_BLUE}; }}
    QHeaderView::section {{ background:{STORM_BLUE}; color:{OFF_WHITE}; border:0; border-bottom:1px solid {DEEP_TEAL}; padding:8px 6px; }}
    QTableCornerButton::section {{ background:{STORM_BLUE}; border:0; }}
    QScrollArea, QStackedWidget, QWidget#previewOverview, QWidget#previewDetail, QWidget#previewBody {{ background:transparent; border:0; }}
    QScrollBar:vertical {{ background:{DEEP_OCEAN}; width:12px; margin:0; }}
    QScrollBar:horizontal {{ background:{DEEP_OCEAN}; height:12px; margin:0; }}
    QScrollBar::handle {{ background:{DEEP_TEAL}; border:2px solid {DEEP_OCEAN}; border-radius:6px; min-height:24px; min-width:24px; }}
    QScrollBar::handle:hover {{ background:{SEA_GREEN}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
    QFrame#ankaHeader, QFrame#ankaFooter {{ background:{DEEP_OCEAN}; border:0; }}
    QFrame#ankaFooter {{ border-top:1px solid {DEEP_TEAL}; }}
    QLabel#ankaName {{ color:{SOFT_BEACON_WHITE}; font-size:28px; font-weight:700; }}
    QLabel#ankaSubtitle, QLabel#ankaVersion {{ color:{MIST_GRAY}; font-size:12px; }}
    QLabel#ankaStep {{ color:{MIST_GRAY}; font-size:14px; font-weight:600; padding:8px 4px; border-bottom:2px solid transparent; }}
    QLabel#ankaStep[active="true"] {{ color:{BRIGHT_SEAFOAM}; border-bottom-color:{BRIGHT_SEAFOAM}; }}
    '''


def apply_theme(widget):
    from qt.core import QColor, QFont, QFontDatabase, QPalette
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if 'Segoe UI' in QFontDatabase.families():
        font = QFont('Segoe UI')
    widget.setFont(font)
    palette = widget.palette()
    for role, value in ((QPalette.ColorRole.Window, DEEP_OCEAN),
                        (QPalette.ColorRole.Base, DEEP_OCEAN),
                        (QPalette.ColorRole.Text, OFF_WHITE),
                        (QPalette.ColorRole.WindowText, OFF_WHITE),
                        (QPalette.ColorRole.PlaceholderText, MIST_GRAY),
                        (QPalette.ColorRole.Highlight, DEEP_TEAL),
                        (QPalette.ColorRole.HighlightedText, OFF_WHITE)):
        palette.setColor(role, QColor(value))
    widget.setPalette(palette)
    widget.setStyleSheet(stylesheet())
