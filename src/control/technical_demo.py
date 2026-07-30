"""
Technical capabilities-tour demo for UR10.

Engineering showcase: exercises each of the 6 joints individually so an
audience can observe the motion character and range of each axis, followed
by a coordinated multi-axis finale.

Architecture follows bow_demo.py / wave_demo.py exactly:
  - ONE URScript infinite-loop program sent via move_joint_program_loop
  - Every movej has r > 0 (no zero-velocity / brake engagement)
  - Per-waypoint [*joints, v, a, r] 9-element vectors
  - Status callback chain emits segment name before each segment
  - _completed flag set in finally before final _notify("Stopped")

Segment choreography (8 segments per cycle):
  1. J1 Sweep      — base rotation: home → +0.6 → -0.6 → home  (medium speed)
  2. J2 Cycle      — shoulder: home → -0.5 → +0.3 → home        (medium-slow; carries load)
  3. J3 Cycle      — elbow: home → -0.5 → +0.5 → home           (medium)
  4. J4 Cycle      — wrist 1: home → +0.7 → -0.7 → home         (medium-fast; light joint)
  5. J5 Cycle      — wrist 2 pitch: home → -0.7 → +0.7 → home   (medium-fast)
  6. J6 Roll       — wrist 3 full roll: home → +0.85 → -0.85 → home  (fast; show the spin)
  7. Coordinated   — all 6 axes ±0.15 rad around home, fluid multi-axis pattern
  8. Return Home   — blends into next cycle (r=0.05, no brake)

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# ----------------------------- Defaults / safety -----------------------------

DEFAULT_JOINT_SPEED     = 0.35    # rad/s base (scaled by speed_scale per-segment)
DEFAULT_JOINT_ACCEL     = 0.5     # rad/s^2
DEFAULT_BLEND_RADIUS    = 0.10    # rad
DEFAULT_SEND_INTERVAL_S = 0.08    # s between waypoint sends (fallback only)
DEFAULT_CYCLE_DELAY_S   = 1.0     # s between full cycles (no-op in URScript)

# Hard safety caps — never exceeded regardless of config.
MAX_JOINT_SPEED_RAD_S   =  1.0
MAX_JOINT_ACCEL_RAD_S2  =  1.5
MAX_DELTA_FROM_HOME_RAD = 0.9    # per-joint absolute deviation from home

# Per-segment speed multipliers (relative to base joint_speed).
# These encode the "weight" of each joint for an educational audience:
#   J2/J3 slower because they carry more inertia/load
#   J4/J5 medium-fast because they are lighter
#   J6 fastest because the wrist roll is effortless
_J1_SPEED_SCALE        = 1.00    # base rotation — moderate
_J2_SPEED_SCALE        = 0.70    # shoulder — heaviest, medium-slow
_J3_SPEED_SCALE        = 0.90    # elbow — medium
_J4_SPEED_SCALE        = 1.15    # wrist 1 — medium-fast
_J5_SPEED_SCALE        = 1.15    # wrist 2 — medium-fast
_J6_SPEED_SCALE        = 1.30    # wrist 3 — fast (× 1.3 per spec)
_COORD_SPEED_SCALE     = 1.00    # coordinated finale — medium
_RETURN_SPEED_SCALE    = 0.85    # return home — gentle

# Choreography amplitudes (radians).
J1_SWING      = 0.60    # base rotation each direction
J2_FORWARD    = 0.50    # shoulder drop
J2_BACK       = 0.30    # shoulder raise-back (smaller — avoids over-extension)
J3_NEG        = 0.50    # elbow flex negative
J3_POS        = 0.50    # elbow flex positive
J4_POS        = 0.70    # wrist-1 positive
J4_NEG        = 0.70    # wrist-1 negative
J5_NEG        = 0.70    # wrist-2 negative
J5_POS        = 0.70    # wrist-2 positive
J6_POS        = 0.85    # wrist-3 full roll positive
J6_NEG        = 0.85    # wrist-3 full roll negative
COORD_AMP     = 0.15    # coordinated multi-axis amplitude (each axis)


@dataclass
class Segment:
    """One choreography segment — part of the single URScript loop."""
    name: str
    waypoints: List[List[float]]
    speed: float    # rad/s (capped + scaled)
    accel: float    # rad/s^2 (capped)
    blend: float    # rad; cycle's last waypoint gets r=0.05 via flat-path builder


class TechnicalDemo:
    """
    Technical Capabilities Tour: exercises each joint axis individually so an
    engineering audience observes the motion character, then demonstrates
    coordinated multi-axis motion.  Brake-free infinite loop via a single
    URScript program.  Use start() / stop() / is_running().
    """

    def __init__(
        self,
        motion_controller: Any,
        home_joints: List[float],
        audience_offset_rad: float = 0.0,
        speed_scale: float = 0.5,
        send_interval_s: float = DEFAULT_SEND_INTERVAL_S,
        cycle_delay_s: float = DEFAULT_CYCLE_DELAY_S,
        joint_speed: float = DEFAULT_JOINT_SPEED,
        joint_acceleration: float = DEFAULT_JOINT_ACCEL,
        blend_radius: float = DEFAULT_BLEND_RADIUS,
        status_callback: Optional[Callable[[str], None]] = None,
        **_unused: Any,    # absorb extra kwargs from _loop_demo_start
    ):
        self.motion_controller   = motion_controller
        self.home_joints         = list(home_joints)
        self.audience_offset_rad = audience_offset_rad
        self.speed_scale         = max(0.01, min(1.0, speed_scale))
        self.send_interval_s     = max(0.02, send_interval_s)
        self.cycle_delay_s       = max(0.0,  cycle_delay_s)
        self.joint_speed         = joint_speed
        self.joint_acceleration  = joint_acceleration
        self.blend_radius        = blend_radius
        self.status_callback     = status_callback
        self.logger              = logging.getLogger(self.__class__.__name__)

        self._stop_requested     = False
        self._thread: Optional[threading.Thread] = None
        self._completed          = True    # True = not running; checked by is_running()

    # ------------------------------- helpers --------------------------------

    def _notify(self, message: str) -> None:
        self.logger.info("notify -> %s", message)
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as exc:
                self.logger.warning("Status callback error: %s", exc)

    def _connected(self) -> bool:
        ctrl = self.motion_controller
        if hasattr(ctrl, "is_connected"):
            try:
                return bool(ctrl.is_connected())
            except Exception:
                return False
        if hasattr(ctrl, "connected"):
            return bool(getattr(ctrl, "connected", False))
        return True

    def _clamp_waypoint(self, wp: List[float]) -> List[float]:
        """Clamp every joint to within MAX_DELTA_FROM_HOME_RAD of home."""
        out: List[float] = []
        for q, h in zip(wp, self.home_joints):
            lo = h - MAX_DELTA_FROM_HOME_RAD
            hi = h + MAX_DELTA_FROM_HOME_RAD
            out.append(max(lo, min(hi, q)))
        return out

    def _sv(self, seg_scale: float) -> float:
        """Scaled+capped speed for a segment."""
        return min(MAX_JOINT_SPEED_RAD_S, max(0.01, self.joint_speed * self.speed_scale * seg_scale))

    def _sa(self, seg_scale: float) -> float:
        """Scaled+capped acceleration for a segment."""
        return min(MAX_JOINT_ACCEL_RAD_S2, max(0.05, self.joint_acceleration * seg_scale))

    def _pose(self, **deltas) -> List[float]:
        """Build a 6-joint waypoint as home + audience_offset on J1 + per-joint deltas.
        Keys: j1..j6 (any subset). All values added to home_joints."""
        j1, j2, j3, j4, j5, j6 = self.home_joints
        wp = [
            j1 + self.audience_offset_rad + deltas.get("j1", 0.0),
            j2 + deltas.get("j2", 0.0),
            j3 + deltas.get("j3", 0.0),
            j4 + deltas.get("j4", 0.0),
            j5 + deltas.get("j5", 0.0),
            j6 + deltas.get("j6", 0.0),
        ]
        return self._clamp_waypoint(wp)

    # --------------------------- segment definitions ------------------------

    def _build_segments(self) -> List[Segment]:
        """
        Assemble the 8-segment capabilities tour.

        Per-segment speed character (intentional, educational):
          J2/J3: slower (heavy, load-bearing joints)
          J4/J5: medium-fast (light wrist joints)
          J6:    fast × 1.3 (effortless spin — impresses audiences)
          Coordinated finale: medium (smooth fluid motion)

        Blend values:
          - r=0.08 between intermediate waypoints within a segment
          - r=0.05 at segment ends (inter-segment transition)
          - r=0.05 on the very last waypoint of the whole cycle (flat-path builder handles this)
        """
        HOME   = self._pose()                 # exact home with audience offset on J1
        BLEND  = 0.08                         # intermediate blend within a segment
        SEG_END = 0.05                        # blend at end of each segment

        segments: List[Segment] = [

            # ------------------------------------------------------------------
            # Segment 1 — J1 Sweep: base rotation only, all others at home.
            # home → +J1 → -J1 → home.  Medium speed.
            # ------------------------------------------------------------------
            Segment(
                name="J1 Base Sweep",
                waypoints=[
                    self._pose(j1=+J1_SWING),
                    self._pose(j1=-J1_SWING),
                    HOME,
                ],
                speed=self._sv(_J1_SPEED_SCALE),
                accel=self._sa(1.0),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 2 — J2 Shoulder: home → drop → raise-back → home.
            # Medium-slow: J2 carries the arm weight; visible effort/deceleration.
            # ------------------------------------------------------------------
            Segment(
                name="J2 Shoulder",
                waypoints=[
                    self._pose(j2=-J2_FORWARD),
                    self._pose(j2=+J2_BACK),
                    HOME,
                ],
                speed=self._sv(_J2_SPEED_SCALE),
                accel=self._sa(0.8),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 3 — J3 Elbow: home → flex negative → flex positive → home.
            # Medium speed.
            # ------------------------------------------------------------------
            Segment(
                name="J3 Elbow",
                waypoints=[
                    self._pose(j3=-J3_NEG),
                    self._pose(j3=+J3_POS),
                    HOME,
                ],
                speed=self._sv(_J3_SPEED_SCALE),
                accel=self._sa(0.9),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 4 — J4 Wrist 1: home → +0.7 → -0.7 → home.
            # Medium-fast: light joint, snappy transitions.
            # ------------------------------------------------------------------
            Segment(
                name="J4 Wrist-1",
                waypoints=[
                    self._pose(j4=+J4_POS),
                    self._pose(j4=-J4_NEG),
                    HOME,
                ],
                speed=self._sv(_J4_SPEED_SCALE),
                accel=self._sa(1.1),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 5 — J5 Wrist 2 (pitch): home → -0.7 → +0.7 → home.
            # Medium-fast: light wrist pitch joint.
            # ------------------------------------------------------------------
            Segment(
                name="J5 Wrist-2 Pitch",
                waypoints=[
                    self._pose(j5=-J5_NEG),
                    self._pose(j5=+J5_POS),
                    HOME,
                ],
                speed=self._sv(_J5_SPEED_SCALE),
                accel=self._sa(1.1),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 6 — J6 Wrist 3 (roll): home → +0.85 → -0.85 → home.
            # Fast (× 1.3): show the effortless high-speed spin of the end-effector.
            # ------------------------------------------------------------------
            Segment(
                name="J6 Wrist-3 Roll",
                waypoints=[
                    self._pose(j6=+J6_POS),
                    self._pose(j6=-J6_NEG),
                    HOME,
                ],
                speed=self._sv(_J6_SPEED_SCALE),
                accel=self._sa(1.2),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 7 — Coordinated: all 6 axes move simultaneously.
            # 4-waypoint pattern: each axis offset with varying phase so the
            # overall motion appears fluid and non-trivially coordinated.
            # Medium speed.
            # ------------------------------------------------------------------
            Segment(
                name="Coordinated Multi-Axis",
                waypoints=[
                    # Waypoint A: J1+, J2-, J3+, J4+, J5-, J6+
                    self._pose(
                        j1=+COORD_AMP,
                        j2=-COORD_AMP,
                        j3=+COORD_AMP,
                        j4=+COORD_AMP,
                        j5=-COORD_AMP,
                        j6=+COORD_AMP,
                    ),
                    # Waypoint B: J1-, J2+, J3-, J4-, J5+, J6-  (full phase flip)
                    self._pose(
                        j1=-COORD_AMP,
                        j2=+COORD_AMP,
                        j3=-COORD_AMP,
                        j4=-COORD_AMP,
                        j5=+COORD_AMP,
                        j6=-COORD_AMP,
                    ),
                    # Waypoint C: partial phase, creates non-linear fluid path
                    self._pose(
                        j1=+COORD_AMP * 0.6,
                        j2=-COORD_AMP * 0.5,
                        j3=+COORD_AMP * 0.7,
                        j4=-COORD_AMP * 0.4,
                        j5=+COORD_AMP * 0.3,
                        j6=-COORD_AMP * 0.8,
                    ),
                    HOME,
                ],
                speed=self._sv(_COORD_SPEED_SCALE),
                accel=self._sa(1.0),
                blend=BLEND,
            ),

            # ------------------------------------------------------------------
            # Segment 8 — Return Home: explicit landing with r=0.05 (cycle-end
            # blend).  The flat-path builder forces the last waypoint's r to 0.05
            # so this loops seamlessly into Segment 1 with no brake click.
            # ------------------------------------------------------------------
            Segment(
                name="Return Home",
                waypoints=[HOME],
                speed=self._sv(_RETURN_SPEED_SCALE),
                accel=self._sa(0.8),
                blend=SEG_END,   # overridden to 0.05 by flat-path builder for cycle wrap
            ),
        ]
        return segments

    # -------------------------------- runner --------------------------------

    def _run_loop(self) -> None:
        final_msg = "Stopped"
        try:
            if len(self.home_joints) != 6:
                final_msg = "Invalid home"
                return
            if not self._connected():
                final_msg = "Disconnected"
                self.logger.warning("Technical demo not started: motion controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "Technical demo started: speed_scale=%.2f, audience_offset=%.3f rad",
                self.speed_scale, self.audience_offset_rad,
            )

            ctrl     = self.motion_controller
            has_loop = hasattr(ctrl, "move_joint_program_loop")
            has_prog = hasattr(ctrl, "move_joint_program")
            has_stop = hasattr(ctrl, "stop_motion")

            segments = self._build_segments()

            # Estimate per-segment UI display durations (Python-side clock only).
            seg_durations = []
            for seg in segments:
                raw = self._estimate_duration(seg.waypoints, seg.speed)
                if seg.blend > 0 and len(seg.waypoints) >= 2:
                    raw *= 0.35
                seg_durations.append(max(0.35, raw + 0.1))

            # Build flat per-waypoint param list: [j1..j6, v, a, r].
            # Rule: every r > 0.  The very last waypoint of the cycle gets r=0.05
            # so the while-True loop blends into the next iteration with no brake.
            big_path: List[List[float]] = []
            last_seg_idx = len(segments) - 1
            for i, seg in enumerate(segments):
                last_wp_idx = len(seg.waypoints) - 1
                for j, wp in enumerate(seg.waypoints):
                    if j == last_wp_idx and i == last_seg_idx:
                        r = 0.05                       # cycle-end blend — no zero-velocity
                    elif j == last_wp_idx:
                        r = max(0.05, seg.blend * 0.6) # inter-segment transition
                    else:
                        r = seg.blend                  # intra-segment blend
                    big_path.append([*wp, seg.speed, seg.accel, r])

            if has_loop:
                # Preferred: ONE infinite-loop URScript program — no brake clicks.
                ok = ctrl.move_joint_program_loop(big_path, self.cycle_delay_s)
                if not ok:
                    final_msg = "Command failed"
                    return
                # Worker loop drives only the Python status-notify clock.
                while not self._stop_requested:
                    for i, seg in enumerate(segments):
                        if self._stop_requested:
                            break
                        self._notify(f"({i+1}/{len(segments)}) {seg.name}")
                        self._sleep_interruptible(seg_durations[i])
                    if self._stop_requested:
                        break
                    if self.cycle_delay_s > 0:
                        self._sleep_interruptible(self.cycle_delay_s)
                if has_stop:
                    try:
                        ctrl.stop_motion(2.0)
                        time.sleep(0.6)
                    except Exception as exc:
                        self.logger.debug("stop_motion failed: %s", exc)

            elif has_prog:
                # Per-cycle program fallback (one brake click per cycle).
                while not self._stop_requested:
                    ok = ctrl.move_joint_program(big_path)
                    if not ok:
                        final_msg = "Command failed"
                        return
                    for i, seg in enumerate(segments):
                        if self._stop_requested:
                            break
                        self._notify(f"({i+1}/{len(segments)}) {seg.name}")
                        self._sleep_interruptible(seg_durations[i])
                    if self._stop_requested:
                        break
                    if self.cycle_delay_s > 0:
                        self._sleep_interruptible(self.cycle_delay_s)
                if has_stop:
                    try:
                        ctrl.stop_motion(2.0)
                        time.sleep(0.6)
                    except Exception as exc:
                        self.logger.debug("stop_motion failed: %s", exc)

            else:
                # Oldest fallback: per-segment send.
                while not self._stop_requested:
                    for i, seg in enumerate(segments):
                        if self._stop_requested:
                            break
                        self._notify(f"({i+1}/{len(segments)}) {seg.name}")
                        if not self._send_path(seg.waypoints, seg.speed, seg.accel, seg.blend):
                            final_msg = "Command failed"
                            return
                        self._sleep_interruptible(seg_durations[i])
                    if self._stop_requested:
                        break
                    if self.cycle_delay_s > 0:
                        self._sleep_interruptible(self.cycle_delay_s)

            # Graceful return to home after stop.
            try:
                self.motion_controller.move_joint(
                    self.home_joints,
                    self._sv(_RETURN_SPEED_SCALE),
                    self._sa(0.8),
                    0.0,
                )
            except Exception as exc:
                self.logger.debug("Return-to-home on stop failed: %s", exc)

        finally:
            # Set _completed BEFORE the final notify so is_running() returns False
            # the instant the UI processes the "Stopped" status update.
            self._completed = True
            self._notify(final_msg)
            self.logger.info("Technical demo stopped")

    def _send_path(self, path, speed, accel, blend):
        """Send path as one URScript program or fall back to per-waypoint."""
        ctrl = self.motion_controller
        if hasattr(ctrl, "move_joint_path"):
            return ctrl.move_joint_path(path, speed, accel, blend)
        last = len(path) - 1
        for i, wp in enumerate(path):
            r = blend if i < last else 0.0
            if not ctrl.move_joint(wp, speed, accel, r):
                return False
            time.sleep(self.send_interval_s)
        return True

    @staticmethod
    def _estimate_duration(path, speed):
        """Conservative estimate: sum dominant-axis deltas / speed."""
        if len(path) < 2 or speed <= 0:
            return 0.0
        total = 0.0
        for a, b in zip(path[:-1], path[1:]):
            total += max(abs(x - y) for x, y in zip(a, b)) / speed
        return total

    def _sleep_interruptible(self, seconds):
        """Sleep in small increments so stop() takes effect quickly."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop_requested:
            time.sleep(0.05)

    # -------------------------------- public API ----------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        if len(self.home_joints) != 6:
            self.logger.error("home_joints must have 6 elements")
            return False
        self._stop_requested = False
        self._completed      = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
