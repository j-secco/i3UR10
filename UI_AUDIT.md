# UI_AUDIT.md — UR10 Jog Control Interface: Migration Audit

**Source file:** `src/ui/main_window_professional.py` (1507 lines)
**Supporting:** `src/ui/widgets/config_dialog.py`, `src/ui/styles/professional_theme.py`, `src/main.py`, `src/control/jog_controller.py`, `config/robot_config.yaml`
**Audit date:** 2026-05-08
**Author:** jsecco

---

## 1. Top-level Architecture

### Class Hierarchy

```
QMainWindow
  └── ProfessionalMainWindow          (src/ui/main_window_professional.py)

logging.Handler
  └── DemoLogHandler                  (src/ui/main_window_professional.py, inner class)

QDialog
  └── ConfigDialog                    (src/ui/widgets/config_dialog.py)
```

`ProfessionalMainWindow` is aliased as `MainWindow` in `src/main.py`:
```python
from ui.main_window_professional import ProfessionalMainWindow as MainWindow
```

### QStackedWidget Pages

The central widget is a `QGridLayout` container with:
- `self.stacked` (`QStackedWidget`) at grid cell (0,0)
- `self._protective_stop_overlay` (`QFrame`) also at (0,0) — layered on top via QGridLayout z-ordering

| Index | Widget reference | Created by | Description |
|-------|-----------------|------------|-------------|
| 0 | `main_page` (local var) | `_setup_ui()` | Three-panel jog view (left: controls, center: position, right: safety) |
| 1 | `self.demo_page` | `_create_demo_screen()` | Scrollable demo card selection grid (13 cards) |
| 2 | `self.loop_demo_page` | `_create_loop_demo_screen()` | Demo runner: start/stop/speed/delay/status/event log |

### Navigation Between Pages

| From | To | Mechanism |
|------|----|-----------|
| Main (0) | Demo selection (1) | `demo_button.clicked` -> `_show_demo_screen()` -> `stacked.setCurrentWidget(demo_page)` |
| Demo selection (1) | Main (0) | `back_btn.clicked` -> `_go_back_from_demo()` -> `stacked.setCurrentIndex(0)` |
| Demo selection (1) | Loop demo (2) | `card_btn.clicked` -> `_on_demo_card_clicked()` -> `stacked.setCurrentWidget(loop_demo_page)` |
| Loop demo (2) | Demo selection (1) | `back_btn.clicked` -> `_go_back_from_loop_demo()` -> `stacked.setCurrentWidget(demo_page)` |

The protective-stop overlay sits above all pages via QGridLayout stacking.

---

## 2. Persistent State (`self.<attr>` on ProfessionalMainWindow)

| Name | Type | Initial value | Set / Read | Critical? |
|------|------|---------------|------------|-----------|
| `config` | `Dict[str, Any]` | Passed from `main.py` | Set in `__init__`; read throughout; mutated by `_save_as_home()` and `_show_settings()` | YES |
| `logger` | `logging.Logger` | `logging.getLogger(__name__)` | Set in `__init__` | no |
| `jog_controller` | `Optional[JogController]` | `None` | Set via `set_jog_controller()` after window shown; read by all jog/connect/demo methods | YES |
| `loop_demo_runner` | instance of active demo class or `None` | `None` | Created in `_loop_demo_start()`; stopped in stop/back/check methods | YES |
| `_active_demo_class` | class ref (subclass of `DemoRunner`) | `DemoRunner` | Set in `_on_demo_card_clicked()`; read in `_loop_demo_start()` | YES |
| `saved_home_joints` | `Optional[List[float]]` (6 radians) | Loaded from `config['demo']['saved_home_joints']` or `None` | Updated by `_save_as_home()`; read by demo start/test/go-to-home | YES |
| `current_jog_mode` | `str` | `"cartesian"` | Set by `_set_jog_mode()`; passed to `jog_controller.set_jog_mode()` | YES |
| `current_position` | `Dict` with `cartesian` and `joint` sub-dicts | all zeros | Updated by `_on_position_updated()`; read by `_update_position_display()` | YES |
| `position_timer` | `QTimer` | `QTimer()` | Started at 100ms in `_setup_timers()`; fires `_update_position_display()` at 10 Hz | YES |
| `status_timer` | `QTimer` | `QTimer()` | Started at 200ms in `_setup_timers()`; fires `_update_status_display()` at 5 Hz | YES |
| `_speed_slider_debounce` | `QTimer` (singleShot=True, 450ms) | `_create_loop_demo_screen()` | Started on speed slider change; fires `_on_speed_slider_settled()` | YES |
| `_protective_stop_overlay` | `QFrame` | `_setup_ui()` | Shown/hidden by `_update_status_display()` / `_on_protective_stop_unlock_clicked()` | YES |
| `_protective_stop_clear_count` | `int` | `0` | Reset to 0 on each True protective_stop; auto-hide debounce is incomplete | no |
| `_protective_stop_logged` | `bool` (dynamic) | unset until first event | True on first protective stop log; False when cleared | no |
| `_position_units` | `Dict[str, str]` | built in `_create_tcp_position_section_compact()` | Read in `_update_position_display()` | no |

