"""theme_v2.py - Centralised light/dark theme for the UR10 jog control UI.

Author: jsecco (R)

Usage:
    from ui import theme_v2
    theme_v2.set_mode("light")            # or "dark"
    widget.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)

The 16 color tokens (BG, SURFACE, ACCENT, ...) and every *_QSS string are
module globals that are rebuilt by set_mode()/_rebuild(). Widgets reference
them as theme_v2.<NAME> so a live theme switch is reflected after they
re-run their setStyleSheet calls (via each widget's apply_theme()).
"""

# =============================================================================
# Spacing tokens (px) -- static, identical in both themes
# =============================================================================

S_4  = 4
S_8  = 8
S_12 = 12
S_16 = 16
S_24 = 24
S_32 = 32
S_48 = 48
S_64 = 64

# =============================================================================
# Border radii (px) -- static
# =============================================================================

R_SM = 8
R_MD = 12
R_LG = 16

# =============================================================================
# Font sizes (px) -- static
# =============================================================================

F_DISPLAY = 40   # Hero numbers, splash titles
F_TITLE   = 32   # Page / section titles
F_HEADING = 24   # Card headings
F_SUBHEAD = 20   # Sub-headings, prominent labels
F_BODY    = 18   # Default body copy
F_SMALL   = 14   # Helper text, captions
F_MICRO   = 12   # Badges, timestamps, fine print
F_MONO    = 16   # Event log, code snippets

# =============================================================================
# Touch / interaction sizing (px) -- static
# =============================================================================

BUTTON_H     = 56   # Standard touch button height
ESTOP_H      = 80   # Emergency-stop button height (larger target)
SLIDER_THUMB = 40   # Slider thumb diameter
CARD_MIN_H   = 160  # Minimum card height

# Category accent stripes (demo card headers) -- semantic, identical in
# both themes, so they stay as static module constants.
CAT_SHOWCASE    = "#8B5CF6"   # Purple  - Showcase demos
CAT_DYNAMIC     = "#F59E0B"   # Amber   - Dynamic demos
CAT_INDUSTRIAL  = "#10B981"   # Green   - Industrial demos
CAT_ENGINEERING = "#3B82F6"   # Blue    - Engineering demos

# rounded-pill radius for the status badges
_BADGE_RADIUS = 18

# =============================================================================
# Palettes
# Each maps the 16 theme-dependent color keys to hex strings. _rebuild()
# copies the active palette's values into module globals of the same name.
# =============================================================================

_DARK = {
    "BG":          "#0F1419",
    "SURFACE":     "#1A1F2B",
    "SURFACE_HI":  "#232936",
    "BORDER":      "#2D3441",
    "TEXT":        "#E5E7EB",
    "TEXT_MUTED":  "#9CA3AF",
    "TEXT_DIM":    "#6B7280",
    "ACCENT":      "#3B82F6",
    "ACCENT_HI":   "#60A5FA",
    "ACCENT_PRESSED": "#2563EB",
    "SUCCESS":     "#10B981",
    "WARN":        "#F59E0B",
    "ERROR":       "#EF4444",
    "BADGE_SUCCESS_BG": "#064E3B",
    "BADGE_WARN_BG":    "#78350F",
    "BADGE_ERROR_BG":   "#7F1D1D",
}

_LIGHT = {
    "BG":          "#F1F3F5",
    "SURFACE":     "#FFFFFF",
    "SURFACE_HI":  "#E6E9EE",
    "BORDER":      "#D3D8DF",
    "TEXT":        "#161B22",
    "TEXT_MUTED":  "#5B6571",
    "TEXT_DIM":    "#9AA2AE",
    "ACCENT":      "#2563EB",
    "ACCENT_HI":   "#3B82F6",
    "ACCENT_PRESSED": "#1D4ED8",
    "SUCCESS":     "#047857",
    "WARN":        "#B45309",
    "ERROR":       "#DC2626",
    "BADGE_SUCCESS_BG": "#D1FAE5",
    "BADGE_WARN_BG":    "#FEF3C7",
    "BADGE_ERROR_BG":   "#FEE2E2",
}

