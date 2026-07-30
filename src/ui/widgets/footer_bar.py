"""footer_bar.py - Persistent bottom status bar for the UR10 jog control UI.

Author: jsecco

Always visible at the bottom of every screen (min 40 px tall).
Contains a log-activity dot, a main status label, and an optional
right-aligned secondary label.

Usage:
    from ui.widgets.footer_bar import FooterBar
    footer = FooterBar(parent=self)
    footer.set_status("Connected to 192.168.10.24", "success")
    footer.flash_log_indicator()
    footer.set_secondary("12 events")
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui import theme_v2
from ui.theme_v2 import F_BODY, F_SMALL, S_8, S_16


# ---------------------------------------------------------------------------
# Level -> text colour mapping (built from the active theme)
# ---------------------------------------------------------------------------

def _level_colors() -> dict:
    return {
        "info":    theme_v2.TEXT,
        "warn":    theme_v2.WARN,
        "error":   theme_v2.ERROR,
        "success": theme_v2.SUCCESS,
    }


# QSS snippets for the log-dot states, built from the active theme.
def _dot_dim_qss() -> str:
    return (
        f"QLabel#logDot {{"
        f" background-color: {theme_v2.TEXT_DIM};"
        f" border-radius: 6px;"
        f"}}"
    )


def _dot_active_qss() -> str:
    return (
        f"QLabel#logDot {{"
        f" background-color: {theme_v2.ACCENT};"
        f" border-radius: 6px;"
        f"}}"
    )


class FooterBar(QWidget):
    """Persistent bottom bar: status text + log activity indicator."""

    def __init__(self, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)

        self.setObjectName("footerBar")
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Current status text + level -- kept so apply_theme() can re-style the
        # status label for the live level rather than a hardcoded one.
        self._status_text: str = "Ready"
        self._status_level: str = "info"
        # Whether the log dot is currently in its active (pulsing) state.
        self._dot_active: bool = False

        # --- Log activity dot -------------------------------------------
        self._dot = QLabel(self)
        self._dot.setObjectName("logDot")
        self._dot.setFixedSize(12, 12)
        self._dot.setToolTip("Log activity")

        # Timer used to revert the dot back to dim after a pulse.
        # QTimer.singleShot is non-blocking; stop()+start() resets the window.
        self._dot_timer = QTimer(self)
        self._dot_timer.setSingleShot(True)
        self._dot_timer.timeout.connect(self._revert_dot)

        # --- Main status label ------------------------------------------
        self._status_label = QLabel("Ready", self)
        self._status_label.setObjectName("statusLabel")
        self._status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        # --- Secondary / right-aligned label ----------------------------
        self._secondary_label = QLabel("", self)
        self._secondary_label.setObjectName("secondaryLabel")
        self._secondary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        # --- Layout -----------------------------------------------------
        layout = QHBoxLayout(self)
        layout.setContentsMargins(S_16, S_8, S_16, S_8)
        layout.setSpacing(S_8)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._secondary_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setLayout(layout)

        # Apply all theme-dependent styling.
        self.apply_theme()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette.

        Restyles the status label for the CURRENT level and the log dot for
        its CURRENT active/dim state.
        """
        self.setStyleSheet(theme_v2.FOOTER_BAR_QSS)
        self._dot.setStyleSheet(
            _dot_active_qss() if self._dot_active else _dot_dim_qss()
        )
        self._secondary_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED}; font-size: {F_SMALL}px;"
            f" background-color: transparent; }}"
        )
        self._apply_status_style()

    def _apply_status_style(self) -> None:
        """Style the status label for the current level."""
        color = _level_colors().get(self._status_level, theme_v2.TEXT)
        self._status_label.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: {F_BODY}px;"
            f" background-color: transparent; }}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, text: str, level: str = "info") -> None:
        """level in {'info', 'warn', 'error', 'success'} — drives text color.
        Sets the main status label text."""
        self._status_text = text
        self._status_level = level
        self._status_label.setText(text)
        self._apply_status_style()

    def flash_log_indicator(self) -> None:
        """Briefly pulse a tiny dot to indicate new log activity.
        Animation: dot fades in over 100ms then back over 400ms.
        Should be safe to call repeatedly (each call resets the pulse).

        Implementation: QTimer + stylesheet swap. The dot switches to ACCENT
        immediately; QTimer.singleShot reverts it to dim after 500 ms.
        Calling stop() before start() on each invocation safely resets the
        window so rapid calls extend rather than stack.
        """
        self._dot_active = True
        self._dot.setStyleSheet(_dot_active_qss())
        self._dot_timer.stop()
        self._dot_timer.start(500)

    def set_secondary(self, text: str) -> None:
        """Optional right-aligned secondary text (e.g. timestamps, counters)."""
        self._secondary_label.setText(text)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _revert_dot(self) -> None:
        """Restore the log dot to its dim/idle appearance."""
        self._dot_active = False
        self._dot.setStyleSheet(_dot_dim_qss())
