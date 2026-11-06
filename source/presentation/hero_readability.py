"""Complete-line synopsis excerpts and width-owned genre presentation."""
from qt.core import (Qt, QObject, QEvent, QLabel, QWidget, QHBoxLayout, QSize,
                     QSizePolicy, QFontMetrics, QTextLayout, QTextOption, QLayout)
from calibre_plugins.manganana.presentation.interface_scale import set_presentation_style


def synopsis_excerpt(text, font, width, height):
    """Use Qt's own word wrapping; expose only complete lines of visible text."""
    text = ' '.join(str(text or '').split())
    width = max(0, width - 2)
    metrics = QFontMetrics(font)
    count = max(0, height // max(1, metrics.lineSpacing()))
    if not text or not count or not width:
        return ''
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    utf16 = text.encode('utf-16-le')
    lines = []
    layout.beginLayout()
    try:
        for index in range(count):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start, length = line.textStart(), line.textLength()
            if index == count - 1 and start + length < len(utf16) // 2:
                tail = utf16[start * 2:].decode('utf-16-le')
                lines.append(metrics.elidedText(tail, Qt.TextElideMode.ElideRight, width))
            else:
                lines.append(utf16[start * 2:(start + length) * 2].decode('utf-16-le').rstrip())
    finally:
        layout.endLayout()
    return '\n'.join(lines)


class SynopsisField(QObject):
    def __init__(self, label, scroll):
        super().__init__(label)
        self.label, self.scroll, self.text = label, scroll, ''
        self._rendering = False
        self._render_key = None
        self._rendered = ''
        label.setWordWrap(False)
        label.setMinimumSize(0, 0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        label.installEventFilter(self)
        scroll.viewport().installEventFilter(self)

    def set_text(self, text):
        text = str(text or '')
        if text != self.text:
            self.text = text
            self.label.setAccessibleDescription(text)
        self.render()

    def render(self):
        if self._rendering:
            return
        self._rendering = True
        try:
            area = self.scroll.viewport().contentsRect()
            key = (self.text, self.label.font().key(), area.width(), area.height())
            if key != self._render_key:
                self._rendered = synopsis_excerpt(self.text, self.label.font(), area.width(), area.height())
                self._render_key = key
            text = self._rendered
            if self.label.text() != text:
                self.label.setText(text)
        finally:
            self._rendering = False

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.FontChange):
            self.render()
        return False


class GenreStrip(QWidget):
    """Never shrink a chip below its readable width to force it into a row."""
    def __init__(self):
        super().__init__()
        self.tags = ()
        self.chips = []
        self._fitting = False
        self._dirty = True
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.overflow = self.chip('')
        row.addWidget(self.overflow)
        row.addStretch(1)

    def chip(self, text):
        label = QLabel(text, self)
        label.setObjectName('genreChip')
        label.setTextFormat(Qt.TextFormat.PlainText)
        set_presentation_style(label, 'background:rgba(28,43,46,220);border:1px solid #46625d;'
            'border-radius:10px;padding:4px 9px;font-size:13px;color:#eef5f3;')
        label.installEventFilter(self)
        return label

    def set_tags(self, tags):
        tags = tuple(str(tag) for tag in tags if str(tag))
        if tags != self.tags:
            self.tags = tags
            for chip in self.chips:
                self.layout().removeWidget(chip)
                chip.hide()
                chip.deleteLater()
            # The remaining tags are available in the overflow tooltip/details.
            self.chips = [self.chip(tag) for tag in tags[:8]]
            for index, chip in enumerate(self.chips):
                self.layout().insertWidget(index, chip)
            self.setToolTip(', '.join(tags))
            self._dirty = True
        self.fit()

    def fit(self):
        if self._fitting or not self._dirty:
            return
        self._fitting = True
        self._dirty = False
        try:
            width = self.contentsRect().width()
            spacing = self.layout().spacing()
            self.overflow.ensurePolished()
            metrics = QFontMetrics(self.overflow.font())
            padding = max(0,self.overflow.sizeHint().width()-metrics.horizontalAdvance(self.overflow.text()))
            shown = 0
            used = 0
            for index, chip in enumerate(self.chips):
                chip.ensurePolished()
                size = chip.sizeHint()
                remainder = len(self.tags) - index - 1
                reserve = metrics.horizontalAdvance('+'+str(remainder)) + padding + spacing if remainder else 0
                cost = size.width() + (spacing if shown else 0)
                if used + cost + reserve > width:
                    break
                used += cost
                shown += 1
            for index, chip in enumerate(self.chips):
                chip.setVisible(index < shown)
                if index < shown:
                    chip.setFixedSize(chip.sizeHint())
            remaining = len(self.tags) - shown
            if self.overflow.text()!='+'+str(remaining):self.overflow.setText('+'+str(remaining))
            self.overflow.setToolTip(', '.join(self.tags[shown:]))
            self.overflow.setAccessibleName('More genres: ' + ', '.join(self.tags[shown:]))
            self.overflow.setVisible(remaining > 0)
            if remaining:
                self.overflow.setFixedSize(self.overflow.sizeHint())
            # The row deliberately has no horizontal layout constraint. Publish
            # its vertical requirement explicitly so a compact parent cannot
            # allocate less height than the fixed-size chip labels need.
            height = self.sizeHint().height()
            if self.minimumHeight() != height:
                self.setMinimumHeight(height)
                self.updateGeometry()
        finally:
            self._fitting = False

    def sizeHint(self):
        return QSize(0, max((chip.sizeHint().height() for chip in [*self.chips, self.overflow]), default=28))

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._dirty = True
        self.fit()

    def eventFilter(self, watched, event):
        if hasattr(self,'overflow') and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._dirty = True
            self.fit()
        return False

    def event(self, event):
        result=super().event(event)
        if hasattr(self,'overflow') and event.type()==QEvent.Type.LayoutRequest:
            self._dirty = True
            self.fit()
        return result

    def showEvent(self, event):
        super().showEvent(event)
        self._dirty = True
        self.fit()
