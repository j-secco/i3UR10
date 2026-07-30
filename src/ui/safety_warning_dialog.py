"""
Safety Warning Dialog - Startup Safety Alert
Displays an air-raid siren and safety zone warning before the main application loads.
Uses ALSA (aplay) for reliable audio output.

Visual design: Neon Industrial concept with full-screen scrolling DANGER text,
pulsing warning rings, fast-blinking icon, countdown timer, and smooth
green transition + fade-out on acknowledge.

Author: jsecco (R)
"""

import logging
import math
import os
import signal
import subprocess
import shutil
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QGridLayout, QFrame, QGraphicsOpacityEffect, QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QPointF, pyqtProperty,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QPainter, QPen, QColor, QBrush,
    QLinearGradient, QRadialGradient, QPainterPath,
)

logger = logging.getLogger(__name__)

SIREN_PATH = Path(__file__).parent.parent.parent / "assets" / "sounds" / "safety_warning.wav"

# ---------------------------------------------------------------------------
# Color palette (matching Neon Industrial concept)
# ---------------------------------------------------------------------------
BG            = QColor("#080808")
SURFACE       = QColor("#111111")
SURFACE_2     = QColor("#161616")
BORDER        = QColor("#222222")
NEON_RED      = QColor("#FF2D55")
NEON_RED_DIM  = QColor(255, 45, 85, 40)
NEON_AMBER    = QColor("#FF9F0A")
NEON_GREEN    = QColor("#30D158")
NEON_GREEN_DIM = QColor(48, 209, 88, 40)
TEXT          = QColor("#EAEAEA")
TEXT_DIM      = QColor("#666666")
TRANSPARENT   = QColor(0, 0, 0, 0)


def _try_load_font(family: str) -> str:
    """Return *family* if the OS has it, otherwise a reasonable fallback."""
    db = QFontDatabase
    families = db.families()
    if family in families:
        return family
    for fallback in ("Consolas", "Courier New", "DejaVu Sans Mono", "monospace"):
        if fallback in families:
            return fallback
    return "monospace"


FONT_DISPLAY = None
FONT_BODY    = None


# ═══════════════════════════════════════════════════════════════════════════
#  Scrolling Danger Background
# ═══════════════════════════════════════════════════════════════════════════
class _ScrollRow:
    """Data for a single scrolling text row."""
    def __init__(self, font_size: int, speed: float, direction: int, opacity: float):
        self.font_size = font_size
        self.speed = speed          # px per tick
        self.direction = direction  # 1 = left, -1 = right
        self.opacity = opacity
        self.offset = 0.0


class ScrollingDangerBackground(QWidget):
    """Fills itself with rows of scrolling 'DANGER — ROBOT IN OPERATION → KEEP CLEAR'."""

    MESSAGE = "DANGER — ROBOT IN OPERATION → KEEP CLEAR — "

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._opacity = 1.0

        self._rows: list[_ScrollRow] = [
            _ScrollRow(72,  0.8,  1,  0.09),
            _ScrollRow(42,  0.6, -1,  0.07),
            _ScrollRow(72,  0.7,  1,  0.06),
            _ScrollRow(32,  0.9,  1,  0.08),
            _ScrollRow(42,  0.7, -1,  0.07),
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)  # ~33 fps

    # Animatable opacity for fade-out --
    def get_bg_opacity(self):
        return self._opacity

    def set_bg_opacity(self, val):
        self._opacity = val
        self.update()

    bgOpacity = pyqtProperty(float, get_bg_opacity, set_bg_opacity)

    def _tick(self):
        for row in self._rows:
            row.offset += row.speed * row.direction
        self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()

        # Vignette-style radial fade (draw text first, vignette last)
        total_rows = len(self._rows)
        row_height = h / total_rows

        for i, row in enumerate(self._rows):
            font = QFont(FONT_DISPLAY, row.font_size)
            font.setWeight(QFont.Weight.Black)
            p.setFont(font)

            alpha = int(255 * row.opacity * self._opacity)
            color = QColor(255, 45, 85, max(0, min(255, alpha)))
            p.setPen(color)

            fm = p.fontMetrics()
            text = self.MESSAGE * 4
            text_width = fm.horizontalAdvance(text)
            if text_width == 0:
                continue

            y = int(row_height * i + row_height / 2 + fm.ascent() / 2 - 4)
            offset = row.offset % text_width
            start_x = -offset if row.direction == 1 else -(text_width - offset)

            x = start_x
            while x < w + text_width:
                p.drawText(int(x), y, text)
                x += text_width

        # Radial vignette overlay
        grad = QRadialGradient(w / 2, h / 2, max(w, h) * 0.7)
        grad.setColorAt(0.0, QColor(8, 8, 8, 0))
        grad.setColorAt(0.5, QColor(8, 8, 8, 0))
        grad.setColorAt(1.0, QColor(8, 8, 8, 180))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(0, 0, w, h)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  Pulsing Rings + Center Icon
