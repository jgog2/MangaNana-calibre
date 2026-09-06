import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from qt.core import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider, Qt, QVBoxLayout,
    QWidget, QPixmap
)

HERE = Path(__file__).resolve().parent
OVERLAY_PATH = HERE / "KoboOverlay.png"
PROFILE_PATH = HERE / "kobo_libra_colour_100.json"


def pil_to_pixmap(image):
    out = io.BytesIO()
    image.convert("RGBA").save(out, "PNG")
    pm = QPixmap()
    if not pm.loadFromData(out.getvalue(), "PNG"):
        raise RuntimeError("Could not convert preview image to QPixmap.")
    return pm


def detect_screen_hole(frame):
    """Find the transparent internal screen opening from the supplied PNG."""
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    w, h = rgba.size

    row_y = h // 2
    row = [alpha.getpixel((x, row_y)) for x in range(w)]
    opaque_x = [x for x, value in enumerate(row) if value > 128]

    col_x = w // 2
    col = [alpha.getpixel((col_x, y)) for y in range(h)]
    opaque_y = [y for y, value in enumerate(col) if value > 128]

    if not opaque_x or not opaque_y:
        raise RuntimeError("Could not identify the frame screen opening.")

    def runs(values):
        result = []
        start = prev = values[0]
        for value in values[1:]:
            if value != prev + 1:
                result.append((start, prev))
                start = value
            prev = value
        result.append((start, prev))
        return result

    xr = runs(opaque_x)
    yr = runs(opaque_y)

    # At the center line the bezel should appear as two opaque runs with the
    # transparent screen between them.
    if len(xr) < 2 or len(yr) < 2:
        raise RuntimeError("Frame transparency does not contain an enclosed screen opening.")

    return (xr[0][1] + 1, yr[0][1] + 1, xr[-1][0], yr[-1][0])