### Widget References Stored as `self.<attr>`

**Jog Controls Panel (left, min/max 350px)**

| Attr | Widget type | Purpose |
|------|-------------|---------|
| `cartesian_button` | `QPushButton` (checkable) | Mode toggle: Cartesian |
| `joint_button` | `QPushButton` (checkable) | Mode toggle: Joint |
| `mode_button_group` | `QButtonGroup` | Exclusive mode button group |
| `speed_slider` | `QSlider` (H, 1-100, default 45) | Jog speed (NOT forwarded to controller — see Section 8) |
| `speed_label` | `QLabel` | Displays speed as text |

**Center Panel (position + connection, stretch=1)**

| Attr | Widget type | Purpose |
|------|-------------|---------|
| `tcp_labels` | `Dict[str, QLabel]` (keys: x,y,z,rx,ry,rz) | TCP position display (mm / deg) |
| `joint_labels` | `Dict[str, QLabel]` (keys: j1-j6) | Joint angle display (deg) |
| `ip_value_label` | `QLabel` | Robot IP from config |
| `status_value_label` | `QLabel` | "Connected" / "Disconnected" |
| `connection_button` | `QPushButton` | Connect/Disconnect toggle |
| `settings_button` | `QPushButton` | Opens ConfigDialog |

**Safety Panel (right, min/max 350px)**

| Attr | Widget type | Purpose |
|------|-------------|---------|
| `emergency_button` | `QPushButton` | EMERGENCY STOP |
| `safety_labels` | `Dict[str, QLabel]` (keys: robot_mode, safety_mode, protective_stop, remote_control, robot_error, robot_warning) | Safety status display |
| `recover_btn` | `QPushButton` | Unlock protective stop (visible only in protective stop) |
| `save_home_btn` | `QPushButton` | Save current joints as home |
| `go_to_home_btn` | `QPushButton` | Move to saved home (enabled: home saved AND connected) |
| `demo_button` | `QPushButton` | Navigate to demo selection |
| `quit_button` | `QPushButton` | EXIT APPLICATION |
| `log_display` | `QTextEdit` (read-only) | System event log, max 1000 lines |

**Demo Selection Page (page 1)**

| Attr | Widget type | Purpose |
|------|-------------|---------|
| `demo_page` | `QWidget` | Container for page 1 |

Card buttons are local variables, not `self.`-stored; connected via lambda capturing `demo_id`.

**Loop Demo Page (page 2)**

| Attr | Widget type | Purpose / state |
|------|-------------|----------------|
| `loop_demo_page` | `QWidget` | Container for page 2 |
| `loop_demo_base_offset_spin` | `QSpinBox` (-360..360, step 15, deg) | Audience direction; lineEdit read-only |
| `loop_demo_speed_slider` | `QSlider` (10-100) | Demo speed %; debounced restart |
| `loop_demo_speed_label` | `QLabel` | Speed % display |
| `loop_demo_delay_spin` | `QDoubleSpinBox` (1.0-6.0 s, step 0.5) | Cycle delay; lineEdit read-only |
| `loop_demo_start_btn` | `QPushButton` | Start demo (disabled until home saved) |
| `loop_demo_stop_btn` | `QPushButton` | Stop demo (disabled when stopped) |
| `loop_demo_test_move_btn` | `QPushButton` | Single movej to home for verification |
| `loop_demo_status_label` | `QLabel` (48px bold, color-coded bg) | Current demo phase/status |
| `loop_demo_event_log` | `QPlainTextEdit` (monospace dark bg, max 200 lines) | Timestamped event history |

---

## 3. Page-by-Page Widget Inventory

### Page 0: Main Jog View

Three-panel `QHBoxLayout` in the central container.

#### Left Panel — Jog Controls

| Widget | self. ref | objectName | Signal -> Slot | State? |
|--------|-----------|------------|----------------|--------|
| `QPushButton("Cartesian")` | `cartesian_button` | `jogModeButton` | `clicked` -> `_set_jog_mode("cartesian")` | YES (checked) |
| `QPushButton("Joint")` | `joint_button` | `jogModeButton` | `clicked` -> `_set_jog_mode("joint")` | YES (checked) |
| `QButtonGroup` | `mode_button_group` | n/a | exclusive | YES |
| `QSlider(H, 1-100, default 45)` | `speed_slider` | n/a | `valueChanged` -> `_on_speed_changed` | YES (display only) |
| `QLabel` (speed text) | `speed_label` | n/a | display only | display |
| 12x `QPushButton` (X-/X+ ... Rz-/Rz+) | local vars | `jogButton` | `pressed` -> `_start_jog(axis,dir)`, `released` -> `_stop_jog` | NO |

#### Center Panel — Position Display

