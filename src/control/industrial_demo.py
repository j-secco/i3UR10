"""
Industrial pick-and-place pantomime demo for UR10 (bare flange).

Mimics a two-station industrial cycle: approach pickup zone → descend →
grasp hold → lift → transport to place zone → descend → release hold →
retreat → home, repeating indefinitely.

Architecture mirrors bow_demo.py exactly:
  - ONE URScript infinite-loop program sent via move_joint_program_loop
  - Every movej has r > 0 (no zero-velocity / brake engagement)
  - Per-waypoint [*joints, v, a, r] 9-element vectors
  - Status callback chain emits segment name before each segment
  - _completed flag set in finally before final _notify("Stopped")

Speed dynamics:
  - Descend / ascend segments: speed_scale × 0.5  (slow, careful)
  - Grasp / release hold:      speed_scale × 0.06 (imperceptible micro-wiggle)
  - Transport swing:           speed_scale × 1.3  (fast, confident)
  - Approach / address:        speed_scale × 0.9  (medium)
  - Retreat / home:            speed_scale × 0.8  (medium-slow)

Author: jsecco
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
DEFAULT_CYCLE_DELAY_S    = 0.0    # s (URScript loop; no sleep needed)

# Hard safety caps — never exceeded regardless of config.
MAX_JOINT_SPEED_RAD_S    =  2.5
MAX_JOINT_ACCEL_RAD_S2   =  5.5
MAX_DELTA_FROM_HOME_RAD  = 0.9   # per-joint absolute deviation from home

# Choreography amplitudes (radians) — tuned to stay inside safety cap on every joint.
PICKUP_J1_OFFSET_RAD   = -0.40   # J1 rotation toward pickup station
PLACE_J1_OFFSET_RAD    = +0.40   # J1 rotation toward place station
APPROACH_J2_RAD        = -0.20   # J2 delta for approach posture (shoulder back)
APPROACH_J3_RAD        = +0.20   # J3 delta for approach posture (elbow forward)
APPROACH_J5_RAD        = -0.20   # J5 wrist tilt down (approach / above-pick)
DESCEND_J2_RAD         = -0.30   # additional J2 delta on descent (arm lowers)
DESCEND_J3_RAD         = +0.40   # additional J3 delta on descent (elbow folds more)
HOLD_WIGGLE_RAD        = 0.010   # J6 micro-wiggle amplitude — imperceptible


@dataclass
class Segment:
    """One choreography segment — executed as part of one big URScript loop."""
    name: str
    waypoints: List[List[float]]
    speed: float    # rad/s (will be capped + scaled)
    accel: float    # rad/s^2 (will be capped)
    blend: float    # rad; intra-segment blend; cycle's last point always r=0.05


class IndustrialDemo:
    """
    Industrial Pick-and-Place: address pickup zone, descend, grasp hold,
    lift, transport to place zone, descend, release hold, retreat, home.
    Brake-free infinite loop via a single URScript program.
    Use start() / stop() / is_running().
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
        Assemble the pick-and-place choreography.  Blend values are per-segment
        defaults; the flat-path builder overrides the very last waypoint of the
        whole cycle to r=0.05 so the loop blends seamlessly into the next
        iteration (no brake engagement).

        9-segment cycle:
          1. Address Pickup  — J1 swings toward pickup station, approach posture
          2. Approach        — wrist tilts down, arm settles above pickup point
          3. Descend         — slow descent: J2 down, J3 folds (arm reaches down)
          4. Grasp Hold      — 3 micro-wiggle waypoints on J6 (~imperceptible)
          5. Lift            — slow reverse of descent back to approach posture
          6. Transport       — FAST J1 swing to place station (confident industrial)
          7. Descend Place   — same slow descent pattern at place station
          8. Release Hold    — 3 micro-wiggle waypoints on J6 (gripper open sim)
          9. Retreat & Home  — lift, untwist, return to home (cycle-end blend r=0.05)
        """
        b_speed = self.joint_speed
        b_accel = self.joint_acceleration

        # ---- reusable poses -------------------------------------------------
        home = self._pose()

        # Approach posture shared by both stations (J1 adjusted per station).
        approach_pickup = self._pose(
            j1=PICKUP_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD,
            j3=APPROACH_J3_RAD,
        )
        above_pickup = self._pose(
            j1=PICKUP_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD,
            j3=APPROACH_J3_RAD,
            j5=APPROACH_J5_RAD,
        )
        at_pickup = self._pose(
            j1=PICKUP_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
        )
        above_place = self._pose(
            j1=PLACE_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD,
            j3=APPROACH_J3_RAD,
            j5=APPROACH_J5_RAD,
        )
        at_place = self._pose(
            j1=PLACE_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
        )

        # Grasp hold — 3 waypoints: +wiggle → -wiggle → neutral (J6 micro-oscillation)
        grasp_plus = self._pose(
            j1=PICKUP_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
            j6=+HOLD_WIGGLE_RAD,
        )
        grasp_minus = self._pose(
            j1=PICKUP_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
            j6=-HOLD_WIGGLE_RAD,
        )

        # Release hold — same pattern at place station
        release_plus = self._pose(
            j1=PLACE_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
            j6=+HOLD_WIGGLE_RAD,
        )
        release_minus = self._pose(
            j1=PLACE_J1_OFFSET_RAD,
            j2=APPROACH_J2_RAD + DESCEND_J2_RAD,
            j3=APPROACH_J3_RAD + DESCEND_J3_RAD,
            j5=APPROACH_J5_RAD,
            j6=-HOLD_WIGGLE_RAD,
        )

        # ---- segments -------------------------------------------------------

        segments: List[Segment] = [

            # 1. Address Pickup — turn J1 toward pickup station, adopt approach posture.
            Segment(
                name="Address Pickup",
                waypoints=[approach_pickup],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 0.9),
                blend=0.08,
            ),

            # 2. Approach — wrist tilts down, arm settles above pickup point.
            Segment(
                name="Approach",
                waypoints=[above_pickup],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 0.9),
                blend=0.08,
            ),

            # 3. Descend — slow careful descent to grasp position.
            Segment(
                name="Descend",
                waypoints=[at_pickup],
                speed=self._scaled_speed(b_speed * 0.5),   # SLOW
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.05,
            ),

            # 4. Grasp Hold — micro-wiggle on J6; arm appears motionless.
            Segment(
                name="Grasp",
                waypoints=[grasp_plus, grasp_minus, at_pickup],
                speed=self._scaled_speed(b_speed * 0.06),  # ~imperceptible
                accel=self._capped_accel(b_accel * 0.30),
                blend=0.05,
            ),

            # 5. Lift — slow reverse of descent back to above-pickup posture.
            Segment(
                name="Lift",
                waypoints=[above_pickup],
                speed=self._scaled_speed(b_speed * 0.5),   # SLOW
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.08,
            ),

            # 6. Transport — FAST J1 swing to place station (confident industrial).
            Segment(
                name="Transport",
                waypoints=[above_place],
                speed=self._scaled_speed(b_speed * 1.3),   # FAST
                accel=self._capped_accel(b_accel * 1.3),
                blend=0.10,
            ),

            # 7. Descend Place — slow descent at place station.
            Segment(
                name="Descend Place",
                waypoints=[at_place],
                speed=self._scaled_speed(b_speed * 0.5),   # SLOW
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.05,
            ),

            # 8. Release Hold — micro-wiggle on J6 simulating gripper opening.
            Segment(
                name="Release",
                waypoints=[release_plus, release_minus, at_place],
                speed=self._scaled_speed(b_speed * 0.06),  # ~imperceptible
                accel=self._capped_accel(b_accel * 0.30),
                blend=0.05,
            ),

            # 9. Retreat & Home — lift from place, untwist, return home.
            #    Last waypoint = home with r=0.05 (via flat-path builder) to blend
            #    seamlessly into next cycle iteration.
            Segment(
                name="Home",
                waypoints=[above_place, home],
                speed=self._scaled_speed(b_speed * 0.8),
                accel=self._capped_accel(b_accel * 0.8),
                blend=0.05,
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
                self.logger.warning("Industrial demo not started: motion controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "Industrial demo started: speed_scale=%.2f, audience_offset=%.3f rad",
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
            self.logger.info("Industrial demo stopped")

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
