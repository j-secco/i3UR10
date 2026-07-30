"""demo_card.py — Clickable demo card widget for the UR10 jog control UI.

Author: jsecco (R)
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from ui import theme_v2
from ui.theme_v2 import (
    CAT_SHOWCASE, CAT_DYNAMIC, CAT_INDUSTRIAL, CAT_ENGINEERING,
    F_HEADING, F_BODY, F_SMALL, F_MICRO, R_SM, R_LG, S_4, S_8, S_16, CARD_MIN_H,
)


def _category_color(category: str) -> str:
    """Resolve a category name to its accent color.

    The four real category colors are theme-independent constants; the
    'future' placeholder uses TEXT_DIM and unknown values use BORDER, both
    of which are theme-dependent and read live from theme_v2.
    """
    category_colors = {
        "showcase":    CAT_SHOWCASE,
        "dynamic":     CAT_DYNAMIC,
        "industrial":  CAT_INDUSTRIAL,
        "engineering": CAT_ENGINEERING,
        "future":      theme_v2.TEXT_DIM,   # placeholder category
    }
    return category_colors.get(category.lower(), theme_v2.BORDER)


class DemoCard(QWidget):
    """Clickable card representing one demo.

    Visual: surface bg, rounded border, a category chip at the top in the
    category color, the demo name + description, and a 'Run' affordance at the
    bottom. Hover shifts the border to ACCENT; pressed tints the background.
    The whole card is the touch target — no nested buttons.
    """

    clicked = pyqtSignal(str)  # emitted with the demo's name when the card is tapped

    def __init__(self, name: str, description: str, category: str, parent=None):
        """category in {'Showcase', 'Dynamic', 'Industrial', 'Engineering', 'Future'}."""
        super().__init__(parent)
        self._name = name
        self._category = category
        self._accent = _category_color(category)
        self._enabled = True

        self.setObjectName("demoCard")
        # A plain QWidget does not paint a stylesheet background/border unless
        # WA_StyledBackground is set (QFrame does it automatically).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(360, 120)   # floor only; the card hugs its content
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("hover", False)
        self.setProperty("pressed", False)
        self.setProperty("cardEnabled", True)

        self._build_layout(name, description)
        self.apply_theme()

    def _build_layout(self, name: str, description: str) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(S_16, S_16, S_16, S_16)
        col.setSpacing(S_8)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Category chip — outline pill in the category color (top-left).
        self._chip = QLabel(self._category.upper())
        self._chip.setObjectName("cardChip")
        cf = QFont()
        cf.setPixelSize(F_MICRO)
        cf.setWeight(QFont.Weight.Bold)
        self._chip.setFont(cf)
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.addWidget(self._chip)
        chip_row.addStretch()
        col.addLayout(chip_row)

        # Demo name.
        self._name_label = QLabel(name)
        self._name_label.setObjectName("cardName")
        nf = QFont()
        nf.setPixelSize(F_HEADING)
        nf.setWeight(QFont.Weight.Bold)
        self._name_label.setFont(nf)
        self._name_label.setWordWrap(False)
        col.addWidget(self._name_label)

        # Description.
        self._desc_label = QLabel(description)
        self._desc_label.setObjectName("cardDesc")
        df = QFont()
        df.setPixelSize(F_BODY)
        self._desc_label.setFont(df)
        self._desc_label.setWordWrap(True)
        col.addWidget(self._desc_label)

        # Run affordance — bottom-right; the whole card is the tap target.
        self._run_label = QLabel("Run  ▶")
        self._run_label.setObjectName("cardRun")
        rf = QFont()
        rf.setPixelSize(F_SMALL)
        rf.setWeight(QFont.Weight.Bold)
        self._run_label.setFont(rf)
        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        run_row.addStretch()
        run_row.addWidget(self._run_label)
        col.addLayout(run_row)
        col.addStretch()   # leftover height (grid row-equalisation) sits below Run

    def apply_theme(self) -> None:
        """Re-apply the card stylesheet from the current theme_v2 palette.

        Recomputes the category accent (the 'future'/unknown fallbacks are
        theme-dependent) before re-styling.
        """
        self._accent = _category_color(self._category)
        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        chip = self._accent if self._enabled else theme_v2.TEXT_DIM
        self.setStyleSheet(
            f"QWidget#demoCard {{"
            f" background-color: {theme_v2.SURFACE};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_LG}px; }}"
            f"QWidget#demoCard[hover=\"true\"] {{ border-color: {theme_v2.ACCENT}; }}"
            f"QWidget#demoCard[pressed=\"true\"] {{ background-color: {theme_v2.SURFACE_HI}; }}"
            f"QLabel#cardChip {{"
            f" color: {chip}; border: 1px solid {chip}; border-radius: {R_SM}px;"
            f" padding: {S_4}px {S_8}px; background-color: transparent;"
            f" letter-spacing: 1px; }}"
            f"QLabel#cardName {{ color: {theme_v2.TEXT};"
            f" background-color: transparent; border: none; }}"
            f"QLabel#cardDesc {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; border: none; }}"
            f"QLabel#cardRun {{ color: {theme_v2.ACCENT_HI};"
            f" background-color: transparent; border: none; }}"
            f"QWidget#demoCard[cardEnabled=\"false\"] QLabel#cardName {{ color: {theme_v2.TEXT_DIM}; }}"
            f"QWidget#demoCard[cardEnabled=\"false\"] QLabel#cardDesc {{ color: {theme_v2.TEXT_DIM}; }}"
            f"QWidget#demoCard[cardEnabled=\"false\"] QLabel#cardRun {{ color: {theme_v2.TEXT_DIM}; }}"
        )

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_enabled_state(self, enabled: bool) -> None:
        """Disabled cards are visually muted and don't emit clicked.
        Used for placeholder cards (e.g. Record & Replay)."""
        self._enabled = enabled
        self.setProperty("cardEnabled", enabled)
        self._run_label.setText("Run  ▶" if enabled else "Coming soon")
        self._apply_stylesheet()
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self._refresh_style()

    def mousePressEvent(self, event) -> None:
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.setProperty("pressed", True)
            self._refresh_style()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.setProperty("pressed", False)
            self._refresh_style()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit(self._name)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        if self._enabled:
            self.setProperty("hover", True)
            self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hover", False)
        self.setProperty("pressed", False)
        self._refresh_style()
        super().leaveEvent(event)
