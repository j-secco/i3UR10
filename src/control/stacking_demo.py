"""
Stacking demo for UR10 (bare flange).

The robot picks pieces from an intake station (J1 left) and stacks them at a
destination station (J1 right).  Each successive piece is placed at a
progressively HIGHER level — piece 1 deepest, piece 3 shallowest — visually
building a tower of 3 pieces per cycle.

Architecture: ONE infinite-loop URScript program via
``WebSocketController.move_joint_program_loop``.  Every movej has r > 0;
the cycle-end waypoint uses r=0.05 to blend seamlessly into the next
iteration with zero brake engagement.

Speed dynamics (relative to base joint_speed × speed_scale):
  Approach / address:    × 0.9  — medium, deliberate
  Pickup descend:        × 0.5  — slow, careful
  Micro-wiggle (grasp):  × 0.06 — imperceptible
  Lift from station:     × 0.55 — slow, controlled lift
  Transport J1 swing:    × 1.3  — fast, confident
  Place descend:         × 0.4  — extra slow as stack grows
  Lift from stack:       × 0.50 — slow retreat
  Survey wrist tilt:     × 0.45 — charming, deliberate admiration
  Return home:           × 0.75 — medium-slow wrap-up

One cycle = 3 piece-stacks = 26 segments total.

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# ----------------------------- Defaults / safety -----------------------------

DEFAULT_JOINT_SPEED     = 0.35   # rad/s base
DEFAULT_JOINT_ACCEL     = 0.50   # rad/s²
DEFAULT_BLEND_RADIUS    = 0.10   # rad
DEFAULT_SEND_INTERVAL_S = 0.08   # s (fallback only)
DEFAULT_CYCLE_DELAY_S   = 0.0    # no URScript sleep needed

# Hard safety caps — never exceeded regardless of config.
MAX_JOINT_SPEED_RAD_S   = 2.0
MAX_JOINT_ACCEL_RAD_S2  = 3.5
MAX_DELTA_FROM_HOME_RAD = 0.9    # per-joint absolute deviation from home

# Choreography geometry (radians).
# Both stations use the same J1 magnitude; sign determines left/right.
INTAKE_J1_OFFSET_RAD  = -0.35   # J1 delta from home toward intake (left)
STACK_J1_OFFSET_RAD   = +0.35   # J1 delta from home toward stack  (right)

# Approach posture common to both stations (applied on top of home).
APPROACH_J2_DELTA = -0.20        # shoulder back / up
APPROACH_J3_DELTA = +0.20        # elbow forward

# Pickup descend (uniform — pieces always at the same intake level).
PICKUP_J2_EXTRA   = -0.30        # from approach J2
PICKUP_J3_EXTRA   = +0.40        # from approach J3

# Stack place levels — each level is shallower than the previous, creating
# a visible rising tower.  Indexed 0-based (piece index 0,1,2 → bottom→top).
# piece 0 (bottom): deepest descent  → highest place point visually
# piece 1 (middle): medium descent
# piece 2 (top):    shallowest descent → appears highest in the stack
PLACE_J2_EXTRAS = [-0.30, -0.20, -0.10]  # J2 delta from approach J2 per level
PLACE_J3_EXTRAS = [+0.40, +0.27, +0.13]  # J3 delta from approach J3 per level

# Grasp / release micro-wiggle — J6 oscillation, visually imperceptible.
HOLD_WIGGLE_RAD  = 0.010

# Survey wrist tilt — J5 nod to "admire" the completed stack.
SURVEY_TILT_RAD  = 0.15


@dataclass
class Segment:
    """One choreography segment — executed as part of a single URScript loop."""
    name: str
    waypoints: List[List[float]]
    speed: float    # rad/s (capped + scaled)
    accel: float    # rad/s² (capped)
    blend: float    # rad; intra-segment; cycle last point forced to r=0.05


class StackingDemo:
    """
    Stacking: pick from intake (left), stack at destination (right).
    Each of 3 pieces per cycle is placed progressively higher, building a
    visible tower.  Bare flange — pickup/release is pantomimed.

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
        **_unused: Any,
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

    def _pose(self, **deltas) -> List[float]:
        """Build a 6-joint waypoint: home + audience_offset on J1 + per-joint deltas.
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
        Assemble the stacking choreography.

        Per cycle (3 pieces):
          For each piece N (label "1"/"2"/"3"):
            N: Approach intake   — J1 swing left + approach posture
            N: Pickup descend    — slow descent to uniform intake level
            N: Grasp             — 2 micro-wiggle waypoints on J6
            N: Lift from intake  — slow ascent back to approach posture
            N: Transport         — fast J1 swing right to stack station
            N: Place descend     — slow descent to LEVEL N (deeper=piece1, shallower=piece3)
            N: Release           — 2 micro-wiggle waypoints on J6
            N: Lift from stack   — slow ascent from place

          After piece 3:
            Survey stack left    — J5 tilt left (admiring)
            Survey stack right   — J5 tilt right
            Return home          — last waypoint r=0.05 (cycle-end blend)

        Total: 8 segments × 3 pieces + 3 final segments = 27 segments.
        """
        b_speed = self.joint_speed
        b_accel = self.joint_acceleration

        home = self._pose()

        # Approach posture (shared base — J1 adjusted per station below)
        appr_j2 = APPROACH_J2_DELTA
        appr_j3 = APPROACH_J3_DELTA

        segments: List[Segment] = []

        for piece_idx in range(3):           # 0, 1, 2 → pieces 1, 2, 3
            label = str(piece_idx + 1)       # "1", "2", "3"

            # ---- reusable poses for this piece ---------------------------------

            approach_intake = self._pose(
                j1=INTAKE_J1_OFFSET_RAD,
                j2=appr_j2,
                j3=appr_j3,
            )
            pickup_pose = self._pose(
                j1=INTAKE_J1_OFFSET_RAD,
                j2=appr_j2 + PICKUP_J2_EXTRA,
                j3=appr_j3 + PICKUP_J3_EXTRA,
            )
            grasp_plus = self._pose(
                j1=INTAKE_J1_OFFSET_RAD,
                j2=appr_j2 + PICKUP_J2_EXTRA,
                j3=appr_j3 + PICKUP_J3_EXTRA,
                j6=+HOLD_WIGGLE_RAD,
            )
            grasp_minus = self._pose(
                j1=INTAKE_J1_OFFSET_RAD,
                j2=appr_j2 + PICKUP_J2_EXTRA,
                j3=appr_j3 + PICKUP_J3_EXTRA,
                j6=-HOLD_WIGGLE_RAD,
            )

            approach_stack = self._pose(
                j1=STACK_J1_OFFSET_RAD,
                j2=appr_j2,
                j3=appr_j3,
            )
            place_j2_extra = PLACE_J2_EXTRAS[piece_idx]
            place_j3_extra = PLACE_J3_EXTRAS[piece_idx]
            place_pose = self._pose(
                j1=STACK_J1_OFFSET_RAD,
                j2=appr_j2 + place_j2_extra,
                j3=appr_j3 + place_j3_extra,
            )
            release_plus = self._pose(
                j1=STACK_J1_OFFSET_RAD,
                j2=appr_j2 + place_j2_extra,
                j3=appr_j3 + place_j3_extra,
                j6=+HOLD_WIGGLE_RAD,
            )
            release_minus = self._pose(
                j1=STACK_J1_OFFSET_RAD,
                j2=appr_j2 + place_j2_extra,
                j3=appr_j3 + place_j3_extra,
                j6=-HOLD_WIGGLE_RAD,
            )

            # ---- 8 segments per piece ------------------------------------------

            # 1. Approach intake
            segments.append(Segment(
                name=f"{label}: Approach intake",
                waypoints=[approach_intake],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 0.9),
                blend=0.08,
            ))

            # 2. Pickup descend
            segments.append(Segment(
                name=f"{label}: Pickup descend",
                waypoints=[pickup_pose],
                speed=self._scaled_speed(b_speed * 0.5),
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.05,
            ))

            # 3. Grasp (2 micro-wiggle + return-neutral)
            segments.append(Segment(
                name=f"{label}: Grasp",
                waypoints=[grasp_plus, grasp_minus],
                speed=self._scaled_speed(b_speed * 0.06),
                accel=self._capped_accel(b_accel * 0.30),
                blend=0.02,
            ))

            # 4. Lift from intake
            segments.append(Segment(
                name=f"{label}: Lift",
                waypoints=[approach_intake],
                speed=self._scaled_speed(b_speed * 0.55),
                accel=self._capped_accel(b_accel * 0.55),
                blend=0.08,
            ))

            # 5. Transport to stack (fast confident swing)
            segments.append(Segment(
                name=f"{label}: Transport",
                waypoints=[approach_stack],
                speed=self._scaled_speed(b_speed * 1.3),
                accel=self._capped_accel(b_accel * 1.2),
                blend=0.10,
            ))

            # 6. Place descend (extra slow — stack is growing)
            segments.append(Segment(
                name=f"{label}: Place descend",
                waypoints=[place_pose],
                speed=self._scaled_speed(b_speed * 0.40),
                accel=self._capped_accel(b_accel * 0.35),
                blend=0.04,
            ))

            # 7. Release (2 micro-wiggle)
            segments.append(Segment(
                name=f"{label}: Release",
                waypoints=[release_plus, release_minus],
                speed=self._scaled_speed(b_speed * 0.06),
                accel=self._capped_accel(b_accel * 0.30),
                blend=0.02,
            ))

            # 8. Lift from stack
            segments.append(Segment(
                name=f"{label}: Lift from stack",
                waypoints=[approach_stack],
                speed=self._scaled_speed(b_speed * 0.50),
                accel=self._capped_accel(b_accel * 0.50),
                blend=0.08,
            ))

        # ---- Post-stack survey (after piece 3) ---------------------------------

        # "Admiring the stack" — two wrist tilts from the stack approach posture
        survey_stack_base = self._pose(
            j1=STACK_J1_OFFSET_RAD,
            j2=appr_j2,
            j3=appr_j3,
        )
        survey_left = self._pose(
            j1=STACK_J1_OFFSET_RAD,
            j2=appr_j2,
            j3=appr_j3,
            j5=+SURVEY_TILT_RAD,
        )
        survey_right = self._pose(
            j1=STACK_J1_OFFSET_RAD,
            j2=appr_j2,
            j3=appr_j3,
            j5=-SURVEY_TILT_RAD,
        )

        segments.append(Segment(
            name="Survey stack",
            waypoints=[survey_left, survey_right, survey_stack_base],
            speed=self._scaled_speed(b_speed * 0.45),
            accel=self._capped_accel(b_accel * 0.45),
            blend=0.08,
        ))

        # Return home — last waypoint of the entire cycle gets r=0.05 (set by builder)
        segments.append(Segment(
            name="Return home",
            waypoints=[home],
            speed=self._scaled_speed(b_speed * 0.75),
            accel=self._capped_accel(b_accel * 0.75),
            blend=0.05,   # will be overridden to 0.05 by builder (already correct)
        ))

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
                self.logger.warning("Stacking demo not started: controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "Stacking demo started: speed_scale=%.2f, audience_offset=%.3f rad",
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
                seg_durations.append(max(0.25, raw + 0.1))

            # Build flat per-waypoint param list: [j1..j6, v, a, r].
            # Rule: every r > 0.  The very last waypoint of the whole cycle gets
            # r=0.05 so the while-True loop blends into the next iteration.
            big_path: List[List[float]] = []
            last_seg_idx = len(segments) - 1
            for i, seg in enumerate(segments):
                last_wp_idx = len(seg.waypoints) - 1
                for j, wp in enumerate(seg.waypoints):
                    if j == last_wp_idx and i == last_seg_idx:
                        r = 0.05           # cycle-end blend — no brake engagement
                    elif j == last_wp_idx:
                        r = max(0.05, seg.blend * 0.6)   # inter-segment blend
                    else:
                        r = max(0.02, seg.blend)          # intra-segment blend
                    big_path.append([*wp, seg.speed, seg.accel, r])

            if has_loop:
                # Preferred: ONE infinite-loop URScript program.
                ok = ctrl.move_joint_program_loop(big_path, self.cycle_delay_s)
                if not ok:
                    final_msg = "Command failed"
                    return
                # Worker loop drives only the status notify clock.
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
            self.logger.info("Stacking demo stopped")

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