| Widget | self. ref | objectName | State? |
|--------|-----------|------------|--------|
| `QGroupBox("TCP Position")` | n/a | `positionPanelGroup` | n/a |
| 6x `QLabel` value (x,y,z,rx,ry,rz) | `tcp_labels[key]` | `valueLabel` | YES (live mm/deg) |
| `QGroupBox("Joint Angles")` | n/a | `positionPanelGroup` | n/a |
| 6x `QLabel` value (j1-j6) | `joint_labels[key]` | `valueLabel` | YES (live deg) |
| `QGroupBox("Connection Status")` | n/a | n/a | n/a |
| `QLabel` (IP) | `ip_value_label` | `connectionIP` | YES |
| `QLabel` (status) | `status_value_label` | `connectionStatus` | YES |
| `QPushButton("Connect")` | `connection_button` | `connectButton`/`disconnectButton` | YES (text+objectName toggled) |
| `QPushButton("Settings")` | `settings_button` | `secondaryButton` | NO |

#### Right Panel — Safety

| Widget | self. ref | objectName | Signal -> Slot | State? |
|--------|-----------|------------|----------------|--------|
| `QPushButton("EMERGENCY\nSTOP")` | `emergency_button` | `emergencyButton` | `clicked` -> `_emergency_stop` | NO |
| 6x `QLabel` (mode/safety/prot/remote/err/warn) | `safety_labels[key]` | n/a | display only | YES (live) |
| `QPushButton("Unlock protective stop")` | `recover_btn` | `warningButton` | `clicked` -> `_recover_protective_stop` | YES (visible flag) |
| `QPushButton("Save as home")` | `save_home_btn` | `secondaryButton` | `clicked` -> `_save_as_home` | NO |
| `QPushButton("Go to home")` | `go_to_home_btn` | `secondaryButton` | `clicked` -> `_go_to_home` | YES (enabled flag) |
| `QPushButton("Demo")` | `demo_button` | `secondaryButton` | `clicked` -> `_show_demo_screen` | NO |
| `QPushButton("EXIT APPLICATION")` | `quit_button` | (inline style) | `clicked` -> `_quit_application` | NO |
| `QTextEdit` (read-only) | `log_display` | n/a | display only | YES (log buffer) |
| `QPushButton("Save log snapshot")` | local var | `secondaryButton` | `clicked` -> `_save_log_snapshot` | NO |

#### Protective Stop Overlay (above all pages, QGridLayout z-order)

| Widget | self. ref | Notes |
|--------|-----------|-------|
| `QFrame` (semi-transparent overlay) | `_protective_stop_overlay` | Hidden by default; shown on protective stop |
| `QPushButton("Unlock protective stop")` | local `unlock_btn` | `clicked` -> `_on_protective_stop_unlock_clicked` |

### Page 1: Demo Selection Screen

- Back button -> `_go_back_from_demo()` -> `stacked.setCurrentIndex(0)`
- `QScrollArea` containing `QGridLayout` of 13 demo cards (2-column)
- `QScroller.grabGesture` for kinetic touch scrolling (try/except guarded)
- Each card `QPushButton` -> `_on_demo_card_clicked(demo_name)`

Demo name to runner class mapping:

| Card name | Runner class | Implemented |
|-----------|-------------|-------------|
| Demo | `DemoRunner` | YES |
| Wave & Greet | `WaveDemo` | YES |
| Bow | `BowDemo` | YES |
| Pendulum | `PendulumDemo` | YES |
| Industrial | `IndustrialDemo` | YES |
| Technical | `TechnicalDemo` | YES |
| Sprint | `SprintDemo` | YES |
| Plunge | `PlungeDemo` | YES |
| Reach | `ReachDemo` | YES |
| Sorting | `SortingDemo` | YES |
| Juggle | `JuggleDemo` | YES |
| Stacking | `StackingDemo` | YES |
| Record & Replay | n/a | NO (shows QMessageBox.information placeholder) |

### Page 2: Loop Demo Runner Screen

- Back button -> `_go_back_from_loop_demo()` -> stops runner if running -> `stacked.setCurrentWidget(demo_page)`
- All state widgets described in Section 2
- Key behavioral rules:
  - `loop_demo_start_btn` enabled only when `bool(self.saved_home_joints)`
  - `loop_demo_stop_btn` enabled only when `runner.is_running()`
  - `loop_demo_test_move_btn` enabled only when not running AND home saved
  - Status label bg: green=running, gray=stopped/idle, blue=complete/done, red=error/fail
  - Event log trims to 200 lines; auto-scrolls on each append
  - Speed slider 450ms debounce triggers stop+restart of running demo

---

## 4. Signals and Slots

### Custom Signals on `ProfessionalMainWindow` — ALL DEAD (never emitted)

| Signal | Parameters | Status |
|--------|-----------|--------|
| `position_updated` | `dict` | Defined, NEVER emitted |
| `safety_status_changed` | `dict` | Defined, NEVER emitted |
| `connection_status_changed` | `bool, str` | Defined, NEVER emitted |

### Widget Signal -> Slot Connection Table