# ═══════════════════════════════════════════════════════════════════════════
class PulsingRingsWidget(QWidget):
    """Concentric expanding rings with a blinking center icon."""

    NUM_RINGS = 4
    RING_CYCLE_MS = 4000  # full cycle per ring
    BLINK_MS = 400        # icon blink period

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(260, 260)
        self._safe = False
        self._blink_on = True
        self._ring_phases = [i / self.NUM_RINGS for i in range(self.NUM_RINGS)]
        self._time_ms = 0

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(50)

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_timer.start(self.BLINK_MS)

    def set_safe(self):
        self._safe = True
        self._blink_on = True
        self._blink_timer.stop()
        self.update()

    def _tick(self):
        self._time_ms += 50
        self.update()

    def _toggle_blink(self):
        self._blink_on = not self._blink_on
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        accent = NEON_GREEN if self._safe else NEON_RED

        # Expanding rings
        for i in range(self.NUM_RINGS):
            phase = ((self._time_ms / self.RING_CYCLE_MS) + self._ring_phases[i]) % 1.0
            radius = 40 + phase * 100
            alpha = int(153 * (1.0 - phase))
            ring_color = QColor(accent)
            ring_color.setAlpha(max(0, alpha))
            pen = QPen(ring_color, 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), radius, radius)

        # Center circle
        icon_radius = 45
        if self._safe:
            bg = QColor(48, 209, 88, 30)
            border = NEON_GREEN
            glow = QColor(48, 209, 88, 60)
            icon_radius = 50  # slightly larger when safe
        else:
            alpha_mult = 1.0 if self._blink_on else 0.25
            bg = QColor(255, 45, 85, int(25 * alpha_mult))
            border = QColor(NEON_RED)
            border.setAlpha(int(255 * alpha_mult))
            glow = QColor(255, 45, 85, int(60 * alpha_mult))

        # Glow
        glow_grad = QRadialGradient(cx, cy, icon_radius * 1.8)
        glow_grad.setColorAt(0.0, glow)
        glow_grad.setColorAt(1.0, TRANSPARENT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow_grad))
        p.drawEllipse(QPointF(cx, cy), icon_radius * 1.8, icon_radius * 1.8)

        # Circle background
        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, 3))
        p.drawEllipse(QPointF(cx, cy), icon_radius, icon_radius)

        # Icon text
        font = QFont(FONT_BODY, 28)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        txt_color = QColor(NEON_GREEN if self._safe else NEON_RED)
        if not self._safe:
            txt_color.setAlpha(int(255 * (1.0 if self._blink_on else 0.25)))
        p.setPen(txt_color)
        symbol = "✓" if self._safe else "⚠"
        p.drawText(QRectF(cx - icon_radius, cy - icon_radius, icon_radius * 2, icon_radius * 2),
                   Qt.AlignmentFlag.AlignCenter, symbol)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  Countdown Ring Widget
