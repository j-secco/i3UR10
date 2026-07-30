"""Persistent top header bar for the redesigned UR10 jog control UI.

Title (left) + connection badge (center-right) + e-stop button (far right).
Always visible; ≥80 px tall.

Author: jsecco (R)
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from ui import theme_v2
from ui.theme_v2 import (
    BUTTON_H, ESTOP_H,
    F_TITLE, F_BODY, F_SMALL, S_8, S_12, S_16, S_24,
)


def _badge_qss_by_state() -> dict:
    """Map a connection state to its badge QSS, built from the active theme."""
    return {
        "idle":       theme_v2.BADGE_NEUTRAL_QSS,
        "connecting": theme_v2.BADGE_WARN_QSS,
        "connected":  theme_v2.BADGE_SUCCESS_QSS,
        "error":      theme_v2.BADGE_ERROR_QSS,
    }


# Text labels are theme-independent.
_BADGE_TEXT_BY_STATE = {
    "idle":       "○  Idle",
    "connecting": "◌  Connecting…",
    "connected":  "●  Connected",
    "error":      "✕  Error",
}


class HeaderBar(QWidget):
    """Persistent top bar: title + connection badge + e-stop button."""

    estop_clicked = pyqtSignal()
    exit_clicked = pyqtSignal()
    recover_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("headerBar")
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Current connection state -- kept so apply_theme() can re-style the
        # badge for the live state rather than a hardcoded idle palette.
        self._connection_state: str = "idle"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(S_24, S_12, S_24, S_12)
        layout.setSpacing(S_16)

        # Title (left)
        self._title_label = QLabel("UR10 Control")
        layout.addWidget(self._title_label)

        # Exit button -- quiet outline button on the left, kept well clear of
        # the E-Stop on the far right so it cannot be tapped by accident.
        self._exit_button = QPushButton("✕  Exit")
        self._exit_button.setObjectName("exitButton")
        self._exit_button.setMinimumSize(104, 44)
        self._exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._exit_button.clicked.connect(self.exit_clicked.emit)
        layout.addWidget(self._exit_button)

        layout.addStretch(1)

        # Recovery button -- hidden until the robot reports a fault. Warning
        # outline so it reads as "attention needed" without competing with the
        # E-Stop. Tapping it reopens the recovery panel.
        self._recover_button = QPushButton("⚠  Recovery")
        self._recover_button.setObjectName("recoverButton")
        self._recover_button.setMinimumSize(150, 44)
        self._recover_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recover_button.clicked.connect(self.recover_clicked.emit)
        self._recover_button.hide()
        layout.addWidget(self._recover_button)

        # Connection + robot state badges (center-right)
        self._connection_badge = QLabel(_BADGE_TEXT_BY_STATE["idle"])
        self._connection_badge.setObjectName("connectionBadge")
        self._connection_badge.setMinimumHeight(44)
        self._connection_badge.setMinimumWidth(150)
        self._connection_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._connection_badge)

        self._robot_state_label = QLabel("")
        self._robot_state_label.setObjectName("robotStateLabel")
        self._robot_state_label.hide()
        layout.addWidget(self._robot_state_label)

        # E-stop (far right)
        self._estop_button = QPushButton("EMERGENCY STOP")
        self._estop_button.setObjectName("estopButton")
        self._estop_button.setMinimumSize(220, ESTOP_H)
        self._estop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._estop_button.clicked.connect(self.estop_clicked.emit)
        layout.addWidget(self._estop_button)

        # Apply all theme-dependent styling.
        self.apply_theme()

    # ---- theming ------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette.

        Restyles the connection badge for the CURRENT connection state.
        """
        self.setStyleSheet(theme_v2.HEADER_BAR_QSS)

        self._title_label.setStyleSheet(
            f"color: {theme_v2.TEXT}; font-size: {F_TITLE}px;"
            f" font-weight: 700; background: transparent;"
        )

        self._exit_button.setStyleSheet(
            f"QPushButton#exitButton {{"
            f" background-color: transparent; color: {theme_v2.TEXT_MUTED};"
            f" border: 1px solid {theme_v2.BORDER}; border-radius: 8px;"
            f" padding: 0 {S_16}px; font-size: {F_BODY}px; font-weight: 600; }}"
            f"QPushButton#exitButton:hover {{ color: {theme_v2.TEXT};"
            f" border-color: {theme_v2.TEXT_MUTED}; }}"
            f"QPushButton#exitButton:pressed {{"
            f" background-color: {theme_v2.SURFACE}; }}"
        )

        self._robot_state_label.setStyleSheet(
            f"color: {theme_v2.TEXT_MUTED}; font-size: {F_SMALL}px;"
            f" background: transparent; padding: 0 {S_8}px;"
        )

        self._estop_button.setStyleSheet(theme_v2.ESTOP_BUTTON_QSS)

        self._recover_button.setStyleSheet(
            f"QPushButton#recoverButton {{"
            f" background-color: transparent; color: {theme_v2.WARN};"
            f" border: 2px solid {theme_v2.WARN}; border-radius: 8px;"
            f" padding: 0 {S_16}px; font-size: {F_BODY}px; font-weight: 700; }}"
            f"QPushButton#recoverButton:hover {{"
            f" background-color: {theme_v2.WARN}; color: white; }}"
            f"QPushButton#recoverButton:pressed {{"
            f" background-color: {theme_v2.WARN}; color: white; }}"
        )

        # Re-style the connection badge for the live state.
        self._connection_badge.setStyleSheet(
            _badge_qss_by_state()[self._connection_state]
        )

    # ---- public API ---------------------------------------------------------

    def set_connection_state(self, state: str, detail: str = "") -> None:
        state = state if state in _BADGE_TEXT_BY_STATE else "idle"
        self._connection_state = state
        text = _BADGE_TEXT_BY_STATE[state]
        if detail:
            text = f"{text} · {detail}"
        self._connection_badge.setText(text)
        self._connection_badge.setStyleSheet(_badge_qss_by_state()[state])

    def set_recovery_available(self, available: bool) -> None:
        """Show or hide the Recovery button (shown only when the robot faults)."""
        self._recover_button.setVisible(bool(available))

    def set_robot_state(self, state: str) -> None:
        if state:
            self._robot_state_label.setText(state)
            self._robot_state_label.show()
        else:
            self._robot_state_label.clear()
            self._robot_state_label.hide()

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)