| Source widget | Signal | Slot method | Purpose |
|---------------|--------|-------------|---------|
| `cartesian_button` | `clicked` | `lambda: _set_jog_mode("cartesian")` | Switch to Cartesian jog mode |
| `joint_button` | `clicked` | `lambda: _set_jog_mode("joint")` | Switch to Joint jog mode |
| `speed_slider` | `valueChanged` | `_on_speed_changed` | Update speed label text only |
| 6x neg jog btns | `pressed` | `lambda a=axis,d=-1: _start_jog(a.lower(), d)` | Begin continuous jog negative |
| 6x neg jog btns | `released` | `_stop_jog` | Stop jog |
| 6x pos jog btns | `pressed` | `lambda a=axis,d=1: _start_jog(a.lower(), d)` | Begin continuous jog positive |
| 6x pos jog btns | `released` | `_stop_jog` | Stop jog |
| `connection_button` | `clicked` | `_toggle_connection` | Connect or disconnect robot |
| `settings_button` | `clicked` | `_show_settings` | Open ConfigDialog |
| `emergency_button` | `clicked` | `_emergency_stop` | Send emergency stop |
| `recover_btn` | `clicked` | `_recover_protective_stop` | unlock_protective_stop + close_safety_popup via Dashboard |
| overlay `unlock_btn` | `clicked` | `_on_protective_stop_unlock_clicked` | Recovery + hide overlay after 1500ms |
| `save_home_btn` | `clicked` | `_save_as_home` | Read/validate/persist joints as home |
| `go_to_home_btn` | `clicked` | `_go_to_home` | movej to saved home joints |
| `demo_button` | `clicked` | `_show_demo_screen` | Navigate to demo selection |
| `quit_button` | `clicked` | `_quit_application` | Confirm + QApplication.quit() |
| `save_log_btn` (local) | `clicked` | `_save_log_snapshot` | Write log to timestamped file |
| `back_btn` (demo page) | `clicked` | `_go_back_from_demo` | Return to main (index 0) |
| 13x `card_btn` | `clicked` | `lambda n=demo_id: _on_demo_card_clicked(n)` | Select demo class; navigate to page 2 |
| `back_btn` (loop demo) | `clicked` | `_go_back_from_loop_demo` | Stop runner; return to demo page |
| `loop_demo_speed_slider` | `valueChanged` | local `_on_speed_changed(v)` | Update label + start debounce timer |
| `_speed_slider_debounce` | `timeout` | `_on_speed_slider_settled` | Stop + restart running demo at new speed |
| `loop_demo_start_btn` | `clicked` | `_loop_demo_start` | Instantiate and start demo runner thread |
| `loop_demo_stop_btn` | `clicked` | `_loop_demo_stop` | Stop runner + schedule poll fallback |
| `loop_demo_test_move_btn` | `clicked` | `_loop_demo_test_move` | Single movej to home at low speed |
| `position_timer` (100ms) | `timeout` | `_update_position_display` | Refresh TCP/joint labels at 10 Hz |
| `status_timer` (200ms) | `timeout` | `_update_status_display` | Refresh safety panel at 5 Hz |

### Controller Callbacks Registered in `set_jog_controller()`

| Registration method | Callback | Thread safety |
|--------------------|----------|--------------|
| `controller.add_position_callback` | `_on_position_updated` | UNSAFE: called from bg thread; writes `current_position` dict without lock |
| `controller.add_position_fetched_callback` | `lambda: QTimer.singleShot(0, _refresh_position_from_robot)` | Safe: deferred to main thread |
| `controller.add_connection_callback` | local closure -> `QTimer.singleShot(0, _update_status_display)` when connected | Safe: deferred |

### DemoLogHandler Forwarding

`_install_demo_log_handler()` attaches a `DemoLogHandler` to these Python loggers at INFO level:
- `"DemoRunner"`, `"WebSocketController"`, `"RTDEController"`

`DemoLogHandler.emit()` uses `QTimer.singleShot(0, ...)` for thread-safe main-thread delivery.

---

## 5. Methods Grouped by Purpose

### Layout / Construction

| Method | Line | Purpose |
|--------|------|---------|
| `__init__` | 85 | Init all state; call _setup_ui, _apply_styling, _setup_timers, _connect_signals, _install_demo_log_handler |
| `_setup_ui` | 130 | Build central container with stacked widget + overlay; add 3 pages |
| `_create_jog_controls_panel` | 191 | Left panel QGroupBox |
| `_create_jog_mode_section` | 211 | Cartesian/Joint toggle buttons + QButtonGroup |
| `_create_speed_control_section` | 247 | Speed QSlider (1-100) + label |
| `_create_jog_buttons_section` | 273 | 12 QPushButtons in 6x2 QGridLayout |
| `_create_position_panel` | 316 | Center panel: TCP + joints side-by-side + connection section |
| `_create_tcp_position_section_compact` | 335 | 6 TCP value labels; populates `tcp_labels` and `_position_units` |
| `_create_joint_angles_section_compact` | 366 | 6 joint value labels; populates `joint_labels` |
| `_create_connection_status_section` | 395 | IP label, status label, Connect/Settings buttons |
| `_create_safety_panel` | 440 | Right panel; calls all _create_*_section methods |
| `_create_emergency_section` | 468 | EMERGENCY STOP button |
| `_create_safety_status_section` | 482 | 6 safety labels + recover_btn (hidden initially) |
| `_create_protective_stop_overlay` | 520 | Full-screen QFrame overlay with unlock button |
| `_create_home_section` | 565 | save_home_btn + go_to_home_btn |
| `_create_logs_section` | 585 | log_display QTextEdit + save snapshot button |
| `_create_demo_section` | 607 | demo_button QPushButton |
| `_create_quit_section` | 616 | EXIT APPLICATION button with inline style |
| `_create_demo_screen` | 740 | Page 1: scroll area + 2-col grid of 13 demo cards |
| `_create_loop_demo_screen` | 824 | Page 2: audience offset, speed slider+debounce, delay, start/stop/test, status label, event log |
| `_apply_styling` | 1184 | Concatenate 3 QSS strings from professional_theme; apply to window |
| `_setup_timers` | 1194 | Start position_timer (100ms) and status_timer (200ms) |
| `_connect_signals` | 1204 | **STUB — body is `pass`** |

