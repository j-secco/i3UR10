"""jog_page.py - Robot Jog Control page for the UR10 redesigned UI.

Author: jsecco

This widget consolidates the legacy main-window jog functionality into a
single, touch-first dark-industrial page. The page is purely a *view*: it
exposes signals for user actions and slot methods for state updates. The
main window is responsible for wiring these to the underlying
``JogController``.

Layout (per UI_REDESIGN_SPEC Section 5.1):

    1. Top control row   - connection actions + mode/frame toggles
    2. Readout panels    - TCP pose card + joint angles card
    3. Axis grid         - QStackedWidget swapping cartesian / joint views
    4. Bottom control row - speed slider, step spinbox, home/log buttons
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui import theme_v2
from ui.theme_v2 import (
    F_BODY,
    F_HEADING,
    F_MICRO,
    F_MONO,
    F_SMALL,
    F_SUBHEAD,
    R_LG,
    R_MD,
    R_SM,
    S_4,
    S_8,
    S_12,
    S_16,
    S_24,
    S_32,
)


# -----------------------------------------------------------------------------
# Axis colour palette (per spec 4.4)
# -----------------------------------------------------------------------------

# Axis hues are fixed semantic colours (X=red, Y=green, Z=blue, ...) and stay
# identical in both themes; only the joint-mode neutral follows the accent.
_AXIS_COLOR_X = "#EF4444"
_AXIS_COLOR_Y = "#10B981"
_AXIS_COLOR_Z = "#3B82F6"
_AXIS_COLOR_RX = "#F87171"
_AXIS_COLOR_RY = "#6EE7B7"
_AXIS_COLOR_RZ = "#93C5FD"


def _blend(fg_hex: str, bg_hex: str, alpha: float) -> str:
    """Composite fg over bg at `alpha`; return an opaque '#RRGGBB'.

    Used to lay a faint, always-on axis tint under the jog buttons. Qt's
    QSS does not reliably honour a translucent background-color (rgba()
    alpha and 8-digit hex are both parsed inconsistently), so the blend
    is precomputed here and emitted as a solid colour, which always
    renders. The bg is the active theme surface, so passing theme_v2's
    current SURFACE keeps the tint correct in both light and dark mode.

    `alpha` is a 0.0-1.0 fraction (share of the foreground axis colour).
    """
    a = max(0.0, min(1.0, alpha))
    fh, bh = fg_hex.lstrip("#"), bg_hex.lstrip("#")
    chan = []
    for i in (0, 2, 4):
        f = int(fh[i:i + 2], 16)
        b = int(bh[i:i + 2], 16)
        chan.append(round(f * a + b * (1.0 - a)))
    return "#{:02X}{:02X}{:02X}".format(*chan)


def _axis_color_joint() -> str:
    """Neutral accent-blue used for joint-mode jog buttons (theme-dependent)."""
    return theme_v2.ACCENT

# Long-press threshold: clicks shorter than this fire the *step* signal,
# longer presses fire continuous *pressed*/*released*.
_STEP_PRESS_MS = 200


def _jog_button_qss(axis_color: str) -> str:
    """Build the stylesheet for a single jog axis button.

    The axis colour is always present as a faint tint + thin border so the
    operator can identify an axis pre-attentively (the squint test) rather
    than only on hover. Hover deepens the tint and thickens the border to
    the solid axis colour; press fills with it for unmistakable feedback.
    """
    surface = theme_v2.SURFACE
    tint_rest = _blend(axis_color, surface, 0.28)
    tint_hover = _blend(axis_color, surface, 0.42)
    return (
        f"QPushButton {{"
        f" background-color: {tint_rest};"
        f" color: {theme_v2.TEXT};"
        f" border: 1px solid {axis_color};"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_16}px;"
        f" min-height: 80px;"
        f" min-width: 120px;"
        f" font-size: {F_HEADING}px;"
        f" font-weight: 700;"
        f" letter-spacing: 1px;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {tint_hover};"
        f" border: 2px solid {axis_color};"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {axis_color};"
        f" color: white;"
        f" border: 2px solid {axis_color};"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: {theme_v2.SURFACE};"
        f" color: {theme_v2.TEXT_DIM};"
        f" border: 1px solid {theme_v2.BORDER};"
        f"}}"
    )


def _toggle_button_qss() -> str:
    """Segmented toggle button QSS - used for mode + frame pickers."""
    return (
        f"QPushButton {{"
        f" background-color: {theme_v2.SURFACE};"
        f" color: {theme_v2.TEXT_MUTED};"
        f" border: 1px solid {theme_v2.BORDER};"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_16}px;"
        f" min-height: 56px;"
        f" min-width: 120px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{"
        f" border-color: {theme_v2.ACCENT_HI};"
        f" color: {theme_v2.TEXT};"
        f"}}"
        f"QPushButton:checked {{"
        f" background-color: {theme_v2.ACCENT};"
        f" color: white;"
        f" border-color: {theme_v2.ACCENT};"
        f"}}"
        f"QPushButton:disabled {{"
        f" color: {theme_v2.TEXT_DIM};"
        f" border-color: {theme_v2.BORDER};"
        f"}}"
    )


def _readout_value_qss() -> str:
    return (
        f"QLabel {{"
        f" color: {theme_v2.TEXT};"
        f" background-color: transparent;"
        f" font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;"
        f" font-size: {F_SUBHEAD}px;"
        f" font-weight: 600;"
        f"}}"
    )


def _readout_label_qss() -> str:
    return (
        f"QLabel {{"
        f" color: {theme_v2.TEXT_MUTED};"
        f" background-color: transparent;"
        f" font-size: {F_SMALL}px;"
        f" font-weight: 600;"
        f" letter-spacing: 1px;"
        f"}}"
    )


def _section_title_qss() -> str:
    return (
        f"QLabel {{"
        f" color: {theme_v2.TEXT};"
        f" background-color: transparent;"
        f" font-size: {F_SUBHEAD}px;"
        f" font-weight: 700;"
        f"}}"
    )


# -----------------------------------------------------------------------------
# Internal helper widget: jog button with press/release timing
# -----------------------------------------------------------------------------


class _JogButton(QPushButton):
    """A QPushButton that distinguishes between short taps (step) and
    long presses (continuous jog).

    Emits ``pressed_long`` once a press exceeds ``_STEP_PRESS_MS``, then
    ``released_long`` on release. If the press is shorter, ``stepped`` is
    emitted on release instead.
    """

    pressed_long = pyqtSignal()
    released_long = pyqtSignal()
    stepped = pyqtSignal()

    def __init__(self, label: str, axis_color: str, parent: Optional[QWidget] = None):
        super().__init__(label, parent)
        # Keep the axis colour so apply_theme() can rebuild the stylesheet.
        self._axis_color = axis_color
        self.setStyleSheet(_jog_button_qss(axis_color))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._is_long_press = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_STEP_PRESS_MS)
        self._timer.timeout.connect(self._on_long_press_timeout)
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)

    def _on_pressed(self) -> None:
        self._is_long_press = False
        self._timer.start()

    def _on_long_press_timeout(self) -> None:
        if self.isDown():
            self._is_long_press = True
            self.pressed_long.emit()

    def _on_released(self) -> None:
        self._timer.stop()
        if self._is_long_press:
            self.released_long.emit()
        else:
            self.stepped.emit()
        self._is_long_press = False

    def apply_theme(self) -> None:
        """Rebuild this button's stylesheet from the current theme palette."""
        self.setStyleSheet(_jog_button_qss(self._axis_color))


