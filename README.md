# i3UR10 - UR10 Jog Control Interface

A PyQt6 touch-optimized control interface for the Universal Robots UR10, running fullscreen on an Elo i3 touchscreen. Provides Cartesian and joint jogging, choreographed demo routines, live safety monitoring, and protective-stop recovery.

**Author:** jsecco ®
**Version:** 2.0.0
**License:** MIT

## Features

### Robot Control
- **Cartesian jogging**: X, Y, Z, Rx, Ry, Rz with color-coded axes
- **Joint jogging**: individual joint control (J1-J6)
- **Step and continuous modes**: precise steps or smooth held-button motion
- **Demo routines**: wave, bow, pendulum, juggle, plunge, reach, sorting, sprint, stacking, technical, and industrial choreographies, executed as a single looping URScript program for smooth, brake-free motion (see `SMOOTH_MOTION.md`)
- **Emergency stop and recovery**: e-stop wiring plus a guided recovery panel for protective stops

### Communication (four channels to the robot)
- **Primary interface (30001)**: URScript execution
- **RTDE (30004, optional)**: motion via ur_rtde when `use_rtde_for_motion` is enabled; more reliable stop/recovery
- **Real-time data (30003)**: high-frequency TCP pose, joint angles, and safety state
- **Dashboard (29999)**: power, brake release, protective-stop unlock, mode queries

### Safety
- Continuous safety-mode polling with on-screen status
- Protective stops logged with joint/TCP context to `logs/safety_events.log`
- Audible warnings (`assets/sounds/`) and a recovery workflow in the UI

### User Interface (v2)
- Fullscreen PyQt6 interface designed for the Elo i3 touchscreen
- Tabbed pages: Jog, Demos, Runner, Settings
- Light and dark themes, on-screen numeric keypad
- Escape key quits (useful with a keyboard attached)

## Requirements

- Universal Robots UR10 (CB series) reachable over the network
- Elo i3 touchscreen or compatible Linux system
- Python 3.10+, Qt6
- `ur_rtde` if RTDE motion is enabled

## Setup

```bash
git clone git@github.com:j-secco/i3UR10.git
cd i3UR10
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp config/robot_config.yaml.template config/robot_config.yaml
# edit config/robot_config.yaml: set your robot IP and motion backend
```

## Running

```bash
./launch.sh                    # production entry, used by the desktop icon
# or
venv/bin/python launch_v2.py
```

Runtime behaviour (safety polling, dashboard connection, recovery commands) is logged to `/tmp/v2_debug.log`.

### Debugging tools (no robot motion)

```bash
python read_state.py    # one-shot read of current robot state
python reach_map.py     # offline reach / self-collision map for demo amplitudes
ping <robot_ip>
nc -zv <robot_ip> 30001
nc -zv <robot_ip> 29999
```

## Project Structure

```
i3UR10/
├── launch.sh                     # production launcher (desktop icon target)
├── launch_v2.py                  # entry point: loads config, shows MainWindowV2
├── src/
│   ├── communication/
│   │   ├── websocket_controller.py   # URScript over Primary (30001)
│   │   ├── rtde_controller.py        # optional ur_rtde motion backend (30004)
│   │   ├── websocket_receiver.py     # realtime state (30003)
│   │   ├── safety_event_logger.py    # protective-stop context logging
│   │   └── dashboard_client.py       # Dashboard commands (29999)
│   ├── control/
│   │   ├── jog_controller.py         # orchestrator
│   │   ├── cartesian_jog.py / joint_jog.py
│   │   ├── safety_monitor.py
│   │   └── *_demo.py, demo_runner.py # choreographed demos
│   └── ui/
│       ├── main_window_v2.py         # MainWindowV2
│       ├── theme_v2.py               # light/dark QSS
│       ├── pages/                    # jog, demos, runner, settings
│       └── widgets/                  # header, footer, tabs, cards, keypad, recovery
├── config/robot_config.yaml          # local config (gitignored; template tracked)
├── assets/                           # icons, sounds
├── logs/                             # safety_events.log and app logs
├── read_state.py, reach_map.py       # debugging tools
└── SMOOTH_MOTION.md                  # motion architecture and demo authoring guide
```

## Safety Considerations

1. Always ensure proper safety measures when operating the robot
2. Verify workspace clearance before jogging or running demos
3. Keep the physical emergency stop accessible at all times
4. Validate new demo amplitudes with `reach_map.py` before running on hardware
5. Test at low speed before increasing velocities
6. Never bypass safety systems or protective measures

## Troubleshooting

- **Cannot connect**: check `ping <robot_ip>`, ports 30001/29999, and that the robot is in remote control mode
- **Protective stop**: use the in-app recovery panel, or inspect `logs/safety_events.log` for the joint/TCP state and controller messages leading up to the stop
- **Jerky demo motion / brake clicks**: see `SMOOTH_MOTION.md`; demos must run inside the single looping URScript program
- **Display issues**: the app expects a running X/Wayland session on the touchscreen (`DISPLAY=:0`)

## Version History

- **v2.0.0** (2026) - v2 UI: tabbed pages, recovery panel, keypad, themes, demo suite, RTDE motion backend, safety event logging. v1 removed; preserved at tag `pre-cleanup-20260730`.
- **v1.0.0** (2024) - initial WebSocket jogging interface.
