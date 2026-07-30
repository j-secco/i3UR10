# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UR10 Jog Control Interface (i3UR10): a PyQt6 touch-optimized control interface for a Universal Robots UR10, running fullscreen on an Elo i3 touchscreen (host `elo3`). It provides Cartesian and joint jogging, choreographed demo routines, safety monitoring, and protective-stop recovery.

**Version:** 2.0 (v2 UI). The original v1 "professional" UI was removed on 2026-07-30; its full state is preserved at git tag `pre-cleanup-20260730`.

## Running the Application

```bash
# Production entry (what the desktop icon runs)
./launch.sh                    # cd to project root, exec venv python launch_v2.py

# Manual
venv/bin/python launch_v2.py   # fullscreen; Escape quits

# Runtime debug log (safety polling, dashboard connect, recovery)
tail -f /tmp/v2_debug.log
```

The app usually already runs on the touchscreen. Check with `pgrep -af launch_v2` before starting a second instance.

## Debugging Tools (no robot motion)

```bash
# One-shot read of current robot state from the realtime interface
python read_state.py            # optional arg: port (default 30001)

# Offline reach / self-collision map for demo choreography amplitudes
python reach_map.py

# Network connectivity
ping 192.168.10.24
nc -zv 192.168.10.24 30001      # Primary interface
nc -zv 192.168.10.24 29999      # Dashboard
```

## Architecture

### Entry chain
`Desktop icon -> launch.sh -> launch_v2.py -> src/ui/main_window_v2.py (MainWindowV2)`

`launch_v2.py` inserts `src` on `sys.path`, so imports are `ui.*`, `control.*`, `communication.*`.

### Communication layer (`src/communication/`)
- **WebSocketController** (port 30001): URScript execution over the Primary interface; used when `robot.use_rtde_for_motion` is false
- **RTDEController** (port 30004): optional motion backend via ur_rtde (moveJ, moveL, speedJ, speedL, stopScript); selected by `robot.use_rtde_for_motion: true`
- **WebSocketReceiver** (port 30003): high-frequency robot state (TCP pose, joints, safety mode); instantiates **SafetyEventLogger**, which records protective stops with context to `logs/safety_events.log`
- **DashboardClient** (port 29999): power, brake release, unlock protective stop, robot/safety mode queries

### Control layer (`src/control/`)
- **JogController**: orchestrator; owns the controller, receiver, and dashboard client and exposes them to the UI
- **CartesianJog** / **JointJog**: continuous (speedl/speedj) and step (movel/movej) jogging
- **SafetyMonitor**: safety state tracking and emergency handling
- **DemoRunner** plus demo modules: `wave`, `bow`, `pendulum`, `juggle`, `plunge`, `reach`, `sorting`, `sprint`, `stacking`, `technical`, `industrial`

### UI layer (`src/ui/`)
- **main_window_v2.py**: MainWindowV2, safety polling, recovery flow, e-stop wiring
- **theme_v2.py**: QSS themes (light/dark)
- **pages/**: `jog_page`, `demos_page`, `runner_page`, `settings_page`
- **widgets/**: `header_bar`, `footer_bar`, `tab_nav`, `demo_card`, `keypad_dialog`, `recovery_panel`

## Demo Authoring

Read `SMOOTH_MOTION.md` before writing or modifying demos. Key rule: demos run as ONE infinite-loop URScript program (`jsecco_demo_loop`) so the controller never hits a program boundary between moves; per-move sends cause full deceleration and brake clicks. The doc covers the motion API, UI feedback wiring, and a new-demo checklist. Use `reach_map.py` to validate choreography amplitudes against self-collision before running on hardware.

## Configuration

`config/robot_config.yaml` (gitignored; `robot_config.yaml.template` is tracked):

```yaml
robot:
  ip_address: "192.168.10.24"
  use_rtde_for_motion: true    # RTDE (30004) for motion; false = Primary (30001)
```

When `use_rtde_for_motion` is true, `ur_rtde` must be installed in the venv.

## Package Layout Notes

`src/communication/__init__.py` exports WebSocketController, WebSocketReceiver, DashboardClient. `src/control/__init__.py` exports JogController, CartesianJog, JointJog, SafetyMonitor, DemoRunner. Do not remove `__init__.py` files or package imports break. Modules that look unreferenced may be loaded through these package re-exports or via optional imports (SafetyEventLogger inside websocket_receiver.py); verify the full import closure before deleting anything.

## Operational Notes

- Logs: `logs/safety_events.log` (protective stops with joint/TCP context), `/tmp/v2_debug.log` (runtime), `logs/ur10_jog_control.log` (legacy)
- The app and this repo live on `elo3`; the local dev machine connects via SSH host `ur10-wifi` (192.168.10.26) or `armbot` (192.168.10.40)
- Commit and push to `git@github.com:j-secco/i3UR10.git`; recent history exists only if pushed, the Elo box is not backed up
