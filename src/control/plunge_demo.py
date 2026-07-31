"""
Plunge demo for UR10 (bare flange).

Character: slow deliberate descent, fast snap-back rise. The 5.5x speed
contrast between plunge (v=0.10) and snap-up (v=0.95) is the whole point.

Architecture: ONE infinite-loop URScript program sent via
`WebSocketController.move_joint_program_loop`. Every movej carries r > 0
(minimum r=0.05) so the controller blends continuously with no brake clicks.

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# ---------------------------------------------------------------------------
# Safety caps (mandatory, matches SMOOTH_MOTION.md)
# ---------------------------------------------------------------------------
MAX_JOINT_SPEED_RAD_S   =  2.5
MAX_JOINT_ACCEL_RAD_S2  =  5.5
MAX_DELTA_FROM_HOME_RAD = 0.9

# Depth is adapted to the CURRENT saved home at start (pose_guard): the deltas
# below assume an elbow around 127 deg at home, and a home re-saved with a more
# folded elbow would otherwise drive plunge_deep into self-collision (this
# caused the 2026-07-30 protective stop at a 166 deg fold). Below this scale
# the choreography is too shallow to read as a plunge, so refuse instead.
MIN_DEPTH_SCALE = 0.35

# Choreography uses J2 (shoulder) + J3 (elbow) for vertical-feeling TCP motion.
# J2 -= N  →  shoulder lifts (arm up)
# J2 += N  →  shoulder drops (arm down)
# J3 += N  →  elbow folds   (TCP drops)
# J3 -= N  →  elbow extends  (TCP rises)


@dataclass
class Segment:
    name:  str
    joints: List[float]   # 6 absolute joint angles (rad)
    speed:  float         # rad/s  — scaled by speed_scale at build time
    accel:  float         # rad/s² — scaled by speed_scale at build time
    blend:  float         # rad    — NOT scaled; must be > 0


class PlungeDemo:
    """
    Plunge: rise high, descend slowly three times, snap back fast each time.

    9-segment cycle:
      1  Address   — face audience (medium)
      2  Rise      — high arm pose  (fast)
      3  Plunge 1  — slow descent   (v=0.10)
      4  Snap up 1 — fast return    (v=0.95)
      5  Plunge 2  — slow descent 60% amplitude (v=0.10)
      6  Snap up 2 — fast return    (v=0.95)
      7  Plunge 3  — slow + dramatic, full amplitude (v=0.08)
      8  Recover   — controlled medium exit (v=0.30)
      9  Home      — back to home  (r=0.05)

    Contrast ratio at speed_scale=1.0: 0.55 / 0.10 = 5.5x
    """

    def __init__(
        self,
        motion_controller: Any,
        home_joints: List[float],
        audience_offset_rad: float = 0.0,
        speed_scale: float = 0.5,
        joint_speed: float = 0.35,
        joint_acceleration: float = 0.5,
        blend_radius: float = 0.10,
        cycle_delay_s: float = 0.0,
        status_callback: Optional[Callable[[str], None]] = None,
        **_unused: Any,
    ):
        self._controller      = motion_controller
        self._home            = list(home_joints)
        self._audience_offset = float(audience_offset_rad)
        self._speed_scale     = max(0.01, min(1.0, float(speed_scale)))
        self._cycle_delay_s   = max(0.0, float(cycle_delay_s))
        self._status_callback = status_callback
        self._log             = logging.getLogger(self.__class__.__name__)

        self._stop_requested  = False
        self._completed       = True
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify(self, msg: str) -> None:
        self._log.info("notify -> %s", msg)
        if self._status_callback:
            try:
                self._status_callback(msg)
            except Exception as exc:
                self._log.warning("status_callback error: %s", exc)

    def _connected(self) -> bool:
        ctrl = self._controller
        if hasattr(ctrl, "is_connected"):
            try:
                return bool(ctrl.is_connected())
            except Exception:
                return False
        return True

    def _cap_speed(self, v: float) -> float:
        return min(MAX_JOINT_SPEED_RAD_S, max(0.01, v * self._speed_scale))

    def _cap_accel(self, a: float) -> float:
        return min(MAX_JOINT_ACCEL_RAD_S2, max(0.05, a * self._speed_scale))

    def _pose(self, dj1=0.0, dj2=0.0, dj3=0.0, dj4=0.0, dj5=0.0, dj6=0.0) -> List[float]:
        """Absolute joint pose = home + audience offset on J1 + per-joint deltas.
        Every result is clamped to MAX_DELTA_FROM_HOME_RAD from home."""
        h = self._home
        raw = [
            h[0] + self._audience_offset + dj1,
            h[1] + dj2,
            h[2] + dj3,
            h[3] + dj4,
            h[4] + dj5,
            h[5] + dj6,
        ]
        return [
            max(h[i] - MAX_DELTA_FROM_HOME_RAD,
                min(h[i] + MAX_DELTA_FROM_HOME_RAD, raw[i]))
            for i in range(6)
        ]

    # ------------------------------------------------------------------
    # Choreography
    # ------------------------------------------------------------------

    def _build_segments(self, depth_scale: float = 1.0) -> List[Segment]:
        """
        All per-segment v/a values are BASE values at speed_scale=1.0.
        They are multiplied by speed_scale inside _build_waypoints().

        depth_scale scales only the DOWNWARD (plunge) deltas; the high pose
        unfolds the arm away from self-collision and stays at full height so
        the speed contrast keeps reading even at reduced depth.

        Plunge character parameters (at speed_scale=1.0):
          Descent: v=0.10, a=0.30  (or 0.08/0.25 for the dramatic third)
          Snap-up: v=0.95, a=1.40
          Contrast: 5.5x (snap vs first plunge)
        """
        s = depth_scale
        home_pose = self._pose()  # home + audience offset, no extra delta

        # Pose definitions
        # High arm: J2 -= 0.50 (shoulder up), J3 -= 0.25 (elbow extends)
        high_pose = self._pose(dj2=-0.50, dj3=-0.25)

        # Full-depth plunge: J2 += 0.45 (shoulder drops), J3 += 0.55 (elbow folds)
        plunge_deep = self._pose(dj2=+0.45 * s, dj3=+0.55 * s)

        # Partial plunge (60% amplitude): 0.27 / 0.33
        plunge_mid  = self._pose(dj2=+0.27 * s, dj3=+0.33 * s)

        segments: List[Segment] = [
            # ---- 1. Address: face audience, medium speed ----
            Segment(
                name   = "Address",
                joints = home_pose,
                speed  = 0.25,
                accel  = 0.50,
                blend  = 0.08,
            ),
            # ---- 2. Rise: reach high pose fast ----
            Segment(
                name   = "Rise",
                joints = high_pose,
                speed  = 0.50,
                accel  = 0.85,
                blend  = 0.10,
            ),
            # ---- 3. Plunge 1: slow controlled descent ----
            Segment(
                name   = "Plunge 1",
                joints = plunge_deep,
                speed  = 0.10,
                accel  = 0.30,
                blend  = 0.05,
            ),
            # ---- 4. Snap up 1: fast recovery to high pose ----
            Segment(
                name   = "Snap up 1",
                joints = high_pose,
                speed  = 0.55,
                accel  = 0.95,
                blend  = 0.10,
            ),
            # ---- 5. Plunge 2: 60% amplitude, slow ----
            Segment(
                name   = "Plunge 2",
                joints = plunge_mid,
                speed  = 0.10,
                accel  = 0.30,
                blend  = 0.05,
            ),
            # ---- 6. Snap up 2: fast return ----
            Segment(
                name   = "Snap up 2",
                joints = high_pose,
                speed  = 0.55,
                accel  = 0.95,
                blend  = 0.10,
            ),
            # ---- 7. Plunge 3: full depth, slowest + most dramatic ----
            Segment(
                name   = "Plunge 3",
                joints = plunge_deep,
                speed  = 0.08,
                accel  = 0.25,
                blend  = 0.05,
            ),
            # ---- 8. Recover: controlled medium exit from deep plunge ----
            Segment(
                name   = "Recover",
                joints = high_pose,
                speed  = 0.30,
                accel  = 0.60,
                blend  = 0.08,
            ),
            # ---- 9. Home: return to home, small blend keeps continuous flow ----
            Segment(
                name   = "Home",
                joints = home_pose,
                speed  = 0.25,
                accel  = 0.50,
                blend  = 0.05,   # r=0.05 — wraps into next iteration, NO brakes
            ),
        ]
        return segments

    def _build_waypoints(self, segments: List[Segment]) -> List[List[float]]:
        """Flatten segments to 9-element rows [j1..j6, v, a, r].
        r is never 0; speed/accel are scaled and capped."""
        rows = []
        for seg in segments:
            v = self._cap_speed(seg.speed)
            a = self._cap_accel(seg.accel)
            r = seg.blend   # blend NOT scaled — geometry stays stable
            assert r > 0.0, f"Segment '{seg.name}' has r=0 — brakes will engage!"
            rows.append(seg.joints + [v, a, r])
        return rows

    @staticmethod
    def _seg_duration(from_joints: List[float], to_joints: List[float], speed: float) -> float:
        """Dominant-axis travel time estimate (conservative upper bound)."""
        if speed <= 0:
            return 1.0
        delta = max(abs(a - b) for a, b in zip(from_joints, to_joints))
        return max(0.3, delta / speed + 0.1)

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop_requested:
            time.sleep(0.05)

    def _safe_depth_scale(self) -> float:
        """Largest plunge depth scale that keeps the whole looped path
        self-collision free from the CURRENT home (pose_guard capsule model).
        Returns 1.0 if the guard is unavailable; the controller-level gate in
        move_joint_program_loop still refuses genuinely unsafe programs."""
        try:
            from control.pose_guard import max_safe_scale
        except Exception as exc:
            self._log.warning("pose_guard unavailable (%s); using full depth", exc)
            return 1.0
        return max_safe_scale(
            lambda s: [seg.joints for seg in self._build_segments(s)]
        )

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
                self._log.warning("PlungeDemo: controller not connected")
                return

            self._notify("Starting Plunge")

            depth_scale = self._safe_depth_scale()
            if depth_scale < MIN_DEPTH_SCALE:
                final_msg = "Unsafe from current Home; re-save Home with a straighter elbow"
                self._log.error(
                    "PlungeDemo refused: max safe depth scale %.2f < %.2f for current home %s",
                    depth_scale, MIN_DEPTH_SCALE, self._home)
                return
            if depth_scale < 0.995:
                self._log.info("PlungeDemo depth limited to %.0f%% for current home",
                               depth_scale * 100)
                self._notify(f"Depth limited to {depth_scale * 100:.0f}% (safe for Home)")

            segments  = self._build_segments(depth_scale)
            waypoints = self._build_waypoints(segments)
            N         = len(segments)

            # Compute per-segment display durations for the notify clock.
            durations: List[float] = []
            prev = self._home
            for seg in segments:
                raw_dur = self._seg_duration(prev, seg.joints, seg.speed * self._speed_scale)
                durations.append(raw_dur)
                prev = seg.joints

            # Send the infinite-loop URScript program once.
            ok = self._controller.move_joint_program_loop(waypoints, self._cycle_delay_s)
            if not ok:
                final_msg = "move_joint_program_loop failed"
                return

            # Notify clock: emit segment names in sync with the robot's motion.
            while not self._stop_requested:
                for i, seg in enumerate(segments):
                    if self._stop_requested:
                        break
                    self._notify(f"({i+1}/{N}) {seg.name}")
                    self._sleep_interruptible(durations[i])
                if self._stop_requested:
                    break
                if self._cycle_delay_s > 0:
                    self._sleep_interruptible(self._cycle_delay_s)

            # Stop the running URScript.
            try:
                self._controller.stop_motion(0.5)
            except Exception as exc:
                self._log.debug("stop_motion: %s", exc)

        finally:
            self._completed = True          # flip BEFORE notify — UI sees is_running()=False
            self._notify(final_msg)
            self._log.info("PlungeDemo stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_requested = False
        self._completed      = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="PlungeDemo")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if self._completed:
            return False
        return self._thread is not None and self._thread.is_alive()

    @property
    def status_callback(self) -> Optional[Callable[[str], None]]:
        return self._status_callback

    @status_callback.setter
    def status_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        self._status_callback = cb
