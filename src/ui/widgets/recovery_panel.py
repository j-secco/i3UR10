"""recovery_panel.py - Fault recovery overlay for the UR10 jog control UI.

A full-screen overlay that surfaces the robot's current safety / robot mode
and exposes every dashboard recovery command as an explicit button:

  Release Protective Stop   (unlock_protective_stop)
  Close Safety Popup        (close_safety_popup)
  Restart Safety            (restart_safety)
  Power On                  (power_on)
  Release Brakes            (brake_release)
  Stop Program              (stop)

The panel does not talk to the robot itself -- it emits recover_requested
with the dashboard method name, and the main window dispatches that on a
worker thread (dashboard socket I/O must not run on the GUI thread). The
live status line is refreshed from the controller's status poll via
set_state(), so after a command the readout updates on its own.

None of these commands command arm motion. Resuming a demo (the only
motion-causing step) stays a separate, explicit Start action.

Author: jsecco (R)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ui import theme_v2
from ui.theme_v2 import (
    S_8, S_12, S_16, S_24, S_32,
    R_MD, R_LG,
    F_TITLE, F_HEADING, F_SUBHEAD, F_BODY, F_SMALL,
    BUTTON_H,
)


# Dashboard recovery commands: (button label, dashboard method name).
_COMMANDS = [
    ("Release Protective Stop", "unlock_protective_stop"),
    ("Close Safety Popup",      "close_safety_popup"),
    ("Enable Robot",            "enable_robot"),
    ("Restart Safety",          "restart_safety"),
    ("Power On",                "power_on"),
    ("Release Brakes",          "brake_release"),
    ("Stop Program",            "stop"),
]


def classify_safety(safety_mode: str) -> str:
    """Map a raw dashboard safetymode string to a normalized token.

    Robust to the format variations UR firmware returns ("NORMAL",
    "Safetymode: PROTECTIVE_STOP", a bare code, etc.) via substring match.
    """
    s = (safety_mode or "").upper()
    if "EMERGENCY" in s:
        return "emergency"
    if "VIOLATION" in s or "FAULT" in s:
        return "fault"
    if "PROTECTIVE" in s:
        return "protective"
    if "SAFEGUARD" in s:
        return "safeguard"
    if "RECOVERY" in s:
        return "recovery"
    if "REDUCED" in s:
        return "reduced"
    if "NORMAL" in s:
        return "normal"
    return "unknown"


FAULT_TOKENS = ("protective", "safeguard", "emergency", "fault", "recovery")


def is_fault(safety_mode: str) -> bool:
    """True when the safety mode is a recoverable fault (not NORMAL/REDUCED)."""
    return classify_safety(safety_mode) in FAULT_TOKENS


def classify_robot(robot_mode: str) -> str:
    """Normalize the dashboard robotmode string."""
    s = (robot_mode or "").upper()
    if "RUNNING" in s:
        return "running"
    if "IDLE" in s:
        return "idle"
    if "POWER_OFF" in s or "POWEROFF" in s:
        return "power_off"
    if "POWER_ON" in s or "POWERON" in s:
        return "power_on"
    if "BOOTING" in s:
        return "booting"
    if "BACKDRIVE" in s:
        return "backdrive"
    return "unknown"


# Recommended next command per safety / robot state -- only used to ACCENT
# the suggested button; every command stays available (explicit control).
def _recommended(safety_tok: str, robot_tok: str) -> str:
    if safety_tok == "protective":
        return "unlock_protective_stop"
    if safety_tok == "safeguard":
        return "close_safety_popup"
    if safety_tok == "emergency":
        return "close_safety_popup"
    if safety_tok == "fault":
        return "restart_safety"
    if robot_tok in ("power_off", "idle", "power_on") and \
            safety_tok in ("normal", "reduced", "unknown"):
        # Powered down or braked but otherwise healthy -> one-tap enable.
        return "enable_robot"
    return ""


# Plain-language description of the situation + what the operator should do.
def _describe(safety_tok: str, robot_tok: str) -> str:
    if safety_tok == "protective":
        return ("Protective stop: the arm hit a safety limit (a joint, speed, "
                "or force limit, or a self-collision). Wait about 5 seconds, "
                "then release the protective stop.")
    if safety_tok == "safeguard":
        return ("Safeguard stop: a safety input is open. Restore it, then "
                "close the safety popup.")
    if safety_tok == "emergency":
        return ("Emergency stop active. Release the physical E-stop button "
                "first, then close the safety popup and power the arm back on.")
    if safety_tok == "fault":
        return ("Safety fault / violation. Restart safety, then power on and "
                "release the brakes.")
    if robot_tok == "power_off":
        return "The arm is powered off. Tap Enable Robot to power on and release the brakes."
    if robot_tok in ("idle", "power_on"):
        return "The arm is powered but the brakes are engaged. Tap Enable Robot to release them."
    if safety_tok in ("normal", "reduced") and robot_tok == "running":
        return "Robot is normal and ready."
    return "Review the robot state below and choose the appropriate action."


class RecoveryPanel(QWidget):
    """Full-screen fault-recovery overlay with explicit dashboard controls."""

    recover_requested = pyqtSignal(str)   # dashboard method name
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("recoveryScrim")
        # The scrim paints its own translucent fill via paintEvent (QPainter
        # honours alpha where QSS rgba does not), so it dims the frozen UI
        # behind the recovery card.
        self._buttons: dict[str, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(S_32, S_32, S_32, S_32)
        outer.addStretch(1)

        # Centered recovery card.
        self._card = QFrame()
        self._card.setObjectName("recoveryCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(self._card, stretch=6)
        card_row.addStretch(1)
        outer.addLayout(card_row, stretch=0)
        outer.addStretch(1)

        col = QVBoxLayout(self._card)
        col.setContentsMargins(S_32, S_24, S_32, S_24)
        col.setSpacing(S_16)

        # Title.
        self._title = QLabel("Robot Recovery")
        tf = QFont()
        tf.setPixelSize(F_TITLE)
        tf.setWeight(QFont.Weight.Bold)
        self._title.setFont(tf)
        col.addWidget(self._title)

        # Live status line: Safety + Robot mode.
        self._status = QLabel("Safety: --    Robot: --")
        sf = QFont()
        sf.setPixelSize(F_SUBHEAD)
        sf.setWeight(QFont.Weight.Bold)
        self._status.setFont(sf)
        col.addWidget(self._status)

        # Plain-language description / instruction.
        self._desc = QLabel("")
        df = QFont()
        df.setPixelSize(F_BODY)
        self._desc.setFont(df)
        self._desc.setWordWrap(True)
        col.addWidget(self._desc)

        # Command buttons -- 2-column grid of large touch targets.
        grid = QGridLayout()
        grid.setSpacing(S_12)
        for idx, (label, method) in enumerate(_COMMANDS):
            btn = QPushButton(label)
            btn.setMinimumHeight(BUTTON_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, m=method: self.recover_requested.emit(m)
            )
            self._buttons[method] = btn
            grid.addWidget(btn, idx // 2, idx % 2)
        col.addLayout(grid)

        # Footer: a transient note (last command result) + Close.
        footer = QHBoxLayout()
        footer.setSpacing(S_12)
        self._note = QLabel("")
        nf = QFont()
        nf.setPixelSize(F_SMALL)
        self._note.setFont(nf)
        self._note.setWordWrap(True)
        footer.addWidget(self._note, stretch=1)

        self._close_btn = QPushButton("Close")
        self._close_btn.setMinimumHeight(BUTTON_H)
        self._close_btn.setMinimumWidth(140)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_requested)
        footer.addWidget(self._close_btn)
        col.addLayout(footer)

        self._safety_tok = "unknown"
        self.apply_theme()

    # ------------------------------------------------------------------
    # Painting -- translucent scrim over the frozen UI
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        # QPainter honours alpha (unlike QSS rgba); dark scrim in both themes.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 168))
        super().paintEvent(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, safety_mode: str, robot_mode: str, note: str = "") -> None:
        """Refresh the readout, description, and recommended-action accent."""
        safety_tok = classify_safety(safety_mode)
        robot_tok = classify_robot(robot_mode)
        self._safety_tok = safety_tok

        safety_txt = (safety_mode or "--").replace("Safetymode:", "").strip() or "--"
        robot_txt = (robot_mode or "--").replace("Robotmode:", "").strip() or "--"
        self._status.setText(f"Safety:  {safety_txt}     Robot:  {robot_txt}")

        # Status colour by severity.
        if safety_tok in ("emergency", "fault"):
            color = theme_v2.ERROR
        elif safety_tok in ("protective", "safeguard", "recovery", "unknown"):
            color = theme_v2.WARN
        else:
            color = theme_v2.SUCCESS
        self._status.setStyleSheet(
            f"QLabel {{ color: {color}; background-color: transparent; }}"
        )

        self._desc.setText(_describe(safety_tok, robot_tok))
        if note:
            self.set_note(note)

        # Accent the recommended button; others stay secondary but enabled.
        recommended = _recommended(safety_tok, robot_tok)
        self._restyle_buttons(recommended)

    def set_note(self, text: str) -> None:
        """Show a transient note (e.g. the result of the last command)."""
        self._note.setText(text)
        self._note.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; }}"
        )

    def apply_theme(self) -> None:
        """Rebuild stylesheets from the current theme palette."""
        self._card.setStyleSheet(
            f"QFrame#recoveryCard {{"
            f" background-color: {theme_v2.SURFACE};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-top: 4px solid {theme_v2.WARN};"
            f" border-radius: {R_LG}px;"
            f"}}"
        )
        self._title.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT}; background-color: transparent; }}"
        )
        self._desc.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; }}"
        )
        self._close_btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        # Re-apply the status colour + button accents for the current state.
        self._note.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; }}"
        )
        self._restyle_buttons(_recommended(self._safety_tok, "unknown"))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _restyle_buttons(self, recommended: str) -> None:
        for method, btn in self._buttons.items():
            if method == recommended:
                btn.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)
            elif method == "stop":
                btn.setStyleSheet(theme_v2.DANGER_BUTTON_QSS)
            else:
                btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
