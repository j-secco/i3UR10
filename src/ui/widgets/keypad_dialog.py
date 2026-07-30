"""keypad_dialog.py - On-screen numeric keypad for the UR10 jog control UI.

A large, touch-friendly modal numeric keypad for entering numbers (integer or
single-decimal) and dotted IPv4 addresses on a keyboard-less industrial
touchscreen.

Author: jsecco (R)
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLabel, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui import theme_v2
from ui.theme_v2 import (
    S_4, S_8, S_12, S_16, S_24, S_32,
    R_SM, R_MD, R_LG,
    F_DISPLAY, F_TITLE, F_HEADING, F_SUBHEAD, F_BODY, F_SMALL, F_MICRO,
    BUTTON_H,
)

# Minimum touch height for keypad keys and footer buttons.
_KEY_H = 72
_FOOTER_H = 64
_DIALOG_W = 440


class KeypadDialog(QDialog):
    """A large on-screen numeric keypad for touch entry.

    Construct fresh per use, call exec(), then read value(). On reject the
    original value is returned unchanged.
    """

    def __init__(
        self,
        parent,
        *,
        title: str,
        unit: str = "",
        value=0,
        decimals: int = 0,
        minimum=None,
        maximum=None,
        allow_sign: bool = False,
        ip_mode: bool = False,
    ):
        super().__init__(parent)

        self._title = title
        self._unit = unit
        self._decimals = int(decimals)
        self._minimum = minimum
        self._maximum = maximum
        self._allow_sign = bool(allow_sign)
        self._ip_mode = bool(ip_mode)

        # The original value -- returned unchanged on reject.
        self._original = value
        # The accepted result -- defaults to the original until Enter succeeds.
        self._result = value

        # Live entry string.
        self._entry = self._format_initial(value)

        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Minimal chrome -- a framed dialog without the OS title bar buttons.
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setFixedWidth(_DIALOG_W)

        # Read the theme palette ONCE -- the dialog is short-lived and built
        # fresh per use, so no live re-theme is needed.
        self._build_ui()
        self._update_display()
        self._center_on_parent()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _format_initial(self, value) -> str:
        """Render the constructor value into the initial entry string."""
        if self._ip_mode:
            return str(value)
        try:
            if self._decimals > 0:
                # Always show the decimals so the initial display matches
                # both the range hint and the settings-page field text.
                return f"{float(value):.{self._decimals}f}"
            return str(int(round(float(value))))
        except (TypeError, ValueError):
            return ""

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(S_24, S_24, S_24, S_24)
        root.setSpacing(S_16)

        # The dialog itself is the card frame.
        self.setStyleSheet(
            f"KeypadDialog {{"
            f" background-color: {theme_v2.SURFACE};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_LG}px;"
            f"}}"
        )

        # ---- Header ----
        self._title_label = QLabel(self._title)
        tf = QFont()
        tf.setPixelSize(F_SUBHEAD)
        tf.setWeight(QFont.Weight.Bold)
        self._title_label.setFont(tf)
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT};"
            f" background-color: transparent; }}"
        )
        root.addWidget(self._title_label)

        self._hint_label = QLabel(self._hint_text())
        hf = QFont()
        hf.setPixelSize(F_SMALL)
        self._hint_label.setFont(hf)
        self._hint_default_qss = (
            f"QLabel {{ color: {theme_v2.TEXT_MUTED};"
            f" background-color: transparent; }}"
        )
        self._hint_error_qss = (
            f"QLabel {{ color: {theme_v2.ERROR};"
            f" background-color: transparent; }}"
        )
        self._hint_label.setStyleSheet(self._hint_default_qss)
        root.addWidget(self._hint_label)

        # ---- Display box ----
        display = QFrame()
        display.setStyleSheet(
            f".QFrame {{"
            f" background-color: {theme_v2.SURFACE_HI};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_MD}px;"
            f"}}"
        )
        disp_h = QHBoxLayout(display)
        disp_h.setContentsMargins(S_16, S_12, S_16, S_12)
        disp_h.setSpacing(S_12)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setStyleSheet(self._clear_button_qss())
        self._clear_btn.setMinimumHeight(BUTTON_H)
        self._clear_btn.clicked.connect(self._on_clear)
        disp_h.addWidget(self._clear_btn)

        self._display_label = QLabel("")
        dlf = QFont()
        dlf.setPixelSize(F_TITLE)
        dlf.setWeight(QFont.Weight.Bold)
        self._display_label.setFont(dlf)
        self._display_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._display_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT};"
            f" background-color: transparent; }}"
        )
        disp_h.addWidget(self._display_label, stretch=1)
        root.addWidget(display)

        # ---- Keypad grid ----
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(S_8)

        key_qss = self._key_qss()
        for row, (a, b, c) in enumerate(
            (("7", "8", "9"), ("4", "5", "6"), ("1", "2", "3"))
        ):
            for col, digit in enumerate((a, b, c)):
                grid.addWidget(self._make_key(digit, key_qss), row, col)

        # Bottom row: [special] 0 [backspace].
        grid.addWidget(self._make_special_key(key_qss), 3, 0)
        grid.addWidget(self._make_key("0", key_qss), 3, 1)

        backspace = self._make_backspace_key(key_qss)
        grid.addWidget(backspace, 3, 2)

        root.addLayout(grid)

        # ---- Footer ----
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(S_12)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._cancel_btn.setMinimumHeight(_FOOTER_H)
        self._cancel_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._cancel_btn.clicked.connect(self.reject)

        self._enter_btn = QPushButton("Enter")
        self._enter_btn.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)
        self._enter_btn.setMinimumHeight(_FOOTER_H)
        self._enter_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._enter_btn.clicked.connect(self._on_enter)

        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._enter_btn)
        root.addLayout(footer)

    def _make_key(self, label: str, qss: str) -> QPushButton:
        """Build a standard digit key. Digits append to the entry."""
        btn = self._blank_key(qss)
        btn.setText(label)
        btn.clicked.connect(lambda: self._on_digit(label))
        return btn

    def _blank_key(self, qss: str) -> QPushButton:
        """Build an unconnected key button with the standard look + size."""
        btn = QPushButton("")
        kf = QFont()
        kf.setPixelSize(F_HEADING)
        kf.setWeight(QFont.Weight.Bold)
        btn.setFont(kf)
        btn.setStyleSheet(qss)
        btn.setMinimumHeight(_KEY_H)
        btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        return btn

    def _make_backspace_key(self, qss: str) -> QPushButton:
        btn = self._blank_key(qss)
        btn.setText("Del")
        btn.clicked.connect(self._on_backspace)
        return btn

    def _make_special_key(self, qss: str) -> QPushButton:
        """Build the bottom-left special key.

        '.' when decimals > 0 or ip_mode, '+/-' when allow_sign, otherwise a
        disabled blank key.
        """
        if self._decimals > 0 or self._ip_mode:
            btn = self._blank_key(qss)
            btn.setText(".")
            btn.clicked.connect(self._on_dot)
            return btn
        if self._allow_sign:
            btn = self._blank_key(qss)
            btn.setText("+/-")
            btn.clicked.connect(self._on_sign)
            return btn
        # Disabled blank placeholder key.
        btn = self._blank_key(qss)
        btn.setEnabled(False)
        return btn

    # ------------------------------------------------------------------
    # QSS builders (read once at construction)
    # ------------------------------------------------------------------

    def _key_qss(self) -> str:
        return (
            f"QPushButton {{"
            f" background-color: {theme_v2.SURFACE_HI};"
            f" color: {theme_v2.TEXT};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_MD}px;"
            f"}}"
            f"QPushButton:pressed {{"
            f" background-color: {theme_v2.ACCENT};"
            f" color: white;"
            f" border-color: {theme_v2.ACCENT};"
            f"}}"
            f"QPushButton:disabled {{"
            f" background-color: {theme_v2.SURFACE};"
            f" color: {theme_v2.TEXT_DIM};"
            f" border-color: {theme_v2.BORDER};"
            f"}}"
        )

    def _clear_button_qss(self) -> str:
        return (
            f"QPushButton {{"
            f" background-color: {theme_v2.SURFACE};"
            f" color: {theme_v2.TEXT_MUTED};"
            f" border: 1px solid {theme_v2.BORDER};"
            f" border-radius: {R_SM}px;"
            f" padding: 0 {S_16}px;"
            f" font-size: {F_SMALL}px;"
            f" font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{"
            f" background-color: {theme_v2.ACCENT};"
            f" color: white;"
            f" border-color: {theme_v2.ACCENT};"
            f"}}"
        )

    # ------------------------------------------------------------------
    # Hint / display text
    # ------------------------------------------------------------------

    def _hint_text(self) -> str:
        if self._ip_mode:
            return "0-255 per octet"
        lo = self._minimum
        hi = self._maximum
        if lo is None and hi is None:
            return self._unit.strip() or " "
        unit = f" {self._unit}" if self._unit else ""
        if self._decimals > 0:
            lo_s = f"{float(lo):.{self._decimals}f}" if lo is not None else "-"
            hi_s = f"{float(hi):.{self._decimals}f}" if hi is not None else "-"
        else:
            lo_s = str(int(lo)) if lo is not None else "-"
            hi_s = str(int(hi)) if hi is not None else "-"
        return f"{lo_s} - {hi_s}{unit}"

    def _update_display(self) -> None:
        """Refresh the display label with the live entry + unit."""
        text = self._entry if self._entry else "0"
        if self._unit and not self._ip_mode:
            text = f"{text} {self._unit}"
        self._display_label.setText(text)

    # ------------------------------------------------------------------
    # Key behaviour
    # ------------------------------------------------------------------

    def _on_digit(self, digit: str) -> None:
        self._entry += digit
        self._update_display()

    def _on_dot(self) -> None:
        if self._ip_mode:
            # Up to three dots; never leading, never doubled.
            if self._entry.count(".") >= 3:
                return
            if not self._entry or self._entry.endswith("."):
                return
            self._entry += "."
        else:
            # Numeric: at most one dot, never leading.
            if "." in self._entry:
                return
            if not self._entry or self._entry == "-":
                self._entry += "0."
            else:
                self._entry += "."
        self._update_display()

    def _on_sign(self) -> None:
        if self._entry.startswith("-"):
            self._entry = self._entry[1:]
        else:
            self._entry = "-" + self._entry
        self._update_display()

    def _on_backspace(self) -> None:
        if self._entry:
            self._entry = self._entry[:-1]
        self._update_display()

    def _on_clear(self) -> None:
        self._entry = ""
        self._update_display()

    # ------------------------------------------------------------------
    # Accept / reject
    # ------------------------------------------------------------------

    def _on_enter(self) -> None:
        if self._ip_mode:
            self._accept_ip()
        else:
            self._accept_numeric()

    def _accept_numeric(self) -> None:
        raw = self._entry.strip()
        if not raw or raw == "-" or raw == ".":
            # Empty entry behaves as Cancel.
            self.reject()
            return
        try:
            num = float(raw)
        except ValueError:
            self.reject()
            return

        if self._minimum is not None:
            num = max(float(self._minimum), num)
        if self._maximum is not None:
            num = min(float(self._maximum), num)

        if self._decimals > 0:
            self._result = round(float(num), self._decimals)
        else:
            self._result = int(round(num))
        self.accept()

    def _accept_ip(self) -> None:
        raw = self._entry.strip()
        if self._valid_ip(raw):
            self._result = raw
            self.accept()
        else:
            # Keep the dialog open; flag the hint line red.
            self._hint_label.setText("Invalid IP - 0-255 per octet")
            self._hint_label.setStyleSheet(self._hint_error_qss)

    @staticmethod
    def _valid_ip(text: str) -> bool:
        """Validate a dotted IPv4 string: 4 octets, each 0-255."""
        parts = text.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not part or not part.isdigit():
                return False
            if len(part) > 3:
                return False
            if int(part) > 255:
                return False
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def value(self):
        """Return the entered result after exec().

        int when decimals == 0, float when decimals > 0, str when ip_mode.
        On reject, returns the original constructor value unchanged.
        """
        return self._result

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------

    def _center_on_parent(self) -> None:
        """Centre the dialog over the parent window."""
        parent = self.parent()
        if parent is None:
            return
        # adjustSize so the height is known before centring.
        self.adjustSize()
        try:
            pgeo = parent.window().frameGeometry()
            cx = pgeo.center().x() - self.width() // 2
            cy = pgeo.center().y() - self.height() // 2
            self.move(cx, cy)
        except Exception:
            # Placement is cosmetic -- never block the dialog over it.
            pass
