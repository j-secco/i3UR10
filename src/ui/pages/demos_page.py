"""demos_page.py — Categorised scrollable card grid of all available demos.

Author: jsecco (R)
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QLabel, QFrame, QSizePolicy, QScroller,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from ui import theme_v2
from ui.theme_v2 import (
    CAT_SHOWCASE, CAT_DYNAMIC, CAT_INDUSTRIAL, CAT_ENGINEERING,
    F_HEADING, F_BODY, F_SMALL,
    S_4, S_8, S_12, S_16, S_24, S_32,
    R_MD, R_LG,
)
from ui.widgets.demo_card import DemoCard

# ---------------------------------------------------------------------------
# Demo inventory — order within each category is significant
# ---------------------------------------------------------------------------

DEMOS: list[tuple[str, str, str]] = [
    # Showcase (purple stripe)
    ("Demo",
     "Run a preset joint-space path in a loop. Connect, save home, then Start.",
     "Showcase"),
    ("Wave & Greet",
     "Turn toward the audience, raise the arm, and wave. Showcase demo for visitors.",
     "Showcase"),
    ("Bow",
     "Theatrical ceremonial bow with a held apex pose. Slow and deliberate.",
     "Showcase"),
    ("Pendulum",
     "Hypnotic side-to-side swing with natural wind-down. Continuous flow.",
     "Showcase"),
    # Dynamic (amber stripe)
    ("Sprint",
     "Fast lateral back-and-forth with rapid acceleration. Athletic and punchy.",
     "Dynamic"),
    ("Plunge",
     "Slow controlled descents contrasted with snap-back rises. ~9× speed contrast.",
     "Dynamic"),
    ("Reach",
     "Long extended sweeps showing full workspace. Big sideways arcs with arm extended.",
     "Dynamic"),
    # Industrial (green stripe)
    ("Industrial",
     "Pick-and-place pantomime: approach, descend, grasp, transport, release, retreat.",
     "Industrial"),
    ("Sorting",
     "Pick from intake, sort into 3 different bins per cycle. Methodical pick-and-place.",
     "Industrial"),
    ("Juggle",
     "Rapid alternation between two stations with brief touches — juggling rhythm.",
     "Industrial"),
    ("Stacking",
     "Build a 3-piece tower: each successive piece placed at a higher level.",
     "Industrial"),
    # Engineering (blue stripe)
    ("Technical",
     "Per-axis capability tour: J1 through J6 individually, then a coordinated finale.",
     "Engineering"),
    # Future (gray / disabled)
    ("Record & Replay",
     "Record your movements, then replay them (coming later).",
     "Future"),
]

# Category display order and their accent colours
_CATEGORY_ORDER: list[str] = [
    "Showcase", "Dynamic", "Industrial", "Engineering", "Future",
]

def _category_colors() -> dict:
    """Map a category to its accent color, built from the active theme.

    The four real categories use theme-independent constants; 'Future' uses
    BORDER, which is theme-dependent.
    """
    return {
        "Showcase":    CAT_SHOWCASE,
        "Dynamic":     CAT_DYNAMIC,
        "Industrial":  CAT_INDUSTRIAL,
        "Engineering": CAT_ENGINEERING,
        "Future":      theme_v2.BORDER,
    }


# ---------------------------------------------------------------------------
# DemosPage
# ---------------------------------------------------------------------------

class DemosPage(QWidget):
    """Categorized scrollable card grid of all available demos.

    Cards are grouped under category headings. Tapping a card emits demo_selected
    with the demo's name. The main window listens and navigates to the runner page.
    """

    demo_selected = pyqtSignal(str)  # demo name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("demosPage")

        # Internal card registry: demo_name → DemoCard
        self._cards: dict[str, DemoCard] = {}
        # Category-heading dot QLabels keyed by category name, plus the
        # heading text labels -- stored so apply_theme() can restyle them.
        self._category_dots: dict[str, QLabel] = {}
        self._category_headings: list[QLabel] = []

        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(S_24, S_24, S_24, S_24)
        self._outer_layout.setSpacing(S_16)

        # --- Running-demo banner (hidden by default) ----------------------
        self._banner = self._build_banner()
        self._banner.hide()
        self._outer_layout.addWidget(self._banner)

        # --- Scroll area --------------------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Kinetic touch scrolling
        QScroller.grabGesture(
            self._scroll.viewport(),
            QScroller.ScrollerGestureType.LeftMouseButtonGesture,
        )

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("scrollContent")
        self._content_layout = QVBoxLayout(self._scroll_content)
        self._content_layout.setContentsMargins(0, 0, 0, S_16)
        self._content_layout.setSpacing(S_24)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._build_card_grid()

        self._content_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)
        self._outer_layout.addWidget(self._scroll, stretch=1)

        # Disable Future cards at construction
        for name, _, category in DEMOS:
            if category == "Future":
                self.set_card_enabled(name, False)

        # Apply all theme-dependent styling.
        self.apply_theme()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette.

        Propagates the theme switch to all DemoCards and restyles the
        category-heading dots and labels.
        """
        self.setStyleSheet(
            f"QWidget#demosPage {{ background-color: {theme_v2.BG}; }}"
        )
        self._scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
            "QScrollBar:vertical { width: 0px; }"
        )
        self._scroll_content.setStyleSheet(
            "QWidget#scrollContent { background-color: transparent; }"
        )

        # Running-demo banner.
        self._banner.setStyleSheet(
            f"QWidget#runningBanner {{"
            f" background-color: {theme_v2.SURFACE_HI};"
            f" border: 1px solid {theme_v2.ACCENT};"
            f" border-radius: {R_MD}px;"
            f"}}"
        )
        self._banner_label.setStyleSheet(
            f"QLabel#bannerLabel {{ color: {theme_v2.ACCENT_HI};"
            f" background: transparent; border: none; }}"
        )

        # Category-heading dots + heading labels.
        colors = _category_colors()
        for category, dot in self._category_dots.items():
            color = colors.get(category, theme_v2.BORDER)
            dot.setStyleSheet(
                f"QLabel {{ background-color: {color};"
                f" border-radius: 6px; border: none; }}"
            )
        for heading in self._category_headings:
            heading.setStyleSheet(
                f"QLabel {{ color: {theme_v2.TEXT};"
                f" background: transparent; border: none; }}"
            )

        # Propagate to every card.
        for card in self._cards.values():
            card.apply_theme()

    # ------------------------------------------------------------------
    # Banner helpers
    # ------------------------------------------------------------------

    def _build_banner(self) -> QWidget:
        banner = QWidget()
        banner.setObjectName("runningBanner")
        banner.setMinimumHeight(48)
        banner.setCursor(Qt.CursorShape.PointingHandCursor)
        # Styling applied via apply_theme().

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(S_16, S_8, S_16, S_8)

        self._banner_label = QLabel()
        self._banner_label.setObjectName("bannerLabel")
        font = QFont()
        font.setPixelSize(F_BODY)
        font.setWeight(QFont.Weight.Medium)
        self._banner_label.setFont(font)
        layout.addWidget(self._banner_label)
        layout.addStretch()

        self._running_name: str | None = None

        # Click on the entire banner widget — install on content child too
        banner.mousePressEvent = self._banner_clicked  # type: ignore[method-assign]
        self._banner_label.mousePressEvent = self._banner_clicked  # type: ignore[method-assign]

        return banner

    def _banner_clicked(self, event) -> None:  # type: ignore[override]
        if self._running_name:
            self.demo_selected.emit(self._running_name)

    # ------------------------------------------------------------------
    # Card grid construction
    # ------------------------------------------------------------------

    def _build_card_grid(self) -> None:
        # Group demos by category, preserving insertion order
        by_category: dict[str, list[tuple[str, str, str]]] = {c: [] for c in _CATEGORY_ORDER}
        for demo in DEMOS:
            cat = demo[2]
            by_category.setdefault(cat, []).append(demo)

        for category in _CATEGORY_ORDER:
            demos_in_cat = by_category.get(category, [])
            if not demos_in_cat:
                continue
            self._content_layout.addWidget(self._build_category_heading(category))
            self._content_layout.addLayout(self._build_category_grid(demos_in_cat))

    def _build_category_heading(self, category: str) -> QWidget:
        container = QWidget()
        container.setStyleSheet("QWidget { background: transparent; }")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(S_12)

        # 12×12 accent dot -- stored so apply_theme() can restyle it.
        dot = QLabel()
        dot.setFixedSize(12, 12)
        row.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._category_dots[category] = dot

        heading = QLabel(category.upper())
        font = QFont()
        font.setPixelSize(F_HEADING)
        font.setWeight(QFont.Weight.Bold)
        heading.setFont(font)
        row.addWidget(heading, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        self._category_headings.append(heading)

        return container

    def _build_category_grid(self, demos: list[tuple[str, str, str]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(S_16)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for idx, (name, description, category) in enumerate(demos):
            card = DemoCard(name, description, category)
            card.clicked.connect(self.demo_selected)
            self._cards[name] = card
            row, col = divmod(idx, 2)
            grid.addWidget(card, row, col)

        return grid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_running_demo(self, name: str | None) -> None:
        """Show/hide the 'running demo' banner at the top of the page.

        If *name* is not None, displays 'Running: <name> — tap to return to runner'
        and enables the banner. Pass None to hide it.
        """
        self._running_name = name
        if name:
            self._banner_label.setText(f"Running: {name} — tap to return to runner")
            self._banner.show()
        else:
            self._banner.hide()

    def set_card_enabled(self, demo_name: str, enabled: bool) -> None:
        """Enable or disable a specific card by demo name.

        Disabled cards remain visible but appear muted and do not emit clicked.
        Used to grey out placeholder demos such as 'Record & Replay'.
        """
        card = self._cards.get(demo_name)
        if card is not None:
            card.set_enabled_state(enabled)
