"""
Juggle demo for UR10 — fast rhythmic pick-and-place between two stations,
alternating like juggling between two hands.

Architecture: one infinite-loop URScript program sent via
move_joint_program_loop.  Every movej carries r > 0 (brake-free).
Cycle-end uses r=0.05 so the loop blends continuously into the next
iteration without any zero-velocity stop or brake engagement.

Character: rapid lateral transitions (v=0.85, a=1.30) contrasted with
brief, visible touches at each station (v=0.45, a=1.0).  The contrast
IS the rhythm — beat A, beat B, beat A, beat B.

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
MAX_JOINT_SPEED_RAD_S   =  1.0
MAX_JOINT_ACCEL_RAD_S2  =  1.5
MAX_DELTA_FROM_HOME_RAD =  0.9


@dataclass
class Segment:
    """One waypoint with its own motion parameters."""
    name:   str
    joints: List[float]   # 6 joint angles (absolute rad)
    speed:  float         # rad/s  — will be capped at MAX_JOINT_SPEED_RAD_S
    accel:  float         # rad/s² — will be capped at MAX_JOINT_ACCEL_RAD_S2
    blend:  float         # rad    — MUST be > 0 (architecture requirement)


class JuggleDemo:
    """
    Juggle: fast rhythmic pick-and-place between Station A (left) and
    Station B (right).  One cycle = Setup + 4 station touches (A→B→A→B) +
    Home, 13 segments total.

    Touch segments (v=0.45, a=1.0) are slow enough to read theatrically.
    Transit segments (v=0.85, a=1.30) snap between stations at near-cap speed.
    The speed contrast creates a clear juggling rhythm for the audience.

    Constructor is compatible with _loop_demo_start — absorbs any extra kwargs
    via **_unused.
    """

    # Saved home: [-0.8442, -1.1413, 2.2144, -3.7987, -1.4705, 0.2638]
    #
    # Station layout (symmetric around audience direction):
    #   Station A (left):  J1 = home_J1 + audience_offset - 0.40 rad
    #   Station B (right): J1 = home_J1 + audience_offset + 0.40 rad
    #
    # Both stations at approach elevation: J2 -= 0.20, J3 += 0.20
    # Touch-down: J2 += 0.18 (descend), Touch-up: back to approach

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
        """Build absolute joint angles as home + audience-offset on J1 + per-joint delta."""
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
        13-segment Juggle cycle.

        Joint deltas from home [-0.8442, -1.1413, 2.2144, -3.7987, -1.4705, 0.2638]:

        Approach elevation:  J2 -= 0.20, J3 += 0.20   (both stations same height)
        Touch-down descent:  J2 += 0.18               (quick dip toward station)
        Station A offset:    J1 -= 0.40               (left of audience center)
        Station B offset:    J1 += 0.40               (right of audience center)

        Max J1 delta = 0.40 rad  < MAX_DELTA_FROM_HOME_RAD=0.9 ✓
        Max J2 delta = 0.20 rad  < 0.9 ✓
        Max J3 delta = 0.20 rad  < 0.9 ✓

        Seg  1  Setup         approach station A          v=0.40 a=0.70 r=0.10
        Seg  2  A-Touch1 dn   descend at station A        v=0.45 a=1.00 r=0.08
        Seg  3  A-Touch1 up   lift back to approach       v=0.45 a=1.00 r=0.08
        Seg  4  → B fast      swing right to station B    v=0.85 a=1.30 r=0.12→0.06
        Seg  5  B-Touch1 dn   descend at station B        v=0.45 a=1.00 r=0.08
        Seg  6  B-Touch1 up   lift back to approach       v=0.45 a=1.00 r=0.08
        Seg  7  → A fast      swing left to station A     v=0.85 a=1.30 r=0.12→0.06
        Seg  8  A-Touch2 dn   second descent at A         v=0.45 a=1.00 r=0.08
        Seg  9  A-Touch2 up   lift back to approach       v=0.45 a=1.00 r=0.08
        Seg 10  → B fast      swing right to station B    v=0.85 a=1.30 r=0.12→0.06
        Seg 11  B-Touch2 dn   second descent at B         v=0.45 a=1.00 r=0.08
        Seg 12  B-Touch2 up   lift back to approach       v=0.45 a=1.00 r=0.08
        Seg 13  Home          settle to home              v=0.30 a=0.60 r=0.05
        """

        # Approach elevation (same for both stations)
        DJ2_RAISE = -0.20
        DJ3_RAISE = +0.20

        # Touch-down offset (descend from approach)
        DJ2_DOWN  = +0.18   # J2 toward shoulder-down = positive delta from raised

        # Station lateral offsets
        A_OFFSET  = -0.40   # station A left
        B_OFFSET  = +0.40   # station B right

        # Motion parameters
        V_SETUP    = 0.40;  A_SETUP    = 0.70
        V_TOUCH    = 0.45;  A_TOUCH    = 1.00
        V_TRANSIT  = 0.85;  A_TRANSIT  = 1.30
        V_HOME     = 0.30;  A_HOME     = 0.60

        # Blend radii
        R_TOUCH    = 0.08   # tight blend for quick touch rhythm
        R_TRANSIT  = 0.12   # loose mid-transit blend (arc feel)
        R_TRANSIT_END = 0.06  # tighter landing at station
        R_HOME     = 0.05   # cycle-end blend — wraps into next iteration

        # Station approach poses
        a_approach = self._pose(dj1=A_OFFSET, dj2=DJ2_RAISE, dj3=DJ3_RAISE)
        b_approach = self._pose(dj1=B_OFFSET, dj2=DJ2_RAISE, dj3=DJ3_RAISE)

        # Station touch-down poses (descended)
        a_touch    = self._pose(dj1=A_OFFSET, dj2=DJ2_RAISE + DJ2_DOWN, dj3=DJ3_RAISE)
        b_touch    = self._pose(dj1=B_OFFSET, dj2=DJ2_RAISE + DJ2_DOWN, dj3=DJ3_RAISE)

        # Home pose (exact)
        home       = list(self._home)

        segs: List[Segment] = [
            # 1. Setup — J1 to station A, raise to approach pose
            Segment(
                name   = "Setup",
                joints = a_approach,
                speed  = V_SETUP,
                accel  = A_SETUP,
                blend  = 0.10,
            ),
            # 2. A-Touch1 down — quick descent to station A
            Segment(
                name   = "A-Touch1 dn",
                joints = a_touch,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 3. A-Touch1 up — quick lift back to approach
            Segment(
                name   = "A-Touch1 up",
                joints = a_approach,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 4. → B fast — fast J1 swing right to station B (the "throw")
            #    Two waypoints flattened here: mid-arc (r=R_TRANSIT) + landing (r=R_TRANSIT_END)
            #    We use the landing as the single segment waypoint with landing blend.
            Segment(
                name   = "→ B fast",
                joints = b_approach,
                speed  = V_TRANSIT,
                accel  = A_TRANSIT,
                blend  = R_TRANSIT_END,
            ),
            # 5. B-Touch1 down — quick descent at station B
            Segment(
                name   = "B-Touch1 dn",
                joints = b_touch,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 6. B-Touch1 up — quick lift back to approach
            Segment(
                name   = "B-Touch1 up",
                joints = b_approach,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 7. → A fast — fast J1 swing left back to station A
            Segment(
                name   = "→ A fast",
                joints = a_approach,
                speed  = V_TRANSIT,
                accel  = A_TRANSIT,
                blend  = R_TRANSIT_END,
            ),
            # 8. A-Touch2 down — second descent at A
            Segment(
                name   = "A-Touch2 dn",
                joints = a_touch,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 9. A-Touch2 up — lift back to approach
            Segment(
                name   = "A-Touch2 up",
                joints = a_approach,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 10. → B fast — second fast swing right to station B
            Segment(
                name   = "→ B fast 2",
                joints = b_approach,
                speed  = V_TRANSIT,
                accel  = A_TRANSIT,
                blend  = R_TRANSIT_END,
            ),
            # 11. B-Touch2 down — second descent at B
            Segment(
                name   = "B-Touch2 dn",
                joints = b_touch,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 12. B-Touch2 up — lift back to approach
            Segment(
                name   = "B-Touch2 up",
                joints = b_approach,
                speed  = V_TOUCH,
                accel  = A_TOUCH,
                blend  = R_TOUCH,
            ),
            # 13. Home — settle to home; r=0.05 blends into next cycle (brake-free)
            Segment(
                name   = "Home",
                joints = home,
                speed  = V_HOME,
                accel  = A_HOME,
                blend  = R_HOME,   # MUST be > 0 — wraps cleanly into seg 1
            ),
        ]
        return segs

    @staticmethod
    def _estimate_seg_duration(seg: Segment, prev_joints: List[float]) -> float:
        """Dominant-axis time estimate for UI notification pacing."""
        delta = max(abs(a - b) for a, b in zip(seg.joints, prev_joints))
        raw = delta / max(seg.speed, 0.01)
        return max(0.10, raw * 0.85)

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
            lines.append(
                f"    movej([{jstr}], v={v:.4f}, a={a:.4f}, r={r:.4f})"
                f"  # {seg.name}"
            )
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
                "JuggleDemo started  speed_scale=%.2f  audience_offset=%.3f rad",
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
            self._log.error("JuggleDemo worker error: %s", exc, exc_info=True)
            final_msg = f"Error: {exc}"
        finally:
            self._completed = True          # flip BEFORE notify — UI sees is_running()=False
            self._notify(final_msg)
            self._log.info("JuggleDemo stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_requested = False
        self._completed      = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="JuggleDemo")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