### Navigation

| Method | Line | Purpose |
|--------|------|---------|
| `_show_demo_screen` | 1157 | stacked.setCurrentWidget(demo_page) |
| `_go_back_from_demo` | 1162 | stacked.setCurrentIndex(0) |
| `_on_demo_card_clicked` | 1167 | Set _active_demo_class; navigate to page 2; or show "not implemented" dialog |
| `_go_back_from_loop_demo` | 1150 | Stop runner if running; stacked.setCurrentWidget(demo_page) |

### Connection / Safety

| Method | Line | Purpose |
|--------|------|---------|
| `_toggle_connection` | 1266 | If connected: disconnect; else: connect(); update UI via _on_connection_status_changed |
| `_emergency_stop` | 1239 | jog_controller.emergency_stop() |
| `_recover_protective_stop` | 1245 | dashboard_client.unlock_protective_stop() + close_safety_popup(); log result |
| `_on_protective_stop_unlock_clicked` | 1260 | _recover_protective_stop(); QTimer.singleShot(1500, overlay.hide) |
| `set_jog_controller` | 1413 | Attach controller; set IP label; register 3 callbacks |
| `_on_connection_status_changed` | 1475 | Update status label + button text/objectName; unpolish/polish; update go_to_home_btn enabled |

### Jog

| Method | Line | Purpose |
|--------|------|---------|
| `_set_jog_mode` | 1209 | Update `current_jog_mode`; call `jog_controller.set_jog_mode()` |
| `_on_speed_changed` | 1216 | Update speed_label text only (speed NOT passed to controller) |
| `_start_jog` | 1223 | Map axis name to index 0-5; call `jog_controller.start_jog(index, direction)` |
| `_stop_jog` | 1233 | Call `jog_controller.stop_jog()` |

### Home Pose

| Method | Line | Purpose |
|--------|------|---------|
| `_save_as_home` | 656 | Read joints from websocket_receiver; reject if all-zero; persist to config + robot_config.yaml; show degree readout dialog |
| `_go_to_home` | 717 | websocket_controller.move_joint(saved_home_joints, speed=0.35, acceleration=0.5, blend=0.0) |

### Demo Runner

| Method | Line | Purpose |
|--------|------|---------|
| `_loop_demo_start` | 1020 | Validate prerequisites; read spinners; instantiate _active_demo_class with full param set; call .start() |
| `_loop_demo_stop` | 1078 | runner.stop(); status "Stopping..."; QTimer.singleShot(500, _loop_demo_check_stopped(0)) |
| `_on_loop_demo_status` | 981 | Update status label text+bg; append to event log; trim to 200 lines; auto-scroll; update button states |
| `_loop_demo_check_stopped` | 1112 | Poll runner.is_running() every 500ms; max 20 attempts (10s); force "Stopped" on timeout |
| `_on_speed_slider_settled` | 1089 | If running: log; _loop_demo_stop(); QTimer.singleShot(900, _restart_after_speed_change) |
| `_restart_after_speed_change` | 1105 | If still running, retry in 300ms (no limit — see Section 8); else _loop_demo_start() |
| `_loop_demo_test_move` | 1125 | Single websocket_controller.move_joint(home, speed=0.2, accel=0.25, blend=0.0) |
| `_on_demo_card_clicked` | 1167 | Set _active_demo_class; navigate to page 2; enable/disable start/test buttons |

### Logging

| Method | Line | Purpose |
|--------|------|---------|
| `add_log_message` | 1372 | Format "[HH:MM:SS] [LEVEL] msg"; append to log_display; trim at 1000 lines from top |
| `_install_demo_log_handler` | 1385 | Attach DemoLogHandler (QTimer.singleShot-based) to DemoRunner/WebSocketController/RTDEController loggers |
| `_save_log_snapshot` | 1397 | Write log_display.toPlainText() to logs/demo_snapshot_<timestamp>.txt |

### Config

