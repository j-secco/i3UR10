"""
Sorting showcase demo for UR10 (bare flange).

One cycle = 3 sorts: Intake → Bin 1 (left), Intake → Bin 2 (centre/near),
Intake → Bin 3 (right).  The robot keeps sweeping between three visually
distinct J1 positions, making every sort visually different from the last.
Pickup and release are pantomimed (micro-wiggle on J6).

Architecture is identical to industrial_demo.py:
  - ONE URScript infinite-loop program via move_joint_program_loop.
  - Every movej r > 0.  Cycle-end waypoint r = 0.05 (never r = 0).
  - Per-waypoint [*joints, v, a, r] 9-element vectors.
  - _notify(f"({i+1}/{N}) {seg.name}") before each segment.
  - _completed flag in finally block, set BEFORE final _notify("Stopped").
  - Hard caps: MAX_JOINT_SPEED_RAD_S=1.0, MAX_JOINT_ACCEL_RAD_S2=1.5,
    MAX_DELTA_FROM_HOME_RAD=0.9.
  - Constructor accepts **_unused for _loop_demo_start compatibility.

Segment naming (5 per sort × 3 sorts + 1 home = 16 total):
  "1/3 Pickup", "1/3 Transport → Bin 1", "1/3 Place", "1/3 Retreat",
  "2/3 Pickup", ..., "3/3 Pickup", ..., "3/3 Retreat", "Home"

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

# ----------------------------- Defaults / safety -----------------------------

DEFAULT_JOINT_SPEED     = 0.35   # rad/s base (scaled by speed_scale per-segment)
DEFAULT_JOINT_ACCEL     = 0.50   # rad/s^2
DEFAULT_BLEND_RADIUS    = 0.10   # rad
DEFAULT_SEND_INTERVAL_S = 0.08   # s (fallback only)
DEFAULT_CYCLE_DELAY_S   = 0.0    # s (URScript loop; no sleep needed)

# Hard safety caps — never exceeded regardless of config.
MAX_JOINT_SPEED_RAD_S   = 1.0
MAX_JOINT_ACCEL_RAD_S2  = 1.5
MAX_DELTA_FROM_HOME_RAD = 0.9    # per-joint absolute deviation from home

# --------------- Sorting-specific choreography parameters -------------------

# Intake station: centred (J1 delta = 0 relative to audience-offset home).
INTAKE_J1_DELTA    =  0.00   # rad  — centred

# Three bin destinations (J1 deltas relative to audience-offset home).
BIN1_J1_DELTA      = -0.45   # rad  — Bin 1, left
BIN2_J1_DELTA      =  0.00   # rad  — Bin 2, centre/near
BIN3_J1_DELTA      = +0.45   # rad  — Bin 3, right

# Bin 2 extra J3 to make it visually distinct from the intake station even
# though both share J1 delta = 0.
BIN2_J3_EXTRA      =  0.10   # rad  — less-folded elbow at Bin 2 place point

# Approach posture (arm raised, ready to descend).
APPROACH_J2_DELTA  = -0.20   # J2 shoulder back
APPROACH_J3_DELTA  = +0.20   # J3 elbow forward

# Descent additions (arm reaches down to pick/place level).
DESCEND_J2_EXTRA   = -0.30   # additional J2 on top of approach
DESCEND_J3_EXTRA   = +0.40   # additional J3 on top of approach

# Grasp / release wiggle — deliberately imperceptible (simulates closed flange).
WIGGLE_RAD         =  0.010  # J6 micro-amplitude


@dataclass
class Segment:
    """One choreography segment, part of the single URScript loop."""
    name:      str
    waypoints: List[List[float]]
    speed:     float   # rad/s (capped + scaled)
    accel:     float   # rad/s^2 (capped)
    blend:     float   # rad — cycle last point overridden to 0.05


class SortingDemo:
    """
    Sorting: robot picks from an intake station and drops each piece into one
    of three bins (left / centre / right) — 3 sorts per cycle.

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
    ) -> None:
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
        self._completed          = True   # True = not running

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

    def _pose(self, **deltas: float) -> List[float]:
        """Return a clamped 6-joint waypoint: home + audience_offset on J1 + deltas.
        Delta keys: j1, j2, j3, j4, j5, j6 (any subset)."""
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

    # -------------------- per-sort segment builder --------------------------

    def _sort_segments(
        self,
        sort_index: int,          # 0, 1, or 2
        bin_j1: float,            # J1 delta for this bin
        bin_label: str,           # "Bin 1", "Bin 2", "Bin 3"
        bin_j3_extra: float,      # additional J3 at bin place point (0 for Bin1/3)
    ) -> List[Segment]:
        """
        Build the 5-segment subroutine for one sort (intake → bin N).

        Segments:
          1. Pickup   — J1 to intake, approach posture, descend, wiggle, lift
          2. Transport— fast J1 swing to bin (the showcase sweep)
          3. Place    — descend into bin, wiggle release
          4. Retreat  — lift out of bin back to approach height above bin

        Wait — the spec calls for 5 short segments per sort so the status panel
        shows live progress.  We split Pickup into "Pickup" (approach+descend+wiggle)
        and "Lift" (ascent), and keep Transport, Place (descend+wiggle), Retreat.

        Naming convention: "N/3 Pickup", "N/3 Lift", "N/3 → Bin X",
                           "N/3 Place", "N/3 Retreat"
        where N = sort_index + 1.
        """
        n   = sort_index + 1          # 1, 2, or 3
        pfx = f"{n}/3"

        b_speed = self.joint_speed
        b_accel = self.joint_acceleration

        # ---- intake station poses ------------------------------------------
        intake_approach = self._pose(
            j1=INTAKE_J1_DELTA,
            j2=APPROACH_J2_DELTA,
            j3=APPROACH_J3_DELTA,
        )
        intake_at = self._pose(
            j1=INTAKE_J1_DELTA,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA,
        )
        intake_grasp_p = self._pose(
            j1=INTAKE_J1_DELTA,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA,
            j6=+WIGGLE_RAD,
        )
        intake_grasp_m = self._pose(
            j1=INTAKE_J1_DELTA,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA,
            j6=-WIGGLE_RAD,
        )

        # ---- bin station poses ---------------------------------------------
        bin_approach = self._pose(
            j1=bin_j1,
            j2=APPROACH_J2_DELTA,
            j3=APPROACH_J3_DELTA,
        )
        bin_at = self._pose(
            j1=bin_j1,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA + bin_j3_extra,
        )
        bin_rel_p = self._pose(
            j1=bin_j1,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA + bin_j3_extra,
            j6=+WIGGLE_RAD,
        )
        bin_rel_m = self._pose(
            j1=bin_j1,
            j2=APPROACH_J2_DELTA + DESCEND_J2_EXTRA,
            j3=APPROACH_J3_DELTA + DESCEND_J3_EXTRA + bin_j3_extra,
            j6=-WIGGLE_RAD,
        )

        # ---- segments ------------------------------------------------------
        return [

            # 1. Pickup — swing to intake, approach, descend (slow), grasp wiggle.
            Segment(
                name=f"{pfx} Pickup",
                waypoints=[intake_approach, intake_at,
                            intake_grasp_p, intake_grasp_m, intake_at],
                speed=self._scaled_speed(b_speed * 0.5),   # slow during descent/grasp
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.05,
            ),

            # 2. Lift — slow ascent back to approach height above intake.
            Segment(
                name=f"{pfx} Lift",
                waypoints=[intake_approach],
                speed=self._scaled_speed(b_speed * 0.5),   # slow
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.08,
            ),

            # 3. Transport — FAST J1 swing from intake to bin (the visual showcase).
            Segment(
                name=f"{pfx} → {bin_label}",
                waypoints=[bin_approach],
                speed=self._scaled_speed(b_speed * 1.30),  # fast confident swing
                accel=self._capped_accel(b_accel * 1.30),
                blend=0.10,
            ),

            # 4. Place — slow descent into bin, release wiggle.
            Segment(
                name=f"{pfx} Place",
                waypoints=[bin_at, bin_rel_p, bin_rel_m, bin_at],
                speed=self._scaled_speed(b_speed * 0.5),   # slow
                accel=self._capped_accel(b_accel * 0.5),
                blend=0.05,
            ),

            # 5. Retreat — slow lift out of bin back to approach height.
            Segment(
                name=f"{pfx} Retreat",
                waypoints=[bin_approach],
                speed=self._scaled_speed(b_speed * 0.6),
                accel=self._capped_accel(b_accel * 0.6),
                blend=0.08,
            ),
        ]

    # --------------------------- full cycle ---------------------------------

    def _build_segments(self) -> List[Segment]:
        """
        Assemble all 16 segments for one full sorting cycle.

        3 sorts × 5 segments each = 15 segments, plus 1 "Home" segment = 16 total.

        Bins:
          Bin 1 (left):         J1 delta = -0.45 rad
          Bin 2 (centre/near):  J1 delta =  0.00 rad, J3 extra = +0.10 at place
          Bin 3 (right):        J1 delta = +0.45 rad
        """
        bins: List[Tuple[float, str, float]] = [
            (BIN1_J1_DELTA, "Bin 1",  0.00),
            (BIN2_J1_DELTA, "Bin 2",  BIN2_J3_EXTRA),
            (BIN3_J1_DELTA, "Bin 3",  0.00),
        ]

        segments: List[Segment] = []
        for sort_idx, (bin_j1, bin_label, bin_j3_extra) in enumerate(bins):
            segments.extend(
                self._sort_segments(sort_idx, bin_j1, bin_label, bin_j3_extra)
            )

        # Final segment: return to home.  The flat-path builder will set the
        # last waypoint's r = 0.05 so the cycle end blends into the next
        # iteration without a brake click.
        home = self._pose()
        segments.append(
            Segment(
                name="Home",
                waypoints=[home],
                speed=self._scaled_speed(self.joint_speed * 0.8),
                accel=self._capped_accel(self.joint_acceleration * 0.8),
                blend=0.05,   # overridden to 0.05 cycle-end blend by builder anyway
            )
        )
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
                self.logger.warning(
                    "Sorting demo not started: motion controller not connected"
                )
                return

            self._notify("Starting")
            self.logger.info(
                "Sorting demo started: speed_scale=%.2f, audience_offset=%.3f rad",
                self.speed_scale, self.audience_offset_rad,
            )

            ctrl     = self.motion_controller
            has_loop = hasattr(ctrl, "move_joint_program_loop")
            has_prog = hasattr(ctrl, "move_joint_program")
            has_stop = hasattr(ctrl, "stop_motion")

            segments = self._build_segments()
            N        = len(segments)

            # Estimate per-segment UI display durations.
            seg_durations: List[float] = []
            for seg in segments:
                raw = self._estimate_duration(seg.waypoints, seg.speed)
                if seg.blend > 0 and len(seg.waypoints) >= 2:
                    raw *= 0.35
                seg_durations.append(max(0.35, raw + 0.1))

            # Build flat per-waypoint param list: [j1..j6, v, a, r].
            # Rule: every r > 0.  Very last waypoint of the whole cycle r = 0.05
            # so the while-True loop blends seamlessly into the next iteration.
            big_path: List[List[float]] = []
            last_seg_idx = N - 1
            for i, seg in enumerate(segments):
                last_wp_idx = len(seg.waypoints) - 1
                for j, wp in enumerate(seg.waypoints):
                    if j == last_wp_idx and i == last_seg_idx:
                        r = 0.05                             # cycle-end blend
                    elif j == last_wp_idx:
                        r = max(0.05, seg.blend * 0.6)       # inter-segment blend
                    else:
                        r = seg.blend                         # intra-segment blend
                    big_path.append([*wp, seg.speed, seg.accel, r])

            if has_loop:
                # Preferred: ONE infinite-loop URScript program.
                ok = ctrl.move_joint_program_loop(big_path, self.cycle_delay_s)
                if not ok:
                    final_msg = "Command failed"
                    return
                # Python worker only drives the status-notify clock.
                while not self._stop_requested:
                    for i, seg in enumerate(segments):
                        if self._stop_requested:
                            break
                        self._notify(f"({i+1}/{N}) {seg.name}")
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
                # Fallback: per-cycle program (one brake click per cycle).
                while not self._stop_requested:
                    ok = ctrl.move_joint_program(big_path)
                    if not ok:
                        final_msg = "Command failed"
                        return
                    for i, seg in enumerate(segments):
                        if self._stop_requested:
                            break
                        self._notify(f"({i+1}/{N}) {seg.name}")
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
                        self._notify(f"({i+1}/{N}) {seg.name}")
                        if not self._send_path(
                            seg.waypoints, seg.speed, seg.accel, seg.blend
                        ):
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
            # False the instant the UI processes "Stopped" — prevents the
            # "Stopping…" stuck-state bug.
            self._completed = True
            self._notify(final_msg)
            self.logger.info("Sorting demo stopped")

    def _send_path(self, path, speed, accel, blend):
        """Send path as one URScript program, or fall back to per-waypoint."""
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
    def _estimate_duration(path: List[List[float]], speed: float) -> float:
        """Conservative estimate: sum dominant-axis deltas / speed."""
        if len(path) < 2 or speed <= 0:
            return 0.0
        total = 0.0
        for a, b in zip(path[:-1], path[1:]):
            total += max(abs(x - y) for x, y in zip(a, b)) / speed
        return total

    def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small increments so stop() takes effect quickly."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop_requested:
            time.sleep(0.05)

    # -------------------------------- public API ----------------------------

    def start(self) -> bool:
        """Start the sorting demo loop. Returns True if launch succeeded."""
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
        """Signal the demo to stop; controller will decelerate to a halt."""
        self._stop_requested = True

    def is_running(self) -> bool:
        """Return True while the demo thread is active."""
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
