"""
Sprint demo for UR10 — fast lateral J1 back-and-forth with athletic snap turns.

Architecture: one infinite-loop URScript program sent via
move_joint_program_loop.  Every movej carries r > 0 (brake-free).
Cycle-end uses r=0.05 so the loop blends continuously into the next
iteration without any zero-velocity stop or brake engagement.

Author: jsecco
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Callable, Any

# ---------------------------------------------------------------------------
# Safety caps — never exceed these values.
# ---------------------------------------------------------------------------
MAX_JOINT_SPEED_RAD_S   =  2.0
MAX_JOINT_ACCEL_RAD_S2  =  3.5
MAX_DELTA_FROM_HOME_RAD = 0.9


@dataclass
class Segment:
    """One waypoint with its own motion parameters."""
    name:   str
    joints: List[float]   # 6 joint angles (absolute rad)
    speed:  float         # rad/s  — will be capped at MAX_JOINT_SPEED_RAD_S
    accel:  float         # rad/s² — will be capped at MAX_JOINT_ACCEL_RAD_S2
    blend:  float         # rad    — MUST be > 0 (architecture requirement)


class SprintDemo:
    """
    Sprint: fast lateral J1 oscillation with a slightly raised arm so the TCP
    traces a wide arc.  Push speed/accel close to the safety caps to give a
    genuinely punchy, athletic feel.  Tight blends at the turnaround points
    (r≈0.08) snap the direction; loose blends in mid-arc let the arm cruise.

    Constructor is compatible with _loop_demo_start — absorbs any extra kwargs
    via **_unused.
    """

    # Saved home: [-0.8442, -1.1413, 2.2144, -3.7987, -1.4705, 0.2638]
    # Raise offset: J2 -= 0.30, J3 += 0.20  → TCP high-and-forward during sprints.

    def __init__(
        self,
        motion_controller: Any,
        home_joints: List[float],
        audience_offset_rad: float = 0.0,
        speed_scale: float = 1.0,
        joint_speed: float = 0.35,
        joint_acceleration: float = 0.5,
        blend_radius: float = 0.10,
        cycle_delay_s: float = 0.0,
        status_callback: Optional[Callable[[str], None]] = None,
        **_unused: Any,
    ):
        self._controller       = motion_controller
        self._home             = list(home_joints)
        self._audience_offset  = audience_offset_rad
        self._speed_scale      = max(0.01, min(1.0, speed_scale))
        self._cycle_delay_s    = max(0.0, cycle_delay_s)
        self._status_callback  = status_callback
        self.status_callback   = status_callback   # public alias (UI wiring)

        self._stop_requested   = False
        self._completed        = True
        self._thread: Optional[threading.Thread] = None
        self._log              = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify(self, msg: str) -> None:
        self._log.info("notify -> %s", msg)
        cb = self._status_callback or self.status_callback
        if cb:
            try:
                cb(msg)
            except Exception as exc:
                self._log.warning("status_callback error: %s", exc)

    def _cap(self, v: float, a: float) -> tuple:
        sv = min(MAX_JOINT_SPEED_RAD_S, max(0.01, v * self._speed_scale))
        sa = min(MAX_JOINT_ACCEL_RAD_S2, max(0.05, a * self._speed_scale))
        return sv, sa

    def _pose(self, dj1=0.0, dj2=0.0, dj3=0.0, dj4=0.0, dj5=0.0, dj6=0.0) -> List[float]:
        """Build absolute joint angles as home + audience-offset + per-joint delta."""
        j1, j2, j3, j4, j5, j6 = self._home
        return [
            j1 + self._audience_offset + dj1,
            j2 + dj2,
            j3 + dj3,
            j4 + dj4,
            j5 + dj5,
            j6 + dj6,
        ]

    def _build_segments(self) -> List[Segment]:
        """
        8-segment Sprint cycle.

        Deltas from home [-0.8442, -1.1413, 2.2144, -3.7987, -1.4705, 0.2638]:

        Seg 1  Setup       J2 -0.30, J3 +0.20 → arm raised & forward
        Seg 2  Sprint L1   J1 +0.55 (left arc, fast)
        Seg 3  Sprint R1   J1 -1.10 (full swing right, fast)
        Seg 4  Sprint L2   J1 +1.10 (full swing back left, fast)
        Seg 5  Sprint R2   J1 -1.10 (full swing right again, fast)
        Seg 6  Sprint Ctr  J1 +0.55 (back to setup centerline, decel)
        Seg 7  Lower       reverse setup, medium-slow
        Seg 8  Home        return to home, r=0.05 (blends into next cycle)

        J1 net displacement check:
          L1: +0.55  → J1 = home+0.55   delta=0.55 ✓
          R1: -1.10  → J1 = home-0.55   delta=0.55 ✓
          L2: +1.10  → J1 = home+0.55   delta=0.55 ✓
          R2: -1.10  → J1 = home-0.55   delta=0.55 ✓
          Ctr:+0.55  → J1 = home         delta=0.00 ✓
        All within MAX_DELTA_FROM_HOME_RAD=0.9 rad. ✓
        """
        # Raised-arm offset (applied to setup/sprint/lower segments)
        DJ2_UP = -0.30   # J2 towards shoulder-up
        DJ3_FW =  0.20   # J3 fold forward → TCP high

        # Sprint speed/accel: full-capability showcase. The J1/J2 hardware
        # limit is 2.09 rad/s (120 deg/s); 1.80 rad/s is 86% of that, and
        # the module caps (2.0 / 3.5) remain the hard ceiling.
        V_SPRINT = 1.80   # rad/s
        A_SPRINT = 3.00   # rad/s^2

        # Setup / lower / home speeds
        V_SETUP  = 0.50
        A_SETUP  = 1.20
        V_LOWER  = 0.35
        A_LOWER  = 0.80

        segs = [
            # 1. Setup: raise arm to sprint posture, medium speed
            Segment(
                name   = "Setup",
                joints = self._pose(dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SETUP,
                accel  = A_SETUP,
                blend  = 0.10,   # loose blend into first sprint
            ),
            # 2. Sprint Left 1 — J1 += 0.55
            Segment(
                name   = "Sprint L1",
                joints = self._pose(dj1=+0.55, dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SPRINT,
                accel  = A_SPRINT,
                blend  = 0.08,   # tight snap turnaround
            ),
            # 3. Sprint Right 1 — J1 -= 1.10 (full swing to right)
            Segment(
                name   = "Sprint R1",
                joints = self._pose(dj1=-0.55, dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SPRINT,
                accel  = A_SPRINT,
                blend  = 0.08,   # tight snap turnaround
            ),
            # 4. Sprint Left 2 — J1 += 1.10 (full swing back left)
            Segment(
                name   = "Sprint L2",
                joints = self._pose(dj1=+0.55, dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SPRINT,
                accel  = A_SPRINT,
                blend  = 0.08,   # tight snap turnaround
            ),
            # 5. Sprint Right 2 — J1 -= 1.10 again
            Segment(
                name   = "Sprint R2",
                joints = self._pose(dj1=-0.55, dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SPRINT,
                accel  = A_SPRINT,
                blend  = 0.10,   # slightly softer this time
            ),
            # 6. Sprint Center — decelerate back to setup centerline
            Segment(
                name   = "Sprint Ctr",
                joints = self._pose(dj2=DJ2_UP, dj3=DJ3_FW),
                speed  = V_SETUP,
                accel  = 0.50,
                blend  = 0.08,   # clean transition into lower
            ),
            # 7. Lower — reverse setup, return toward home posture
            Segment(
                name   = "Lower",
                joints = self._pose(),
                speed  = V_LOWER,
                accel  = A_LOWER,
                blend  = 0.08,
            ),
            # 8. Home — last waypoint r=0.05 blends into next cycle (brake-free)
            Segment(
                name   = "Home",
                joints = list(self._home),
                speed  = V_LOWER,
                accel  = A_LOWER,
                blend  = 0.05,   # MUST be > 0 — wraps cleanly into seg 1
            ),
        ]
        return segs

    @staticmethod
    def _estimate_seg_duration(seg: Segment, prev_joints: List[float]) -> float:
        """Simple dominant-axis estimate for UI notification pacing."""
        delta = max(abs(a - b) for a, b in zip(seg.joints, prev_joints))
        raw = delta / max(seg.speed, 0.01)
        return max(0.15, raw * 0.9)

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop_requested:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # URScript render (for offline verification)
    # ------------------------------------------------------------------

    def render_urscript(self, speed_scale: Optional[float] = None) -> str:
        """Return the URScript that would be sent for one cycle at given scale."""
        old_scale = self._speed_scale
        if speed_scale is not None:
            self._speed_scale = max(0.01, min(1.0, speed_scale))
        segs = self._build_segments()
        lines = ["def jsecco_demo_loop():", "  while True:"]
        for seg in segs:
            v, a = self._cap(seg.speed, seg.accel)
            r = seg.blend
            j = seg.joints
            jstr = ", ".join(f"{x:.4f}" for x in j)
            lines.append(f"    movej([{jstr}], v={v:.4f}, a={a:.4f}, r={r:.4f})"
                         f"  # {seg.name}")
        lines += ["  end", "end", "jsecco_demo_loop()"]
        self._speed_scale = old_scale
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        final_msg = "Stopped"
        try:
            if len(self._home) != 6:
                final_msg = "Invalid home (need 6 joints)"
                return

            self._notify("Starting")
            self._log.info(
                "SprintDemo started  speed_scale=%.2f  audience_offset=%.3f rad",
                self._speed_scale, self._audience_offset,
            )

            segs = self._build_segments()
            N    = len(segs)

            # Build flat per-waypoint list: [j1..j6, v, a, r]
            waypoints = []
            for seg in segs:
                v, a = self._cap(seg.speed, seg.accel)
                waypoints.append(seg.joints + [v, a, seg.blend])

            # Validate: all r > 0
            for i, wp in enumerate(waypoints):
                assert wp[8] > 0, f"Segment {i} has r=0 — would cause brake click!"

            # Validate: joint deltas within safety cap
            for seg in segs:
                for q, h in zip(seg.joints, self._home):
                    delta = abs(q - h)
                    assert delta <= MAX_DELTA_FROM_HOME_RAD, (
                        f"Segment '{seg.name}' joint delta {delta:.3f} rad > "
                        f"{MAX_DELTA_FROM_HOME_RAD} rad cap"
                    )

            ctrl = self._controller
            ok = ctrl.move_joint_program_loop(waypoints, self._cycle_delay_s)
            if not ok:
                final_msg = "Command failed"
                return

            # Notify loop — mirrors the URScript timing for the UI panel
            prev = self._home
            while not self._stop_requested:
                for i, seg in enumerate(segs):
                    if self._stop_requested:
                        break
                    self._notify(f"({i+1}/{N}) {seg.name}")
                    dur = self._estimate_seg_duration(seg, prev)
                    self._sleep_interruptible(dur)
                    prev = seg.joints

            try:
                ctrl.stop_motion(0.5)
                time.sleep(0.6)
            except Exception as exc:
                self._log.debug("stop_motion: %s", exc)

        except Exception as exc:
            self._log.error("SprintDemo worker error: %s", exc, exc_info=True)
            final_msg = f"Error: {exc}"
        finally:
            self._completed = True          # flip BEFORE notify — UI sees is_running()=False
            self._notify(final_msg)
            self._log.info("SprintDemo stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_requested = False
        self._completed      = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="SprintDemo")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
