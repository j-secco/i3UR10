"""
Reach demo for UR10 — long extended lateral sweeps showing maximum workspace.

The TCP travels big arcs with the arm fully extended, demonstrating the full
reach envelope: wide J1 swings (±0.85 rad from audience-center) with J2 raised
and J3 opened so the TCP is far from the base.  Think: warehouse scanner.

Architecture: ONE infinite-loop URScript program via
``WebSocketController.move_joint_program_loop``.  Every movej has r > 0.
Cycle-end uses r=0.05 to blend back into iteration 1 with no brake click.

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# ---------------------------------------------------------------------------
# Safety caps — must not be exceeded after speed_scale is applied.
# ---------------------------------------------------------------------------
MAX_JOINT_SPEED_RAD_S   =  2.5
MAX_JOINT_ACCEL_RAD_S2  =  5.5
MAX_DELTA_FROM_HOME_RAD = 0.9   # per-joint absolute deviation from home


@dataclass
class Segment:
    """One choreography segment (maps to one movej in the URScript loop)."""
    name: str
    joints: List[float]   # 6 joint angles (absolute, already clamped)
    speed: float          # rad/s  — will be clamped + scaled
    accel: float          # rad/s² — will be clamped
    blend: float          # rad    — MUST be > 0 for continuous motion


class ReachDemo:
    """
    Reach: long lateral sweeps with arm fully extended, maximum workspace demo.

    8-segment cycle:
      1. Extend        — shoulder up, elbow open, wrist straighten
      2. Reach left    — J1 +0.85 rad (full left reach)
      3. Sweep right   — J1 -1.70 rad (full-amplitude right)
      4. Sweep left    — J1 +1.70 rad (full-amplitude left again)
      5. Centre        — J1 -0.85 back to extended-centre
      6. Higher reach  — additional J2 lift + wrist tilt
      7. Lower         — reverse lift back toward home posture
      8. Home          — cycle-end, r=0.05 chains into next iteration

    Runs in a background thread; use start() / stop() / is_running().
    Constructor is compatible with ``_loop_demo_start`` (accepts **_unused).
    """

    def __init__(
        self,
        motion_controller: Any,
        home_joints: List[float],
        audience_offset_rad: float = 0.0,
        speed_scale: float = 0.5,
        joint_speed: float = 0.35,
        joint_acceleration: float = 0.55,
        blend_radius: float = 0.10,
        cycle_delay_s: float = 0.0,
        status_callback: Optional[Callable[[str], None]] = None,
        **_unused: Any,
    ) -> None:
        self._controller    = motion_controller
        self._home          = list(home_joints)
        self._ao            = float(audience_offset_rad)
        self._speed_scale   = max(0.01, min(1.0, float(speed_scale)))
        self._base_speed    = float(joint_speed)
        self._base_accel    = float(joint_acceleration)
        self._blend_radius  = float(blend_radius)
        self._cycle_delay_s = max(0.0, float(cycle_delay_s))
        self._status_callback = status_callback
        self.logger         = logging.getLogger(self.__class__.__name__)

        self._stop_requested = False
        self._completed      = True
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify(self, msg: str) -> None:
        self.logger.info("notify -> %s", msg)
        if self._status_callback:
            try:
                self._status_callback(msg)
            except Exception as exc:
                self.logger.warning("status_callback error: %s", exc)

    def _connected(self) -> bool:
        ctrl = self._controller
        for attr in ("is_connected", "connected"):
            if hasattr(ctrl, attr):
                val = getattr(ctrl, attr)
                try:
                    return bool(val() if callable(val) else val)
                except Exception:
                    return False
        return True

    def _v(self, base: float) -> float:
        """Scale speed and apply hard cap."""
        return min(MAX_JOINT_SPEED_RAD_S, max(0.01, base * self._speed_scale))

    @staticmethod
    def _a(base: float) -> float:
        """Apply hard accel cap (not scaled — keeps motion feel consistent)."""
        return min(MAX_JOINT_ACCEL_RAD_S2, max(0.05, base))

    def _pose(self, dj: List[float]) -> List[float]:
        """Return absolute joint angles = home + audience_offset_on_J1 + dj[6].

        dj must be length-6; values are *deltas from home*.
        The audience offset is added only to J1 (index 0).
        Each joint is clamped to [home_i ± MAX_DELTA_FROM_HOME_RAD].
        """
        out = []
        for i, (h, d) in enumerate(zip(self._home, dj)):
            raw = h + d + (self._ao if i == 0 else 0.0)
            lo  = h - MAX_DELTA_FROM_HOME_RAD
            hi  = h + MAX_DELTA_FROM_HOME_RAD
            out.append(max(lo, min(hi, raw)))
        return out

    # ------------------------------------------------------------------
    # Segment definitions
    # ------------------------------------------------------------------

    def _build_segments(self) -> List[Segment]:
        """
        Choreography: 8 segments.  Joint deltas are relative to home.

        home = [-0.8442, -1.1413, 2.2144, -3.7987, -1.4705, 0.2638]

        Extended pose:   J2 -0.45  (shoulder up),
                         J3 -0.20  (elbow opens → arm extends),
                         J5 +0.20  (wrist straightens).

        J1 amplitudes:   ±0.85 rad for reach tips (near cap),
                         ±0.85 sweep legs each 1.70 rad full-swing.

        Audience offset is applied on top in _pose(); we keep deltas
        audience-agnostic so _pose() can apply the offset uniformly.
        The total J1 deviation = delta_j1 + audience_offset_rad; clamping
        in _pose() ensures it never exceeds MAX_DELTA_FROM_HOME_RAD = 0.9 rad.
        """

        # Base extended arm deltas (shoulder up, elbow open, wrist straight)
        EXT_J2 = -0.45   # raise shoulder
        EXT_J3 = -0.20   # open elbow (extends TCP away from base)
        EXT_J5 = +0.20   # straighten wrist

        # Higher-reach additional deltas (segments 6-7)
        HIGH_J2 = -0.20  # extra lift (total J2 delta = -0.65)
        HIGH_J5 = -0.30  # wrist tilts for dramatic higher reach

        # J1 sweep magnitudes
        REACH_L =  0.85   # far left  (near cap)
        REACH_R = -0.85   # far right (near cap)

        # Per-segment speed/accel values (before speed_scale is applied to v)
        V_SLOW   = 0.25   # settle / approach
        V_MED    = 0.45   # extend / centre moves
        V_FAST   = 0.85   # lateral sweeps

        A_SLOW   = 0.50
        A_MED    = 0.55
        A_FAST   = 0.75

        segments: List[Segment] = [
            # 1. Extend — arm into scanning pose
            Segment(
                name="Extend",
                joints=self._pose([0.0, EXT_J2, EXT_J3, 0.0, EXT_J5, 0.0]),
                speed=self._v(V_MED),
                accel=self._a(A_MED),
                blend=0.10,
            ),
            # 2. Reach far left — J1 + REACH_L (~0.85 rad)
            #    mid-arc blend 0.15 is baked into a single movej;
            #    we use blend 0.15 here for end-to-end smoothness, then
            #    a second waypoint (segment 3 start) acts as the "end" point.
            Segment(
                name="Reach left",
                joints=self._pose([REACH_L, EXT_J2, EXT_J3, 0.0, EXT_J5, 0.0]),
                speed=self._v(V_FAST),
                accel=self._a(A_FAST),
                blend=0.08,   # tighter at the extreme reach — visibly punctuated
            ),
            # 3. Full sweep to far right — 1.70 rad swing through centre
            Segment(
                name="Sweep right",
                joints=self._pose([REACH_R, EXT_J2, EXT_J3, 0.0, EXT_J5, 0.0]),
                speed=self._v(V_FAST),
                accel=self._a(A_FAST),
                blend=0.08,
            ),
            # 4. Full sweep back to far left — 1.70 rad swing
            Segment(
                name="Sweep left",
                joints=self._pose([REACH_L, EXT_J2, EXT_J3, 0.0, EXT_J5, 0.0]),
                speed=self._v(V_FAST),
                accel=self._a(A_FAST),
                blend=0.08,
            ),
            # 5. Centre reach — decelerate back to extended-centre
            Segment(
                name="Centre",
                joints=self._pose([0.0, EXT_J2, EXT_J3, 0.0, EXT_J5, 0.0]),
                speed=self._v(V_MED),
                accel=self._a(A_MED),
                blend=0.10,
            ),
            # 6. Higher reach — additional J2 lift + wrist tilt
            Segment(
                name="Higher reach",
                joints=self._pose([0.0, EXT_J2 + HIGH_J2, EXT_J3, 0.0,
                                   EXT_J5 + HIGH_J5, 0.0]),
                speed=self._v(V_MED),
                accel=self._a(A_MED),
                blend=0.10,
            ),
            # 7. Lower — reverse lift back toward home posture (partial)
            Segment(
                name="Lower",
                joints=self._pose([0.0, EXT_J2 * 0.5, EXT_J3 * 0.5, 0.0,
                                   EXT_J5 * 0.5, 0.0]),
                speed=self._v(V_SLOW),
                accel=self._a(A_SLOW),
                blend=0.10,
            ),
            # 8. Home — cycle-end; blend r=0.05 chains into next iteration
            Segment(
                name="Home",
                joints=self._pose([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                speed=self._v(V_MED),
                accel=self._a(A_MED),
                blend=0.05,   # cycle-end: small blend, NEVER r=0
            ),
        ]
        return segments

    # ------------------------------------------------------------------
    # Waypoint builder
    # ------------------------------------------------------------------

    def _build_waypoints(self, segments: List[Segment]) -> List[List[float]]:
        """Flatten segments to per-waypoint 9-element vectors [j1..j6, v, a, r].

        The last segment gets r=0.05 (cycle-end blend) regardless of its
        segment.blend value so the loop wraps continuously.
        Every r is guaranteed > 0.
        """
        waypoints: List[List[float]] = []
        last = len(segments) - 1
        for i, seg in enumerate(segments):
            r = 0.05 if i == last else seg.blend
            assert r > 0, f"Segment '{seg.name}' has r=0 — brake click!"
            waypoints.append(seg.joints + [seg.speed, seg.accel, r])
        return waypoints

    # ------------------------------------------------------------------
    # Duration estimation (for notify-clock pacing only)
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_duration(joints_a: List[float], joints_b: List[float],
                            speed: float) -> float:
        if speed <= 0:
            return 1.0
        delta = max(abs(a - b) for a, b in zip(joints_a, joints_b))
        return max(0.3, delta / speed + 0.1)

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop_requested:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        final_msg = "Stopped"
        try:
            if len(self._home) != 6:
                final_msg = "Invalid home (need 6 joints)"
                return

            if not self._connected():
                final_msg = "Disconnected"
                self.logger.warning("ReachDemo: controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "ReachDemo started: speed_scale=%.2f  audience_offset=%.3f rad",
                self._speed_scale, self._ao,
            )

            segments  = self._build_segments()
            waypoints = self._build_waypoints(segments)
            N = len(segments)

            # Send the infinite-loop URScript — one program, brake-free forever.
            ok = self._controller.move_joint_program_loop(
                waypoints, self._cycle_delay_s
            )
            if not ok:
                final_msg = "move_joint_program_loop failed"
                return

            # Notify-clock: mirror segment sequencing so the UI panel stays live.
            # We estimate travel time between consecutive waypoints.
            prev_joints = self._home
            while not self._stop_requested:
                for i, seg in enumerate(segments):
                    if self._stop_requested:
                        break
                    self._notify(f"({i + 1}/{N}) {seg.name}")
                    dur = self._estimate_duration(prev_joints, seg.joints, seg.speed)
                    self._sleep_interruptible(dur)
                    prev_joints = seg.joints
                # After a full cycle, prev_joints wraps back near home
                prev_joints = self._home

        finally:
            # _completed = True BEFORE _notify("Stopped") so is_running()
            # returns False the moment the UI processes the final status.
            self._completed = True
            try:
                self._controller.stop_motion(0.5)
            except Exception as exc:
                self.logger.debug("stop_motion: %s", exc)
            self._notify(final_msg)
            self.logger.info("ReachDemo stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        if len(self._home) != 6:
            self.logger.error("home_joints must have 6 elements")
            return False
        self._stop_requested = False
        self._completed      = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