# The 16 theme-dependent color-token names, in palette-key order.
_COLOR_KEYS = (
    "BG", "SURFACE", "SURFACE_HI", "BORDER",
    "TEXT", "TEXT_MUTED", "TEXT_DIM",
    "ACCENT", "ACCENT_HI", "ACCENT_PRESSED",
    "SUCCESS", "WARN", "ERROR",
    "BADGE_SUCCESS_BG", "BADGE_WARN_BG", "BADGE_ERROR_BG",
)

# Active theme mode -- light is the default.
_mode = "light"


def current_mode() -> str:
    """Return the active theme mode: 'light' or 'dark'."""
    return _mode


def set_mode(mode: str) -> None:
    """Switch the active theme and rebuild every color token + QSS global.

    Args:
        mode: 'light' or 'dark'. Unknown values fall back to 'light'.
    """
    global _mode
    _mode = "dark" if str(mode).lower() == "dark" else "light"
    _rebuild()


def _shade(hex_color: str, factor: float) -> str:
    """Lighten (factor > 0, toward white) or darken (factor < 0) a colour.

    Used to build the gentle vertical gradient that gives cards and tiles
    a visible surface across the app -- Qt QSS gradient stops want solid
    '#RRGGBB' colours, so the blend is precomputed here.
    """
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16)
        c = c + (255 - c) * factor if factor >= 0 else c * (1.0 + factor)
        out.append(max(0, min(255, round(c))))
    return "#{:02X}{:02X}{:02X}".format(*out)