# ═══════════════════════════════════════════════════════════════════════════
class CountdownRingWidget(QWidget):
    """Circular countdown arc with number in the center."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._progress = 0.0   # 0..1
        self._done = False
        self._text = "5"

    def set_progress(self, val: float, text: str):
        self._progress = val
        self._text = text
        self.update()

    def set_done(self):
        self._done = True
        self._progress = 1.0
        self._text = "✓"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, 56, 56)

        # Background track
        p.setPen(QPen(BORDER, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # Progress arc
        color = NEON_GREEN if self._done else NEON_AMBER
        p.setPen(QPen(color, 4, cap=Qt.PenCapStyle.RoundCap))
        span = int(-self._progress * 360 * 16)
        p.drawArc(rect, 90 * 16, span)

        # Center text
        font = QFont(FONT_DISPLAY, 18)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(color)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  Styled helper widgets
# ═══════════════════════════════════════════════════════════════════════════
class _StatusTile(QFrame):
    """Small status tile (label + value)."""

    def __init__(self, label_text: str, value_text: str, value_color: QColor, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {SURFACE_2.name()};"
            f"border: 1px solid {BORDER.name()};"
            "border-radius: 10px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(label_text)
        lbl.setFont(QFont(FONT_BODY, 9, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        self._val = QLabel(value_text)
        self._val.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._val.setStyleSheet(f"color: {value_color.name()}; background: transparent; border: none;")
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._val)

    def set_value(self, text: str, color: QColor):
        self._val.setText(text)
        self._val.setStyleSheet(f"color: {color.name()}; background: transparent; border: none;")


class _InstructionItem(QFrame):
    """Numbered instruction row."""

    def __init__(self, number: str, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {SURFACE_2.name()};"
            f"border: 1px solid {BORDER.name()};"
            "border-radius: 8px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self._num = QLabel(number)
        self._num.setFixedSize(24, 24)
        self._num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num.setFont(QFont(FONT_DISPLAY, 10, QFont.Weight.Bold))
        self._num.setStyleSheet(
            f"color: {NEON_RED.name()};"
            f"background-color: rgba(255,45,85,25);"
            f"border: 1px solid rgba(255,45,85,50);"
            "border-radius: 6px;"
        )
        layout.addWidget(self._num)

        lbl = QLabel(text)
        lbl.setFont(QFont(FONT_BODY, 12, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent; border: none;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl, 1)

    def set_done(self):
        self._num.setText("✓")
        self._num.setStyleSheet(
            f"color: {NEON_GREEN.name()};"
            "background-color: rgba(48,209,88,38);"
            "border: 1px solid rgba(48,209,88,75);"
            "border-radius: 6px;"
        )


class _SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setFont(QFont(FONT_BODY, 9, QFont.Weight.Bold))
        self.setStyleSheet(f"color: rgba(255,255,255,50); letter-spacing: 3px;")


class _NeonLine(QFrame):
    """Thin glowing horizontal line."""
    def __init__(self, color: QColor = NEON_RED, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(2)
        self.setFixedWidth(200)
        self._update_style()

    def set_color(self, color: QColor):
        self._color = color
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(
            f"background-color: {self._color.name()};"
            "border: none; border-radius: 1px;"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Main Dialog
# ═══════════════════════════════════════════════════════════════════════════
class SafetyWarningDialog(QDialog):
    """Full-screen safety warning dialog with air-raid siren."""

    COUNTDOWN_SECONDS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._siren_process = None
        self._remaining = self.COUNTDOWN_SECONDS
        self._acknowledged = False

        # Lazy-init fonts (QFontDatabase requires QApplication to exist)
        global FONT_DISPLAY, FONT_BODY
        if FONT_DISPLAY is None:
            FONT_DISPLAY = _try_load_font("Orbitron")
        if FONT_BODY is None:
            FONT_BODY = _try_load_font("Outfit")
        self._setup_ui()
        self._setup_timers()
        self._setup_siren()

    # ------------------------------------------------------------------
    #  UI Construction
    # ------------------------------------------------------------------
    def _setup_ui(self):
        self.setWindowTitle("SAFETY WARNING")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setMinimumSize(1024, 700)
        self.setStyleSheet(f"background-color: {BG.name()};")

        # --- Root stacked layout: background + foreground ---
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scrolling danger background (fills entire dialog)
        self._scroll_bg = ScrollingDangerBackground(self)
        root.addWidget(self._scroll_bg, 0, 0)

        # Foreground content on top of background
        foreground = QWidget(self)
        foreground.setStyleSheet("background: transparent;")
        root.addWidget(foreground, 0, 0)

        fg_layout = QHBoxLayout(foreground)
        fg_layout.setContentsMargins(0, 0, 0, 0)
        fg_layout.setSpacing(0)

        # --- Left panel (visual) ---
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(20)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._rings = PulsingRingsWidget()
        left_layout.addWidget(self._rings, 0, Qt.AlignmentFlag.AlignCenter)

        self._neon_line = _NeonLine(NEON_RED)
        left_layout.addWidget(self._neon_line, 0, Qt.AlignmentFlag.AlignCenter)

        self._hero_title = QLabel("ROBOT CELL\nACTIVE")
        self._hero_title.setFont(QFont(FONT_DISPLAY, 38, QFont.Weight.Black))
        self._hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_title.setStyleSheet(f"color: {NEON_RED.name()}; background: transparent;")
        left_layout.addWidget(self._hero_title)

        self._hero_sub = QLabel(
            "Motion systems engaged — stay behind the safety\n"
            "perimeter at all times. Do not enter the work cell\n"
            "until the system is disarmed."
        )
        self._hero_sub.setFont(QFont(FONT_BODY, 14, QFont.Weight.Medium))
        self._hero_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_sub.setWordWrap(True)
        self._hero_sub.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent;")
        left_layout.addWidget(self._hero_sub)

        fg_layout.addWidget(left, 1)

        # --- Right panel (controls) ---
        right = QFrame()
        right.setFixedWidth(380)
        right.setStyleSheet(
            f"QFrame {{ background-color: rgba(17,17,17,235);"
            f"border-left: 1px solid {BORDER.name()}; }}"
        )
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(22, 22, 22, 22)
        right_layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)
        self._live_dot = QLabel("●")
        self._live_dot.setFont(QFont(FONT_BODY, 10))
        self._live_dot.setStyleSheet(f"color: {NEON_RED.name()}; background: transparent; border: none;")
        header.addWidget(self._live_dot)
        hdr_lbl = QLabel("SAFETY SYSTEM")
        hdr_lbl.setFont(QFont(FONT_DISPLAY, 11, QFont.Weight.Bold))
        hdr_lbl.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent; border: none;")
        header.addWidget(hdr_lbl)
        header.addStretch()
        self._clock_label = QLabel("--:--")
        self._clock_label.setFont(QFont(FONT_DISPLAY, 10))
        self._clock_label.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent; border: none;")
        header.addWidget(self._clock_label)
        right_layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {BORDER.name()}; border: none;")
        right_layout.addWidget(sep)

        # Status tiles
        right_layout.addWidget(_SectionLabel("System Status"))
        tiles_layout = QGridLayout()
        tiles_layout.setSpacing(8)
        self._tile_cell = _StatusTile("CELL", "ARMED", NEON_RED)
        self._tile_zone = _StatusTile("ZONE", "LOCKED", NEON_AMBER)
        self._tile_estop = _StatusTile("E-STOP", "READY", NEON_GREEN)
        self._tile_siren = _StatusTile("SIREN", "ON", NEON_RED)
        tiles_layout.addWidget(self._tile_cell, 0, 0)
        tiles_layout.addWidget(self._tile_zone, 0, 1)
        tiles_layout.addWidget(self._tile_estop, 1, 0)
        tiles_layout.addWidget(self._tile_siren, 1, 1)
        right_layout.addLayout(tiles_layout)

        # Instructions
        right_layout.addWidget(_SectionLabel("Required Actions"))
        self._instr1 = _InstructionItem("1", "Verify all personnel are outside the perimeter")
        self._instr2 = _InstructionItem("2", "Confirm E-Stop is accessible and functional")
        self._instr3 = _InstructionItem("3", "Acknowledge to proceed with operation")
        right_layout.addWidget(self._instr1)
        right_layout.addWidget(self._instr2)
        right_layout.addWidget(self._instr3)

        # Countdown
        right_layout.addWidget(_SectionLabel("Verification"))
        cd_container = QFrame()
        cd_container.setStyleSheet(
            f"QFrame {{ background-color: {SURFACE_2.name()};"
            f"border: 1px solid {BORDER.name()}; border-radius: 10px; }}"
        )
        cd_layout = QHBoxLayout(cd_container)
        cd_layout.setContentsMargins(16, 14, 16, 14)
        cd_layout.setSpacing(16)

        self._cd_ring = CountdownRingWidget()
        cd_layout.addWidget(self._cd_ring)

        cd_info = QVBoxLayout()
        cd_info.setSpacing(2)
        cd_title = QLabel("Area Clearance")
        cd_title.setFont(QFont(FONT_BODY, 12, QFont.Weight.DemiBold))
        cd_title.setStyleSheet(f"color: {TEXT.name()}; background: transparent; border: none;")
        cd_info.addWidget(cd_title)
        self._cd_sub = QLabel(f"Mandatory wait: {self.COUNTDOWN_SECONDS}s")
        self._cd_sub.setFont(QFont(FONT_BODY, 11))
        self._cd_sub.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent; border: none;")
        cd_info.addWidget(self._cd_sub)
        cd_layout.addLayout(cd_info, 1)
        right_layout.addWidget(cd_container)

        right_layout.addStretch()

        # Acknowledge button
        self._ack_btn = QPushButton("ACKNOWLEDGE — AREA CLEAR")
        self._ack_btn.setFont(QFont(FONT_DISPLAY, 12, QFont.Weight.Bold))
        self._ack_btn.setMinimumHeight(56)
        self._ack_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ack_btn.setEnabled(False)
        self._ack_btn.setStyleSheet(self._button_style(enabled=False))
        self._ack_btn.clicked.connect(self._on_acknowledge)
        right_layout.addWidget(self._ack_btn)

        fg_layout.addWidget(right)

    @staticmethod
    def _button_style(enabled: bool) -> str:
        if enabled:
            return (
                "QPushButton {"
                f"  color: {NEON_GREEN.name()};"
                f"  background-color: rgba(48,209,88,30);"
                f"  border: 1px solid {NEON_GREEN.name()};"
                "   border-radius: 10px;"
                "   padding: 14px 20px;"
                "   letter-spacing: 2px;"
                "}"
                "QPushButton:hover {"
                f"  background-color: {NEON_GREEN.name()};"
                f"  color: #080808;"
                "}"
                "QPushButton:pressed {"
                f"  background-color: {NEON_GREEN.darker(120).name()};"
                "}"
            )
        return (
            "QPushButton {"
            f"  color: #444444;"
            f"  background-color: {SURFACE_2.name()};"
            f"  border: 1px solid {BORDER.name()};"
            "   border-radius: 10px;"
            "   padding: 14px 20px;"
            "   letter-spacing: 2px;"
            "}"
        )

    # ------------------------------------------------------------------
    #  Timers
    # ------------------------------------------------------------------
    def _setup_timers(self):
        # Clock update
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        # Live-dot blink
        self._dot_on = True
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._toggle_dot)
        self._dot_timer.start(600)

        # Countdown
        self._cd_timer = QTimer(self)
        self._cd_timer.timeout.connect(self._tick_countdown)
        self._cd_timer.start(1000)

    def _update_clock(self):
        from datetime import datetime
        self._clock_label.setText(datetime.now().strftime("%H:%M"))

    def _toggle_dot(self):
        self._dot_on = not self._dot_on
        alpha = "255" if self._dot_on else "50"
        self._live_dot.setStyleSheet(
            f"color: rgba(255,45,85,{alpha}); background: transparent; border: none;"
        )

    def _tick_countdown(self):
        self._remaining -= 1
        progress = (self.COUNTDOWN_SECONDS - self._remaining) / self.COUNTDOWN_SECONDS

        if self._remaining <= 0:
            self._cd_timer.stop()
            self._cd_ring.set_done()
            self._cd_sub.setText("✓ Verification complete")
            self._cd_sub.setStyleSheet(
                f"color: {NEON_GREEN.name()}; background: transparent; border: none;"
                "font-weight: 600;"
            )
            self._ack_btn.setEnabled(True)
            self._ack_btn.setStyleSheet(self._button_style(enabled=True))
        else:
            self._cd_ring.set_progress(progress, str(self._remaining))
            self._cd_sub.setText(f"Mandatory wait: {self._remaining}s")

    # ------------------------------------------------------------------
    #  Acknowledge + Green Transition + Fade-Out
    # ------------------------------------------------------------------
    def _on_acknowledge(self):
        if self._acknowledged:
            return
        self._acknowledged = True
        self._stop_siren()
        logger.info("Safety warning acknowledged by operator")

        # --- Disable button ---
        self._ack_btn.setEnabled(False)
        self._ack_btn.setText("✓ ACKNOWLEDGED")
        self._ack_btn.setStyleSheet(
            "QPushButton {"
            f"  color: #080808;"
            f"  background-color: {NEON_GREEN.name()};"
            f"  border: 1px solid {NEON_GREEN.name()};"
            "   border-radius: 10px; padding: 14px 20px;"
            "   letter-spacing: 2px;"
            "}"
        )

        # --- Turn everything green ---
        self._rings.set_safe()
        self._neon_line.set_color(NEON_GREEN)
        self._hero_title.setText("AREA\nCLEARED")
        self._hero_title.setStyleSheet(f"color: {NEON_GREEN.name()}; background: transparent;")

        self._live_dot.setStyleSheet(
            f"color: {NEON_GREEN.name()}; background: transparent; border: none;"
        )
        self._dot_timer.stop()

        self._tile_cell.set_value("SAFE", NEON_GREEN)
        self._tile_zone.set_value("OPEN", NEON_GREEN)
        self._tile_siren.set_value("OFF", NEON_GREEN)

        self._instr1.set_done()
        self._instr2.set_done()
        self._instr3.set_done()

        # --- Fade out scrolling background ---
        self._bg_fade = QPropertyAnimation(self._scroll_bg, b"bgOpacity")
        self._bg_fade.setDuration(1200)
        self._bg_fade.setStartValue(1.0)
        self._bg_fade.setEndValue(0.0)
        self._bg_fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._bg_fade.start()

        # --- After delay, fade out entire dialog and accept ---
        QTimer.singleShot(2000, self._begin_dismiss)

    def _begin_dismiss(self):
        self._dismiss_anim = QPropertyAnimation(self, b"windowOpacity")
        self._dismiss_anim.setDuration(900)
        self._dismiss_anim.setStartValue(1.0)
        self._dismiss_anim.setEndValue(0.0)
        self._dismiss_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._dismiss_anim.finished.connect(self.accept)
        self._dismiss_anim.start()

    # ------------------------------------------------------------------
    #  Audio  (preserved from original)
    # ------------------------------------------------------------------
    def _set_volume_max(self):
        """Set all hardware and software volume controls to maximum."""
        amixer = shutil.which("amixer")
        if amixer is None:
            logger.warning("amixer not found -- cannot set volume")
            return

        # Enable Auto-Mute so external speakers get priority
        try:
            subprocess.run(
                [amixer, "-c", "0", "-D", "hw:0", "sset", "Auto-Mute Mode", "Enabled"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
            )
        except Exception:
            pass

        # Set hardware controls on card 0
        for control in ["Speaker", "Master", "Headphone"]:
            try:
                subprocess.run(
                    [amixer, "-c", "0", "-D", "hw:0", "sset", control, "100%", "unmute"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
                )
            except Exception:
                pass

        # PipeWire/PulseAudio virtual Master
        try:
            subprocess.run(
                [amixer, "sset", "Master", "100%", "unmute"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
            )
        except Exception:
            pass

        # Boost PipeWire sink to max
        wpctl = shutil.which("wpctl")
        if wpctl:
            try:
                subprocess.run(
                    [wpctl, "set-volume", "-l", "2.0", "@DEFAULT_AUDIO_SINK@", "2.0"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
                )
            except Exception:
                pass

        logger.info("All audio volumes set to maximum")

    def _setup_siren(self):
        """Play the air-raid siren via aplay (ALSA) in a loop."""
        if not SIREN_PATH.exists():
            logger.warning("Siren sound file not found: %s", SIREN_PATH)
            return

        aplay = shutil.which("aplay")
        if aplay is None:
            logger.warning("aplay not found -- siren will be silent")
            return

        self._set_volume_max()

        try:
            self._siren_process = subprocess.Popen(
                ["bash", "-c", f'while true; do aplay -q "{SIREN_PATH}"; done'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Safety siren started via aplay (pid=%d)", self._siren_process.pid)
        except Exception as exc:
            logger.error("Failed to start siren: %s", exc)

    def _stop_siren(self):
        """Terminate the aplay siren subprocess tree."""
        if self._siren_process is not None:
            try:
                os.killpg(os.getpgid(self._siren_process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            try:
                self._siren_process.terminate()
                self._siren_process.wait(timeout=2)
            except Exception:
                self._siren_process.kill()
            self._siren_process = None
            logger.info("Safety siren stopped")

    # ------------------------------------------------------------------
    #  Overrides
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """Ensure siren stops if dialog is closed."""
        self._stop_siren()
        self._scroll_bg._timer.stop()
        super().closeEvent(event)

    def reject(self):
        """Prevent closing via Escape key -- operator must acknowledge."""
        pass

    def showEvent(self, event):
        """Go full screen on first show."""
        super().showEvent(event)
        if not self.isFullScreen():
            self.showFullScreen()
