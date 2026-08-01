"""main_window_v2.py - Redesigned main window for the UR10 jog control UI.

Orchestrates the v2 widget stack:
  HeaderBar  (persistent top: title, connection badge, e-stop)
  TabNav     (persistent middle: Jog | Demos | Settings)
  QStackedWidget
      [0] JogPage
      [1] DemosPage
      [2] SettingsPage
      [3] RunnerPage      (transient — entered via demo selection)
  FooterBar  (persistent bottom: status, log dot, secondary)

Wires every signal/slot to the existing controllers (JogController,
WebSocketController, DashboardClient, WebSocketReceiver) and to the demo
runner classes. All worker-thread callbacks marshal to the main thread via
QTimer.singleShot(0, ...). Restart and stop loops are bounded to prevent
runaway QTimer chains.

Anomaly fixes (per UI_AUDIT.md Section 8):
  1. _restart_active_demo_with_new_speed: 20 × 300 ms cap, then force-start.
  2. _check_demo_stopped: 20 × 500 ms cap, then force UI to "Stopped".
  3. All demo-runner status callbacks marshal to main thread before touching
     any widget.
  4. No dead pyqtSignals on the main window; direct method calls only.

Author: jsecco
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

import yaml
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Controllers
from control.jog_controller import JogController
from control.demo_runner import DemoRunner
from control.wave_demo import WaveDemo
from control.bow_demo import BowDemo
from control.pendulum_demo import PendulumDemo
from control.industrial_demo import IndustrialDemo
from control.technical_demo import TechnicalDemo
from control.sprint_demo import SprintDemo
from control.plunge_demo import PlungeDemo
from control.reach_demo import ReachDemo
from control.sorting_demo import SortingDemo
from control.juggle_demo import JuggleDemo
from control.stacking_demo import StackingDemo

# Theme + foundation widgets
from ui import theme_v2
from ui.widgets.header_bar import HeaderBar
from ui.widgets.tab_nav import TabNav
from ui.widgets.footer_bar import FooterBar
from ui.pages.jog_page import JogPage
from ui.pages.demos_page import DemosPage
from ui.pages.runner_page import RunnerPage
from ui.pages.settings_page import SettingsPage
from ui.widgets.recovery_panel import (
    RecoveryPanel, classify_safety, classify_robot, is_fault, FAULT_TOKENS,
)


# ---------------------------------------------------------------------------
# Demo registry: card name -> runnable class
# ---------------------------------------------------------------------------
RUNNABLE: Dict[str, Type[Any]] = {
    "Demo": DemoRunner,
    "Wave & Greet": WaveDemo,
    "Bow": BowDemo,
    "Pendulum": PendulumDemo,
    "Sprint": SprintDemo,
    "Plunge": PlungeDemo,
    "Reach": ReachDemo,
    "Industrial": IndustrialDemo,
    "Sorting": SortingDemo,
    "Juggle": JuggleDemo,
    "Stacking": StackingDemo,
    "Technical": TechnicalDemo,
}

# Stacked-widget indices
_PAGE_JOG = 0
_PAGE_DEMOS = 1
_PAGE_SETTINGS = 2
_PAGE_RUNNER = 3

# Bounded retry limits for anomaly-fix loops
_RESTART_MAX_ATTEMPTS = 20    # × 300 ms = 6 s ceiling
_RESTART_INTERVAL_MS = 300
_STOP_POLL_MAX_ATTEMPTS = 20  # × 500 ms = 10 s ceiling
_STOP_POLL_INTERVAL_MS = 500

# Position polling rate (main-thread QTimer)
_POSITION_POLL_INTERVAL_MS = 100

_ICON_PATH = "/home/ur10/Documents/i3UR10/assets/icons/aegis-icon.svg"
_CONFIG_PATH = "config/robot_config.yaml"


def _phase_state_from_message(message: str) -> str:
    """Heuristically classify a demo status message into a phase state."""
    low = (message or "").lower()
    if "fail" in low or "error" in low:
        return "error"
    if "stopping" in low:
        return "stopping"
    if "stopped" in low or low == "idle":
        return "stopped"
    if "complete" in low or "done" in low:
        return "complete"
    if "starting" in low or "start" in low:
        return "starting"
    return "running"


class MainWindowV2(QMainWindow):
    """Redesigned main window: HeaderBar + TabNav + content stack + FooterBar.

    Tabs: Jog, Demos, Settings.
    Demo selection navigates to a transient Runner view (4th stacked page).
    Back from runner returns to Demos.
    """

    # Emitted from the safety-poll worker thread with (safety_mode, robot_mode).
    # A pyqtSignal is the correct cross-thread marshal: it is delivered as a
    # queued connection on the MAIN thread's event loop. (QTimer.singleShot
    # from a worker thread does NOT fire -- the worker has no event loop.)
    _safety_polled = pyqtSignal(str, str)
    # Recovery-command result text, marshalled worker -> main for the panel note.
    _recover_noted = pyqtSignal(str)

    def __init__(self, config: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.logger = logging.getLogger(__name__)

        # ---- Controller / robot state ----
        self.jog_controller: Optional[JogController] = None
        self._connection_state: str = "idle"

        # ---- Demo state ----
        self._loop_demo_runner: Optional[Any] = None
        self._active_demo_name: Optional[str] = None
        self._active_demo_class: Optional[Type[Any]] = None
        self._restart_attempts: int = 0

        # ---- Saved home joints (from config or set via Save Home) ----
        self._saved_home_joints: Optional[List[float]] = None
        demo_cfg = self.config.get("demo", {})
        saved = demo_cfg.get("saved_home_joints")
        if isinstance(saved, list) and len(saved) == 6:
            try:
                self._saved_home_joints = [float(x) for x in saved]
            except (TypeError, ValueError):
                self._saved_home_joints = None

        # ---- Jog UI state (held by main window, applied on jog action) ----
        self._jog_mode: str = "cartesian"
        self._jog_frame: str = "base"
        self._jog_speed_fraction: float = 0.5
        self._jog_step: float = 0.010

        # ---- Robot safety state (driven by the controller status poll) ----
        self._latest_safety_mode: str = ""
        self._latest_robot_mode: str = ""
        self._robot_faulted: bool = False

        # ---- Window setup ----
        self.setWindowTitle("UR10 Control - AEG\\S")
        try:
            self.setWindowIcon(QIcon(_ICON_PATH))
        except Exception as e:
            self.logger.warning("Could not load window icon: %s", e)

        # Resolve and apply the persisted theme BEFORE building the UI, so
        # every widget constructs against the correct palette.
        theme_v2.set_mode(self.config.get("ui", {}).get("theme", "light"))
        self.setStyleSheet(theme_v2.WINDOW_QSS)

        # Build UI
        self._build_ui()
        self._wire_signals()

        # Default size; respect config fullscreen
        ui_cfg = self.config.get("ui", {}).get("window", {})
        width = int(ui_cfg.get("width", 1024))
        height = int(ui_cfg.get("height", 768))
        self.resize(max(1024, width), max(768, height))
        if bool(ui_cfg.get("fullscreen", False)):
            self.showFullScreen()

        # Position polling timer (started after connect)
        self._position_timer = QTimer(self)
        self._position_timer.timeout.connect(self._poll_position)

        # Dedicated safety poll -- queries the dashboard (safetymode / robotmode)
        # directly so fault detection does not depend on the controller's
        # status-callback plumbing. Started after connect.
        self._safety_timer = QTimer(self)
        self._safety_timer.timeout.connect(self._poll_safety)
        self._safety_poll_busy = False
        # Worker-thread -> main-thread marshal for the safety poll result.
        self._safety_polled.connect(self._on_safety_poll)
        self._recover_noted.connect(self.recovery_panel.set_note)

        # Initial UI state
        self.header.set_connection_state("idle")
        self.jog_page.set_connection_state("idle")
        self.jog_page.set_home_saved(bool(self._saved_home_joints))
        self.runner_page.set_test_move_enabled(False)
        self.footer.set_status("Ready", "info")
        self.tab_nav.set_active("Jog")
        self.stack.setCurrentIndex(_PAGE_JOG)

        self.logger.info("MainWindowV2 initialised")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralV2")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = HeaderBar(self)
        layout.addWidget(self.header)

        self.tab_nav = TabNav(["Jog", "Demos", "Settings"], self)
        layout.addWidget(self.tab_nav)

        self.stack = QStackedWidget(self)

        self.jog_page = JogPage(self)
        self.demos_page = DemosPage(self)
        self.settings_page = SettingsPage(self)
        self.runner_page = RunnerPage(self)

        self.stack.addWidget(self.jog_page)       # 0
        self.stack.addWidget(self.demos_page)     # 1
        self.stack.addWidget(self.settings_page)  # 2
        self.stack.addWidget(self.runner_page)    # 3

        layout.addWidget(self.stack, 1)

        self.footer = FooterBar(self)
        layout.addWidget(self.footer)

        self.setCentralWidget(central)

        # Fault-recovery overlay -- a child of the central widget, sized to
        # cover it, hidden until a fault occurs or the operator opens it.
        self.recovery_panel = RecoveryPanel(central)
        self.recovery_panel.hide()
        self._position_recovery()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        # ---- Header ----
        self.header.estop_clicked.connect(self._on_estop_clicked)
        self.header.exit_clicked.connect(self._on_exit_clicked)
        self.header.recover_clicked.connect(self._show_recovery)

        # ---- Recovery overlay ----
        self.recovery_panel.recover_requested.connect(self._on_recover)
        self.recovery_panel.close_requested.connect(self._hide_recovery)

        # ---- Tab nav ----
        self.tab_nav.tab_changed.connect(self._on_tab_changed)

        # ---- Jog page ----
        self.jog_page.connect_clicked.connect(self._connect_to_robot)
        self.jog_page.disconnect_clicked.connect(self._disconnect_from_robot)
        self.jog_page.home_save_clicked.connect(self._on_home_save_clicked)
        self.jog_page.home_go_clicked.connect(self._on_home_go_clicked)
        self.jog_page.save_log_clicked.connect(self._on_save_log_clicked)
        self.jog_page.mode_changed.connect(self._on_jog_mode_changed)
        self.jog_page.frame_changed.connect(self._on_jog_frame_changed)
        self.jog_page.speed_changed.connect(self._on_jog_speed_changed)
        self.jog_page.step_changed.connect(self._on_jog_step_changed)
        self.jog_page.jog_axis_pressed.connect(self._on_jog_axis_pressed)
        self.jog_page.jog_axis_released.connect(self._on_jog_axis_released)
        self.jog_page.jog_axis_stepped.connect(self._on_jog_axis_stepped)

        # ---- Demos page ----
        self.demos_page.demo_selected.connect(self._on_demo_selected)

        # ---- Runner page ----
        self.runner_page.back_clicked.connect(self._on_runner_back)
        self.runner_page.start_clicked.connect(self._on_runner_start)
        self.runner_page.stop_clicked.connect(self._on_runner_stop)
        self.runner_page.test_move_clicked.connect(self._on_runner_test_move)
        self.runner_page.audience_changed.connect(lambda _v: None)
        self.runner_page.cycle_delay_changed.connect(lambda _v: None)
        self.runner_page.speed_changed.connect(lambda _v: None)
        self.runner_page.speed_settled.connect(self._on_runner_speed_settled)

        # ---- Settings page ----
        self.settings_page.save_clicked.connect(self._on_settings_save)
        self.settings_page.cancel_clicked.connect(self._on_settings_cancel)
        self.settings_page.theme_changed.connect(self._apply_theme)

    # ==================================================================
    # Theme switching
    # ==================================================================

    def _apply_theme(self, mode: str) -> None:
        """Switch the UI theme live, then persist the choice.

        Rebuilds theme_v2's palette + QSS globals, re-applies the window
        stylesheet, and propagates apply_theme() to every persistent widget
        and page. demos_page.apply_theme() loops its own DemoCards.
        """
        theme_v2.set_mode(mode)
        self.setStyleSheet(theme_v2.WINDOW_QSS)

        for widget in (
            self.header,
            self.tab_nav,
            self.footer,
            self.jog_page,
            self.demos_page,
            self.settings_page,
            self.runner_page,
            self.recovery_panel,
        ):
            try:
                widget.apply_theme()
            except Exception as e:
                self.logger.warning("apply_theme failed for %s: %s", widget, e)

        # Persist the choice into config and write it back to YAML.
        self.config.setdefault("ui", {})["theme"] = theme_v2.current_mode()
        self._persist_config()

    # ==================================================================
    # Header / E-stop
    # ==================================================================

    def _on_estop_clicked(self) -> None:
        """Belt-and-suspenders e-stop: dashboard + websocket + UI."""
        self.logger.warning("E-STOP clicked")
        self.footer.set_status("EMERGENCY STOP TRIGGERED", "error")
        self.footer.flash_log_indicator()

        try:
            if self.jog_controller and self.jog_controller.dashboard_client \
                    and self.jog_controller.dashboard_client.is_connected():
                self.jog_controller.dashboard_client.emergency_stop()
        except Exception as e:
            self.logger.error("Dashboard e-stop failed: %s", e)

        try:
            if self.jog_controller and self.jog_controller.websocket_controller \
                    and self.jog_controller.websocket_controller.is_connected():
                self.jog_controller.websocket_controller.emergency_stop()
        except Exception as e:
            self.logger.error("WebSocket e-stop failed: %s", e)

        # Stop any running demo
        self._stop_active_demo()

        # Reflect in jog page
        self.jog_page.set_safety_state("emergency", "Emergency stop activated")

    def _on_exit_clicked(self) -> None:
        """Confirm with the operator, then shut the application down cleanly."""
        reply = QMessageBox.question(
            self,
            "Exit Application",
            "Quit the UR10 control application?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.logger.info("Exit requested by operator")
        try:
            self._stop_active_demo()
        except Exception as e:
            self.logger.debug("stop demo on exit failed: %s", e)
        try:
            if self.jog_controller:
                self.jog_controller.disconnect()
        except Exception as e:
            self.logger.debug("disconnect on exit failed: %s", e)
        QApplication.quit()

    # ==================================================================
    # Fault recovery
    # ==================================================================

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._position_recovery()

    def _position_recovery(self) -> None:
        """Keep the recovery overlay sized to cover the central widget."""
        central = self.centralWidget()
        if central is not None and hasattr(self, "recovery_panel"):
            self.recovery_panel.setGeometry(central.rect())

    def _show_recovery(self) -> None:
        self._position_recovery()
        self.recovery_panel.set_state(
            self._latest_safety_mode, self._latest_robot_mode
        )
        self.recovery_panel.show()
        self.recovery_panel.raise_()

    def _hide_recovery(self) -> None:
        self.recovery_panel.hide()

    def _on_recover(self, method: str) -> None:
        """Dispatch a dashboard recovery command on a worker thread.

        Dashboard socket I/O is blocking, so it must not run on the GUI
        thread. The controller's status poll refreshes the panel readout
        within ~0.5s, so we only report the send result here.
        """
        dc = self.jog_controller.dashboard_client if self.jog_controller else None
        if dc is None or not dc.is_connected():
            self.recovery_panel.set_note("Not connected to the robot dashboard.")
            return
        self.logger.warning("Recovery command requested: %s", method)

        # "Enable Robot" is a composite: close any safety popup, power on, wait
        # for the motors, then release the brakes -- bringing the arm from
        # POWER_OFF/IDLE to a movable RUNNING state.
        if method == "enable_robot":
            self.recovery_panel.set_note("Enabling robot: power on + release brakes ...")

            def enable_work() -> None:
                steps = []
                try:
                    dc.close_safety_popup()
                    time.sleep(0.3)
                    steps.append(f"power on: {'ok' if dc.power_on() else 'no'}")
                    # Wait for the motors to come up before releasing brakes.
                    for _ in range(20):
                        time.sleep(0.5)
                        m = (dc.get_robot_mode() or "").upper()
                        if "IDLE" in m or "POWER_ON" in m or "RUNNING" in m:
                            break
                    steps.append(f"brakes: {'ok' if dc.brake_release() else 'no'}")
                    msg = "Enable robot -> " + ", ".join(steps)
                except Exception as e:  # noqa: BLE001
                    msg = f"Enable robot failed: {e}"
                self.logger.warning(msg)
                self._recover_noted.emit(msg)

            threading.Thread(target=enable_work, daemon=True).start()
            return

        fn = getattr(dc, method, None)
        if fn is None:
            self.recovery_panel.set_note(f"Unknown command: {method}")
            return
        label = method.replace("_", " ")
        self.recovery_panel.set_note(f"Sending: {label} ...")

        def work() -> None:
            try:
                ok = bool(fn())
                err = ""
            except Exception as e:  # noqa: BLE001 - report any failure to UI
                ok, err = False, str(e)
            msg = f"{label}: {'sent' if ok else 'failed'}"
            if err:
                msg += f" ({err})"
            self.logger.warning("Recovery result -> %s", msg)
            self._recover_noted.emit(msg)

        threading.Thread(target=work, daemon=True).start()

    def _on_robot_status(self, status: Dict[str, Any]) -> None:
        """Main-thread handler for the controller's robot_status broadcast.

        Drives the recovery overlay, the header recovery button, the jog-page
        safety badge, and demo abort-on-fault.
        """
        # safety_mode arrives either as a dashboard STRING
        # ("Safetymode: PROTECTIVE_STOP") or, from the realtime receiver, as an
        # INT code. The protective_stopped / emergency_stopped booleans are set
        # reliably by BOTH sources, so treat them as the primary fault signal
        # and use the string only to distinguish safeguard / violation / fault.
        protective = bool(status.get("protective_stopped"))
        emergency = bool(status.get("emergency_stopped"))
        safety = str(status.get("safety_mode", "") or "")
        mode = str(status.get("robot_mode", "") or "")

        safety_tok = classify_safety(safety)
        if safety_tok in ("unknown", "normal", "reduced"):
            # An int code or NORMAL string does not override an explicit stop.
            if emergency:
                safety_tok = "emergency"
            elif protective:
                safety_tok = "protective"
        robot_tok = classify_robot(mode)
        faulted = (safety_tok in FAULT_TOKENS) or protective or emergency

        # Canonical safety label for the recovery readout: keep a meaningful
        # dashboard string, else synthesize one from the stop booleans.
        if classify_safety(safety) in FAULT_TOKENS or \
                "NORMAL" in safety.upper() or "REDUCED" in safety.upper():
            self._latest_safety_mode = safety
        elif faulted:
            self._latest_safety_mode = safety_tok.upper().replace("EMERGENCY", "ROBOT_EMERGENCY_STOP")
        else:
            self._latest_safety_mode = safety or "NORMAL"
        self._latest_robot_mode = mode

        # "Ready" means safe AND running. A protective stop keeps the arm
        # RUNNING (so release -> ready), but an emergency stop powers the arm
        # OFF -- which is NOT ready and still needs Enable Robot. Gating ready
        # on robot_mode keeps the recovery affordance reachable until the arm
        # is actually movable again.
        ready = (not faulted) and robot_tok == "running"

        # Header recovery button: visible whenever connected and not ready, so
        # power-off / idle states (where Enable Robot is needed) stay reachable.
        self.header.set_recovery_available(
            self._connection_state == "connected" and not ready
        )

        # Reflect on the jog-page safety badge.
        if emergency or safety_tok == "emergency":
            self.jog_page.set_safety_state("emergency")
        elif safety_tok in ("protective", "safeguard", "fault", "recovery"):
            self.jog_page.set_safety_state("protective_stop")
        elif ready:
            self.jog_page.set_safety_state("normal")

        # Transition INTO a fault: auto-surface recovery, abort any demo.
        if faulted and not self._robot_faulted:
            self.logger.warning("Robot fault detected: safety=%s mode=%s", safety, mode)
            self.footer.set_status(f"Robot fault: {safety_tok.upper()}", "error")
            self.footer.flash_log_indicator()
            if self._loop_demo_runner is not None and self._loop_demo_runner.is_running():
                self._stop_active_demo()
                self.runner_page.set_phase(
                    f"Stopped: {safety_tok} stop", "error"
                )
                self.demos_page.set_running_demo(None)
            self._show_recovery()
        self._robot_faulted = faulted

        # Auto-dismiss once the robot is fully ready (running, no fault). Covers
        # BOTH protective release (stays RUNNING) and the emergency / power-off
        # path (POWER_OFF -> Enable Robot -> RUNNING). While not ready, keep the
        # overlay's readout live.
        if ready:
            if self.recovery_panel.isVisible():
                self._hide_recovery()
                self.footer.set_status("Robot ready", "success")
                self.footer.flash_log_indicator()
        elif self.recovery_panel.isVisible():
            self.recovery_panel.set_state(self._latest_safety_mode, mode)

    def _poll_safety(self) -> None:
        """Query the dashboard for safety + robot mode on a worker thread.

        Self-healing: if the dashboard dropped, reconnect it. The result is
        routed back through _on_robot_status (string path), so detection no
        longer depends on the controller's status broadcast.
        """
        if self._safety_poll_busy:
            return
        dc = self.jog_controller.dashboard_client if self.jog_controller else None
        if dc is None:
            return
        self._safety_poll_busy = True

        def work() -> None:
            safety, mode, note = "", "", ""
            try:
                if not dc.is_connected():
                    if dc.connect():
                        self.logger.info("Dashboard reconnected for safety poll")
                    else:
                        note = "dashboard offline"
                if dc.is_connected():
                    safety = dc.get_safety_mode() or ""
                    mode = dc.get_robot_mode() or ""
            except Exception as e:  # noqa: BLE001
                note = f"poll error: {e}"
                self.logger.warning("Safety poll error: %s", e)
            self.logger.info("Safety poll: safety=%r mode=%r %s", safety, mode, note)
            # Marshal to the main thread via a queued signal (NOT singleShot,
            # which would silently never fire from this worker thread).
            self._safety_polled.emit(safety, mode)

        threading.Thread(target=work, daemon=True).start()

    def _on_safety_poll(self, safety: str, mode: str) -> None:
        """Main-thread: feed the polled dashboard strings to the fault logic."""
        self._safety_poll_busy = False
        if safety or mode:
            self._on_robot_status({"safety_mode": safety, "robot_mode": mode})

    # ==================================================================
    # Tab navigation
    # ==================================================================

    def _on_tab_changed(self, name: str) -> None:
        if name == "Jog":
            self.stack.setCurrentIndex(_PAGE_JOG)
        elif name == "Demos":
            self.stack.setCurrentIndex(_PAGE_DEMOS)
        elif name == "Settings":
            # Refresh form from current config every time we land on Settings
            self.settings_page.load_settings(self._snapshot_settings_for_form())
            self.stack.setCurrentIndex(_PAGE_SETTINGS)
        else:
            self.logger.warning("Unknown tab: %s", name)

    # ==================================================================
    # Connection lifecycle
    # ==================================================================

    def _connect_to_robot(self) -> None:
        """Instantiate JogController, connect, hook callbacks, start position polling."""
        if self.jog_controller and self.jog_controller.is_connected():
            self.footer.set_status("Already connected", "info")
            return

        self.header.set_connection_state("connecting")
        self.jog_page.set_connection_state("connecting")
        self.footer.set_status("Connecting to robot...", "info")

        try:
            if self.jog_controller is None:
                self.jog_controller = JogController(self.config)

            success = self.jog_controller.connect()
            if not success:
                self._on_connection_failed("Connection returned False")
                return

            # The dashboard connection is the source of safety-mode strings and
            # the channel for every recovery command. The controller treats it
            # as non-critical, so make sure it is up -- without it, fault
            # detection and recovery cannot work.
            dc = getattr(self.jog_controller, "dashboard_client", None)
            if dc is not None and not dc.is_connected():
                try:
                    if dc.connect():
                        self.logger.info("Dashboard connected (recovery enabled)")
                    else:
                        self.logger.warning("Dashboard connect failed; recovery unavailable")
                except Exception as e:
                    self.logger.warning("Dashboard connect error: %s", e)

            # Hook callbacks (these run on the receiver/controller worker thread —
            # marshal to main thread before touching widgets).
            self.jog_controller.add_position_fetched_callback(
                lambda: QTimer.singleShot(0, self._refresh_position_now)
            )
            self.jog_controller.add_connection_callback(
                lambda connected: QTimer.singleShot(
                    0, lambda c=connected: self._on_controller_connection_changed(c)
                )
            )
            # Safety/robot-mode status -- the controller polls the dashboard
            # every ~0.5s and broadcasts robot_status. Marshal to the main
            # thread before touching any widget.
            self.jog_controller.add_status_callback(
                lambda status: QTimer.singleShot(
                    0, lambda s=dict(status): self._on_robot_status(s)
                )
            )

            # Start the main-thread position polling timer
            self._position_timer.start(_POSITION_POLL_INTERVAL_MS)
            # Start the dedicated dashboard safety poll (1.5 s).
            self._safety_timer.start(1500)
            self.logger.info("Safety poll started")

            ip = self.config.get("robot", {}).get("ip_address", "")
            self._connection_state = "connected"
            self.header.set_connection_state("connected", ip)
            self.jog_page.set_connection_state("connected")
            self.jog_page.set_home_saved(bool(self._saved_home_joints))
            self.footer.set_status(f"Connected to {ip}", "success")
            self.footer.flash_log_indicator()
            self.logger.info("Robot connected at %s", ip)

        except Exception as e:
            self.logger.exception("Connect failed")
            self._on_connection_failed(str(e))

    def _on_connection_failed(self, reason: str) -> None:
        self._connection_state = "error"
        self.header.set_connection_state("error")
        self.jog_page.set_connection_state("error")
        self.footer.set_status(f"Connection failed: {reason}", "error")
        self.footer.flash_log_indicator()

    def _disconnect_from_robot(self) -> None:
        """Stop polling, drop callbacks, disconnect controller, reset UI."""
        try:
            if self._position_timer.isActive():
                self._position_timer.stop()
            if self._safety_timer.isActive():
                self._safety_timer.stop()
        except Exception:
            pass

        # Stop any running demo first
        self._stop_active_demo()

        try:
            if self.jog_controller:
                self.jog_controller.disconnect()
        except Exception as e:
            self.logger.warning("Disconnect error: %s", e)

        self._connection_state = "idle"
        self.header.set_connection_state("idle")
        self.jog_page.set_connection_state("idle")
        self.footer.set_status("Disconnected", "info")
        self.footer.flash_log_indicator()
        self.logger.info("Robot disconnected")

    def _on_controller_connection_changed(self, connected: bool) -> None:
        """Marshalled to main thread by the connect-callback wrapper."""
        if connected:
            ip = self.config.get("robot", {}).get("ip_address", "")
            self._connection_state = "connected"
            self.header.set_connection_state("connected", ip)
            self.jog_page.set_connection_state("connected")
        else:
            # Only flip back to idle if we weren't already in error
            if self._connection_state != "error":
                self._connection_state = "idle"
                self.header.set_connection_state("idle")
                self.jog_page.set_connection_state("idle")

    # ==================================================================
    # Position polling (main thread)
    # ==================================================================

    def _poll_position(self) -> None:
        """Pull TCP pose + joint angles from receiver and push to JogPage."""
        if not self.jog_controller or not self.jog_controller.is_connected():
            return
        try:
            tcp_pose = self.jog_controller.get_tcp_pose()
            joints = self.jog_controller.get_joint_angles()
            if tcp_pose and len(tcp_pose) == 6:
                self.jog_page.set_tcp_pose(tcp_pose)
            if joints and len(joints) == 6:
                self.jog_page.set_joint_angles(joints)
        except Exception as e:
            self.logger.debug("Position poll error: %s", e)

    def _refresh_position_now(self) -> None:
        """One-shot refresh after position fetched callback fires."""
        self._poll_position()

    # ==================================================================
    # Jog actions
    # ==================================================================

    def _on_jog_mode_changed(self, mode: str) -> None:
        self._jog_mode = mode
        if self.jog_controller:
            try:
                self.jog_controller.set_jog_mode(mode)
            except Exception as e:
                self.logger.warning("set_jog_mode failed: %s", e)
        self.footer.set_status(f"Jog mode: {mode}", "info")

    def _on_jog_frame_changed(self, frame: str) -> None:
        self._jog_frame = frame
        self.footer.set_status(f"Jog frame: {frame}", "info")

    def _on_jog_speed_changed(self, fraction: float) -> None:
        self._jog_speed_fraction = max(0.01, min(1.0, fraction))

    def _on_jog_step_changed(self, value: float) -> None:
        self._jog_step = max(0.001, value)

    def _on_jog_axis_pressed(self, axis: int, direction: int) -> None:
        if not self.jog_controller or not self.jog_controller.is_connected():
            self.footer.set_status("Connect to robot before jogging", "warn")
            return
        try:
            self.jog_controller.start_jog(axis, direction, speed_scale=self._jog_speed_fraction)
        except Exception as e:
            self.logger.warning("start_jog failed: %s", e)

    def _on_jog_axis_released(self, axis: int, direction: int) -> None:
        if not self.jog_controller:
            return
        try:
            self.jog_controller.stop_jog()
        except Exception as e:
            self.logger.warning("stop_jog failed: %s", e)

    def _on_jog_axis_stepped(self, axis: int, direction: int) -> None:
        """Short tap: do a brief start_jog/stop_jog pulse for a step nudge."""
        if not self.jog_controller or not self.jog_controller.is_connected():
            self.footer.set_status("Connect to robot before jogging", "warn")
            return
        try:
            self.jog_controller.start_jog(axis, direction, speed_scale=self._jog_speed_fraction)
            QTimer.singleShot(120, self.jog_controller.stop_jog)
        except Exception as e:
            self.logger.warning("step jog failed: %s", e)

    # ==================================================================
    # Home save / go-home
    # ==================================================================

    def _on_home_save_clicked(self) -> None:
        if not self.jog_controller or not self.jog_controller.is_connected():
            self.footer.set_status("Connect to robot before saving home", "warn")
            return
        try:
            joints = self.jog_controller.get_joint_angles()
        except Exception as e:
            self.logger.warning("get_joint_angles failed: %s", e)
            joints = None

        if not joints or len(joints) != 6 or all(abs(q) < 0.01 for q in joints):
            self.footer.set_status(
                "Position not yet received - wait a few seconds and retry", "warn"
            )
            return

        self._saved_home_joints = list(joints)
        self.config.setdefault("demo", {})["saved_home_joints"] = self._saved_home_joints
        self._persist_config()
        self.jog_page.set_home_saved(True)
        self.runner_page.set_test_move_enabled(self._connection_state == "connected")
        self.footer.set_status("Home position saved", "success")
        self.footer.flash_log_indicator()

    def _on_home_go_clicked(self) -> None:
        if not self._saved_home_joints:
            self.footer.set_status("No home saved", "warn")
            return
        if not self.jog_controller or not self.jog_controller.websocket_controller \
                or not self.jog_controller.websocket_controller.is_connected():
            self.footer.set_status("Connect before going home", "warn")
            return
        ok = self.jog_controller.websocket_controller.move_joint(
            self._saved_home_joints, speed=0.2, acceleration=0.25, blend=0.0
        )
        if ok:
            self.footer.set_status("Moving to home", "info")
        else:
            self.footer.set_status("Go-home command failed", "error")

    # ==================================================================
    # Save log snapshot
    # ==================================================================

    def _on_save_log_clicked(self) -> None:
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = log_dir / f"demo_snapshot_{ts}.txt"
            # Pull the runner page's event log buffer (best-effort).
            content = ""
            if hasattr(self.runner_page, "_event_log"):
                try:
                    content = self.runner_page._event_log.toPlainText()
                except Exception:
                    pass
            if not content:
                content = f"[{ts}] No event log content available.\n"
            path.write_text(content, encoding="utf-8")
            self.footer.set_status(f"Log saved: {path.name}", "success")
            self.footer.flash_log_indicator()
        except Exception as e:
            self.logger.exception("Save log failed")
            self.footer.set_status(f"Save log failed: {e}", "error")

    # ==================================================================
    # Demo selection
    # ==================================================================

    def _on_demo_selected(self, name: str) -> None:
        if name not in RUNNABLE:
            self.footer.set_status(f"'{name}' not implemented yet", "warn")
            return
        self._active_demo_name = name
        self._active_demo_class = RUNNABLE[name]
        self.runner_page.set_demo_name(name)
        self.runner_page.clear_event_log()
        self.runner_page.set_running(False)
        self.runner_page.set_test_move_enabled(
            bool(self._saved_home_joints) and self._connection_state == "connected"
        )
        # Initial phase: stopped/idle
        self.runner_page.set_phase("Stopped", "stopped")
        self.stack.setCurrentIndex(_PAGE_RUNNER)
        self.footer.set_status(f"Demo: {name}", "info")

    # ==================================================================
    # Runner: Back / Start / Stop / Test
    # ==================================================================

    def _on_runner_back(self) -> None:
        # Stop running demo before leaving
        if self._loop_demo_runner is not None and self._loop_demo_runner.is_running():
            self._stop_active_demo()
        self._active_demo_name = None
        self._active_demo_class = None
        self.demos_page.set_running_demo(None)
        self.tab_nav.set_active("Demos")
        self.stack.setCurrentIndex(_PAGE_DEMOS)

    def _on_runner_start(self) -> None:
        # Guards
        if not self.jog_controller or not self.jog_controller.is_connected():
            self.footer.set_status("Connect to robot before starting demo", "error")
            return
        if not self._saved_home_joints or len(self._saved_home_joints) != 6:
            self.footer.set_status("Save a home position before starting demo", "error")
            return
        if self._active_demo_class is None:
            self.footer.set_status("No demo selected", "error")
            return
        if self._loop_demo_runner is not None and self._loop_demo_runner.is_running():
            self.footer.set_status("Demo already running", "warn")
            return
        # Safety gate: never start a demo while the robot is faulted -- it would
        # just trip again. Surface recovery instead.
        if is_fault(self._latest_safety_mode) or \
                (self.jog_controller and self.jog_controller.is_emergency_stopped()):
            self.footer.set_status(
                "Robot faulted - recover before starting a demo", "error"
            )
            self.runner_page.set_phase("Recover the robot first", "error")
            self._show_recovery()
            return

        self._reset_restart_attempts()
        self._launch_active_demo()

    def _launch_active_demo(self) -> None:
        """Build the runner with current parameters and start it."""
        name = self._active_demo_name or "Demo"
        cls = self._active_demo_class
        if cls is None:
            return

        audience_deg = self.runner_page.audience_offset_degrees()
        audience_rad = math.radians(audience_deg)
        speed_pct = self.runner_page.speed_percent() / 100.0
        cycle_delay = self.runner_page.cycle_delay_seconds()

        demo_cfg = self.config.get("demo", {})
        joint_speed = float(demo_cfg.get("joint_speed", 0.9))
        joint_accel = float(demo_cfg.get("joint_acceleration", 2.0))
        blend_radius = float(demo_cfg.get("blend_radius_rad", 0.10))
        send_interval = float(demo_cfg.get("send_interval_s", 0.08))

        status_callback = self._make_status_callback()

        # Demos build their waypoints as offsets from this pose, and the
        # controller shrinks a program towards it when the choreography would
        # otherwise self-collide. Set here, at the one place the home is handed
        # to a demo, so the two can never be told different things.
        self.jog_controller.websocket_controller.demo_home = (
            list(self._saved_home_joints) if self._saved_home_joints else None)

        try:
            runner = cls(
                self.jog_controller.websocket_controller,
                home_joints=self._saved_home_joints,
                audience_offset_rad=audience_rad,
                speed_scale=speed_pct,
                joint_speed=joint_speed,
                joint_acceleration=joint_accel,
                blend_radius=blend_radius,
                send_interval_s=send_interval,
                cycle_delay_s=cycle_delay,
                status_callback=status_callback,
            )
        except Exception as e:
            self.logger.exception("Demo runner construction failed")
            self.footer.set_status(f"Demo init failed: {e}", "error")
            self.runner_page.set_phase(f"Init failed: {e}", "error")
            return

        self._loop_demo_runner = runner
        if runner.start():
            self.runner_page.set_running(True)
            self.runner_page.set_phase("Running", "running")
            self.demos_page.set_running_demo(name)
            self.footer.set_status(f"Running {name}", "success")
            self.footer.flash_log_indicator()
        else:
            self.runner_page.set_running(False)
            self.runner_page.set_phase("Start failed", "error")
            self.footer.set_status("Demo failed to start", "error")

    def _make_status_callback(self) -> Callable[[str], None]:
        """Return a thread-safe status callback that marshals to main thread."""
        def cb(message: str) -> None:
            QTimer.singleShot(0, lambda m=message: self._on_demo_status(m))
        return cb

    def _on_demo_status(self, message: str) -> None:
        """Demo status update on the MAIN THREAD (always)."""
        state = _phase_state_from_message(message)
        try:
            self.runner_page.set_phase(message, state)
        except Exception as e:
            self.logger.debug("set_phase failed: %s", e)
        self.footer.flash_log_indicator()

        if state in ("stopped", "complete", "error"):
            self.runner_page.set_running(False)
            self.demos_page.set_running_demo(None)

    def _on_runner_stop(self) -> None:
        self._stop_active_demo()
        # Schedule a bounded poll to force the UI to "Stopped" if the runner
        # never publishes its final status.
        QTimer.singleShot(_STOP_POLL_INTERVAL_MS, lambda: self._check_demo_stopped(0))

    def _stop_active_demo(self) -> None:
        runner = self._loop_demo_runner
        if runner is None:
            return
        try:
            if runner.is_running():
                runner.stop()
                self.runner_page.set_phase("Stopping...", "stopping")
                self.footer.set_status("Demo stopping", "info")
        except Exception as e:
            self.logger.warning("Demo stop failed: %s", e)

    def _check_demo_stopped(self, attempt: int) -> None:
        """Poll fallback: ensure UI reaches 'Stopped' even if final notify is lost.

        Bounded at _STOP_POLL_MAX_ATTEMPTS × _STOP_POLL_INTERVAL_MS = 10 s.
        """
        runner = self._loop_demo_runner
        if runner is None or not runner.is_running():
            self.runner_page.set_running(False)
            self.runner_page.set_phase("Stopped", "stopped")
            self.demos_page.set_running_demo(None)
            self.footer.set_status("Demo stopped", "info")
            return
        if attempt >= _STOP_POLL_MAX_ATTEMPTS:
            self.logger.warning("Demo stop poll timed out; forcing UI Stopped")
            self.runner_page.set_running(False)
            self.runner_page.set_phase("Stopped (forced)", "stopped")
            self.demos_page.set_running_demo(None)
            self.footer.set_status("Demo stop forced", "warn")
            return
        QTimer.singleShot(
            _STOP_POLL_INTERVAL_MS,
            lambda a=attempt + 1: self._check_demo_stopped(a),
        )

    def _on_runner_test_move(self) -> None:
        if not self.jog_controller or not self.jog_controller.websocket_controller \
                or not self.jog_controller.websocket_controller.is_connected():
            self.footer.set_status("Connect before test move", "warn")
            return
        if not self._saved_home_joints:
            self.footer.set_status("Save home before test move", "warn")
            return
        ok = self.jog_controller.websocket_controller.move_joint(
            self._saved_home_joints, speed=0.2, acceleration=0.25, blend=0.0
        )
        if ok:
            self.footer.set_status("Test move sent", "info")
            self.runner_page.set_phase("Test move...", "starting")
        else:
            self.footer.set_status("Test move failed", "error")

    # ==================================================================
    # Speed-settled restart (BOUNDED)
    # ==================================================================

    def _reset_restart_attempts(self) -> None:
        self._restart_attempts = 0

    def _on_runner_speed_settled(self, percent: int) -> None:
        """User changed the speed slider; if a demo is running, restart it."""
        runner = self._loop_demo_runner
        if runner is None or not runner.is_running():
            return  # Nothing to restart; new value applies on next Start.
        self.footer.set_status(f"Restarting demo at {percent}%", "info")
        self._stop_active_demo()
        self._reset_restart_attempts()
        QTimer.singleShot(
            _RESTART_INTERVAL_MS, self._restart_active_demo_with_new_speed
        )

    def _restart_active_demo_with_new_speed(self) -> None:
        """Bounded restart loop: cap at _RESTART_MAX_ATTEMPTS retries.

        After the cap is reached, log a warning and force-launch anyway.
        Anomaly fix vs. legacy unbounded recursion.
        """
        runner = self._loop_demo_runner
        still_running = runner is not None and runner.is_running()

        if not still_running:
            # Safe to relaunch
            if self._active_demo_class is not None and self._saved_home_joints \
                    and self.jog_controller and self.jog_controller.is_connected():
                self._launch_active_demo()
            return

        self._restart_attempts += 1
        if self._restart_attempts >= _RESTART_MAX_ATTEMPTS:
            self.logger.warning(
                "Restart retry cap (%d) reached; forcing relaunch despite stale runner",
                _RESTART_MAX_ATTEMPTS,
            )
            self.footer.set_status("Restart retry capped; forcing", "warn")
            # Drop the stale runner reference to avoid blocking the new one
            self._loop_demo_runner = None
            if self._active_demo_class is not None and self._saved_home_joints \
                    and self.jog_controller and self.jog_controller.is_connected():
                self._launch_active_demo()
            return

        QTimer.singleShot(
            _RESTART_INTERVAL_MS, self._restart_active_demo_with_new_speed
        )

    # ==================================================================
    # Settings save / cancel
    # ==================================================================

    def _snapshot_settings_for_form(self) -> Dict[str, Any]:
        """Build the dict that SettingsPage.load_settings() expects."""
        robot = self.config.get("robot", {}) or {}
        safety = self.config.get("safety", {}) or {}
        demo = self.config.get("demo", {}) or {}
        return {
            "robot_ip": robot.get("ip_address", "192.168.10.24"),
            "use_rtde": bool(robot.get("use_rtde_for_motion", True)),
            "connection_timeout": float(safety.get("connection_timeout", 5.0)),
            "demo_base_offset_deg": int(demo.get("base_offset_degrees", 0)),
            "demo_waypoint_delay_s": float(demo.get("waypoint_delay_s", 2.5)),
            "demo_default_speed_percent": int(demo.get("default_speed_percent", 50)),
        }

    def _on_settings_save(self, values: Dict[str, Any]) -> None:
        """Merge the form values into self.config and persist to YAML."""
        try:
            self.config.setdefault("robot", {})["ip_address"] = values.get(
                "robot_ip", "192.168.10.24"
            )
            self.config["robot"]["use_rtde_for_motion"] = bool(
                values.get("use_rtde", True)
            )
            self.config.setdefault("safety", {})["connection_timeout"] = float(
                values.get("connection_timeout", 5.0)
            )
            demo_cfg = self.config.setdefault("demo", {})
            demo_cfg["base_offset_degrees"] = int(values.get("demo_base_offset_deg", 0))
            demo_cfg["waypoint_delay_s"] = float(values.get("demo_waypoint_delay_s", 2.5))
            demo_cfg["default_speed_percent"] = int(
                values.get("demo_default_speed_percent", 50)
            )
            self._persist_config()
            self.footer.set_status("Settings saved", "success")
            self.footer.flash_log_indicator()
        except Exception as e:
            self.logger.exception("Settings save failed")
            self.footer.set_status(f"Save failed: {e}", "error")

    def _on_settings_cancel(self) -> None:
        self.footer.set_status("Settings reverted", "info")

    def _persist_config(self) -> None:
        """Write self.config back to robot_config.yaml (best-effort)."""
        try:
            path = Path(_CONFIG_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            full = {}
            if path.exists():
                with open(path, "r") as f:
                    full = yaml.safe_load(f) or {}
            # Shallow-merge our top-level keys back in
            for key in ("robot", "safety", "demo", "ui"):
                if key in self.config:
                    full[key] = self.config[key]
            with open(path, "w") as f:
                yaml.dump(full, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            self.logger.warning("Could not write config: %s", e)

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def closeEvent(self, event) -> None:
        try:
            if self._position_timer.isActive():
                self._position_timer.stop()
        except Exception:
            pass
        try:
            self._stop_active_demo()
        except Exception:
            pass
        try:
            if self.jog_controller:
                self.jog_controller.disconnect()
        except Exception as e:
            self.logger.warning("Disconnect on close failed: %s", e)
        try:
            self._persist_config()
        except Exception:
            pass
        self.logger.info("MainWindowV2 closing")
        event.accept()