# =============================================================================
# JogPage
# =============================================================================


class JogPage(QWidget):
    """Robot jog control page: TCP/joint readout, axis buttons, mode toggle,
    speed/step controls, connection + safety actions."""

    # === User-action signals ===================================================
    connect_clicked = pyqtSignal()
    disconnect_clicked = pyqtSignal()
    home_save_clicked = pyqtSignal()
    home_go_clicked = pyqtSignal()
    save_log_clicked = pyqtSignal()

    mode_changed = pyqtSignal(str)   # 'cartesian' | 'joint'
    frame_changed = pyqtSignal(str)  # 'base' | 'tool'
    speed_changed = pyqtSignal(float)
    step_changed = pyqtSignal(float)

    # Continuous jog (long press)
    jog_axis_pressed = pyqtSignal(int, int)
    jog_axis_released = pyqtSignal(int, int)

    # Step jog (short tap)
    jog_axis_stepped = pyqtSignal(int, int)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("jogPage")

        # --- Internal state ---
        self._mode: str = "cartesian"
        self._frame: str = "base"
        self._connection_state: str = "idle"
        self._home_saved: bool = False
        # Active safety override on the status badge ('' = none). Kept so a
        # live theme switch re-applies the correct badge instead of resetting
        # to the plain connection state.
        self._safety_override: str = ""

        # Storage for value labels keyed by axis name
        self._tcp_value_labels: dict[str, QLabel] = {}
        self._joint_value_labels: dict[str, QLabel] = {}

        # --- Restyling registries (populated during _build_ui) ---
        # Cards (QFrame) styled with CARD_QSS.
        self._cards: list[QFrame] = []
        # Section/title labels styled via _section_title_qss().
        self._title_labels: list[QLabel] = []
        # Small caption labels styled via _readout_label_qss().
        self._caption_labels: list[QLabel] = []
        # Value readout labels styled via _readout_value_qss().
        self._value_labels: list[QLabel] = []
        # Jog axis buttons (each restyles itself via apply_theme()).
        self._jog_buttons: list[_JogButton] = []
        # Joint-mode jog buttons -- their axis colour follows the theme accent,
        # so apply_theme() refreshes that colour before restyling them.
        self._joint_jog_buttons: list[_JogButton] = []
        # Segmented toggle buttons (mode + frame pickers).
        self._toggle_buttons: list[QPushButton] = []

        # --- Build UI ---
        self._build_ui()

        # Apply initial states
        self._apply_connection_state()
        self._apply_home_saved()

        # Apply all theme-dependent styling.
        self.apply_theme()

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(S_24, S_16, S_24, S_16)
        root.setSpacing(S_16)

        # Top: connection actions + mode/frame toggles (full width).
        root.addLayout(self._build_top_row())

        # Body: the axis grid is the primary control (left, wide); the TCP and
        # joint readouts stack in a narrower right column. Two columns fit the
        # 572px content area where a full-width vertical stack does not.
        body = QHBoxLayout()
        body.setSpacing(S_16)
        body.addWidget(self._build_axis_grid_card(), stretch=3)

        readout_col = QVBoxLayout()
        readout_col.setSpacing(S_12)
        readout_col.addWidget(self._build_readout_card(
            title="TCP Position",
            rows=(("X", "m"), ("Y", "m"), ("Z", "m"),
                  ("Rx", "rad"), ("Ry", "rad"), ("Rz", "rad")),
            store=self._tcp_value_labels,
        ), stretch=1)
        readout_col.addWidget(self._build_readout_card(
            title="Joint Angles",
            rows=(("J1", "rad"), ("J2", "rad"), ("J3", "rad"),
                  ("J4", "rad"), ("J5", "rad"), ("J6", "rad")),
            store=self._joint_value_labels,
        ), stretch=1)
        body.addLayout(readout_col, stretch=2)

        root.addLayout(body, stretch=1)

        # Bottom: speed / step / home / log (full width).
        root.addWidget(self._build_bottom_row(), stretch=0)

    # -------------------------------------------------------------------------
    # Theming
    # -------------------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette.

        Re-styles cards, labels, toggle/jog buttons, the slider, spinbox and
        action buttons, and re-applies the connection-state badge for the
        CURRENT state so a live theme switch is fully reflected.
        """
        # Cards.
        for card in self._cards:
            card.setStyleSheet(theme_v2.CARD_QSS)

        # Section titles + caption/value labels.
        title_qss = _section_title_qss()
        for lbl in self._title_labels:
            lbl.setStyleSheet(title_qss)
        caption_qss = _readout_label_qss()
        for lbl in self._caption_labels:
            lbl.setStyleSheet(caption_qss)
        value_qss = _readout_value_qss()
        for lbl in self._value_labels:
            lbl.setStyleSheet(value_qss)

        # Segmented toggle buttons.
        toggle_qss = _toggle_button_qss()
        for btn in self._toggle_buttons:
            btn.setStyleSheet(toggle_qss)

        # Jog axis buttons -- refresh joint-mode buttons' accent first.
        joint_color = _axis_color_joint()
        for btn in self._joint_jog_buttons:
            btn._axis_color = joint_color
        for btn in self._jog_buttons:
            btn.apply_theme()

        # Connection / action buttons.
        self._btn_connect.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)
        self._btn_disconnect.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._btn_save_home.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._btn_go_home.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)
        self._btn_save_log.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)

        # Speed slider + step spinbox.
        self._speed_slider.setStyleSheet(theme_v2.SLIDER_QSS)
        self._step_spinbox.setStyleSheet(theme_v2.SPINBOX_QSS)

        # Bottom control strip -- card surface without the 160px card min-height.
        self._bottom_bar.setStyleSheet(
            f".QFrame {{ background-color: {theme_v2.SURFACE};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_LG}px; }}"
        )

        # Status badge -- re-apply for the live state (a safety override
        # takes precedence over the plain connection state).
        if self._safety_override == "protective":
            self._lbl_status.setStyleSheet(theme_v2.BADGE_WARN_QSS)
        elif self._safety_override == "emergency":
            self._lbl_status.setStyleSheet(theme_v2.BADGE_ERROR_QSS)
        else:
            self._apply_connection_state()

    # ----- Top row: connection + mode/frame toggles --------------------------

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(S_16)

        # Connection panel (left)
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.clicked.connect(self.connect_clicked)

        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.clicked.connect(self.disconnect_clicked)

        self._lbl_status = QLabel("Status: Idle")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_status.setMinimumHeight(40)
        self._lbl_status.setMinimumWidth(160)

        row.addWidget(self._btn_connect)
        row.addWidget(self._btn_disconnect)
        row.addWidget(self._lbl_status)
        row.addStretch(1)

        # Mode toggle (right)
        mode_label = QLabel("Mode")
        self._caption_labels.append(mode_label)

        self._btn_mode_cart = QPushButton("Cartesian")
        self._btn_mode_joint = QPushButton("Joint")
        for btn in (self._btn_mode_cart, self._btn_mode_joint):
            btn.setCheckable(True)
            self._toggle_buttons.append(btn)

        self._btn_mode_cart.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._btn_mode_cart, 0)
        self._mode_group.addButton(self._btn_mode_joint, 1)
        self._btn_mode_cart.clicked.connect(lambda: self._on_mode_change("cartesian"))
        self._btn_mode_joint.clicked.connect(lambda: self._on_mode_change("joint"))

        # Frame toggle
        frame_label = QLabel("Frame")
        self._caption_labels.append(frame_label)

        self._btn_frame_base = QPushButton("Base")
        self._btn_frame_tool = QPushButton("Tool")
        for btn in (self._btn_frame_base, self._btn_frame_tool):
            btn.setCheckable(True)
            self._toggle_buttons.append(btn)

        self._btn_frame_base.setChecked(True)
        self._frame_group = QButtonGroup(self)
        self._frame_group.setExclusive(True)
        self._frame_group.addButton(self._btn_frame_base, 0)
        self._frame_group.addButton(self._btn_frame_tool, 1)
        self._btn_frame_base.clicked.connect(lambda: self._on_frame_change("base"))
        self._btn_frame_tool.clicked.connect(lambda: self._on_frame_change("tool"))

        row.addWidget(mode_label)
        row.addWidget(self._btn_mode_cart)
        row.addWidget(self._btn_mode_joint)
        row.addSpacing(S_16)
        row.addWidget(frame_label)
        row.addWidget(self._btn_frame_base)
        row.addWidget(self._btn_frame_tool)

        return row

    # ----- Readout cards: TCP + Joint ----------------------------------------

    def _build_readout_card(
        self,
        title: str,
        rows: tuple,
        store: dict,
    ) -> QFrame:
        card = QFrame()
        card.setMinimumHeight(150)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cards.append(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(S_16, S_12, S_16, S_12)
        layout.setSpacing(S_8)

        title_lbl = QLabel(title)
        self._title_labels.append(title_lbl)
        layout.addWidget(title_lbl)
        layout.addStretch(1)   # centre the readout block in the card

        grid = QGridLayout()
        grid.setHorizontalSpacing(S_16)
        grid.setVerticalSpacing(S_12)

        # Two columns of (label, value) - 6 rows shown in 3x2 grid
        for idx, (axis, unit) in enumerate(rows):
            r = idx % 3
            c = idx // 3
            base_col = c * 3

            label = QLabel(axis)
            label.setMinimumWidth(32)
            self._caption_labels.append(label)

            value = QLabel("---")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value.setMinimumWidth(110)
            self._value_labels.append(value)

            unit_lbl = QLabel(unit)
            self._caption_labels.append(unit_lbl)

            grid.addWidget(label, r, base_col + 0)
            grid.addWidget(value, r, base_col + 1)
            grid.addWidget(unit_lbl, r, base_col + 2)
            store[axis] = value

        layout.addLayout(grid)
        layout.addStretch(1)
        return card

    # ----- Axis grid (cartesian + joint via QStackedWidget) -------------------

    def _build_axis_grid_card(self) -> QFrame:
        card = QFrame()
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cards.append(card)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(S_16, S_12, S_16, S_16)
        outer.setSpacing(S_12)

        title = QLabel("Jog Axes")
        self._title_labels.append(title)
        outer.addWidget(title)

        self._axis_stack = QStackedWidget()
        # Transparent so the card surface shows through behind the pages;
        # a QStackedWidget otherwise paints the window background, which
        # shows as a band across the heading row and gutter.
        self._axis_stack.setStyleSheet(
            "QStackedWidget { background-color: transparent; }"
        )
        self._axis_stack.addWidget(self._build_cartesian_grid())  # idx 0
        self._axis_stack.addWidget(self._build_joint_grid())      # idx 1
        outer.addWidget(self._axis_stack, stretch=1)

        return card

    def _build_cartesian_grid(self) -> QWidget:
        """6 cartesian axes split into two labelled groups.

        Layout::

            TRANSLATION            ROTATION
            X-  X+                 Rx-  Rx+
            Y-  Y+                 Ry-  Ry+
            Z-  Z+                 Rz-  Rz+

        Column 2 is a fixed-width gutter so the translation and rotation
        groups read as distinct, not one undifferentiated 4-wide grid.
        """
        page = QWidget()
        # Transparent so the card surface shows through the heading row and
        # the gutter column -- a plain QWidget paints the window background.
        page.setObjectName("axisGridPage")
        page.setStyleSheet("QWidget#axisGridPage { background-color: transparent; }")
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(S_12)
        grid.setVerticalSpacing(S_8)

        # Group subheadings on row 0 -- each spans its group's button pair.
        grid.addWidget(self._make_group_heading("TRANSLATION"), 0, 0, 1, 2)
        grid.addWidget(self._make_group_heading("ROTATION"), 0, 3, 1, 2)

        translation_axes = (
            ("X", 0, _AXIS_COLOR_X),
            ("Y", 1, _AXIS_COLOR_Y),
            ("Z", 2, _AXIS_COLOR_Z),
        )
        rotation_axes = (
            ("Rx", 3, _AXIS_COLOR_RX),
            ("Ry", 4, _AXIS_COLOR_RY),
            ("Rz", 5, _AXIS_COLOR_RZ),
        )

        for row, (name, axis_idx, color) in enumerate(translation_axes):
            btn_minus = self._make_jog_button(f"{name}-", color, axis_idx, -1)
            btn_plus = self._make_jog_button(f"{name}+", color, axis_idx, +1)
            grid.addWidget(btn_minus, row + 1, 0)
            grid.addWidget(btn_plus, row + 1, 1)

        for row, (name, axis_idx, color) in enumerate(rotation_axes):
            btn_minus = self._make_jog_button(f"{name}-", color, axis_idx, -1)
            btn_plus = self._make_jog_button(f"{name}+", color, axis_idx, +1)
            grid.addWidget(btn_minus, row + 1, 3)
            grid.addWidget(btn_plus, row + 1, 4)

        # Columns 0,1 + 3,4 hold the button pairs; column 2 is the gutter.
        grid.setColumnMinimumWidth(2, S_24)
        for col in (0, 1, 3, 4):
            grid.setColumnStretch(col, 1)
        grid.setColumnStretch(2, 0)
        grid.setRowStretch(0, 0)            # heading row -- natural height
        for r in range(1, 4):
            grid.setRowStretch(r, 1)

        return page

    def _build_joint_grid(self) -> QWidget:
        """6 joints split into the arm (J1-J3) and wrist (J4-J6) groups.

        Layout::

            ARM                    WRIST
            J1-  J1+               J4-  J4+
            J2-  J2+               J5-  J5+
            J3-  J3+               J6-  J6+

        Mirrors the cartesian grid: two labelled groups with a gutter
        column between them.
        """
        page = QWidget()
        page.setObjectName("axisGridPage")
        page.setStyleSheet("QWidget#axisGridPage { background-color: transparent; }")
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(S_12)
        grid.setVerticalSpacing(S_8)

        grid.addWidget(self._make_group_heading("ARM"), 0, 0, 1, 2)
        grid.addWidget(self._make_group_heading("WRIST"), 0, 3, 1, 2)

        joint_color = _axis_color_joint()
        for axis_idx in range(6):
            name = f"J{axis_idx + 1}"
            btn_minus = self._make_jog_button(
                f"{name}-", joint_color, axis_idx, -1, is_joint=True
            )
            btn_plus = self._make_jog_button(
                f"{name}+", joint_color, axis_idx, +1, is_joint=True
            )
            row = axis_idx % 3
            col_pair = axis_idx // 3            # 0 for J1-J3, 1 for J4-J6
            base_col = 0 if col_pair == 0 else 3
            grid.addWidget(btn_minus, row + 1, base_col + 0)
            grid.addWidget(btn_plus, row + 1, base_col + 1)

        grid.setColumnMinimumWidth(2, S_24)
        for col in (0, 1, 3, 4):
            grid.setColumnStretch(col, 1)
        grid.setColumnStretch(2, 0)
        grid.setRowStretch(0, 0)
        for r in range(1, 4):
            grid.setRowStretch(r, 1)

        return page

    def _make_group_heading(self, text: str) -> QLabel:
        """Build a small caption label that titles an axis group.

        Registered as a caption label so apply_theme() restyles it; uses
        the same muted, letter-spaced treatment as the readout captions.
        """
        lbl = QLabel(text)
        self._caption_labels.append(lbl)
        return lbl

    def _make_jog_button(
        self, label: str, color: str, axis_idx: int, direction: int,
        is_joint: bool = False,
    ) -> _JogButton:
        btn = _JogButton(label, color)
        btn.pressed_long.connect(
            lambda a=axis_idx, d=direction: self.jog_axis_pressed.emit(a, d)
        )
        btn.released_long.connect(
            lambda a=axis_idx, d=direction: self.jog_axis_released.emit(a, d)
        )
        btn.stepped.connect(
            lambda a=axis_idx, d=direction: self.jog_axis_stepped.emit(a, d)
        )
        self._jog_buttons.append(btn)
        if is_joint:
            self._joint_jog_buttons.append(btn)
        return btn

    # ----- Bottom row: speed slider, step spinbox, home/log buttons ----------

    def _build_bottom_row(self) -> QFrame:
        # Card-style surface, but WITHOUT the 160px card min-height so the bar
        # can stay a slim 96-120px control strip. Styled in apply_theme().
        self._bottom_bar = QFrame()
        self._bottom_bar.setMinimumHeight(96)
        self._bottom_bar.setMaximumHeight(120)
        self._bottom_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        layout = QHBoxLayout(self._bottom_bar)
        layout.setContentsMargins(S_16, S_12, S_16, S_12)
        layout.setSpacing(S_24)

        # Speed group
        speed_label = QLabel("Speed")
        self._caption_labels.append(speed_label)
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(10, 100)
        self._speed_slider.setValue(50)
        self._speed_slider.setMinimumWidth(220)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)

        self._speed_value_lbl = QLabel("50%")
        self._speed_value_lbl.setMinimumWidth(56)
        self._value_labels.append(self._speed_value_lbl)

        layout.addWidget(speed_label)
        layout.addWidget(self._speed_slider, stretch=1)
        layout.addWidget(self._speed_value_lbl)

        # Step group
        step_label = QLabel("Step")
        self._caption_labels.append(step_label)
        self._step_spinbox = QDoubleSpinBox()
        self._step_spinbox.setRange(0.001, 1.000)
        self._step_spinbox.setSingleStep(0.005)
        self._step_spinbox.setDecimals(3)
        self._step_spinbox.setValue(0.010)
        self._step_spinbox.setSuffix(" m/rad")
        self._step_spinbox.setMinimumWidth(160)
        self._step_spinbox.valueChanged.connect(self.step_changed)

        layout.addWidget(step_label)
        layout.addWidget(self._step_spinbox)

        # Home + log buttons
        self._btn_save_home = QPushButton("Save Home")
        self._btn_save_home.clicked.connect(self.home_save_clicked)

        self._btn_go_home = QPushButton("Go Home")
        self._btn_go_home.clicked.connect(self.home_go_clicked)

        self._btn_save_log = QPushButton("Save Log")
        self._btn_save_log.clicked.connect(self.save_log_clicked)

        layout.addWidget(self._btn_save_home)
        layout.addWidget(self._btn_go_home)
        layout.addWidget(self._btn_save_log)

        return self._bottom_bar

    # -------------------------------------------------------------------------
    # Internal slot handlers
    # -------------------------------------------------------------------------

    def _on_mode_change(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._axis_stack.setCurrentIndex(0 if mode == "cartesian" else 1)
        self.mode_changed.emit(mode)

    def _on_frame_change(self, frame: str) -> None:
        if frame == self._frame:
            return
        self._frame = frame
        self.frame_changed.emit(frame)

    def _on_speed_changed(self, value: int) -> None:
        self._speed_value_lbl.setText(f"{value}%")
        self.speed_changed.emit(value / 100.0)

    # -------------------------------------------------------------------------
    # Public API: external state updates
    # -------------------------------------------------------------------------

    def set_tcp_pose(self, pose: List[float]) -> None:
        """Update the TCP pose readout. Expects [x, y, z, rx, ry, rz]."""
        if pose is None or len(pose) < 6:
            return
        labels = ("X", "Y", "Z", "Rx", "Ry", "Rz")
        for axis, val in zip(labels, pose[:6]):
            lbl = self._tcp_value_labels.get(axis)
            if lbl is not None:
                lbl.setText(f"{val:+.3f}")

    def set_joint_angles(self, joints: List[float]) -> None:
        """Update the joint readout. Expects [j1..j6] in radians."""
        if joints is None or len(joints) < 6:
            return
        for i, val in enumerate(joints[:6]):
            lbl = self._joint_value_labels.get(f"J{i + 1}")
            if lbl is not None:
                lbl.setText(f"{val:+.3f}")

    def set_connection_state(self, state: str) -> None:
        """Drive button enable/disable + status badge.

        Accepted: 'idle', 'connecting', 'connected', 'error'.
        """
        self._connection_state = state.lower()
        self._apply_connection_state()

    def _apply_connection_state(self) -> None:
        state = self._connection_state
        if state == "connected":
            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._lbl_status.setText("● Connected")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_SUCCESS_QSS)
        elif state == "connecting":
            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._lbl_status.setText("◌ Connecting...")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_WARN_QSS)
        elif state == "error":
            self._btn_connect.setEnabled(True)
            self._btn_disconnect.setEnabled(False)
            self._lbl_status.setText("✕ Error")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_ERROR_QSS)
        else:  # idle / unknown
            self._btn_connect.setEnabled(True)
            self._btn_disconnect.setEnabled(False)
            self._lbl_status.setText("○ Idle")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_NEUTRAL_QSS)

        # Jog/home actions only useful when connected
        connected = state == "connected"
        self._axis_stack.setEnabled(connected)
        self._btn_save_home.setEnabled(connected)
        # Go-Home requires both connection AND a saved pose
        self._btn_go_home.setEnabled(connected and self._home_saved)

    def set_safety_state(self, state: str, message: str = "") -> None:
        """Reflect safety state. v1: status badge takeover (header bar handles
        full e-stop overlay separately).
        """
        s = (state or "").lower()
        if s in ("protective_stop", "protective"):
            self._safety_override = "protective"
            self._lbl_status.setText("⚠ Protective Stop")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_WARN_QSS)
            self._axis_stack.setEnabled(False)
        elif s in ("emergency", "estop", "e_stop"):
            self._safety_override = "emergency"
            self._lbl_status.setText("✕ EMERGENCY")
            self._lbl_status.setStyleSheet(theme_v2.BADGE_ERROR_QSS)
            self._axis_stack.setEnabled(False)
        elif s in ("normal", "ok", "ready"):
            # Restore badge from underlying connection state
            self._safety_override = ""
            self._apply_connection_state()
        # Note: optional message popup left for the main window to surface.

    def set_home_saved(self, saved: bool) -> None:
        """Enables/disables 'Go Home' depending on whether a home pose exists."""
        self._home_saved = bool(saved)
        self._apply_home_saved()

    def _apply_home_saved(self) -> None:
        # Go-home requires saved pose AND active connection
        self._btn_go_home.setEnabled(
            self._home_saved and self._connection_state == "connected"
        )