def contain_on_canvas(image, target_size):
    image = image.convert("RGB")
    fitted = ImageOps.contain(image, target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, "white")
    x = (target_size[0] - fitted.width) // 2
    y = (target_size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def reduce_chroma_resolution(image, percent):
    """Keep luma full-resolution while reducing Cb/Cr spatial resolution."""
    percent = max(1, min(100, int(percent)))
    if percent >= 100:
        return image

    ycbcr = image.convert("YCbCr")
    y, cb, cr = ycbcr.split()

    dw = max(1, round(image.width * percent / 100.0))
    dh = max(1, round(image.height * percent / 100.0))

    cb = cb.resize((dw, dh), Image.Resampling.BILINEAR).resize(image.size, Image.Resampling.BILINEAR)
    cr = cr.resize((dw, dh), Image.Resampling.BILINEAR).resize(image.size, Image.Resampling.BILINEAR)

    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def apply_tone(image, black_floor, white_ceiling, gamma):
    black_floor = max(0, min(254, int(black_floor)))
    white_ceiling = max(black_floor + 1, min(255, int(white_ceiling)))
    gamma = max(0.25, min(4.0, float(gamma)))

    lut = []
    for value in range(256):
        normalized = value / 255.0
        corrected = normalized ** (1.0 / gamma)
        out = black_floor + corrected * (white_ceiling - black_floor)
        lut.append(max(0, min(255, round(out))))

    return image.point(lut * 3)


def apply_channel_gains(image, red_gain, green_gain, blue_gain):
    r, g, b = image.split()

    def gain(channel, factor):
        factor = max(0.5, min(1.5, float(factor)))
        return channel.point([max(0, min(255, round(i * factor))) for i in range(256)])

    return Image.merge("RGB", (gain(r, red_gain), gain(g, green_gain), gain(b, blue_gain)))


def emulate(image, settings):
    portrait = image.height >= image.width
    target = (1264, 1680) if portrait else (1680, 1264)

    # Device rasterization changes the page pixels but never the application window.
    out = contain_on_canvas(image, target)

    # Kaleido-style spatial split: full luma detail, lower chroma detail.
    out = reduce_chroma_resolution(out, settings["chroma"])

    # Provisional measured appearance transform.
    out = apply_tone(out, settings["black"], settings["white"], settings["gamma"])
    out = apply_channel_gains(out, settings["red"], settings["green"], settings["blue"])
    out = ImageEnhance.Color(out).enhance(settings["saturation"])

    if settings["softness"] > 0:
        out = out.filter(ImageFilter.GaussianBlur(radius=settings["softness"]))

    return out


def frame_image(screen, overlay):
    """Composite the simulated framebuffer under the user's transparent Kobo frame."""
    portrait = screen.height >= screen.width
    frame = overlay.rotate(90, expand=True) if portrait else overlay.copy()
    hole = detect_screen_hole(frame)
    x0, y0, x1, y1 = hole
    hole_w, hole_h = x1 - x0, y1 - y0

    # Preserve the simulated screen aspect ratio. The supplied frame is decorative
    # and its transparent opening is not assumed to be metrically exact.
    fitted = ImageOps.contain(screen.convert("RGBA"), (hole_w, hole_h), Image.Resampling.LANCZOS)

    base = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    # Black behind unused opening pixels keeps the decorative frame visually clean.
    black = Image.new("RGBA", (hole_w, hole_h), (0, 0, 0, 255))
    base.alpha_composite(black, (x0, y0))

    px = x0 + (hole_w - fitted.width) // 2
    py = y0 + (hole_h - fitted.height) // 2
    base.alpha_composite(fitted, (px, py))
    base.alpha_composite(frame)
    return base


class SliderRow(QWidget):
    def __init__(self, label, minimum, maximum, value, suffix="", scale=1.0, parent=None):
        super().__init__(parent)
        self.scale = float(scale)
        self.suffix = suffix

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.label = QLabel(label)
        self.label.setMinimumWidth(118)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum), int(maximum))
        self.slider.setValue(int(value))

        self.value_label = QLabel()
        self.value_label.setMinimumWidth(62)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(self.label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        value = self.value()
        if self.scale == 1.0:
            text = f"{value:g}{self.suffix}"
        else:
            text = f"{value:.2f}{self.suffix}"
        self.value_label.setText(text)

    def value(self):
        return self.slider.value() * self.scale

    def set_raw(self, raw):
        self.slider.setValue(int(raw))


class KoboEmulationLab(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MangaNana Kobo Emulation Lab")
        self.resize(1480, 900)

        self.source = None
        self.simulated = None
        self.display_image = None
        self.profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        self.overlay = Image.open(OVERLAY_PATH).convert("RGBA")

        self.setStyleSheet("""
            QWidget { background:#111315; color:#ECECEC; font-size:12px; }
            QFrame#panel { background:#191C1F; border:1px solid #30353A; border-radius:8px; }
            QPushButton, QComboBox {
                background:#1B1E21; color:#E6E6E6; border:1px solid #41464B;
                border-radius:5px; padding:6px 9px;
            }
            QPushButton:hover { border-color:#FF6740; }
            QSlider::groove:horizontal { height:4px; background:#30353A; }
            QSlider::handle:horizontal {
                background:#FF6740; width:14px; margin:-5px 0; border-radius:7px;
            }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        controls_frame = QFrame()
        controls_frame.setObjectName("panel")
        controls_frame.setFixedWidth(360)
        controls = QVBoxLayout(controls_frame)
        controls.setContentsMargins(14, 14, 14, 14)
        controls.setSpacing(9)

        title = QLabel("Kobo Emulation Lab")
        title.setStyleSheet("font-size:18px; font-weight:700; color:#FF6740;")
        controls.addWidget(title)

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("No Emulation", "none")
        self.profile_combo.addItem("Kobo Libra Colour - 100% Frontlight", "kobo")
        self.profile_combo.setCurrentIndex(1)
        controls.addWidget(self.profile_combo)

        load_btn = QPushButton("Load Test Image…")
        load_btn.clicked.connect(self.load_image)
        controls.addWidget(load_btn)

        self.frame_check = QCheckBox("Show Kobo device frame")
        self.frame_check.setChecked(True)
        controls.addWidget(self.frame_check)

        controls.addWidget(QLabel("Measured-profile tuning"))

        p = self.profile
        self.black = SliderRow("Black floor", 0, 100, p["tone"]["black_floor"])
        self.white = SliderRow("White ceiling", 140, 255, p["tone"]["white_ceiling"])
        self.gamma = SliderRow("Gamma", 50, 200, round(p["tone"]["gamma"] * 100), scale=0.01)
        self.saturation = SliderRow("Saturation", 0, 100, round(p["color"]["saturation"] * 100), suffix="%")
        self.chroma = SliderRow("Chroma resolution", 25, 100, p["spatial"]["chroma_resolution_percent"], suffix="%")
        self.softness = SliderRow("Panel softness", 0, 150, round(p["spatial"]["softness_radius"] * 100), scale=0.01)

        self.red = SliderRow("Red gain", 70, 130, round(p["color"]["red_gain"] * 100), scale=0.01)
        self.green = SliderRow("Green gain", 70, 130, round(p["color"]["green_gain"] * 100), scale=0.01)
        self.blue = SliderRow("Blue gain", 70, 130, round(p["color"]["blue_gain"] * 100), scale=0.01)

        for row in (self.black, self.white, self.gamma, self.saturation, self.chroma,
                    self.softness, self.red, self.green, self.blue):
            controls.addWidget(row)
            row.slider.valueChanged.connect(self.rebuild)

        controls.addStretch(1)

        save_btn = QPushButton("Save Tuned Profile JSON…")
        save_btn.clicked.connect(self.save_profile)
        controls.addWidget(save_btn)

        note = QLabel(
            "The initial numbers are provisional. The purpose of this lab is to tune "
            "and validate the Kobo transform before any MangaNana production code changes."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9DA3A8; font-size:11px;")
        controls.addWidget(note)

        root.addWidget(controls_frame)

        preview_frame = QFrame()
        preview_frame.setObjectName("panel")
        pv = QVBoxLayout(preview_frame)
        pv.setContentsMargins(10, 10, 10, 10)

        toolbar = QHBoxLayout()
        self.status = QLabel("Load any manga/test image.")
        self.status.setStyleSheet("color:#AEB3B8;")
        toolbar.addWidget(self.status, 1)

        toolbar.addWidget(QLabel("Zoom:"))
        self.zoom = QComboBox()
        for label, factor in (
            ("Fit", 0), ("50%", 0.5), ("75%", 0.75), ("100% Device Pixels", 1.0),
            ("125%", 1.25), ("150%", 1.5), ("200%", 2.0)
        ):
            self.zoom.addItem(label, factor)
        self.zoom.currentIndexChanged.connect(self.refresh_pixmap)
        toolbar.addWidget(self.zoom)

        pv.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.scroll.setWidget(self.image_label)
        pv.addWidget(self.scroll, 1)

        root.addWidget(preview_frame, 1)

        self.profile_combo.currentIndexChanged.connect(self.rebuild)
        self.frame_check.toggled.connect(self.rebuild)

    def settings(self):
        return {
            "black": int(self.black.value()),
            "white": int(self.white.value()),
            "gamma": float(self.gamma.value()),
            "saturation": float(self.saturation.value()) / 100.0,
            "chroma": int(self.chroma.value()),
            "softness": float(self.softness.value()),
            "red": float(self.red.value()),
            "green": float(self.green.value()),
            "blue": float(self.blue.value()),
        }

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load test image", str(HERE),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"
        )
        if not path:
            return
        self.source = Image.open(path).convert("RGB")
        self.status.setText(f"{Path(path).name} | source {self.source.width}×{self.source.height}")
        self.rebuild()

    def rebuild(self):
        if self.source is None:
            return

        if self.profile_combo.currentData() == "none":
            self.simulated = self.source.copy()
            self.display_image = self.simulated
        else:
            self.simulated = emulate(self.source, self.settings())
            self.display_image = (
                frame_image(self.simulated, self.overlay)
                if self.frame_check.isChecked()
                else self.simulated
            )

        self.refresh_pixmap()

    def refresh_pixmap(self):
        if self.display_image is None:
            return

        pm = pil_to_pixmap(self.display_image)
        factor = self.zoom.currentData()

        if not factor:
            viewport = self.scroll.viewport().size()
            if viewport.width() > 20 and viewport.height() > 20:
                pm = pm.scaled(
                    max(1, viewport.width() - 20),
                    max(1, viewport.height() - 20),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            self.image_label.resize(pm.size())
        else:
            w = max(1, round(pm.width() * float(factor)))
            h = max(1, round(pm.height() * float(factor)))
            pm = pm.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            )
            self.image_label.resize(pm.size())

        self.image_label.setPixmap(pm)
        self.image_label.setMinimumSize(pm.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom.currentData() == 0 and self.display_image is not None:
            self.refresh_pixmap()

    def save_profile(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save tuned Kobo profile", str(HERE / "kobo_libra_colour_tuned.json"),
            "JSON (*.json)"
        )
        if not path:
            return

        payload = dict(self.profile)
        payload["provisional"] = False
        payload["tone"] = {
            "black_floor": self.settings()["black"],
            "white_ceiling": self.settings()["white"],
            "gamma": self.settings()["gamma"],
        }
        payload["color"] = {
            "saturation": self.settings()["saturation"],
            "red_gain": self.settings()["red"],
            "green_gain": self.settings()["green"],
            "blue_gain": self.settings()["blue"],
        }
        payload["spatial"] = {
            "chroma_resolution_percent": self.settings()["chroma"],
            "softness_radius": self.settings()["softness"],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status.setText(f"Saved tuned profile: {Path(path).name}")


app = QApplication(sys.argv)
window = KoboEmulationLab()
window.show()
sys.exit(app.exec())
