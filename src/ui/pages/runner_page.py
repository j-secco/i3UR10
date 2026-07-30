"""runner_page.py — Demo Runner page widget for the UR10 jog control UI.

Displays the live phase indicator, parameter controls (audience direction,
speed, cycle delay), Start/Stop/Test Move buttons, and the live event log.

Layout (vertically stacked):
  1. Top bar: Back button + demo name title
  2. Phase panel (large color-coded, ~200 px)
  3. Live event log (dark monospace, ~200 px expanding)
  4. Parameter row: audience spinbox, speed slider+label, cycle-delay spinbox
  5. Action row: Test Move, Start, Stop

Author: jsecco
"""

from __future__ import annotations

import re
from datetime import datetime

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui import theme_v2
from ui.theme_v2 import (
    BUTTON_H,
    F_BODY,
    F_DISPLAY,
    F_TITLE,
    R_LG,
    S_12,
    S_16,
    S_24,
    S_8,
)

# Maximum lines kept in the event log before trimming from the top.
_LOG_MAX_LINES = 200

# Matches a "(3/9)" segment counter inside a demo phase message, so the
# progress bar can self-update from the existing status callbacks.
_SEG_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")

# Debounce interval for speed slider (ms). After slider stops moving for this
# duration, speed_settled is emitted; the main window decides what to do.
_SPEED_DEBOUNCE_MS = 450

# Cap on _restart_after_speed_change retries (prevents unbounded loop).
_SPEED_RESTART_MAX_RETRIES = 15