| Method | Line | Purpose |
|--------|------|---------|
| `_show_settings` | 1290 | Open ConfigDialog; on Accepted: config.update(new_config); refresh ip_value_label |
| `_save_as_home` | 656 | Also writes saved_home_joints to robot_config.yaml via yaml.dump |

### Position / Status Updates

| Method | Line | Purpose |
|--------|------|---------|
| `_update_position_display` | 1310 | Read current_position dict; format and set tcp_labels (mm) + joint_labels (deg) |
| `_update_status_display` | 1327 | Poll get_robot_status(); update safety_labels; show/hide recover_btn; manage overlay |
| `_on_position_updated` | 1443 | Controller callback (BG THREAD): convert m->mm and rad->deg; store in current_position; call _update_position_display() immediately |
| `_refresh_position_from_robot` | 1435 | Main-thread: read controller get_tcp_pose/get_joint_angles; pass to _on_position_updated |
| `_on_status_updated` | 1471 | **STUB — body is `pass`** |

### Lifecycle

| Method | Line | Purpose |
|--------|------|---------|
| `__init__` | 85 | Construct window; load saved_home_joints from config |
| `set_jog_controller` | 1413 | Late-attach controller (called via QTimer.singleShot(0) from main.py) |
| `closeEvent` | 1503 | Call jog_controller.disconnect() |
| `_quit_application` | 643 | QMessageBox confirm; QApplication.quit() |

---

## 6. External Dependencies

### Imports from `control.*`

| Module | Symbol(s) | Purpose |
|--------|-----------|---------|
| `control.jog_controller` | `JogController` | Main robot controller |
| `control.demo_runner` | `DemoRunner` | Default demo (preset joint loop) |
| `control.wave_demo` | `WaveDemo` | Wave & Greet |
| `control.bow_demo` | `BowDemo` | Bow |
| `control.pendulum_demo` | `PendulumDemo` | Pendulum |
| `control.industrial_demo` | `IndustrialDemo` | Industrial pick-and-place |
| `control.technical_demo` | `TechnicalDemo` | Per-axis capability tour |
| `control.sprint_demo` | `SprintDemo` | Fast lateral |
| `control.plunge_demo` | `PlungeDemo` | Descent/snap-back |
| `control.reach_demo` | `ReachDemo` | Long sweep |
| `control.sorting_demo` | `SortingDemo` | Sorting |
| `control.juggle_demo` | `JuggleDemo` | Juggling rhythm |
| `control.stacking_demo` | `StackingDemo` | Stacking |

### JogController Public Interface Used by UI

| Method / attribute | Used in |
|-------------------|---------|
| `connect() -> bool` | `_toggle_connection` |
| `disconnect()` | `_toggle_connection`, `closeEvent` |
| `connected: bool` | `_toggle_connection`, `_update_status_display` |
| `set_jog_mode(mode: str)` | `_set_jog_mode` |
| `start_jog(axis_index, direction) -> bool` | `_start_jog` |
| `stop_jog() -> bool` | `_stop_jog` |
| `emergency_stop() -> bool` | `_emergency_stop` |
| `get_robot_status() -> Dict` | `_update_status_display` |
| `get_tcp_pose() -> List[float]` | `_refresh_position_from_robot` |
| `get_joint_angles() -> List[float]` | `_refresh_position_from_robot` |
| `add_position_callback(cb)` | `set_jog_controller` |
| `add_position_fetched_callback(cb)` | `set_jog_controller` |
| `add_connection_callback(cb)` | `set_jog_controller` |
| `config: Dict` | `set_jog_controller` (read robot IP) |
| `websocket_controller` | `_go_to_home`, `_loop_demo_start`, `_loop_demo_test_move` |
| `websocket_receiver` | `_save_as_home` |
| `dashboard_client` | `_recover_protective_stop` |

### Imports from `ui.widgets.*`

| Module | Symbol | Purpose |
|--------|--------|---------|
| `ui.widgets.config_dialog` | `ConfigDialog` | Settings dialog (module-level import + re-imported inside `_show_settings`) |

### Imports from `ui.styles.*`

| Module | Symbol | Purpose |
|--------|--------|---------|
| `ui.styles.professional_theme` | `create_professional_stylesheet` | Main application QSS |
| `ui.styles.professional_theme` | `create_jog_mode_buttons_style` | Mode button QSS |
| `ui.styles.professional_theme` | `create_connection_status_style` | Connection status QSS |

### Imports from `PyQt6.*`

| Submodule | Symbols |
|-----------|---------|
| `PyQt6.QtWidgets` | QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSlider, QSpinBox, QDoubleSpinBox, QFrame, QGroupBox, QTextEdit, QPlainTextEdit, QButtonGroup, QScrollArea, QApplication, QMessageBox, QStackedWidget |
| `PyQt6.QtCore` | Qt, QTimer, pyqtSignal, QSize |
| `PyQt6.QtGui` | QFont, QPalette, QColor, QIcon |
| `PyQt6.QtWidgets` (conditional) | QScroller (try/except guarded inside `_create_demo_screen`) |

### Standard Library / Third-party

