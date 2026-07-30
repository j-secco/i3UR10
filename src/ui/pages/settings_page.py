"""settings_page.py - Touch settings page for the UR10 jog control UI.

Two side-by-side instrument-style cards, no scrolling. Every value is a
tappable tile with a large centred readout: numbers open an on-screen
keypad, binary choices cycle in place. The cards carry a soft drop shadow
so the page reads with depth rather than as a flat form.

  - Robot Connection : IP address, motion backend, connection timeout
  - Demo Defaults    : audience offset, cycle delay, default speed

A compact Theme cycle tile and the Cancel / Save actions sit on the bottom
row; a single muted version line replaces the old About card.

Author: jsecco (R) - 2026
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QSizePolicy, QDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ui import theme_v2
from ui.theme_v2 import (
    # spacing
    S_4, S_8, S_12, S_16, S_24, S_32,
    # radii
    R_SM, R_MD, R_LG,
    # font sizes
    F_DISPLAY, F_TITLE, F_HEADING, F_SUBHEAD, F_BODY, F_SMALL, F_MICRO,
    # interaction sizing
    BUTTON_H,
)
from ui.widgets.keypad_dialog import KeypadDialog

APP_VERSION = "2.0"
APP_AUTHOR  = "jsecco (R)"
ROBOT_MODEL = "UR10"

# Tappable value tile heights.
_TILE_H = 100
_TILE_H_COMPACT = 64


def _shade(hex_color: str, factor: float) -> str:
    """Lighten (factor > 0, toward white) or darken (factor < 0) a colour.

    Used to build each tile's subtle vertical gradient. Returns a solid
    '#RRGGBB' string -- Qt QSS gradient stops take solid colours.
    """
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16)
        c = c + (255 - c) * factor if factor >= 0 else c * (1.0 + factor)
        out.append(max(0, min(255, round(c))))
    return "#{:02X}{:02X}{:02X}".format(*out)


# ===========================================================================
# ValueField - one tappable setting tile (caption + large centred readout)
# ===========================================================================

class ValueField(QWidget):
    """A single tappable setting tile.

    The tile shows a small uppercase caption above a large centred value.
    Cycle fields flank the value with accent chevrons that hint the value
    flips in place. Tapping the tile emits `tapped`.
    """

    tapped = pyqtSignal()

    def __init__(self, caption: str, kind: str = "keypad",
                 compact: bool = False, parent=None):
        """kind is "keypad" (tap-to-edit) or "cycle" (tap-to-flip)."""
        super().__init__(parent)
        self._kind = kind
        self._compact = compact

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # ---- The tile itself ----
        self._tile = QFrame()
        self._tile.setObjectName("valueTile")
        # A plain QFrame paints its objectName QSS background only with
        # WA_StyledBackground set.
        self._tile.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tile.setMinimumHeight(_TILE_H_COMPACT if compact else _TILE_H)
        self._tile.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tile.setProperty("pressed", False)
        # Route the tile's mouse events through this widget's handlers.
        self._tile.mousePressEvent = self._tile_press
        self._tile.mouseReleaseEvent = self._tile_release

        pad = S_8 if compact else S_12
        tl = QVBoxLayout(self._tile)
        tl.setContentsMargins(S_16, pad, S_16, pad)
        tl.setSpacing(S_4)
        tl.addStretch(1)

        # Caption -- small, uppercase, letter-spaced, centred.
        self._caption = QLabel(caption.upper())
        cf = QFont()
        cf.setPixelSize(F_SMALL)
        cf.setWeight(QFont.Weight.Bold)
        cf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        self._caption.setFont(cf)
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(self._caption)

        # Accent tick -- a short centred bar under the caption. A small spot
        # of colour + structure so the tile is not a plain box. Hidden on
        # compact tiles, which are too small to carry it.
        self._tick = QLabel()
        self._tick.setObjectName("captionTick")
        self._tick.setFixedSize(34, 3)
        tick_row = QHBoxLayout()
        tick_row.setContentsMargins(0, 0, 0, 0)
        tick_row.addStretch(1)
        tick_row.addWidget(self._tick)
        tick_row.addStretch(1)
        tl.addLayout(tick_row)
        if compact:
            self._tick.hide()

        # Value row -- large centred value; chevrons pinned to the tile edges
        # for cycle fields, hidden for keypad fields.
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(0)

        chev_px = F_SUBHEAD if compact else F_TITLE
        self._lchev = QLabel("‹")   # single left-pointing angle quote
        self._rchev = QLabel("›")   # single right-pointing angle quote
        for ch in (self._lchev, self._rchev):
            chf = QFont()
            chf.setPixelSize(chev_px)
            chf.setWeight(QFont.Weight.Bold)
            ch.setFont(chf)
            ch.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._value = QLabel("")
        vf = QFont()
        # The value is the readout -- display-sized so the tile reads as an
        # instrument, not a form field.
        vf.setPixelSize(F_HEADING if compact else F_DISPLAY)
        vf.setWeight(QFont.Weight.Bold)
        self._value.setFont(vf)
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        value_row.addWidget(self._lchev)
        value_row.addStretch(1)
        value_row.addWidget(self._value)
        value_row.addStretch(1)
        value_row.addWidget(self._rchev)
        tl.addLayout(value_row)
        tl.addStretch(1)

        if kind != "cycle":
            self._lchev.hide()
            self._rchev.hide()

        col.addWidget(self._tile)
        self.apply_theme()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_value_text(self, text: str) -> None:
        """Update the displayed value."""
        self._value.setText(text)

    def apply_theme(self) -> None:
        """Rebuild every stylesheet from the current theme palette."""
        # Subtle vertical gradient -- a soft convex sheen so the tile reads
        # as a physical surface rather than a flat rectangle.
        grad_top = _shade(theme_v2.SURFACE_HI, 0.15)
        grad_bot = _shade(theme_v2.SURFACE_HI, -0.15)
        self._tile.setStyleSheet(
            f"QFrame#valueTile {{"
            f" background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {grad_top}, stop:1 {grad_bot});"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_MD}px;"
            f"}}"
            f"QFrame#valueTile:hover {{"
            f" border-color: {theme_v2.ACCENT};"
            f"}}"
            f"QFrame#valueTile[pressed=\"true\"] {{"
            f" background-color: {theme_v2.SURFACE};"
            f" border-color: {theme_v2.ACCENT};"
            f"}}"
        )
        self._caption.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; }}"
        )
        self._tick.setStyleSheet(
            f"QLabel#captionTick {{ background-color: {theme_v2.ACCENT};"
            f" border: none; border-radius: 1px; }}"
        )
        self._value.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT};"
            f" background-color: transparent; }}"
        )
        chev_qss = (
            f"QLabel {{ color: {theme_v2.ACCENT};"
            f" background-color: transparent; }}"
        )
        self._lchev.setStyleSheet(chev_qss)
        self._rchev.setStyleSheet(chev_qss)

    # ------------------------------------------------------------------
    # Interaction -- press feedback + tapped emission
    # ------------------------------------------------------------------

    def _repolish(self) -> None:
        self._tile.style().unpolish(self._tile)
        self._tile.style().polish(self._tile)
        self._tile.update()

    def _tile_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._tile.setProperty("pressed", True)
            self._repolish()

    def _tile_release(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._tile.setProperty("pressed", False)
            self._repolish()
            if self._tile.rect().contains(event.position().toPoint()):
                self.tapped.emit()


# ===========================================================================
# SettingsPage
# ===========================================================================

class SettingsPage(QWidget):
    """Touch settings: Robot Connection / Demo Defaults, no scrolling.

    Settings are LOADED from a config dict via load_settings() and SAVED back
    via the save_clicked signal -- the main window persists to YAML.
    """

    save_clicked   = pyqtSignal(dict)   # emitted with the current settings dict
    cancel_clicked = pyqtSignal()       # revert to last loaded values
    theme_changed  = pyqtSignal(str)    # emitted with 'light' or 'dark' on toggle

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal snapshot for cancel revert.
        self._last_loaded: dict = {}

        # Current setting values (the source of truth for current_settings()).
        self._robot_ip: str   = "192.168.10.24"
        self._use_rtde: bool  = True
        self._timeout: float  = 5.0
        self._offset: int     = 0
        self._delay: float    = 2.5
        self._speed: int      = 50

        # Restyling registries.
        self._cards: list[QFrame] = []
        self._heading_dots: list[QLabel] = []
        self._heading_labels: list[QLabel] = []
        self._value_fields: list[ValueField] = []

        # ---- Root layout ----
        # No page title -- the tab bar already reads "Settings"; the two card
        # headings carry the structure. Dropping it frees the height the
        # instrument tiles need.
        root = QVBoxLayout(self)
        root.setContentsMargins(S_24, S_24, S_24, S_24)
        root.setSpacing(S_24)

        # ---- Main area: two equal cards ----
        main = QHBoxLayout()
        # Margins give the card drop shadows room to paint without clipping.
        main.setContentsMargins(S_8, S_8, S_8, S_8)
        main.setSpacing(S_24)
        main.addWidget(self._build_robot_card(), stretch=1)
        main.addWidget(self._build_demo_card(), stretch=1)
        root.addLayout(main, stretch=1)

        # ---- Bottom row: Theme tile + Cancel/Save ----
        root.addLayout(self._build_bottom_row())

        # ---- Version line (replaces the old About card) ----
        self._about_label = QLabel(
            f"UR10 Jog Control v{APP_VERSION}  ·  {APP_AUTHOR}"
            f"  ·  {ROBOT_MODEL}"
        )
        af = QFont()
        af.setPixelSize(F_SMALL)
        self._about_label.setFont(af)
        root.addWidget(self._about_label)

        # Apply all theme-dependent styling.
        self.apply_theme()
        self._refresh_all_fields()

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    def _make_card(self) -> QFrame:
        """Build a section card.

        Depth comes from QSS alone (gradient surface + accent top stripe +
        border) so it renders on every Qt platform, including the Wayland
        kiosk where QGraphicsDropShadowEffect was unreliable.
        """
        card = QFrame()
        card.setObjectName("settingsCard")
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._cards.append(card)
        return card

    def _make_heading(self, text: str) -> QWidget:
        """Build a section heading: a small accent dot + the heading text."""
        row = QWidget()
        row.setStyleSheet("QWidget { background-color: transparent; }")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(S_12)

        dot = QLabel()
        dot.setObjectName("headingDot")
        dot.setFixedSize(12, 12)
        self._heading_dots.append(dot)
        h.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        lbl = QLabel(text)
        f = QFont()
        f.setPixelSize(F_HEADING)
        f.setWeight(QFont.Weight.Bold)
        lbl.setFont(f)
        self._heading_labels.append(lbl)
        h.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        h.addStretch()
        return row

    def _build_robot_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(S_16, S_16, S_16, S_16)
        layout.setSpacing(S_8)

        # Heading pinned at the top; the three tiles are distributed down the
        # card body with equal stretches so the card reads as a composed
        # whole rather than three rows clustered against a void.
        layout.addWidget(self._make_heading("Robot Connection"))
        layout.addStretch(1)

        self._ip_field = ValueField("IP Address", "keypad")
        self._ip_field.tapped.connect(self._on_ip_tapped)
        self._value_fields.append(self._ip_field)
        layout.addWidget(self._ip_field)
        layout.addStretch(1)

        self._backend_field = ValueField("Motion Backend", "cycle")
        self._backend_field.tapped.connect(self._on_backend_tapped)
        self._value_fields.append(self._backend_field)
        layout.addWidget(self._backend_field)
        layout.addStretch(1)

        self._timeout_field = ValueField("Connection Timeout", "keypad")
        self._timeout_field.tapped.connect(self._on_timeout_tapped)
        self._value_fields.append(self._timeout_field)
        layout.addWidget(self._timeout_field)
        layout.addStretch(1)
        return card

    def _build_demo_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(S_16, S_16, S_16, S_16)
        layout.setSpacing(S_8)

        # Tiles distributed down the card body -- see _build_robot_card.
        layout.addWidget(self._make_heading("Demo Defaults"))
        layout.addStretch(1)

        self._offset_field = ValueField("Audience Offset", "keypad")
        self._offset_field.tapped.connect(self._on_offset_tapped)
        self._value_fields.append(self._offset_field)
        layout.addWidget(self._offset_field)
        layout.addStretch(1)

        self._delay_field = ValueField("Cycle Delay", "keypad")
        self._delay_field.tapped.connect(self._on_delay_tapped)
        self._value_fields.append(self._delay_field)
        layout.addWidget(self._delay_field)
        layout.addStretch(1)

        self._speed_field = ValueField("Default Speed", "keypad")
        self._speed_field.tapped.connect(self._on_speed_tapped)
        self._value_fields.append(self._speed_field)
        layout.addWidget(self._speed_field)
        layout.addStretch(1)
        return card

    def _build_bottom_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(S_8, 0, S_8, 0)
        row.setSpacing(S_16)

        # Compact Theme cycle tile on the left.
        self._theme_field = ValueField("Theme", "cycle", compact=True)
        self._theme_field.setMaximumWidth(260)
        self._theme_field.tapped.connect(self._on_theme_tapped)
        # Not in _value_fields -- restyled explicitly in apply_theme().
        row.addWidget(self._theme_field)

        row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setMinimumHeight(BUTTON_H)
        self._cancel_btn.setMinimumWidth(140)
        self._cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setMinimumHeight(BUTTON_H)
        self._save_btn.setMinimumWidth(140)
        self._save_btn.clicked.connect(self._on_save)
        row.addWidget(self._save_btn)

        return row

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette."""
        self.setStyleSheet(
            f"QWidget {{ background-color: {theme_v2.BG};"
            f" color: {theme_v2.TEXT}; }}"
        )

        # Section cards -- gradient surface plus an accent stripe along the
        # top edge. Pure QSS so it renders on the Wayland kiosk; border-top
        # is allowed (the design ban is on side-stripe borders only).
        card_top = _shade(theme_v2.SURFACE, 0.04)
        card_bot = _shade(theme_v2.SURFACE, -0.05)
        card_qss = (
            f"QFrame#settingsCard {{"
            f" background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {card_top}, stop:1 {card_bot});"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-top: 3px solid {theme_v2.ACCENT};"
            f" border-radius: {R_LG}px;"
            f"}}"
        )
        for card in self._cards:
            card.setStyleSheet(card_qss)

        # Heading accent dots.
        dot_qss = (
            f"QLabel#headingDot {{"
            f" background-color: {theme_v2.ACCENT};"
            f" border-radius: 6px;"
            f"}}"
        )
        for dot in self._heading_dots:
            dot.setStyleSheet(dot_qss)

        # Heading text.
        heading_qss = (
            f"QLabel {{ color: {theme_v2.TEXT};"
            f" background-color: transparent; }}"
        )
        for lbl in self._heading_labels:
            lbl.setStyleSheet(heading_qss)

        # Value tiles.
        for field in self._value_fields:
            field.apply_theme()
        self._theme_field.apply_theme()

        # Action buttons.
        self._cancel_btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._save_btn.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)

        # Version line.
        self._about_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_DIM};"
            f" background-color: transparent; }}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_settings(self, settings: dict) -> None:
        """Populate the page from a settings dict.

        Expected keys (sensible defaults applied via .get()):
          - robot_ip: str  (default '192.168.10.24')
          - use_rtde: bool (default True)
          - connection_timeout: float (default 5.0)
          - demo_base_offset_deg: int (default 0)
          - demo_waypoint_delay_s: float (default 2.5)
          - demo_default_speed_percent: int (default 50)

        Stores the loaded values so cancel_clicked can revert.
        """
        self._last_loaded = dict(settings)

        self._robot_ip = str(settings.get("robot_ip", "192.168.10.24"))
        self._use_rtde = bool(settings.get("use_rtde", True))
        self._timeout = float(settings.get("connection_timeout", 5.0))
        self._offset = int(settings.get("demo_base_offset_deg", 0))
        self._delay = float(settings.get("demo_waypoint_delay_s", 2.5))
        speed = int(settings.get("demo_default_speed_percent", 50))
        self._speed = max(1, min(100, speed))

        self._refresh_all_fields()

    def current_settings(self) -> dict:
        """Return the current values as a dict matching load_settings keys."""
        return {
            "robot_ip":                   self._robot_ip,
            "use_rtde":                   self._use_rtde,
            "connection_timeout":         round(self._timeout, 1),
            "demo_base_offset_deg":       self._offset,
            "demo_waypoint_delay_s":      round(self._delay, 1),
            "demo_default_speed_percent": self._speed,
        }

    # ------------------------------------------------------------------
    # Display formatting
    # ------------------------------------------------------------------

    def _refresh_all_fields(self) -> None:
        """Push every current value into its ValueField display."""
        self._ip_field.set_value_text(self._robot_ip)
        self._backend_field.set_value_text(
            "RTDE · 30004" if self._use_rtde
            else "Primary · 30001"
        )
        self._timeout_field.set_value_text(f"{self._timeout:.1f} s")
        self._offset_field.set_value_text(f"{self._offset}°")
        self._delay_field.set_value_text(f"{self._delay:.1f} s")
        self._speed_field.set_value_text(f"{self._speed} %")
        self._theme_field.set_value_text(
            "Dark" if theme_v2.current_mode() == "dark" else "Light"
        )

    # ------------------------------------------------------------------
    # Field interactions
    # ------------------------------------------------------------------

    def _on_ip_tapped(self) -> None:
        dlg = KeypadDialog(
            self, title="IP Address", value=self._robot_ip, ip_mode=True
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._robot_ip = dlg.value()
            self._refresh_all_fields()

    def _on_timeout_tapped(self) -> None:
        dlg = KeypadDialog(
            self, title="Connection Timeout", unit="s", value=self._timeout,
            decimals=1, minimum=1.0, maximum=60.0,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._timeout = dlg.value()
            self._refresh_all_fields()

    def _on_offset_tapped(self) -> None:
        dlg = KeypadDialog(
            self, title="Audience Offset", unit="deg", value=self._offset,
            decimals=0, minimum=-360, maximum=360, allow_sign=True,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._offset = dlg.value()
            self._refresh_all_fields()

    def _on_delay_tapped(self) -> None:
        dlg = KeypadDialog(
            self, title="Cycle Delay", unit="s", value=self._delay,
            decimals=1, minimum=0.5, maximum=30.0,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._delay = dlg.value()
            self._refresh_all_fields()

    def _on_speed_tapped(self) -> None:
        dlg = KeypadDialog(
            self, title="Default Speed", unit="%", value=self._speed,
            decimals=0, minimum=1, maximum=100,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._speed = dlg.value()
            self._refresh_all_fields()

    def _on_backend_tapped(self) -> None:
        """Motion backend is binary -- flip it in place, no dialog."""
        self._use_rtde = not self._use_rtde
        self._refresh_all_fields()

    def _on_theme_tapped(self) -> None:
        """Flip light <-> dark, switch the theme, and notify listeners."""
        new_mode = "dark" if theme_v2.current_mode() == "light" else "light"
        theme_v2.set_mode(new_mode)
        self.theme_changed.emit(new_mode)
        # main_window also calls apply_theme() on this page via its theme
        # handler; refresh the Theme tile text here so it is correct
        # regardless of call ordering.
        self._refresh_all_fields()

    # ------------------------------------------------------------------
    # Save / cancel
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        self._last_loaded = self.current_settings()
        self.save_clicked.emit(self.current_settings())

    def _on_cancel(self) -> None:
        if self._last_loaded:
            self.load_settings(self._last_loaded)
        self.cancel_clicked.emit()
