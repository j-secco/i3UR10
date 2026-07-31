"""
Bow showcase demo for UR10 (bare flange).

Ceremonial bow choreography: turn to audience, lift slightly, perform a slow
deliberate bow, hold the bowed position with micro-active motion to prevent
brake engagement, recover, and return home — then loop continuously.

Architecture mirrors wave_demo.py exactly:
  - ONE URScript infinite-loop program sent via move_joint_program_loop
  - Every movej has r > 0 (no zero-velocity / brake engagement)
  - Per-waypoint [*joints, v, a, r] 9-element vectors
  - Status callback chain emits segment name before each segment
  - _completed flag set in finally before final _notify("Stopped")

Author: jsecco (R)
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# ----------------------------- Defaults / safety -----------------------------

DEFAULT_JOINT_SPEED      = 0.35   # rad/s base (scaled by speed_scale per-segment)
DEFAULT_JOINT_ACCEL      = 0.5    # rad/s^2
DEFAULT_BLEND_RADIUS     = 0.10   # rad
DEFAULT_SEND_INTERVAL_S  = 0.08   # s (fallback only)
DEFAULT_CYCLE_DELAY_S    = 1.0    # s between full cycles

# Hard safety caps — never exceeded regardless of config.
MAX_JOINT_SPEED_RAD_S    =  2.5
MAX_JOINT_ACCEL_RAD_S2   =  5.5
MAX_DELTA_FROM_HOME_RAD  = 0.9   # per-joint absolute deviation from home

# Choreography amplitudes (radians).
AUDIENCE_TURN_RAD    = 0.0    # caller supplies audience_offset_rad; no extra offset needed
SHOULDER_PRE_RAD     = 0.20   # J2 small raise before bow (shoulder up)
BOW_SHOULDER_RAD     = 0.40   # J2 further raise into bow (total J2 rise = PRE + this)
BOW_ELBOW_RAD        = 0.50   # J3 elbow fold during bow
BOW_WRIST_DOWN_RAD   = 0.40   # J5 wrist tilt toward floor during bow
HOLD_WIGGLE_RAD      = 0.010  # J5 micro-wiggle amplitude to keep controller active


@dataclass
class Segment:
    """One choreography segment — executed as part of one big URScript loop."""
    name: str
    waypoints: List[List[float]]
    speed: float    # rad/s (will be capped + scaled)
    accel: float    # rad/s^2 (will be capped)
    blend: float    # rad; intra-segment blend; cycle's last point always r=0.05


class BowDemo:
    """
    Ceremonial Bow: turn to audience, lift, bow slowly, hold (active),
    recover, return home, repeat.  Brake-free infinite loop via a single
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
        **_unused: Any,   # absorb extra kwargs from _loop_demo_start
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
        self._completed          = True   # True = not running; checked by is_running()

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

    def _scaled_speed(self, base: float) -> float:
        return min(MAX_JOINT_SPEED_RAD_S, max(0.01, base * self.speed_scale))

    @staticmethod
    def _capped_accel(base: float) -> float:
        return min(MAX_JOINT_ACCEL_RAD_S2, max(0.05, base))

    # ------------------------------ pose helpers ----------------------------

    def _pose(self, **deltas) -> List[float]:
        """Build a 6-joint waypoint as home + audience_offset on J1 + per-joint deltas.
        Keys: j1, j2, j3, j4, j5, j6 (any subset)."""
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
        Assemble the bow choreography.  Blend values are per-segment defaults;
        the flat-path builder overrides the very last waypoint of the whole
        cycle to r=0.05 so the loop blends seamlessly into the next iteration.

        Segment list:
          1. Address  — face audience (J1 audience offset already in _pose; may be 0)
          2. Lift     — small shoulder rise to "presentation" stance
          3. Bow      — slow deliberate forward lean (J2 up, J3 fold, J5 down)
          4. Hold     — three micro-wiggle waypoints keep URScript active at bow apex
          5. Recover  — mirror of bow, return to lift pose
          6. Untwist  — lower arm back to home
        """
        b_speed = self.joint_speed
        b_accel = self.joint_acceleration

        # ---- reusable poses -------------------------------------------------
        home = self._pose()

        # "Addressed" pose: J1 already rotated via audience_offset in _pose().
        addressed = self._pose()  # identical to home when audience_offset==0; named for clarity

        # Presentation lift: J2 rises slightly, J3 folds gently.
        lifted = self._pose(
            j2=+SHOULDER_PRE_RAD,
            j3=+BOW_ELBOW_RAD * 0.25,
        )

        # Full bow apex: J2 total rise, J3 deep fold, J5 wrist tips toward floor.
        bowed = self._pose(
            j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD),
            j3=+BOW_ELBOW_RAD,
            j5=+BOW_WRIST_DOWN_RAD,
        )

        # Hold micro-wiggle waypoints (±HOLD_WIGGLE_RAD on J5, near-zero speed).
        # Three waypoints: neutral → +wiggle → -wiggle → back to neutral
        # These run so slowly the arm appears completely still to observers.
        hold_neutral = self._pose(
            j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD),
            j3=+BOW_ELBOW_RAD,
            j5=+BOW_WRIST_DOWN_RAD,
        )
        hold_plus = self._pose(
            j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD),
            j3=+BOW_ELBOW_RAD,
            j5=+BOW_WRIST_DOWN_RAD + HOLD_WIGGLE_RAD,
        )
        hold_minus = self._pose(
            j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD),
            j3=+BOW_ELBOW_RAD,
            j5=+BOW_WRIST_DOWN_RAD - HOLD_WIGGLE_RAD,
        )

        # ---- segments -------------------------------------------------------

        segments: List[Segment] = [
            # 1. Address — turn J1 to face audience (audience_offset already baked in).
            Segment(
                name="Address",
                waypoints=[addressed],
                speed=self._scaled_speed(b_speed * 0.8),
                accel=self._capped_accel(b_accel * 0.8),
                blend=0.08,
            ),

            # 2. Lift — shoulder rises to presentation stance, medium speed.
            Segment(
                name="Lift",
                waypoints=[
                    self._pose(j2=+SHOULDER_PRE_RAD * 0.5, j3=+BOW_ELBOW_RAD * 0.1),
                    lifted,
                ],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 1.0),
                blend=0.08,
            ),

            # 3. Bow — slow, deliberate ceremonial lean (speed × 0.5, accel × 0.5).
            Segment(
                name="Bow",
                waypoints=[
                    # Mid-bow: shoulder halfway up, elbow half-folded.
                    self._pose(
                        j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD * 0.5),
                        j3=+BOW_ELBOW_RAD * 0.55,
                        j5=+BOW_WRIST_DOWN_RAD * 0.45,
                    ),
                    bowed,
                ],
                speed=self._scaled_speed(b_speed * 0.50),  # SLOW — ceremonial
                accel=self._capped_accel(b_accel * 0.50),
                blend=0.06,
            ),

            # 4. Hold — micro-wiggle keeps controller active; arm appears motionless.
            Segment(
                name="Hold",
                waypoints=[hold_plus, hold_minus, hold_neutral],
                speed=self._scaled_speed(b_speed * 0.06),  # ~0.021 rad/s — imperceptible
                accel=self._capped_accel(b_accel * 0.30),
                blend=0.05,
            ),

            # 5. Recover — mirror bow back to lifted pose, medium speed.
            Segment(
                name="Recover",
                waypoints=[
                    self._pose(
                        j2=+(SHOULDER_PRE_RAD + BOW_SHOULDER_RAD * 0.5),
                        j3=+BOW_ELBOW_RAD * 0.55,
                        j5=+BOW_WRIST_DOWN_RAD * 0.45,
                    ),
                    lifted,
                ],
                speed=self._scaled_speed(b_speed * 0.75),
                accel=self._capped_accel(b_accel * 0.80),
                blend=0.08,
            ),

            # 6. Untwist — lower arm back to home and release audience turn.
            Segment(
                name="Untwist",
                waypoints=[
                    self._pose(j2=+SHOULDER_PRE_RAD * 0.4),
                    home,
                ],
                speed=self._scaled_speed(b_speed * 0.80),
                accel=self._capped_accel(b_accel * 0.80),
                blend=0.05,  # last waypoint of last segment gets r=0.05 via flat-path builder
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
                self.logger.warning("Bow demo not started: motion controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "Bow showcase started: speed_scale=%.2f, audience_offset=%.3f rad",
                self.speed_scale, self.audience_offset_rad,
            )

            ctrl     = self.motion_controller
            has_loop = hasattr(ctrl, "move_joint_program_loop")
            has_prog = hasattr(ctrl, "move_joint_program")
            has_stop = hasattr(ctrl, "stop_motion")

            segments = self._build_segments()

            # Estimate per-segment UI display durations.
            seg_durations = []
            for seg in segments:
                raw = self._estimate_duration(seg.waypoints, seg.speed)
                if seg.blend > 0 and len(seg.waypoints) >= 2:
                    raw *= 0.35
                seg_durations.append(max(0.35, raw + 0.1))

            # Build flat per-waypoint param list: [j1..j6, v, a, r].
            # Rule: every r > 0.  The very last waypoint of the whole cycle gets
            # r=0.05 so the while-True loop blends into the next iteration with
            # zero brake engagement.
            big_path: List[List[float]] = []
            last_seg_idx = len(segments) - 1
            for i, seg in enumerate(segments):
                last_wp_idx = len(seg.waypoints) - 1
                for j, wp in enumerate(seg.waypoints):
                    if j == last_wp_idx and i == last_seg_idx:
                        r = 0.05          # cycle-end blend — no zero-velocity, no brake
                    elif j == last_wp_idx:
                        r = max(0.05, seg.blend * 0.6)   # inter-segment blend
                    else:
                        r = seg.blend     # intra-segment blend
                    big_path.append([*wp, seg.speed, seg.accel, r])

            if has_loop:
                # Preferred path: ONE infinite-loop URScript program.
                ok = ctrl.move_joint_program_loop(big_path, self.cycle_delay_s)
                if not ok:
                    final_msg = "Command failed"
                    return
                # Worker loop: only drives the status notify clock.
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
                # Per-cycle program (one brake click per cycle, acceptable fallback).
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
                    self._scaled_speed(self.joint_speed * 0.7),
                    self._capped_accel(self.joint_acceleration * 0.7),
                    0.0,
                )
            except Exception as exc:
                self.logger.debug("Return-to-home on stop failed: %s", exc)

        finally:
            # Set _completed BEFORE the final notify so is_running() returns
            # False the instant the UI processes "Stopped".
            self._completed = True
            self._notify(final_msg)
            self.logger.info("Bow showcase stopped")

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