| Module | Purpose |
|--------|---------|
| `yaml` | Load/save robot_config.yaml in `_save_as_home` |
| `pathlib.Path` | Config file path construction |
| `datetime.datetime` | Log and event log timestamps |
| `logging` | Module logger; DemoLogHandler base class |
| `math` | `math.radians()` inside `_loop_demo_start` |
| `typing` | Optional, Dict, Any, List |

### Config Keys Read from `robot_config.yaml`

| YAML path | Used in | Purpose |
|-----------|---------|---------|
| `ui.window.title` | `_setup_ui` | Window title |
| `ui.window.width` | `_setup_ui` | Initial width (min 1160) |
| `ui.window.height` | `_setup_ui` | Initial height (min 720) |
| `ui.window.fullscreen` | `_setup_ui` | showFullScreen() on launch |
| `robot.ip_address` | `set_jog_controller` | IP label display |
| `demo.saved_home_joints` | `__init__` | Pre-load saved home (6 floats, radians) |
| `demo.base_offset_degrees` | `_create_loop_demo_screen` | Initial audience offset spinbox value |
| `demo.waypoint_delay_s` | `_create_loop_demo_screen` | Initial cycle delay spinbox value |
| `demo.blend_radius_rad` | `_loop_demo_start` | Passed to demo runner |
| `demo.send_interval_s` | `_loop_demo_start` | Passed to demo runner |
| `demo.joint_acceleration` | `_loop_demo_start` | Passed to demo runner |

---

## 7. Functional Requirements List

### Critical (operator must have to use the robot at all)

- **Connect / Disconnect:** Single button toggles all three robot interfaces (primary TCP 30001, realtime 30003, dashboard 29999); button changes text and color on state change.
- **Emergency Stop:** Large dedicated button always visible on main page; calls `emergency_stop()` via primary interface AND dashboard.
- **Protective Stop detection:** 5 Hz polling of `robot_status['protective_stopped']`; full-screen modal overlay appears automatically; `recover_btn` shown in safety panel.
- **Protective Stop recovery:** Overlay unlock button and safety panel button both call `unlock_protective_stop()` + `close_safety_popup()` via Dashboard.
- **Cartesian jog (X, Y, Z, Rx, Ry, Rz):** Press-and-hold buttons for all 6 axes; continuous mode; stop on release.
- **Joint jog (J1-J6):** Same 6-axis press-and-hold pattern; mode toggled by Cartesian/Joint buttons.
- **Jog mode switch:** Exclusive button group; calls `jog_controller.set_jog_mode()` immediately.
- **Safety status display:** robot_mode, safety_mode, protective_stop, remote_control, robot_error, robot_warning shown and updated at 5 Hz.
- **TCP and joint position display:** Both panels updated at 10 Hz; values in mm (TCP XYZ) and degrees (TCP Rx/Ry/Rz and all joints).

### Important (operators rely on daily)

- **Save as home:** Reads live joint angles; rejects all-zero values (data not yet received); persists 6 floats to `robot_config.yaml`; shows degree readout dialog for operator verification against teach pendant.
- **Go to home:** `move_joint()` at speed=0.35, accel=0.5; button disabled until home saved AND connected.
- **Test move:** Single `move_joint()` to home at lower speed (0.2/0.25) to verify robot responds to commands.
- **Save log snapshot:** Writes full log panel text to `logs/demo_snapshot_<timestamp>.txt`.
- **Audience direction control:** Base offset spinbox (±360 deg, step 15 deg) applied as `audience_offset_rad` at demo start.
- **Demo speed slider (10-100%):** `speed_scale` fed to demo runner on start; triggers stop+restart (450ms debounce) when demo is already running.
- **Cycle delay control:** `waypoint_delay_s` (1.0-6.0 s) passed to demo runner.
- **All 12 runnable demos reachable:** Each card navigates to runner page and sets correct `_active_demo_class`.
- **Demo start/stop with poll fallback:** `runner.start()` / `runner.stop()` with 20-poll/10s fallback chain.
- **Live event log on demo page:** Timestamped QPlainTextEdit, max 200 lines, auto-scroll, color-coded status label.
- **System log panel:** QTextEdit in right panel; receives `add_log_message()` and forwarded demo/controller records; max 1000 lines.
- **Settings dialog (5 tabs):** Robot Connection, Jogging, Safety, Interface, Error recovery; saves to in-memory config on Accept.
- **Error recovery tab:** Four Dashboard commands when connected: unlock protective stop, close safety popup, close popup, restart safety.

### Nice-to-have

- **Log auto-trim:** `log_display` trims at 1000 lines; `loop_demo_event_log` trims at 200 lines.
- **Status color coding:** `connection_button` objectName drives CSS color; demo status label bg codes phase.
- **Kinetic touch scrolling:** `QScroller.grabGesture` on demo card scroll area (silently skipped if unavailable).
- **Spinner read-only line edits:** Audience offset and delay spinners have `lineEdit().setReadOnly(True)` — touch only.
- **Minimum window size enforcement:** `setMinimumSize(1160, 720)` prevents three-panel collapse.

---

## 8. Risks and Gotchas for Migration

