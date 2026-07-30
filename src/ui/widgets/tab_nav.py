"""tab_nav.py - Horizontal tab-navigation strip for the UR10 jog control UI.

Author: jsecco (R)

Three tabs (Jog · Demos · Settings) with accent-underline active state.
Each tab is a checkable QPushButton inside an exclusive QButtonGroup so
exactly one tab is active at all times.

Usage::

    from ui.widgets.tab_nav import TabNav
    nav = TabNav(["Jog", "Demos", "Settings"], parent=self)
    nav.tab_changed.connect(self._on_tab_changed)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ui import theme_v2
from ui.theme_v2 import F_SUBHEAD


# ---------------------------------------------------------------------------
# QSS for the tab-strip buttons
# ---------------------------------------------------------------------------
# Inactive  : TEXT_MUTED text, SURFACE background, no underline
# Hover     : TEXT text, SURFACE_HI background, BORDER underline (3 px)
# Active    : ACCENT text, BG background, ACCENT underline (3 px)
# Pressed   : same as active
# Built per call so a live theme switch is picked up.
# ---------------------------------------------------------------------------
def _tab_button_qss() -> str:
    return (
        f"QPushButton {{"
        f" background-color: {theme_v2.SURFACE};"
        f" color: {theme_v2.TEXT_MUTED};"
        f" border: none;"
        f" border-bottom: 3px solid transparent;"
        f" min-height: 64px;"
        f" font-size: {F_SUBHEAD}px;"
        f" font-weight: 600;"
        f" padding: 0 24px;"
        f"}}"
        f"QPushButton:hover {{"
        f" background-color: {theme_v2.SURFACE_HI};"
        f" color: {theme_v2.TEXT};"
        f" border-bottom: 3px solid {theme_v2.BORDER};"
        f"}}"
        f"QPushButton:checked {{"
        f" background-color: {theme_v2.BG};"
        f" color: {theme_v2.ACCENT};"
        f" border-bottom: 3px solid {theme_v2.ACCENT};"
        f" font-weight: 700;"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {theme_v2.BG};"
        f" color: {theme_v2.ACCENT};"
        f" border-bottom: 3px solid {theme_v2.ACCENT};"
        f"}}"
    )


# Widget-level QSS: bottom border so the active underline visually contrasts.
def _widget_qss() -> str:
    return (
        f"QWidget#tabNav {{"
        f" background-color: {theme_v2.SURFACE};"
        f" border-bottom: 1px solid {theme_v2.BORDER};"
        f"}}"
    )


class TabNav(QWidget):
    """Horizontal tab strip with accent-underline active state.

    Each tab is a QPushButton with checkable=True, member of a QButtonGroup
    so exactly one is active at a time.
    """

    tab_changed = pyqtSignal(str)  # emitted with tab name when a different tab is selected

    def __init__(self, tabs: list[str], parent: QWidget | None = None) -> None:
        """tabs: ordered list of tab names, e.g. ['Jog', 'Demos', 'Settings']."""
        super().__init__(parent)
        self.setObjectName("tabNav")

        self._tabs: list[str] = list(tabs)
        self._buttons: dict[str, QPushButton] = {}

        # Exclusive button group — exactly one checked at a time
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for name in self._tabs:
            btn = QPushButton(name, self)
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(64)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            self._buttons[name] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)

        # Activate first tab silently (no signal at init)
        if self._tabs:
            self._buttons[self._tabs[0]].setChecked(True)

        # Connect after initial state is set
        self._group.buttonClicked.connect(self._on_button_clicked)

        # Apply all theme-dependent styling.
        self.apply_theme()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette."""
        self.setStyleSheet(_widget_qss())
        tab_qss = _tab_button_qss()
        for btn in self._buttons.values():
            btn.setStyleSheet(tab_qss)

    # ------------------------------------------------------------------
    # Internal slot
    # ------------------------------------------------------------------

    def _on_button_clicked(self, btn: QPushButton) -> None:
        """Emit tab_changed when a button in the group is clicked."""
        name = btn.text()
        self.tab_changed.emit(name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, name: str) -> None:
        """Programmatically switch to the named tab without emitting tab_changed."""
        btn = self._buttons.get(name)
        if btn is None:
            raise ValueError(f"Unknown tab: {name!r}. Available: {self._tabs}")
        self._group.blockSignals(True)
        btn.setChecked(True)
        self._group.blockSignals(False)

    def active(self) -> str:
        """Return the name of the currently active tab."""
        checked = self._group.checkedButton()
        if checked is None:
            return ""
        return checked.text()
