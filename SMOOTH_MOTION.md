# Smooth Continuous Motion — UR10 Jog Control

**Author:** jsecco  
**Project:** i3UR10 — `/home/ur10/Documents/i3UR10/`  
**Last updated:** 2026-05-08

---

## Table of Contents

1. [The Brake-Locking Problem](#1-the-brake-locking-problem)
2. [The Fix: One Infinite-Loop URScript Program](#2-the-fix-one-infinite-loop-urscript-program)
3. [Motion API Reference](#3-motion-api-reference)
4. [Demo Authoring Pattern](#4-demo-authoring-pattern)
5. [UI Feedback Wiring](#5-ui-feedback-wiring)
6. [Adding a New Demo — Checklist](#6-adding-a-new-demo--checklist)

---

## 1. The Brake-Locking Problem

### Symptom

Between waypoints, segments, or cycles you hear an audible **click** from the robot arm — the joints briefly fully decelerate, the controller engages the mechanical brakes, then releases them for the next move. This produces jerky, stuttering motion and is hard on the hardware.

### Root Cause 1 — Program boundary deceleration

UR's URScript blend radius parameter (`r=`) **only blends across moves that exist within a single executing program**. When you send each `movej` as a separate URScript payload over the Primary Interface (port 30001), the controller treats every send as a new program start/end. Between programs the arm must:

1. Decelerate to zero velocity (so it reaches a known safe state)
2. Release the previous motion context
3. Re-parse and begin the new program

The `r=` blend radius has no effect across this boundary — it only allows adjacent moves *inside the same program* to overlap their velocity profiles.

### Root Cause 2 — Firmware brake engagement on zero velocity

UR firmware engages joint brakes after a brief period of zero velocity even when the robot is nominally "active" — including during `sleep()` calls and `sync()`-loop active-wait patterns inside URScript. Inserting a pause at home between cycles (e.g. `sleep(cycle_delay_s)`) is therefore enough to trigger brake engagement, causing the click at the start of the next cycle.

### What does NOT work

```urscript
# BAD — each send is its own program; full decel + brake between sends
movej([0.0, -1.57, 1.57, -1.57, -1.57, 0.0], a=0.4, v=0.2, r=0.05)
# ... Python sends next program here ... click!
movej([0.3, -1.2, 1.3, -1.4, -1.57, 0.0], a=0.4, v=0.2, r=0.05)
```

```urscript
# BAD — sleep inside URScript triggers brake even within one program
def bad_loop():
  while True:
    movej(waypoint_a, a=0.4, v=0.2, r=0.05)
    movej(home,       a=0.3, v=0.15, r=0.0)  # r=0 at home + sleep = click
    sleep(2.0)                                # brake engages here
  end
end
bad_loop()
```

---

## 2. The Fix: One Infinite-Loop URScript Program

### Principle

Send **one single URScript program** that contains `while True` around the entire motion cycle. Every `movej` carries `r > 0` so the controller can blend velocity profiles continuously across all moves, including the wrap-around from the last waypoint back to the first.

Never insert `sleep()` or `sync()` in the URScript loop for cycle pacing — this triggers brakes. Cycle delay is handled in Python (UI layer) only.

### URScript template

```urscript
def jsecco_demo_loop():
  while True:
    # --- segment 1: extend toward audience ---
    movej([0.15, -1.20, 1.45, -1.82, -1.57, 0.15],  a=0.55, v=0.30, r=0.10)
    # --- segment 2: wave right ---
    movej([0.40, -1.35, 1.60, -1.82, -1.57, 0.15],  a=0.55, v=0.35, r=0.10)
    # --- segment 3: wave left ---
    movej([-0.10, -1.35, 1.60, -1.82, -1.57, 0.15], a=0.55, v=0.35, r=0.10)
    # --- return home — r > 0 chains smoothly into next iteration ---
    movej([0.0, -1.57, 1.57, -1.57, -1.57, 0.0],    a=0.30, v=0.15, r=0.05)
  end
end
jsecco_demo_loop()
```

### Critical rules

| Rule | Why |
|---|---|
| Wrap entire cycle in `while True` | One long-lived program; no program-boundary decelerations |
| `r > 0` on **every** `movej`, including the return-to-home | Blends the last move back into the first move of the next iteration |
| No `sleep()` / `sync()` in URScript | These stall velocity → firmware engages brakes |
| `cycle_delay_s` lives only in Python | Used for UI pacing; do NOT pass it into URScript |
| Termination via `stopj(decel)` | Sent through `WebSocketController.stop_motion()`; cleanly aborts the running program |

---

## 3. Motion API Reference

Source: `src/control/websocket_controller.py`

### `WebSocketController.move_joint(joints, speed, acceleration, blend)`

Sends a **single** `movej` program. Legacy convenience method. Uses a single program send, so chaining multiple calls produces brake clicks between them. Use for one-shot positioning only (e.g., moving to a calibration pose before a demo).

```python
controller.move_joint(
    joints=[0.0, -1.57, 1.57, -1.57, -1.57, 0.0],
    speed=0.2,
    acceleration=0.4,
    blend=0.0   # r=0 acceptable here; it is a single isolated move
)
```

### `WebSocketController.move_joint_path(path, speed, acc, blend)`

Sends a **multi-waypoint single program** where every waypoint shares the same `speed`, `acc`, and `blend`. The controller blends smoothly across all waypoints because they live in one program. Uniform parameters make this convenient for scripted paths but inflexible for per-segment tuning.

```python
path = [
    [0.15, -1.20, 1.45, -1.82, -1.57, 0.15],
    [0.40, -1.35, 1.60, -1.82, -1.57, 0.15],
    [0.0,  -1.57, 1.57, -1.57, -1.57, 0.0 ],
]
controller.move_joint_path(path, speed=0.25, acc=0.5, blend=0.08)
```

### `WebSocketController.move_joint_program(waypoints_with_params)`

Like `move_joint_path` but accepts **per-waypoint** velocity, acceleration, and blend. Each row in `waypoints_with_params` is a flat list `[j1, j2, j3, j4, j5, j6, v, a, r]`. The controller still executes it as one program so blending works correctly. Use this when different segments need different speeds (e.g., a fast approach, slow expressive gesture, fast return).

```python
waypoints_with_params = [
    [0.15, -1.20, 1.45, -1.82, -1.57, 0.15,  0.30, 0.55, 0.10],  # extend
    [0.40, -1.35, 1.60, -1.82, -1.57, 0.15,  0.35, 0.55, 0.10],  # wave right
    [0.0,  -1.57, 1.57, -1.57, -1.57, 0.0,   0.15, 0.30, 0.05],  # home
]
controller.move_joint_program(waypoints_with_params)
```

### `WebSocketController.move_joint_program_loop(waypoints_with_params, cycle_delay_s)`

**This is the brake-free workhorse.** Wraps the per-waypoint program in `while True` and sends it as a single long-lived URScript. The arm executes the sequence indefinitely, blending across waypoints and across the loop boundary, with no stops and no brake clicks.

`cycle_delay_s` is accepted for API compatibility with the demo constructor contract but is **currently a no-op** in the URScript; the infinite loop runs as fast as the motion profile allows. UI-level pacing is handled by the status callback timing in the demo class.

```python
controller.move_joint_program_loop(
    waypoints_with_params=waypoints_with_params,
    cycle_delay_s=0.0   # no-op; kept for API compat
)
```

### `WebSocketController.stop_motion(deceleration)`

Sends `stopj(deceleration)` to the robot, aborting the currently running URScript program. The arm decelerates smoothly to a stop at the rate specified (rad/s²). Call this from the demo's `stop()` method to terminate the infinite loop cleanly.

```python
controller.stop_motion(deceleration=0.5)   # 0.5 rad/s² — smooth stop
```

---

## 4. Demo Authoring Pattern

**Canonical reference:** `src/control/wave_demo.py`

Every demo is a self-contained class that the runner page instantiates. Here is the full contract a new demo must satisfy.

### Constructor signature

```python
class GreetDemo:
    def __init__(
        self,
        motion_controller,       # WebSocketController instance
        home_joints,             # list[float] — 6 joint angles for home pose
        audience_offset_rad,     # float — lateral offset applied to wrist joints
        speed_scale,             # float — multiplier 0.0–1.0 applied to all speeds
        joint_speed,             # float — base joint speed (rad/s)
        joint_acceleration,      # float — base joint acceleration (rad/s²)
        blend_radius,            # float — base blend radius (rad)
        cycle_delay_s,           # float — accepted, currently no-op in URScript
        status_callback,         # Callable[[str], None] — UI update hook
        **_unused                # absorb any future kwargs without breaking
    ):
        ...
```

### Required public interface

```python
def start(self) -> bool:
    """Start the demo loop. Returns True if launch succeeded."""
    ...

def stop(self) -> None:
    """Signal the demo to stop; calls stop_motion() on the controller."""
    ...

def is_running(self) -> bool:
    """Return True while the demo thread is active."""
    ...
```

### The `_completed` flag pattern (fixes "Stopping…" stuck bug)

The demo runs in a background thread. The UI polls `is_running()` and reads the last status string. If `_notify("Stopped")` fires before `_completed` is set, the UI may call `is_running()` → True in the same frame that it processes the "Stopped" message, leaving the panel showing "Stopping…" forever.

**Always set `_completed = True` inside a `finally` block BEFORE calling `_notify("Stopped")`:**

```python
def _run(self):
    try:
        self._controller.move_joint_program_loop(self._waypoints, self._cycle_delay_s)
        # ... wait loop or blocking join ...
    finally:
        self._completed = True          # flip first
        self._notify("Stopped")         # UI reads is_running()=False in same frame
```

### Building waypoints with continuous blends

Use a `Segment` dataclass to keep the definition readable, then flatten to the per-waypoint list:

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Segment:
    name: str
    joints: List[float]   # 6 values
    speed: float          # rad/s
    accel: float          # rad/s²
    blend: float          # rad — MUST be > 0 for continuous motion

MAX_JOINT_SPEED_RAD_S   = 0.6
MAX_JOINT_ACCEL_RAD_S2  = 1.0
MAX_DELTA_FROM_HOME_RAD = 0.9

segments = [
    Segment("Extend",     [0.15, -1.20, 1.45, -1.82, -1.57, 0.15], 0.30, 0.55, 0.10),
    Segment("Wave right", [0.40, -1.35, 1.60, -1.82, -1.57, 0.15], 0.35, 0.55, 0.10),
    Segment("Wave left",  [-0.10,-1.35, 1.60, -1.82, -1.57, 0.15], 0.35, 0.55, 0.10),
    Segment("Home",       [0.0,  -1.57, 1.57, -1.57, -1.57, 0.0 ], 0.15, 0.30, 0.05),
]

def _build_waypoints(segments, speed_scale):
    waypoints = []
    for seg in segments:
        v = min(seg.speed * speed_scale, MAX_JOINT_SPEED_RAD_S)
        a = min(seg.accel * speed_scale, MAX_JOINT_ACCEL_RAD_S2)
        r = seg.blend  # blend radius is NOT scaled — keep geometry stable
        assert r > 0, f"Segment '{seg.name}' has r=0 — this will cause a brake click!"
        waypoints.append(seg.joints + [v, a, r])
    return waypoints
```

### Live status notifications

Emit a status string before each segment so the UI panel and event log receive live updates:

```python
N = len(segments)
for i, seg in enumerate(segments):
    self._notify(f"({i+1}/{N}) {seg.name}")
    # ... if needed, insert per-segment pre-positioning logic here ...
```

`_notify` is a thin wrapper around `status_callback`:

```python
def _notify(self, msg: str) -> None:
    if self._status_callback:
        self._status_callback(msg)
```

### Safety caps (enforce in constructor, not just in `_build_waypoints`)

```python
assert 0.0 < speed_scale <= 1.0
# Validate no joint drifts too far from home
for seg in segments:
    for j_demo, j_home in zip(seg.joints, home_joints):
        delta = abs(j_demo - j_home)
        assert delta <= MAX_DELTA_FROM_HOME_RAD, (
            f"Segment '{seg.name}' joint delta {delta:.3f} rad exceeds safety cap"
        )
```

---

## 5. UI Feedback Wiring

The runner page (`src/ui/main_window_professional.py`) already provides all feedback infrastructure. A compliant demo class plugs in automatically.

**Phase panel (`loop_demo_status_label`)** — A large colored label that shows the current status string. It updates on every `_notify()` call via the `status_callback` registered at demo construction time. The background color cycles through defined phase colors (e.g., green for running, amber for stopping, red for error).

**Live event log (`loop_demo_event_log`)** — A scrolling text widget that timestamps every `_notify()` string. Useful for post-run review and debugging segment timing. No extra code needed in the demo class.

**Poll-based fallback (`_loop_demo_check_stopped`)** — A periodic timer in the UI that calls `runner.is_running()`. If it returns `False`, the UI force-flips the panel to the "Stopped" state regardless of whether the final `_notify("Stopped")` was processed. This handles any cross-thread deliver-glitch edge cases. Combined with the `_completed`-before-notify pattern, the UI always reaches a clean stopped state.

**Speed slider** — Maps 10–100% to a `speed_scale` float injected at demo construction. Changing it mid-run has no effect on the running URScript program (it is baked in at `move_joint_program_loop` call time); the new value applies on the next Start.

**Audience-direction spinbox** — Provides `audience_offset_rad`. Demo classes use this to rotate wrist joints so gestures face the audience rather than a fixed direction.

**Cycle-delay spinbox** — Provides `cycle_delay_s`. Currently a no-op in URScript; retained for future use (e.g., a sleep-free pause implemented via an extra slow-blend waypoint at home).

---

## 6. Adding a New Demo — Checklist

1. **Create the demo file** — `src/control/<name>_demo.py` implementing the contract from Section 4. Use `wave_demo.py` as your template; copy it and rename the class.

2. **Register in the runner** — In `src/ui/main_window_professional.py`, find `_on_demo_card_clicked`. Add an entry to the `runnable` mapping:
   ```python
   runnable = {
       "Wave & Greet": WaveDemo,
       "Your New Demo": YourNewDemo,   # add here
   }
   ```

3. **Add the card** — In `_create_demo_screen`, add an entry to the `demos` list:
   ```python
   demos = [
       {"label": "Wave & Greet", "description": "Friendly wave cycle toward audience"},
       {"label": "Your New Demo", "description": "One-line description for the card"},
   ]
   ```

4. **Import the class** — Add the import near the top of `main_window_professional.py`:
   ```python
   from src.control.your_new_demo import YourNewDemo
   ```

5. **Validate waypoints offline** — Before running on the physical robot, print the `_build_waypoints()` output and verify all `r > 0` values and that joint deltas are within `MAX_DELTA_FROM_HOME_RAD = 0.9` rad.

6. **Test** — Relaunch the desktop icon, tap **Demo → Your New Demo → Start**. Watch the phase panel and event log for correct segment sequencing. Verify no audible brake clicks between iterations.

---

## Quick Reference: Why Each Parameter Matters

| Parameter | Where set | Effect on motion |
|---|---|---|
| `v` (joint_speed) | Per waypoint in `Segment` | Peak velocity; higher = faster but less smooth at low `r` |
| `a` (joint_accel) | Per waypoint in `Segment` | Ramp rate; too high feels jerky, too low = slow transitions |
| `r` (blend_radius) | Per waypoint — **never 0** | Overlap radius; larger = smoother corners, less precise waypoint reach |
| `speed_scale` | UI slider → constructor | Linear scale on v and a; does not affect r |
| `audience_offset_rad` | UI spinbox → constructor | Added to wrist joints to face gestures toward audience |
| `cycle_delay_s` | UI spinbox → constructor | No-op in URScript; available for future use |
| `deceleration` in `stop_motion` | Demo `stop()` | Braking rate on abort; 0.3–0.8 rad/s² is typical |

---

*End of document.*