### Thread Safety: Position Callback Race Condition
`_on_position_updated` is registered as a `position_callback` and is called directly from the `JogController._status_loop` background thread. It writes to `self.current_position` (a plain dict) without a lock, while the main thread reads the same dict in `_update_position_display`. This is a data race. The correct pattern (already used for `position_fetched_callback`) is `QTimer.singleShot(0, ...)` or a pyqtSignal. Migration MUST fix this.

### The Stop-Poll Chain (`_loop_demo_check_stopped`)
`_loop_demo_stop()` calls `runner.stop()` then schedules `_loop_demo_check_stopped(attempt=0)` after 500ms. The chain polls `runner.is_running()` every 500ms, up to 20 attempts (10s), then forces "Stopped" in UI regardless. This is intentional defensive coding. Migration must preserve this chain — if the runner thread stalls, the UI must still become usable.

### `_restart_after_speed_change` Has No Iteration Limit
This method calls `QTimer.singleShot(300, self._restart_after_speed_change)` if `runner.is_running()` is still True. Unlike the stop-poll chain, there is no attempt counter. If a runner never stops, this creates an infinite 300ms retry loop. Migration should add a maximum retry count.

### QTimer.singleShot Status Callback Captures Strong `self` Reference
In `_loop_demo_start`:

    status_callback = lambda msg: QTimer.singleShot(0, lambda m=msg: self._on_loop_demo_status(m))

This captures a strong reference to `self`. If the window is destroyed before the timer fires, this will crash. Migration should use a weakref or a proper pyqtSignal.

### Jog Speed Slider Is Not Wired to Controller
`_on_speed_changed(value)` only updates `speed_label` text. The `_start_jog` method calls `jog_controller.start_jog(axis_index, direction)` with no `speed_scale` argument (default is used). The slider has no effect on actual jog speed. Migration must decide: wire the slider properly or remove it.

### Three Dead pyqtSignals
`position_updated`, `safety_status_changed`, `connection_status_changed` are defined but never emitted. All status propagation uses direct method calls and QTimer polling. Remove in migration unless they are to be properly wired.

### `_on_status_updated` and `_connect_signals` Are Stubs
Both have `pass` as their only body line. `_on_status_updated` is never called. `_connect_signals` is called in `__init__` but does nothing. Migration should remove or implement them.

### ConfigDialog Does Not Restart Timers on Rate Change
When the operator changes position/status update rates in the Interface tab, the new Hz values are stored in `config` but `position_timer` and `status_timer` are not restarted. They keep running at the original 100ms/200ms intervals.

### Protective Stop Overlay Has No Auto-Hide on External Clear
The overlay is hidden ONLY when the user clicks "Unlock protective stop" (via `QTimer.singleShot(1500, overlay.hide)`). If the robot clears the protective stop externally (e.g. via teach pendant), the overlay persists indefinitely. `_protective_stop_clear_count` exists but the auto-hide debounce was never completed.

### `saved_home_joints` Zero-Check is a Safety Gate
`_save_as_home` rejects saving when `all(abs(q) < 0.01 for q in joints)` — guards against saving before the robot has sent real position data. `_loop_demo_start` and `_loop_demo_test_move` check `bool(self.saved_home_joints)`. Do not remove these guards in migration.

### Demo Runner Constructor Signature Contract
All 12 runner classes are instantiated with the identical keyword signature from `_loop_demo_start`:

    runner_cls(
        websocket_controller,
        home_joints=..., audience_offset_rad=..., speed_scale=...,
        send_interval_s=..., cycle_delay_s=...,
        joint_speed=..., joint_acceleration=..., blend_radius=...,
        status_callback=...
    )

Any new demo class added must conform to this exact interface.

### SafetyWarningDialog Not in Audited Files
`src/main.py` imports `from ui.safety_warning_dialog import SafetyWarningDialog` and shows it fullscreen before creating the main window. This file is NOT in `src/ui/widgets/` and was not audited. It must be preserved or reimplemented.

### JogController Attached After Window Is Visible
`MainWindow` is shown (`showFullScreen()`) before `jog_controller` is attached. The controller is attached via `QTimer.singleShot(0, attach_jog_controller)` in `main.py`. Every method touching `jog_controller` guards with `if self.jog_controller:`. Migration must maintain this deferred-init pattern or explicitly redesign the startup sequence.

### objectName-Based Dynamic Styling
`_on_connection_status_changed` toggles `connection_button.setObjectName("connectButton")` vs `"disconnectButton"` then calls `style().unpolish(widget); style().polish(widget)` to force CSS re-evaluation. Migration must replicate this unpolish/polish pattern or switch to explicit `setStyleSheet()` per state.

### QScroller Availability Guard
    try:
        from PyQt6.QtWidgets import QScroller
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    except Exception:
        pass

`QScroller` is not available in all PyQt6 builds. The try/except guard must be preserved.

---

*Audit produced from direct SSH reads of all source files. All line numbers reference `src/ui/main_window_professional.py` at 1507 lines as audited. Ready for migration agents to consume.*
