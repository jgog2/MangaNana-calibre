import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

from qt.core import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QTabWidget, Qt, QTimer, QVBoxLayout, QWidget, QPixmap
)

from kaleido_surface import (
    CFA_LAYOUT_NAME, LANDSCAPE, PORTRAIT, apply_kaleido_surface,
    diagnostic_image, merge_lab_profile, normalized_surface,
)

HERE = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = HERE / "kobo_libra_colour_lab_profile.json"


def pil_to_pixmap(image):
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, "PNG")
    pm = QPixmap()
    if not pm.loadFromData(buffer.getvalue(), "PNG"):
        raise RuntimeError("Could not convert Pillow image to QPixmap.")
    return pm


def contain_on_canvas(image, target_size):
    image = image.convert("RGB")
    fitted = ImageOps.contain(image, target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, "white")
    x = (target_size[0] - fitted.width) // 2
    y = (target_size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def reduce_chroma_resolution(image, percent):
    """Preserve full-resolution luminance while reducing only Cb/Cr detail."""
    percent = max(1, min(100, int(round(percent))))
    if percent >= 100:
        return image

    ycbcr = image.convert("YCbCr")
    y, cb, cr = ycbcr.split()
    dw = max(1, round(image.width * percent / 100.0))
    dh = max(1, round(image.height * percent / 100.0))

    cb = cb.resize((dw, dh), Image.Resampling.BILINEAR)
    cr = cr.resize((dw, dh), Image.Resampling.BILINEAR)
    cb = cb.resize(image.size, Image.Resampling.BILINEAR)
    cr = cr.resize(image.size, Image.Resampling.BILINEAR)

    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def apply_tone(image, black_floor, white_ceiling, gamma):
    black_floor = max(0, min(254, int(round(black_floor))))
    white_ceiling = max(black_floor + 1, min(255, int(round(white_ceiling))))
    gamma = max(0.25, min(4.0, float(gamma)))

    lut = []
    for value in range(256):
        normalized = value / 255.0
        corrected = normalized ** (1.0 / gamma)
        mapped = black_floor + corrected * (white_ceiling - black_floor)
        lut.append(max(0, min(255, round(mapped))))

    return image.point(lut * 3)


def apply_channel_gains(image, red_gain, green_gain, blue_gain):
    r, g, b = image.split()

    def adjusted(channel, factor):
        factor = max(0.25, min(2.0, float(factor)))
        lut = [max(0, min(255, round(i * factor))) for i in range(256)]
        return channel.point(lut)

    return Image.merge(
        "RGB",
        (
            adjusted(r, red_gain),
            adjusted(g, green_gain),
            adjusted(b, blue_gain),
        ),
    )


def circular_hue_weight(hue_byte, center_degrees, half_width_degrees=35.0):
    """Triangular hue weight in 0..255, including wrap-around at red."""
    hue_degrees = hue_byte * (360.0 / 255.0)
    distance = abs(hue_degrees - center_degrees)
    distance = min(distance, 360.0 - distance)
    weight = max(0.0, 1.0 - distance / half_width_degrees)
    return round(weight * 255)


def saturation_gate_weight(sat_byte, threshold_percent):
    threshold = max(0.0, min(99.0, float(threshold_percent))) * 2.55
    if sat_byte <= threshold:
        return 0
    remaining = max(1.0, 255.0 - threshold)
    return round(255.0 * (sat_byte - threshold) / remaining)


def apply_hue_corrections(image, hue_data):
    """Apply gentle saturation-gated hue-localized brightness/color corrections.

    This is intentionally a lab model, not production behavior. Each anchor blends
    an adjusted version of the current image through a smooth hue + saturation mask.
    """
    if not hue_data or not hue_data.get("enabled", False):
        return image

    gate_percent = hue_data.get("saturation_gate_percent", 25)
    anchors = hue_data.get("anchors", {})
    out = image.convert("RGB")

    # Hue and saturation are sampled from the globally transformed image so the
    # corrections describe the color that is actually about to be displayed.
    hsv = out.convert("HSV")
    h_channel, s_channel, _v_channel = hsv.split()

    saturation_mask = s_channel.point(
        lambda s: saturation_gate_weight(s, gate_percent)
    )

    for name, anchor in anchors.items():
        lightness = float(anchor.get("lightness_percent", 0.0))
        saturation = float(anchor.get("saturation_percent", 0.0))
        if abs(lightness) < 1e-9 and abs(saturation) < 1e-9:
            continue

        center = float(anchor.get("hue_degrees", 0.0))
        hue_mask = h_channel.point(
            lambda h, center=center: circular_hue_weight(h, center)
        )
        mask = ImageChops.multiply(hue_mask, saturation_mask)

        adjusted = out
        if abs(saturation) >= 1e-9:
            adjusted = ImageEnhance.Color(adjusted).enhance(max(0.0, 1.0 + saturation / 100.0))
        if abs(lightness) >= 1e-9:
            adjusted = ImageEnhance.Brightness(adjusted).enhance(max(0.0, 1.0 + lightness / 100.0))

        out = Image.composite(adjusted, out, mask)

    return out


def emulate(image, values, profile):
    orientation = values.get("device_orientation", PORTRAIT)
    target = tuple(profile["native_portrait"] if orientation == PORTRAIT
                   else profile["native_landscape"])

    # Screen emulation changes only the internal device framebuffer. It never
    # changes the application window or output CBZ.
    out = contain_on_canvas(image, target)
    out = reduce_chroma_resolution(out, values["chroma_resolution_percent"])
    out = apply_tone(out, values["black_floor"], values["white_ceiling"], values["gamma"])
    out = apply_channel_gains(out, values["red_gain"], values["green_gain"], values["blue_gain"])
    out = ImageEnhance.Color(out).enhance(values["saturation"])
    out = apply_hue_corrections(out, values["hue_corrections"])

    out = apply_kaleido_surface(
        out, values.get("kaleido_surface") or {}, orientation,
        portrait_height=int(profile["native_portrait"][1]),
        portrait_width=int(profile["native_portrait"][0]),
    )

    softness = max(0.0, float(values["softness_radius"]))
    if softness > 0.0:
        out = out.filter(ImageFilter.GaussianBlur(radius=softness))

    return out


def portrait_screen_rect_from_landscape(frame_width, screen_rect):
    """Rotate landscape frame 90 degrees CCW and transform its exact screen rect."""
    x = int(screen_rect["x"])
    y = int(screen_rect["y"])
    w = int(screen_rect["width"])
    h = int(screen_rect["height"])
    # Pillow Image.rotate(90, expand=True): old rectangle -> new rectangle.
    return {
        "x": y,
        "y": frame_width - (x + w),
        "width": h,
        "height": w,
    }


def compose_device_frame(screen, profile, frame_image):
    """Place the framebuffer at the exact user-measured frame rectangle."""
    landscape_rect = profile["frame"]["landscape_screen_rect"]

    if screen.height >= screen.width:
        frame = frame_image.rotate(90, expand=True)
        rect = portrait_screen_rect_from_landscape(frame_image.width, landscape_rect)
    else:
        frame = frame_image.copy()
        rect = dict(landscape_rect)

    target = (int(rect["width"]), int(rect["height"]))
    if screen.size != target:
        # This should normally be exact: 1680x1264 or 1264x1680.
        screen = screen.resize(target, Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.alpha_composite(screen.convert("RGBA"), (int(rect["x"]), int(rect["y"])))
    canvas.alpha_composite(frame)
    return canvas


class NumberSlider(QWidget):
    """Slider + editable number box, always synchronized in both directions."""

    def __init__(
        self, label, minimum, maximum, value, decimals=0, step=1.0,
        suffix="", parent=None
    ):
        super().__init__(parent)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.decimals = int(decimals)
        self.factor = 10 ** self.decimals

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.label = QLabel(label)
        self.label.setMinimumWidth(122)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(
            round(self.minimum * self.factor),
            round(self.maximum * self.factor),
        )
        self.slider.setSingleStep(max(1, round(float(step) * self.factor)))

        self._integer_box = not bool(self.decimals)
        if self.decimals:
            self.number = QDoubleSpinBox()
            self.number.setDecimals(self.decimals)
            self.number.setSingleStep(float(step))
            self.number.setRange(float(self.minimum), float(self.maximum))
        else:
            self.number = QSpinBox()
            self.number.setSingleStep(max(1, int(round(step))))
            self.number.setRange(int(round(self.minimum)), int(round(self.maximum)))
        self.number.setSuffix(suffix)
        self.number.setMinimumWidth(92)

        row.addWidget(self.label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.number)

        self.slider.valueChanged.connect(self._from_slider)
        self.number.valueChanged.connect(self._from_number)
        self.set_value(value)

    def _from_slider(self, raw):
        value = raw / self.factor
        previous = self.number.blockSignals(True)
        if self._integer_box:
            self.number.setValue(int(round(value)))
        else:
            self.number.setValue(float(value))
        self.number.blockSignals(previous)
        self._emit_changed()

    def _from_number(self, value):
        raw = round(float(value) * self.factor)
        previous = self.slider.blockSignals(True)
        self.slider.setValue(raw)
        self.slider.blockSignals(previous)
        self._emit_changed()

    def _emit_changed(self):
        # Parent lab connects to both slider and number changes via this callback.
        callback = getattr(self, "on_changed", None)
        if callback:
            callback()

    def set_value(self, value):
        value = max(self.minimum, min(self.maximum, float(value)))
        p1 = self.slider.blockSignals(True)
        p2 = self.number.blockSignals(True)
        self.slider.setValue(round(value * self.factor))
        if self._integer_box:
            self.number.setValue(int(round(value)))
        else:
            self.number.setValue(float(value))
        self.slider.blockSignals(p1)
        self.number.blockSignals(p2)

    def value(self):
        return float(self.number.value())


class HueAnchorEditor(QWidget):
    def __init__(self, name, anchor, changed_callback, parent=None):
        super().__init__(parent)
        self.name = name
        self.anchor = anchor

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 7)
        box.setSpacing(3)

        heading = QLabel(f"{name.title()}  ·  {anchor['hue_degrees']}°")
        heading.setStyleSheet("font-weight:700; color:#D8D8D8;")
        box.addWidget(heading)

        self.lightness = NumberSlider(
            "Lightness", -30.0, 30.0, anchor.get("lightness_percent", 0.0),
            decimals=1, step=0.5, suffix="%"
        )
        self.saturation = NumberSlider(
            "Saturation", -50.0, 50.0, anchor.get("saturation_percent", 0.0),
            decimals=1, step=0.5, suffix="%"
        )
        self.lightness.on_changed = changed_callback
        self.saturation.on_changed = changed_callback

        box.addWidget(self.lightness)
        box.addWidget(self.saturation)

    def values(self):
        result = dict(self.anchor)
        result["lightness_percent"] = self.lightness.value()
        result["saturation_percent"] = self.saturation.value()
        return result

    def reset(self):
        self.lightness.set_value(0.0)
        self.saturation.set_value(0.0)


class KoboEmulationLab(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MangaNana Kobo Emulation Lab v2")
        self.resize(1520, 920)

        self.profile_path = DEFAULT_PROFILE_PATH
        self.default_profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.profile = merge_lab_profile(self.default_profile, self.default_profile)
        self.frame_image = Image.open(HERE / self.profile["frame"]["asset"]).convert("RGBA")

        self.source = None
        self.simulated = None
        self.display_image = None

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(120)
        self.render_timer.timeout.connect(self.rebuild_now)

        self.setStyleSheet("""
            QWidget { background:#111315; color:#ECECEC; font-size:12px; }
            QFrame#panel { background:#191C1F; border:1px solid #30353A; border-radius:8px; }
            QTabWidget::pane { border:1px solid #30353A; background:#151719; }
            QTabBar::tab { background:#1B1E21; padding:7px 10px; border:1px solid #30353A; }
            QTabBar::tab:selected { color:#FF6740; border-bottom-color:#FF6740; }
            QPushButton, QComboBox, QSpinBox, QDoubleSpinBox {
                background:#1B1E21; color:#E6E6E6; border:1px solid #41464B;
                border-radius:5px; padding:5px 8px;
            }
            QPushButton:hover, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color:#FF6740;
            }
            QSlider::groove:horizontal { height:4px; background:#30353A; }
            QSlider::handle:horizontal {
                background:#FF6740; width:14px; margin:-5px 0; border-radius:7px;
            }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        left = QFrame()
        left.setObjectName("panel")
        left.setFixedWidth(420)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        title = QLabel("Kobo Emulation Lab v2")
        title.setStyleSheet("font-size:18px; font-weight:800; color:#FF6740;")
        left_layout.addWidget(title)

        condition = self.profile.get("target_condition", {})
        subtitle = QLabel(
            f"{self.profile['name']}  ·  Frontlight {condition.get('frontlight_percent', 100)}%  "
            f"·  Warmth {condition.get('comfortlight_warmth', 0)}"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#AEB3B8;")
        left_layout.addWidget(subtitle)

        actions = QHBoxLayout()
        load_image = QPushButton("Load Image…")
        load_image.clicked.connect(self.load_image)
        load_profile = QPushButton("Load Profile…")
        load_profile.clicked.connect(self.load_profile)
        load_diagnostic = QPushButton("Diagnostic")
        load_diagnostic.clicked.connect(self.load_diagnostic)
        actions.addWidget(load_image)
        actions.addWidget(load_profile)
        actions.addWidget(load_diagnostic)
        left_layout.addLayout(actions)

        self.emulation_enabled = QCheckBox("Enable Kobo emulation")
        self.emulation_enabled.setChecked(True)
        self.emulation_enabled.toggled.connect(self.schedule_rebuild)
        left_layout.addWidget(self.emulation_enabled)

        self.show_frame = QCheckBox("Show Kobo device border")
        self.show_frame.setChecked(True)
        self.show_frame.toggled.connect(self.schedule_rebuild)
        left_layout.addWidget(self.show_frame)

        orientation_row = QHBoxLayout()
        orientation_row.addWidget(QLabel("Device Orientation"))
        self.device_orientation = QComboBox()
        self.device_orientation.addItem("Portrait", PORTRAIT)
        self.device_orientation.addItem("Landscape", LANDSCAPE)
        self.device_orientation.currentIndexChanged.connect(self._orientation_changed)
        orientation_row.addWidget(self.device_orientation, 1)
        left_layout.addLayout(orientation_row)

        tabs = QTabWidget()
        left_layout.addWidget(tabs, 1)

        # Global profile tab.
        global_tab = QWidget()
        gv = QVBoxLayout(global_tab)
        gv.setContentsMargins(9, 9, 9, 9)
        gv.setSpacing(5)

        tone = self.profile["tone"]
        color = self.profile["color"]
        spatial = self.profile["spatial"]

        self.black_floor = NumberSlider("Black floor", 0, 120, tone["black_floor"], step=1)
        self.white_ceiling = NumberSlider("White ceiling", 130, 255, tone["white_ceiling"], step=1)
        self.gamma = NumberSlider("Gamma", 0.50, 2.00, tone["gamma"], decimals=2, step=0.01)
        self.saturation = NumberSlider(
            "Global saturation", 0.00, 1.00, color["saturation"],
            decimals=2, step=0.01
        )
        self.red_gain = NumberSlider("Red gain", 0.50, 1.50, color["red_gain"], decimals=2, step=0.01)
        self.green_gain = NumberSlider("Green gain", 0.50, 1.50, color["green_gain"], decimals=2, step=0.01)
        self.blue_gain = NumberSlider("Blue gain", 0.50, 1.50, color["blue_gain"], decimals=2, step=0.01)
        self.chroma = NumberSlider(
            "Chroma resolution", 25, 100, spatial["chroma_resolution_percent"],
            step=1, suffix="%"
        )
        self.global_rows = (
            self.black_floor, self.white_ceiling, self.gamma, self.saturation,
            self.red_gain, self.green_gain, self.blue_gain, self.chroma,
        )
        for row in self.global_rows:
            row.on_changed = self.schedule_rebuild
            gv.addWidget(row)

        baseline_note = QLabel(
            "These fields start at the exact tuned values used during the close "
            "real-Kobo comparison. Every value can be typed directly."
        )
        baseline_note.setWordWrap(True)
        baseline_note.setStyleSheet("color:#9CA2A7; font-size:11px;")
        gv.addWidget(baseline_note)
        gv.addStretch(1)
        tabs.addTab(global_tab, "Global")

        # Hue response tab.
        hue_tab = QWidget()
        hue_root = QVBoxLayout(hue_tab)
        hue_root.setContentsMargins(8, 8, 8, 8)

        self.hue_enabled = QCheckBox("Enable hue-specific corrections")
        self.hue_enabled.setChecked(bool(self.profile["hue_corrections"].get("enabled", False)))
        self.hue_enabled.toggled.connect(self.schedule_rebuild)
        hue_root.addWidget(self.hue_enabled)

        self.saturation_gate = NumberSlider(
            "Saturation gate", 0, 80,
            self.profile["hue_corrections"].get("saturation_gate_percent", 25),
            step=1, suffix="%"
        )
        self.saturation_gate.on_changed = self.schedule_rebuild
        hue_root.addWidget(self.saturation_gate)

        hint = QLabel(
            "The gate protects low-saturation colors such as the pastel pink that "
            "already matched well. Corrections blend smoothly between hue anchors."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9CA2A7; font-size:11px;")
        hue_root.addWidget(hint)

        hue_scroll = QScrollArea()
        hue_scroll.setWidgetResizable(True)
        hue_container = QWidget()
        hv = QVBoxLayout(hue_container)
        hv.setContentsMargins(3, 3, 3, 3)

        self.hue_editors = {}
        for name, anchor in self.profile["hue_corrections"]["anchors"].items():
            editor = HueAnchorEditor(name, anchor, self.schedule_rebuild)
            self.hue_editors[name] = editor
            hv.addWidget(editor)
        hv.addStretch(1)
        hue_scroll.setWidget(hue_container)
        hue_root.addWidget(hue_scroll, 1)

        reset_hue = QPushButton("Reset Hue Corrections to 0")
        reset_hue.clicked.connect(self.reset_hue_corrections)
        hue_root.addWidget(reset_hue)

        tabs.addTab(hue_tab, "Hue Response")

        # Experimental Kaleido surface tab. These values remain lab-only.
        surface_tab = QWidget()
        surface_root = QVBoxLayout(surface_tab)
        surface_root.setContentsMargins(9, 9, 9, 9)
        surface_root.setSpacing(7)
        surface = normalized_surface(self.profile)

        self.cfa_enabled = QCheckBox("Enable CFA Surface")
        self.cfa_enabled.setChecked(surface["cfa_enabled"])
        self.cfa_enabled.toggled.connect(self._surface_changed)
        surface_root.addWidget(self.cfa_enabled)
        self.cfa_strength = NumberSlider(
            "CFA Strength", 0.00, 0.35, surface["cfa_strength"],
            decimals=2, step=0.01)
        self.mirror_cfa_horizontal = QCheckBox("Mirror CFA Horizontally")
        self.mirror_cfa_horizontal.setChecked(surface["mirror_cfa_horizontal"])
        self.mirror_cfa_horizontal.toggled.connect(self._surface_changed)
        self.softness = NumberSlider(
            "Panel Softness", 0.00, 0.90, spatial["softness_radius"],
            decimals=2, step=0.01)
        self.micro_grain_enabled = QCheckBox("Enable Micro-Grain")
        self.micro_grain_enabled.setChecked(surface["micro_grain_enabled"])
        self.micro_grain_enabled.toggled.connect(self._surface_changed)
        self.grain_strength = NumberSlider(
            "Grain Strength", 0.0, 4.0, surface["grain_strength"],
            decimals=1, step=0.1)
        for row in (self.cfa_strength, self.softness, self.grain_strength):
            row.on_changed = self.schedule_rebuild
            surface_root.addWidget(row)
        surface_root.insertWidget(2, self.mirror_cfa_horizontal)
        surface_root.insertWidget(4, self.micro_grain_enabled)

        self.surface_diagnostics = QLabel()
        self.surface_diagnostics.setWordWrap(True)
        self.surface_diagnostics.setStyleSheet("color:#9CA2A7; font-size:11px;")
        surface_root.addWidget(self.surface_diagnostics)
        surface_root.addStretch(1)
        tabs.addTab(surface_tab, "Kaleido Surface")
        self._update_surface_controls()

        buttons = QHBoxLayout()
        save_profile = QPushButton("Save Profile…")
        save_profile.clicked.connect(self.save_profile)
        reset_baseline = QPushButton("Reset Baseline")
        reset_baseline.clicked.connect(self.reset_baseline)
        buttons.addWidget(reset_baseline)
        buttons.addWidget(save_profile)
        left_layout.addLayout(buttons)

        geometry_note = self.profile["frame"]["landscape_screen_rect"]
        info = QLabel(
            "Frame screen rectangle: "
            f"x={geometry_note['x']}, y={geometry_note['y']}, "
            f"{geometry_note['width']}×{geometry_note['height']} px. "
            "Measured from KoboBoarderCenterFinder.png."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#81878C; font-size:10px;")
        left_layout.addWidget(info)

        root.addWidget(left)

        # Preview panel.
        right = QFrame()
        right.setObjectName("panel")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 10, 10, 10)
        rv.setSpacing(7)

        top = QHBoxLayout()
        self.status = QLabel("Load the original calibration page or any manga page.")
        self.status.setStyleSheet("color:#AEB3B8;")
        top.addWidget(self.status, 1)

        self.preview_mode = QComboBox()
        self.preview_mode.addItem("Emulated", "emulated")
        self.preview_mode.addItem("Original Source", "source")
        self.preview_mode.currentIndexChanged.connect(self.refresh_pixmap)
        top.addWidget(self.preview_mode)

        top.addWidget(QLabel("Zoom:"))
        self.zoom = QComboBox()
        for label, factor in (
            ("Fit", 0.0),
            ("50%", 0.5),
            ("75%", 0.75),
            ("100% Device Pixels", 1.0),
            ("125%", 1.25),
            ("150%", 1.5),
            ("200%", 2.0),
        ):
            self.zoom.addItem(label, factor)
        self.zoom.currentIndexChanged.connect(self.refresh_pixmap)
        top.addWidget(self.zoom)
        rv.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.scroll.setWidget(self.image_label)
        rv.addWidget(self.scroll, 1)

        root.addWidget(right, 1)

    def values(self):
        hue = {
            "enabled": self.hue_enabled.isChecked(),
            "saturation_gate_percent": self.saturation_gate.value(),
            "anchors": {name: editor.values() for name, editor in self.hue_editors.items()},
        }
        return {
            "black_floor": self.black_floor.value(),
            "white_ceiling": self.white_ceiling.value(),
            "gamma": self.gamma.value(),
            "saturation": self.saturation.value(),
            "red_gain": self.red_gain.value(),
            "green_gain": self.green_gain.value(),
            "blue_gain": self.blue_gain.value(),
            "chroma_resolution_percent": self.chroma.value(),
            "softness_radius": self.softness.value(),
            "hue_corrections": hue,
            "device_orientation": self.device_orientation.currentData(),
            "kaleido_surface": {
                "cfa_enabled": self.cfa_enabled.isChecked(),
                "cfa_strength": self.cfa_strength.value(),
                "mirror_cfa_horizontal": self.mirror_cfa_horizontal.isChecked(),
                "micro_grain_enabled": self.micro_grain_enabled.isChecked(),
                "grain_strength": self.grain_strength.value(),
            },
        }

    def _orientation_changed(self, *_args):
        self._update_surface_controls()
        self.schedule_rebuild()

    def _surface_changed(self, *_args):
        self._update_surface_controls()
        self.schedule_rebuild()

    def _update_surface_controls(self):
        self.cfa_strength.setEnabled(self.cfa_enabled.isChecked())
        self.mirror_cfa_horizontal.setEnabled(self.cfa_enabled.isChecked())
        self.grain_strength.setEnabled(self.micro_grain_enabled.isChecked())
        orientation = "Portrait" if self.device_orientation.currentData() == PORTRAIT else "Landscape"
        mirrored = self.mirror_cfa_horizontal.isChecked()
        diagonal = ("/" if mirrored else "\\") if orientation == "Portrait" else ("\\" if mirrored else "/")
        self.surface_diagnostics.setText(
            f"CFA Layout: {CFA_LAYOUT_NAME}\n"
            "Anchor: device framebuffer\n"
            f"Orientation: {orientation}\n"
            f"CFA Handedness: {'Mirrored Horizontal' if mirrored else 'Current'}\n"
            f"Visible Diagonal: {diagonal}"
        )

    def schedule_rebuild(self, *_args):
        self.render_timer.start()

    def rebuild_now(self):
        if self.source is None:
            return

        if self.emulation_enabled.isChecked():
            self.simulated = emulate(self.source, self.values(), self.profile)
        else:
            self.simulated = self.source.copy()

        if self.show_frame.isChecked() and self.emulation_enabled.isChecked():
            self.display_image = compose_device_frame(
                self.simulated, self.profile, self.frame_image
            )
        else:
            self.display_image = self.simulated

        self.refresh_pixmap()

    def current_preview_image(self):
        if self.preview_mode.currentData() == "source":
            return self.source
        return self.display_image

    def refresh_pixmap(self):
        image = self.current_preview_image()
        if image is None:
            return

        pm = pil_to_pixmap(image)
        factor = float(self.zoom.currentData())

        if factor <= 0:
            viewport = self.scroll.viewport().size()
            max_w = max(1, viewport.width() - 18)
            max_h = max(1, viewport.height() - 18)
            pm = pm.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pm = pm.scaled(
                max(1, round(pm.width() * factor)),
                max(1, round(pm.height() * factor)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )

        self.image_label.setPixmap(pm)
        self.image_label.resize(pm.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom.currentData() == 0.0:
            self.refresh_pixmap()

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load source image",
            str(HERE),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not path:
            return
        self.source = Image.open(path).convert("RGB")
        self.status.setText(
            f"{Path(path).name} · source {self.source.width}×{self.source.height}"
        )
        self.rebuild_now()

    def load_diagnostic(self):
        self.source = diagnostic_image()
        self.status.setText(
            f"Synthetic Kaleido surface target · source {self.source.width}×{self.source.height}"
        )
        self.rebuild_now()

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Kobo lab profile", str(HERE), "JSON (*.json)"
        )
        if not path:
            return
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        self.profile = merge_lab_profile(loaded, self.default_profile)
        self.apply_profile_to_controls()
        self.status.setText(f"Loaded profile: {Path(path).name}")
        self.schedule_rebuild()

    def apply_profile_to_controls(self):
        tone = self.profile["tone"]
        color = self.profile["color"]
        spatial = self.profile["spatial"]
        self.black_floor.set_value(tone["black_floor"])
        self.white_ceiling.set_value(tone["white_ceiling"])
        self.gamma.set_value(tone["gamma"])
        self.saturation.set_value(color["saturation"])
        self.red_gain.set_value(color["red_gain"])
        self.green_gain.set_value(color["green_gain"])
        self.blue_gain.set_value(color["blue_gain"])
        self.chroma.set_value(spatial["chroma_resolution_percent"])
        self.softness.set_value(spatial["softness_radius"])

        surface = normalized_surface(self.profile)
        self.cfa_enabled.setChecked(surface["cfa_enabled"])
        self.cfa_strength.set_value(surface["cfa_strength"])
        self.mirror_cfa_horizontal.setChecked(surface["mirror_cfa_horizontal"])
        self.micro_grain_enabled.setChecked(surface["micro_grain_enabled"])
        self.grain_strength.set_value(surface["grain_strength"])
        orientation = self.profile.get("lab_state", {}).get("device_orientation", PORTRAIT)
        self.device_orientation.setCurrentIndex(max(0, self.device_orientation.findData(orientation)))

        hue = self.profile.get("hue_corrections", {})
        self.hue_enabled.setChecked(bool(hue.get("enabled", False)))
        self.saturation_gate.set_value(hue.get("saturation_gate_percent", 25))
        anchors = hue.get("anchors", {})
        for name, editor in self.hue_editors.items():
            values = anchors.get(name, {})
            editor.lightness.set_value(values.get("lightness_percent", 0.0))
            editor.saturation.set_value(values.get("saturation_percent", 0.0))
        self._update_surface_controls()

    def reset_baseline(self):
        baseline_path = HERE / "baseline_tuned_profile.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.black_floor.set_value(baseline["tone"]["black_floor"])
        self.white_ceiling.set_value(baseline["tone"]["white_ceiling"])
        self.gamma.set_value(baseline["tone"]["gamma"])
        self.saturation.set_value(baseline["color"]["saturation"])
        self.red_gain.set_value(baseline["color"]["red_gain"])
        self.green_gain.set_value(baseline["color"]["green_gain"])
        self.blue_gain.set_value(baseline["color"]["blue_gain"])
        self.chroma.set_value(baseline["spatial"]["chroma_resolution_percent"])
        self.softness.set_value(baseline["spatial"]["softness_radius"])
        self.cfa_enabled.setChecked(False)
        self.cfa_strength.set_value(0.0)
        self.mirror_cfa_horizontal.setChecked(False)
        self.micro_grain_enabled.setChecked(False)
        self.grain_strength.set_value(0.0)
        self.reset_hue_corrections()
        self.schedule_rebuild()

    def reset_hue_corrections(self):
        self.hue_enabled.setChecked(False)
        for editor in self.hue_editors.values():
            editor.reset()
        self.schedule_rebuild()

    def save_profile(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save tuned Kobo lab profile",
            str(HERE / "kobo_libra_colour_tuned_v2.json"),
            "JSON (*.json)",
        )
        if not path:
            return

        values = self.values()
        payload = dict(self.profile)
        payload["schema_version"] = 3
        payload["provisional"] = False
        payload["tone"] = {
            "black_floor": round(values["black_floor"]),
            "white_ceiling": round(values["white_ceiling"]),
            "gamma": values["gamma"],
        }
        payload["color"] = {
            "saturation": values["saturation"],
            "red_gain": values["red_gain"],
            "green_gain": values["green_gain"],
            "blue_gain": values["blue_gain"],
        }
        payload["spatial"] = {
            "chroma_resolution_percent": round(values["chroma_resolution_percent"]),
            "softness_radius": values["softness_radius"],
        }
        payload["hue_corrections"] = values["hue_corrections"]
        payload["kaleido_surface"] = values["kaleido_surface"]
        payload["lab_state"] = {"device_orientation": values["device_orientation"]}

        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status.setText(f"Saved profile: {Path(path).name}")


def main():
    app = QApplication(sys.argv)
    window = KoboEmulationLab()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