class RunnerPage(QWidget):
    """Demo runner: phase indicator + parameter controls + event log + Start/Stop.

    Layout (vertically stacked):
      1. Top bar: 'Back' button + demo name title
      2. Big phase panel (large color-coded text)
      3. Live event log (dark monospace, scrolling)
      4. Parameter row: audience direction spinbox, speed slider, cycle delay spinbox
      5. Action row: Test Move, Start, Stop buttons
    """

    # === User-action signals ===
    back_clicked = pyqtSignal()
    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    test_move_clicked = pyqtSignal()

    audience_changed = pyqtSignal(int)    # degrees
    speed_changed = pyqtSignal(int)       # 10..100 percent
    cycle_delay_changed = pyqtSignal(float)  # seconds

    # Emitted only when speed slider stops moving for ~450 ms while a demo is
    # running. The main window decides whether to restart.
    speed_settled = pyqtSignal(int)       # percent

    # ------------------------------------------------------------------ #
    #  Construction                                                        #
    # ------------------------------------------------------------------ #

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Current phase panel state -- kept so apply_theme() re-applies the
        # status_panel_qss for the live state, not a hardcoded idle one.
        self._phase_state: str = "idle"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(S_24, S_24, S_24, S_24)
        outer.setSpacing(S_16)

        # 1. Top bar ──────────────────────────────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(S_16)

        self._back_btn = QPushButton("← Back to Demos")
        self._back_btn.setMinimumHeight(BUTTON_H)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self.back_clicked)
        top_bar.addWidget(self._back_btn)

        self._title_label = QLabel("Demo")
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        top_bar.addWidget(self._title_label)
        outer.addLayout(top_bar)

        # 2. Phase panel ──────────────────────────────────────────────────
        self._phase_frame = QFrame()
        self._phase_frame.setObjectName("phasePanel")
        self._phase_frame.setMinimumHeight(180)
        self._phase_frame.setMaximumHeight(180)
        self._phase_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        phase_inner = QVBoxLayout(self._phase_frame)
        phase_inner.setContentsMargins(S_16, S_12, S_16, S_12)
        phase_inner.setSpacing(S_8)
        # Centre the content with stretches rather than layout alignment --
        # QLayout.setAlignment misbehaves with word-wrapped labels and causes
        # the children to overlap.
        phase_inner.addStretch(1)

        self._phase_hint = QLabel("PHASE")
        self._phase_hint.setObjectName("phaseSubLabel")
        self._phase_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        phase_inner.addWidget(self._phase_hint)

        self._phase_label = QLabel("Stopped")
        self._phase_label.setObjectName("phaseLabel")
        self._phase_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._phase_label.setWordWrap(False)
        # Set the large font via QFont, NOT QSS. A QSS "font-size" does not
        # feed the label's sizeHint, so the layout allocates only a default
        # line of height and the progress bar below overlaps the text.
        _phase_font = QFont()
        _phase_font.setPixelSize(F_DISPLAY)
        _phase_font.setWeight(QFont.Weight.Bold)
        self._phase_label.setFont(_phase_font)
        phase_inner.addWidget(self._phase_label)

        # Segment progress bar — fills the panel and shows how far through the
        # choreography the demo is. Self-updates from the "(N/M)" counter in
        # demo phase messages (see set_phase).
        self._progress = QProgressBar()
        self._progress.setObjectName("phaseProgress")
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        phase_inner.addWidget(self._progress)

        self._segment_label = QLabel("")
        self._segment_label.setObjectName("phaseSegment")
        self._segment_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        phase_inner.addWidget(self._segment_label)
        phase_inner.addStretch(1)

        outer.addWidget(self._phase_frame)

        # 3. Event log ────────────────────────────────────────────────────
        self._event_log = QPlainTextEdit()
        self._event_log.setReadOnly(True)
        self._event_log.setPlaceholderText("Demo not running")
        self._event_log.setMinimumHeight(200)
        self._event_log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._event_log.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer.addWidget(self._event_log)

        # 4. Parameter row ────────────────────────────────────────────────
        param_row = QHBoxLayout()
        param_row.setSpacing(S_16)

        # Audience direction spinbox
        aud_box = QVBoxLayout()
        self._aud_lbl = QLabel("Audience")
        aud_box.addWidget(self._aud_lbl)
        self._audience_spin = QSpinBox()
        self._audience_spin.setRange(-360, 360)
        self._audience_spin.setSingleStep(15)
        self._audience_spin.setSuffix("°")
        self._audience_spin.setValue(0)
        self._audience_spin.setMinimumHeight(BUTTON_H)
        self._audience_spin.setMinimumWidth(150)
        self._audience_spin.valueChanged.connect(self.audience_changed)
        aud_box.addWidget(self._audience_spin)
        aud_box.addStretch()
        param_row.addLayout(aud_box)

        # Speed slider + live value label
        speed_box = QVBoxLayout()
        self._speed_val_label = QLabel("Speed: 50%")
        speed_box.addWidget(self._speed_val_label)
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(10, 100)
        self._speed_slider.setValue(50)
        self._speed_slider.setMinimumHeight(BUTTON_H)
        self._speed_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        speed_box.addWidget(self._speed_slider)
        speed_box.addStretch()
        param_row.addLayout(speed_box, stretch=2)

        # Cycle delay spinbox
        delay_box = QVBoxLayout()
        self._delay_lbl = QLabel("Cycle Delay")
        delay_box.addWidget(self._delay_lbl)
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(1.0, 6.0)
        self._delay_spin.setSingleStep(0.5)
        self._delay_spin.setDecimals(1)
        self._delay_spin.setSuffix(" s")
        self._delay_spin.setValue(2.5)
        self._delay_spin.setMinimumHeight(BUTTON_H)
        self._delay_spin.setMinimumWidth(150)
        self._delay_spin.valueChanged.connect(self.cycle_delay_changed)
        delay_box.addWidget(self._delay_spin)
        delay_box.addStretch()
        param_row.addLayout(delay_box)

        outer.addLayout(param_row)

        # 5. Action row ───────────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(S_16)
        action_row.addStretch()

        self._test_btn = QPushButton("Test Move")
        self._test_btn.setMinimumHeight(BUTTON_H)
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.clicked.connect(self.test_move_clicked)
        action_row.addWidget(self._test_btn)

        self._start_btn = QPushButton("Start")
        self._start_btn.setMinimumHeight(BUTTON_H)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self.start_clicked)
        action_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setMinimumHeight(BUTTON_H)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.clicked.connect(self.stop_clicked)
        action_row.addWidget(self._stop_btn)

        outer.addLayout(action_row)

        # ── Speed debounce timer ─────────────────────────────────────────
        # Fires speed_settled only after slider has been still for 450 ms.
        # Restart logic is intentionally NOT here — that belongs to main window.
        self._speed_debounce = QTimer(self)
        self._speed_debounce.setSingleShot(True)
        self._speed_debounce.setInterval(_SPEED_DEBOUNCE_MS)
        self._speed_debounce.timeout.connect(self._on_speed_debounce_fired)

        self._speed_slider.valueChanged.connect(self._on_speed_changed)

        # Apply all theme-dependent styling.
        self.apply_theme()

    # ------------------------------------------------------------------ #
    #  Theming                                                             #
    # ------------------------------------------------------------------ #

    def apply_theme(self) -> None:
        """Re-apply every stylesheet from the current theme_v2 palette.

        Re-applies the phase panel for the CURRENT phase state so a live
        theme switch keeps the running/error/etc. colours correct.
        """
        # Top bar.
        self._back_btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT}; font-size: {F_TITLE}px;"
            f" font-weight: 700; background-color: transparent; }}"
        )

        # Phase panel -- re-apply for the live state.
        self._phase_frame.setStyleSheet(theme_v2.status_panel_qss(self._phase_state))

        # Segment progress bar.
        self._progress.setStyleSheet(
            f"QProgressBar#phaseProgress {{ background-color: {theme_v2.BORDER};"
            f" border: none; border-radius: 5px; }}"
            f"QProgressBar#phaseProgress::chunk {{"
            f" background-color: {theme_v2.ACCENT};"
            f" border-radius: 5px; }}"
        )
        self._segment_label.setStyleSheet(
            f"QLabel {{ color: {theme_v2.TEXT_MUTED}; font-size: {F_BODY}px;"
            f" background-color: transparent; border: none; }}"
        )

        # Event log.
        self._event_log.setStyleSheet(theme_v2.EVENT_LOG_QSS)

        # Parameter row labels.
        param_label_qss = (
            f"QLabel {{ color: {theme_v2.TEXT_MUTED}; font-size: {F_BODY}px;"
            f" background-color: transparent; }}"
        )
        for lbl in (self._aud_lbl, self._speed_val_label, self._delay_lbl):
            lbl.setStyleSheet(param_label_qss)

        # Parameter row inputs.
        self._audience_spin.setStyleSheet(theme_v2.SPINBOX_QSS)
        self._delay_spin.setStyleSheet(theme_v2.SPINBOX_QSS)
        self._speed_slider.setStyleSheet(theme_v2.SLIDER_QSS)

        # Action row buttons.
        self._test_btn.setStyleSheet(theme_v2.SECONDARY_BUTTON_QSS)
        self._start_btn.setStyleSheet(theme_v2.PRIMARY_BUTTON_QSS)
        self._stop_btn.setStyleSheet(theme_v2.DANGER_BUTTON_QSS)

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _on_speed_changed(self, value: int) -> None:
        """Update speed label live and restart the debounce timer."""
        self._speed_val_label.setText(f"Speed: {value}%")
        self.speed_changed.emit(value)
        # Restart timer; fires speed_settled only after 450 ms of stillness.
        self._speed_debounce.start()

    def _on_speed_debounce_fired(self) -> None:
        """Emit speed_settled with the current slider value."""
        self.speed_settled.emit(self._speed_slider.value())

    def _scroll_log_to_bottom(self) -> None:
        sb: QScrollBar = self._event_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _trim_log(self) -> None:
        """Remove oldest lines when the log exceeds _LOG_MAX_LINES blocks."""
        doc = self._event_log.document()
        while doc.blockCount() > _LOG_MAX_LINES:
            cursor = self._event_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    # ------------------------------------------------------------------ #
    #  External state updates (called by main window)                     #
    # ------------------------------------------------------------------ #

    def set_demo_name(self, name: str) -> None:
        """Set the demo title shown in the top bar."""
        self._title_label.setText(name)

    def set_phase(self, message: str, state: str = "running") -> None:
        """Update the phase panel text and color.

        state must be one of:
          'idle', 'starting', 'running', 'stopping', 'stopped', 'complete', 'error'
        The background/border color is driven by theme_v2.status_panel_qss(state).
        Also appends the message to the event log.
        """
        self._phase_state = state
        self._phase_label.setText(message)
        self._phase_frame.setStyleSheet(theme_v2.status_panel_qss(state))
        # Self-update the progress bar from a "(N/M)" segment counter, if the
        # message carries one; clear it on a terminal state.
        match = _SEG_RE.search(message or "")
        if match:
            self.set_progress(int(match.group(1)), int(match.group(2)))
        elif state in ("idle", "stopped", "complete", "error"):
            self.set_progress(0, 0)
        self.append_event(message)

    def set_progress(self, current: int, total: int) -> None:
        """Update the phase-panel segment progress bar.

        current/total are the completed/total choreography segments. Pass
        total <= 0 to clear the bar (e.g. when the demo is idle or stopped).
        """
        if total and total > 0:
            current = max(0, min(total, current))
            self._progress.setRange(0, total)
            self._progress.setValue(current)
            self._segment_label.setText(f"segment {current} of {total}")
        else:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            self._segment_label.setText("")

    def append_event(self, message: str) -> None:
        """Append a timestamped line to the event log and auto-scroll to bottom.

        Format: HH:MM:SS  <message>
        Trims to _LOG_MAX_LINES (200) lines.
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self._event_log.appendPlainText(f"{ts}  {message}")
        self._trim_log()
        self._scroll_log_to_bottom()

    def clear_event_log(self) -> None:
        """Clear the event log and stamp the start time (matches legacy behavior)."""
        self._event_log.clear()
        ts = datetime.now().strftime("%H:%M:%S")
        self._event_log.appendPlainText(f"--- Demo started: {ts} ---")
        self._scroll_log_to_bottom()

    def set_running(self, running: bool) -> None:
        """Toggle button states for running vs stopped.

        running=True:  disable Start + Test Move, enable Stop.
        running=False: enable Start + Test Move (if test-move-enabled), disable Stop.
        """
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        # Test Move re-enable is gated via set_test_move_enabled; keep it
        # consistent: disable while running regardless of home-pose state.
        if running:
            self._test_btn.setEnabled(False)

    def set_test_move_enabled(self, enabled: bool) -> None:
        """Gate the Test Move button on whether a saved-home pose exists."""
        self._test_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    #  Getters (main window reads values when starting a demo)            #
    # ------------------------------------------------------------------ #

    def audience_offset_degrees(self) -> int:
        """Current audience direction offset in degrees."""
        return self._audience_spin.value()

    def speed_percent(self) -> int:
        """Current speed slider value, 10..100."""
        return self._speed_slider.value()

    def cycle_delay_seconds(self) -> float:
        """Current cycle delay in seconds, 1.0..6.0."""
        return self._delay_spin.value()