def _rebuild() -> None:
    """Rebuild the 16 color-token globals and every *_QSS string global.

    Called once at import and again on every set_mode(). All assignments go
    through globals() so the names remain plain module-level attributes that
    callers reference as theme_v2.<NAME>.
    """
    g = globals()
    palette = _DARK if _mode == "dark" else _LIGHT

    # ---- 16 theme-dependent color tokens ----
    for key in _COLOR_KEYS:
        g[key] = palette[key]

    BG               = g["BG"]
    SURFACE          = g["SURFACE"]
    SURFACE_HI       = g["SURFACE_HI"]
    BORDER           = g["BORDER"]
    TEXT             = g["TEXT"]
    TEXT_MUTED       = g["TEXT_MUTED"]
    TEXT_DIM         = g["TEXT_DIM"]
    ACCENT           = g["ACCENT"]
    ACCENT_HI        = g["ACCENT_HI"]
    ACCENT_PRESSED   = g["ACCENT_PRESSED"]
    SUCCESS          = g["SUCCESS"]
    WARN             = g["WARN"]
    ERROR            = g["ERROR"]
    BADGE_SUCCESS_BG = g["BADGE_SUCCESS_BG"]
    BADGE_WARN_BG    = g["BADGE_WARN_BG"]
    BADGE_ERROR_BG   = g["BADGE_ERROR_BG"]

    # =========================================================================
    # Window & root widget
    # Applied to QMainWindow + base QWidget to establish global bg/text defaults.
    # =========================================================================
    g["WINDOW_QSS"] = (
        f"QMainWindow {{ background-color: {BG}; }}"
        # Font stack lists only faces actually installed on the Elo i3 target,
        # so the declared family matches what renders. Liberation Sans is the
        # metric-compatible neutral sans shipped on the device.
        f"QWidget {{ background-color: {BG}; color: {TEXT};"
        f" font-family: 'Liberation Sans', 'DejaVu Sans', sans-serif;"
        f" font-size: {F_BODY}px; }}"
    )

    # =========================================================================
    # Primary button
    # Used for main call-to-action actions (Start demo, Connect, etc.).
    # Requires no objectName; apply directly via setStyleSheet.
    # =========================================================================
    g["PRIMARY_BUTTON_QSS"] = (
        f"QPushButton {{"
        f" background-color: {ACCENT};"
        f" color: white;"
        f" border: none;"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_24}px;"
        f" min-height: {BUTTON_H}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {ACCENT_HI};"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {ACCENT_PRESSED};"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: {SURFACE_HI};"
        f" color: {TEXT_DIM};"
        f"}}"
        f"QPushButton:focus {{"
        f" border: 2px solid {ACCENT_HI};"
        f"}}"
    )

    # =========================================================================
    # Emergency-stop button
    # Tall, bright red, bold -- maximum visual urgency.
    # The urgent-red hues (#B91C1C, #DC2626, #991B1B) stay hardcoded: an
    # e-stop must read as the same alarm red regardless of theme.
    # =========================================================================
    g["ESTOP_BUTTON_QSS"] = (
        f"QPushButton {{"
        f" background-color: {ERROR};"
        f" color: white;"
        f" border: 2px solid #B91C1C;"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_32}px;"
        f" min-height: {ESTOP_H}px;"
        f" font-size: {F_SUBHEAD}px;"
        f" font-weight: 700;"
        f" letter-spacing: 1px;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: #DC2626;"
        f" border-color: #991B1B;"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: #B91C1C;"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: {SURFACE_HI};"
        f" color: {TEXT_DIM};"
        f" border-color: {BORDER};"
        f"}}"
    )

    # =========================================================================
    # Secondary button
    # Outlined style; used for secondary / cancel actions.
    # =========================================================================
    g["SECONDARY_BUTTON_QSS"] = (
        f"QPushButton {{"
        f" background-color: {SURFACE};"
        f" color: {TEXT};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_24}px;"
        f" min-height: {BUTTON_H}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 500;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {SURFACE_HI};"
        f" border-color: {ACCENT};"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {SURFACE_HI};"
        f" border-color: {ACCENT_HI};"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: {SURFACE};"
        f" color: {TEXT_DIM};"
        f" border-color: {BORDER};"
        f"}}"
        f"QPushButton:focus {{"
        f" border-color: {ACCENT};"
        f"}}"
    )

    # =========================================================================
    # Danger button
    # Used for destructive actions (Stop, Reset fault, etc.).
    # =========================================================================
    g["DANGER_BUTTON_QSS"] = (
        f"QPushButton {{"
        f" background-color: transparent;"
        f" color: {ERROR};"
        f" border: 1px solid {ERROR};"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_24}px;"
        f" min-height: {BUTTON_H}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {ERROR};"
        f" color: white;"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: #B91C1C;"
        f" color: white;"
        f" border-color: #B91C1C;"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: transparent;"
        f" color: {TEXT_DIM};"
        f" border-color: {BORDER};"
        f"}}"
    )

    # =========================================================================
    # Ghost button
    # Transparent background, accent-coloured text -- for subtle / icon actions.
    # =========================================================================
    g["GHOST_BUTTON_QSS"] = (
        f"QPushButton {{"
        f" background-color: transparent;"
        f" color: {ACCENT};"
        f" border: none;"
        f" border-radius: {R_MD}px;"
        f" padding: 0 {S_16}px;"
        f" min-height: {BUTTON_H}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 500;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {SURFACE_HI};"
        f" color: {ACCENT_HI};"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {SURFACE};"
        f"}}"
        f"QPushButton:disabled {{"
        f" color: {TEXT_DIM};"
        f"}}"
    )

    # =========================================================================
    # Card / panel frame
    # Applied to QFrame or QWidget used as a card container.
    # "Hover lift" is conveyed by a brighter border (no box-shadow in Qt QSS).
    # =========================================================================
    # Card has a subtle vertical gradient surface and a thin accent stripe
    # along its top edge -- robust QSS-only depth that renders on every Qt
    # platform (no QGraphicsEffect needed). border-top accent is permitted;
    # the design ban is on border-LEFT/RIGHT side stripes.
    card_top = _shade(SURFACE, 0.04)
    card_bot = _shade(SURFACE, -0.05)
    g["CARD_QSS"] = (
        # ".QFrame" (class selector) matches QFrame instances ONLY -- not
        # subclasses. A bare "QFrame" selector would also match QLabel (a
        # QFrame subclass), pushing the border + min-height onto every label
        # in the card.
        f".QFrame {{"
        f" background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {card_top}, stop:1 {card_bot});"
        f" border: 1px solid {BORDER};"
        f" border-top: 3px solid {ACCENT};"
        f" border-radius: {R_LG}px;"
        f" min-height: {CARD_MIN_H}px;"
        f"}}"
        f".QFrame:hover {{"
        f" border-color: {ACCENT};"
        f" border-top-color: {ACCENT};"
        f"}}"
    )

    # =========================================================================
    # Tab bar
    # Horizontal tab widget; active tab gets an accent underline via border-bottom.
    # Qt QSS does not support ::after pseudo-elements, so border-bottom is used.
    # =========================================================================
    g["TAB_BAR_QSS"] = (
        f"QTabWidget::pane {{"
        f" background-color: {SURFACE};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_MD}px;"
        f"}}"
        f"QTabBar::tab {{"
        f" background-color: transparent;"
        f" color: {TEXT_MUTED};"
        f" border: none;"
        f" border-bottom: 2px solid transparent;"
        f" padding: {S_12}px {S_24}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 500;"
        f" margin-right: {S_4}px;"
        f"}}"
        f"QTabBar::tab:selected {{"
        f" color: {ACCENT};"
        f" border-bottom: 2px solid {ACCENT};"
        f"}}"
        f"QTabBar::tab:hover:!selected {{"
        f" color: {TEXT};"
        f" border-bottom: 2px solid {BORDER};"
        f"}}"
    )

    # =========================================================================
    # Slider
    # Large track and large thumb for touch / glove-friendly interaction.
    # Qt supports ::groove and ::handle sub-controls.
    # =========================================================================
    g["SLIDER_QSS"] = (
        f"QSlider::groove:horizontal {{"
        f" background-color: {SURFACE_HI};"
        f" height: 8px;"
        f" border-radius: 4px;"
        f"}}"
        f"QSlider::sub-page:horizontal {{"
        f" background-color: {ACCENT};"
        f" height: 8px;"
        f" border-radius: 4px;"
        f"}}"
        f"QSlider::handle:horizontal {{"
        f" background-color: {ACCENT};"
        f" border: 3px solid {BG};"
        f" width: {SLIDER_THUMB}px;"
        f" height: {SLIDER_THUMB}px;"
        f" margin: -{SLIDER_THUMB // 2 - 4}px 0;"
        f" border-radius: {SLIDER_THUMB // 2}px;"
        f"}}"
        f"QSlider::handle:horizontal:hover {{"
        f" background-color: {ACCENT_HI};"
        f"}}"
        f"QSlider::handle:horizontal:disabled {{"
        f" background-color: {SURFACE_HI};"
        f" border-color: {BORDER};"
        f"}}"
        f"QSlider::groove:vertical {{"
        f" background-color: {SURFACE_HI};"
        f" width: 8px;"
        f" border-radius: 4px;"
        f"}}"
        f"QSlider::sub-page:vertical {{"
        f" background-color: {ACCENT};"
        f" width: 8px;"
        f" border-radius: 4px;"
        f"}}"
        f"QSlider::handle:vertical {{"
        f" background-color: {ACCENT};"
        f" border: 3px solid {BG};"
        f" width: {SLIDER_THUMB}px;"
        f" height: {SLIDER_THUMB}px;"
        f" margin: 0 -{SLIDER_THUMB // 2 - 4}px;"
        f" border-radius: {SLIDER_THUMB // 2}px;"
        f"}}"
    )

    # =========================================================================
    # SpinBox
    # Numeric input for joint angles, speeds, positions.
    # =========================================================================
    g["SPINBOX_QSS"] = (
        f"QSpinBox, QDoubleSpinBox {{"
        f" background-color: {SURFACE};"
        f" color: {TEXT};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_SM}px;"
        f" padding: {S_8}px {S_12}px;"
        f" font-size: {F_BODY}px;"
        f" min-height: {BUTTON_H}px;"
        f"}}"
        f"QSpinBox:focus, QDoubleSpinBox:focus {{"
        f" border-color: {ACCENT};"
        f"}}"
        f"QSpinBox:hover, QDoubleSpinBox:hover {{"
        f" border-color: {ACCENT_HI};"
        f"}}"
        f"QSpinBox:disabled, QDoubleSpinBox:disabled {{"
        f" background-color: {SURFACE_HI};"
        f" color: {TEXT_DIM};"
        f" border-color: {BORDER};"
        f"}}"
        f"QSpinBox::up-button, QDoubleSpinBox::up-button {{"
        f" background-color: {SURFACE_HI};"
        f" border: none;"
        f" border-radius: 0 {R_SM}px 0 0;"
        f" width: 28px;"
        f"}}"
        f"QSpinBox::down-button, QDoubleSpinBox::down-button {{"
        f" background-color: {SURFACE_HI};"
        f" border: none;"
        f" border-radius: 0 0 {R_SM}px 0;"
        f" width: 28px;"
        f"}}"
        f"QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,"
        f"QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{"
        f" background-color: {ACCENT};"
        f"}}"
    )

    # =========================================================================
    # LineEdit
    # Text input for IP addresses, waypoint names, etc.
    # =========================================================================
    g["LINEEDIT_QSS"] = (
        f"QLineEdit {{"
        f" background-color: {SURFACE};"
        f" color: {TEXT};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_SM}px;"
        f" padding: {S_8}px {S_12}px;"
        f" font-size: {F_BODY}px;"
        f" min-height: {BUTTON_H}px;"
        f" selection-background-color: {ACCENT};"
        f"}}"
        f"QLineEdit:focus {{"
        f" border-color: {ACCENT};"
        f"}}"
        f"QLineEdit:hover {{"
        f" border-color: {ACCENT_HI};"
        f"}}"
        f"QLineEdit:disabled {{"
        f" background-color: {SURFACE_HI};"
        f" color: {TEXT_DIM};"
        f" border-color: {BORDER};"
        f"}}"
        f"QLineEdit[readOnly=\"true\"] {{"
        f" background-color: {BG};"
        f" border-color: {BORDER};"
        f"}}"
    )

    # =========================================================================
    # ScrollArea
    # Transparent wrapper; scrollbar is styled separately via SCROLLBAR_QSS.
    # =========================================================================
    g["SCROLLAREA_QSS"] = (
        f"QScrollArea {{"
        f" background-color: transparent;"
        f" border: none;"
        f"}}"
        f"QScrollArea > QWidget > QWidget {{"
        f" background-color: transparent;"
        f"}}"
    )

    # =========================================================================
    # Scrollbar
    # 14 px wide, rounded handle, subtle on the window background.
    # Qt QSS supports ::handle, ::add-line, ::sub-line, ::add-page, ::sub-page.
    # =========================================================================
    g["SCROLLBAR_QSS"] = (
        f"QScrollBar:vertical {{"
        f" background-color: {BG};"
        f" width: 14px;"
        f" margin: 0;"
        f"}}"
        f"QScrollBar::handle:vertical {{"
        f" background-color: {SURFACE_HI};"
        f" border-radius: 7px;"
        f" min-height: 32px;"
        f" margin: 2px;"
        f"}}"
        f"QScrollBar::handle:vertical:hover {{"
        f" background-color: {TEXT_DIM};"
        f"}}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
        f" height: 0;"
        f" background-color: none;"
        f"}}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
        f" background-color: none;"
        f"}}"
        f"QScrollBar:horizontal {{"
        f" background-color: {BG};"
        f" height: 14px;"
        f" margin: 0;"
        f"}}"
        f"QScrollBar::handle:horizontal {{"
        f" background-color: {SURFACE_HI};"
        f" border-radius: 7px;"
        f" min-width: 32px;"
        f" margin: 2px;"
        f"}}"
        f"QScrollBar::handle:horizontal:hover {{"
        f" background-color: {TEXT_DIM};"
        f"}}"
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{"
        f" width: 0;"
        f" background-color: none;"
        f"}}"
        f"QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{"
        f" background-color: none;"
        f"}}"
    )

    # =========================================================================
    # Phase / status panel
    # Large full-width status panel displayed during demo execution.
    # Base style only -- dynamic state uses status_panel_qss() callable below.
    # =========================================================================
    g["PHASE_PANEL_QSS"] = (
        f"QFrame#phasePanel {{"
        f" background-color: {SURFACE};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_LG}px;"
        f" padding: {S_24}px;"
        f"}}"
        f"QLabel#phaseLabel {{"
        f" color: {TEXT};"
        f" font-size: {F_TITLE}px;"
        f" font-weight: 700;"
        f" background-color: transparent;"
        f"}}"
        f"QLabel#phaseSubLabel {{"
        f" color: {TEXT_MUTED};"
        f" font-size: {F_BODY}px;"
        f" background-color: transparent;"
        f"}}"
    )

    # =========================================================================
    # Event log
    # Monospaced, read-only text area for robot event / debug output.
    # =========================================================================
    g["EVENT_LOG_QSS"] = (
        f"QPlainTextEdit, QTextEdit {{"
        f" background-color: {BG};"
        f" color: {TEXT_MUTED};"
        f" border: 1px solid {BORDER};"
        f" border-radius: {R_SM}px;"
        f" font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;"
        f" font-size: {F_MONO}px;"
        f" padding: {S_8}px;"
        f" selection-background-color: {ACCENT};"
        f"}}"
        f"QPlainTextEdit:focus, QTextEdit:focus {{"
        f" border-color: {BORDER};"
        f"}}"
    )

    # =========================================================================
    # Header bar
    # Persistent top bar containing logo, connection status, global controls.
    # =========================================================================
    g["HEADER_BAR_QSS"] = (
        f"QWidget#headerBar {{"
        f" background-color: {SURFACE};"
        f" border-bottom: 1px solid {BORDER};"
        f"}}"
        f"QLabel#appTitle {{"
        f" color: {TEXT};"
        f" font-size: {F_HEADING}px;"
        f" font-weight: 700;"
        f" background-color: transparent;"
        f"}}"
        f"QLabel#connectionBadge {{"
        f" color: {TEXT_MUTED};"
        f" font-size: {F_SMALL}px;"
        f" background-color: transparent;"
        f"}}"
    )

    # =========================================================================
    # Footer bar
    # Persistent bottom bar with safety status, mode indicator, quick actions.
    # =========================================================================
    g["FOOTER_BAR_QSS"] = (
        f"QWidget#footerBar {{"
        f" background-color: {SURFACE};"
        f" border-top: 1px solid {BORDER};"
        f" padding: 0 {S_16}px;"
        f"}}"
        f"QLabel#statusText {{"
        f" color: {TEXT_MUTED};"
        f" font-size: {F_SMALL}px;"
        f" background-color: transparent;"
        f"}}"
    )

    # =========================================================================
    # Badges
    # Small pill labels for status indicators (setObjectName not required --
    # apply the full QSS directly to QLabel instances as needed).
    # =========================================================================
    g["BADGE_NEUTRAL_QSS"] = (
        f"QLabel {{"
        f" background-color: {SURFACE_HI};"
        f" color: {TEXT_MUTED};"
        f" border-radius: {_BADGE_RADIUS}px;"
        f" padding: 6px {S_16}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
    )

    g["BADGE_SUCCESS_QSS"] = (
        f"QLabel {{"
        f" background-color: {BADGE_SUCCESS_BG};"
        f" color: {SUCCESS};"
        f" border-radius: {_BADGE_RADIUS}px;"
        f" padding: 6px {S_16}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
    )

    g["BADGE_WARN_QSS"] = (
        f"QLabel {{"
        f" background-color: {BADGE_WARN_BG};"
        f" color: {WARN};"
        f" border-radius: {_BADGE_RADIUS}px;"
        f" padding: 6px {S_16}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
    )

    g["BADGE_ERROR_QSS"] = (
        f"QLabel {{"
        f" background-color: {BADGE_ERROR_BG};"
        f" color: {ERROR};"
        f" border-radius: {_BADGE_RADIUS}px;"
        f" padding: 6px {S_16}px;"
        f" font-size: {F_BODY}px;"
        f" font-weight: 600;"
        f"}}"
    )


# =============================================================================
# Callable helpers
# These read the (theme-dependent) module-global color names at call time, so
# they automatically follow set_mode() without needing their own rebuild hook.
# =============================================================================

_CATEGORY_COLORS: dict[str, str] = {
    "showcase":    CAT_SHOWCASE,
    "dynamic":     CAT_DYNAMIC,
    "industrial":  CAT_INDUSTRIAL,
    "engineering": CAT_ENGINEERING,
}


def category_accent_qss(category: str) -> str:
    """Return the accent stripe color QSS for a demo-category card.

    The stripe is implemented as a top border on the card QFrame so that
    it renders correctly without CSS gradient or pseudo-element support.

    Args:
        category: One of 'showcase', 'dynamic', 'industrial', 'engineering'.
                  Falls back to BORDER for unknown values.

    Returns:
        A QSS string to apply via QFrame.setStyleSheet().
    """
    color = _CATEGORY_COLORS.get(category.lower(), BORDER)
    card_top = _shade(SURFACE, 0.04)
    card_bot = _shade(SURFACE, -0.05)
    return (
        f"QFrame {{"
        f" background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {card_top}, stop:1 {card_bot});"
        f" border: 1px solid {BORDER};"
        f" border-top: 4px solid {color};"
        f" border-radius: {R_LG}px;"
        f" min-height: {CARD_MIN_H}px;"
        f"}}"
        f"QFrame:hover {{"
        f" border-color: {color};"
        f" border-top-color: {color};"
        f"}}"
    )


def status_panel_qss(state: str) -> str:
    """Return the QSS for the big phase panel in a given robot state.

    Args:
        state: One of 'idle', 'running', 'complete', 'error', 'stopping'.
               Unknown values fall back to the 'idle' palette.

    Returns:
        A QSS string to apply via the phasePanel QFrame's setStyleSheet().
        Uses border-color to convey state rather than background shift, to
        keep text readability on the SURFACE background.
    """
    # Built per call so it tracks the active theme's reassigned color globals.
    state_colors = {
        # state: (border_color, label_color)
        "idle":      (BORDER,   TEXT_MUTED),
        "running":   (ACCENT,   ACCENT_HI),
        "complete":  (SUCCESS,  SUCCESS),
        "error":     (ERROR,    ERROR),
        "stopping":  (WARN,     WARN),
    }
    border_color, label_color = state_colors.get(
        state.lower(), state_colors["idle"]
    )
    panel_top = _shade(SURFACE, 0.04)
    panel_bot = _shade(SURFACE, -0.05)
    return (
        # No QSS "padding" here -- the panel's QVBoxLayout already sets
        # contentsMargins. QSS padding would stack on top, starving the
        # layout of height and squashing the phase label below its minimum.
        f"QFrame#phasePanel {{"
        f" background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {panel_top}, stop:1 {panel_bot});"
        f" border: 2px solid {border_color};"
        f" border-radius: {R_LG}px;"
        f"}}"
        # Colour only -- the font is set on the label via QFont so its
        # sizeHint is correct. A QSS font-size here would cascade onto the
        # label, override the QFont, and break the layout's height maths.
        f"QLabel#phaseLabel {{"
        f" color: {label_color};"
        f" background-color: transparent;"
        f"}}"
        f"QLabel#phaseSubLabel {{"
        f" color: {TEXT_MUTED};"
        f" font-size: {F_BODY}px;"
        f" background-color: transparent;"
        f"}}"
    )


# Build the color-token + *_QSS globals once at import so they always exist.
_rebuild()
