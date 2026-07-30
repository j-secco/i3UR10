"""
Wave & Greet showcase demo for UR10 (bare flange).

Segment-driven choreography. Each named segment is sent to the controller as
ONE URScript program (single moveJ-with-blend chain) via
`WebSocketController.move_joint_path`. Between segments the controller comes
to a clean precise stop, which is exactly what we want for theatrical pacing.

Live status updates: each segment emits its name through `status_callback`
before motion begins, so the touchscreen UI shows the operator what is
happening in real time ("Greeting", "Sweep", "Bow", ...).

Public API matches DemoRunner so the existing UI runner page can swap it in.

Author: jsecco (R)
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Callable, Any

# ----------------------------- Defaults / safety -----------------------------

# Conservative base defaults; per-segment overrides scale from these.
DEFAULT_JOINT_SPEED = 0.35           # rad/s (base; scaled by speed_scale)
DEFAULT_JOINT_ACCELERATION = 0.5     # rad/s^2
DEFAULT_BLEND_RADIUS = 0.10          # rad
DEFAULT_SEND_INTERVAL_S = 0.08       # s between waypoint sends (fallback only)
DEFAULT_CYCLE_DELAY_S = 1.0          # s pause between full cycles

# Hard safety caps applied to every segment, regardless of config.
MAX_JOINT_SPEED_RAD_S = 1.0
MAX_JOINT_ACCEL_RAD_S2 = 1.5
MAX_DELTA_FROM_HOME_RAD = 0.9        # per-joint absolute deviation from home

# Choreography amplitudes (radians). Tuned to read well from across a room
# while staying inside MAX_DELTA_FROM_HOME_RAD on every joint.
SHOULDER_LIFT_RAD   = 0.55   # J2 up
ELBOW_FOLD_RAD      = 0.30   # J3 fold
WRIST_TILT_RAD      = 0.30   # J5 forward tilt
WAVE_AMPLITUDE_RAD  = 0.55   # J5 wave swing
SWEEP_AMPLITUDE_RAD = 0.55   # J1 sideways sweep
WRIST_FOLLOW_RAD    = 0.25   # J4 follow during sweep
WRIST_ROLL_RAD      = 0.70   # J6 flourish
BOW_LEAN_RAD        = 0.45   # J2/J3 forward lean


@dataclass
class Segment:
    """One choreography segment, executed as a single URScript program."""
    name: str
    waypoints: List[List[float]]
    speed: float          # rad/s (will be capped + scaled)
    accel: float          # rad/s^2 (will be capped)
    blend: float          # rad; intra-segment blend; final point always r=0


class WaveDemo:
    """
    Wave & Greet: turn toward audience, raise the arm, wave, sweep, flourish,
    bow, and recover. Multi-segment showcase with visible accel/decel.
    Runs in a background thread; use start() / stop() / is_running().
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
        joint_acceleration: float = DEFAULT_JOINT_ACCELERATION,
        blend_radius: float = DEFAULT_BLEND_RADIUS,
        wave_count: int = 4,
        status_callback: Optional[Callable[[str], None]] = None,
        **_unused: Any,  # tolerate extra kwargs from older UI wiring
    ):
        self.motion_controller = motion_controller
        self.home_joints = list(home_joints)
        self.audience_offset_rad = audience_offset_rad
        self.speed_scale = max(0.01, min(1.0, speed_scale))
        self.send_interval_s = max(0.02, send_interval_s)
        self.cycle_delay_s = max(0.0, cycle_delay_s)
        self.joint_speed = joint_speed
        self.joint_acceleration = joint_acceleration
        self.blend_radius = blend_radius
        self.wave_count = max(1, int(wave_count))
        self.status_callback = status_callback
        self.logger = logging.getLogger(self.__class__.__name__)

        self._stop_requested = False
        self._thread: Optional[threading.Thread] = None
        # True when the worker has fully wrapped up. Used by is_running() so the UI
        # sees the demo as finished the moment the final "Stopped" notify arrives,
        # not after the worker function physically returns.
        self._completed = True

    # ------------------------------- helpers --------------------------------

    def _notify(self, message: str) -> None:
        # Diagnostic: log every notify so we can verify the worker reached this point.
        self.logger.info("notify -> %s", message)
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning("Status callback error: %s", e)

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
        """Build a 6-joint waypoint as home + audience offset on J1 + per-joint deltas.
        deltas keys: j1, j2, j3, j4, j5, j6 (any subset)."""
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
        """Assemble the showcase. Each segment ends with a precise stop (blend=0).
        Within a segment, intermediate waypoints use a small blend so the body
        of the move flows; the final landing is always crisp."""
        # Reusable poses
        home = self._pose()
        turned = self._pose()           # turned == home + audience offset (audience is added in _pose)
        raised = self._pose(
            j2=-SHOULDER_LIFT_RAD,
            j3=+ELBOW_FOLD_RAD,
            j5=-WRIST_TILT_RAD,
        )

        # Wave (J5 oscillation). Final waypoint blend=0 for clean stop.
        wave_pts: List[List[float]] = []
        amps = [WAVE_AMPLITUDE_RAD, WAVE_AMPLITUDE_RAD * 0.85,
                WAVE_AMPLITUDE_RAD, WAVE_AMPLITUDE_RAD * 0.6]
        # Pad/repeat to wave_count
        while len(amps) < self.wave_count:
            amps.append(WAVE_AMPLITUDE_RAD * 0.5)
        amps = amps[: self.wave_count]
        for i, a in enumerate(amps):
            sgn = 1.0 if (i % 2 == 0) else -1.0
            wave_pts.append(self._pose(
                j2=-SHOULDER_LIFT_RAD,
                j3=+ELBOW_FOLD_RAD,
                j5=-WRIST_TILT_RAD + sgn * a,
            ))
        # Re-center the wrist as the precise-stop landing of the wave segment
        wave_pts.append(raised)

        # Sweep (J1 ± big arc with J4 follow, fast cruise + decel landing).
        sweep_pts = [
            self._pose(j1=+SWEEP_AMPLITUDE_RAD * 0.6,
                       j2=-SHOULDER_LIFT_RAD * 0.7,
                       j3=+ELBOW_FOLD_RAD * 0.7,
                       j4=+WRIST_FOLLOW_RAD,
                       j5=-WRIST_TILT_RAD),
            self._pose(j1=-SWEEP_AMPLITUDE_RAD * 0.6,
                       j2=-SHOULDER_LIFT_RAD * 0.7,
                       j3=+ELBOW_FOLD_RAD * 0.7,
                       j4=-WRIST_FOLLOW_RAD,
                       j5=-WRIST_TILT_RAD),
            self._pose(j1=+SWEEP_AMPLITUDE_RAD * 0.4,
                       j2=-SHOULDER_LIFT_RAD * 0.7,
                       j3=+ELBOW_FOLD_RAD * 0.7,
                       j4=+WRIST_FOLLOW_RAD * 0.5,
                       j5=-WRIST_TILT_RAD),
            # Decel landing: re-center on audience facing, precise stop.
            raised,
        ]

        # Flourish (J6 wrist roll with small J5 nod, theatrical).
        flourish_pts = [
            self._pose(j2=-SHOULDER_LIFT_RAD,
                       j3=+ELBOW_FOLD_RAD,
                       j5=-WRIST_TILT_RAD - 0.10,
                       j6=+WRIST_ROLL_RAD),
            self._pose(j2=-SHOULDER_LIFT_RAD,
                       j3=+ELBOW_FOLD_RAD,
                       j5=-WRIST_TILT_RAD + 0.10,
                       j6=-WRIST_ROLL_RAD),
            self._pose(j2=-SHOULDER_LIFT_RAD,
                       j3=+ELBOW_FOLD_RAD,
                       j5=-WRIST_TILT_RAD,
                       j6=+WRIST_ROLL_RAD * 0.4),
            raised,  # precise stop
        ]

        # Bow (J2/J3 forward lean, slow controlled, deep precise stop).
        bow_pts = [
            self._pose(j2=-SHOULDER_LIFT_RAD * 0.6,
                       j3=+ELBOW_FOLD_RAD * 0.5,
                       j5=-WRIST_TILT_RAD * 0.7),
            # Bow-down apex: lean forward (J2 toward shoulder forward = positive delta
            # from raised; we express as smaller -lift + larger fold).
            self._pose(j2=-SHOULDER_LIFT_RAD * 0.2,
                       j3=+BOW_LEAN_RAD,
                       j5=-WRIST_TILT_RAD * 0.4),
            self._pose(j2=-SHOULDER_LIFT_RAD * 0.2,
                       j3=+BOW_LEAN_RAD,
                       j5=-WRIST_TILT_RAD * 0.4),  # held at bottom, decel into stop
        ]

        # Recover: bow -> raised -> turned -> home, each with precise stop.
        recover_pts = [raised, turned, home]

        # Per-segment speed/accel scaling (relative to base joint_speed).
        # Base is already conservative; we ride within [0.5x .. 1.4x] of base.
        b_speed = self.joint_speed
        b_accel = self.joint_acceleration

        segments: List[Segment] = [
            Segment(
                name="Greet",
                waypoints=[turned],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 0.8),
                blend=0.0,
            ),
            Segment(
                name="Lift",
                waypoints=[
                    # Inner waypoint with mild blend, final raised pose precise-stops.
                    self._pose(j2=-SHOULDER_LIFT_RAD * 0.5,
                               j3=+ELBOW_FOLD_RAD * 0.5,
                               j5=-WRIST_TILT_RAD * 0.5),
                    raised,
                ],
                speed=self._scaled_speed(b_speed * 0.9),
                accel=self._capped_accel(b_accel * 1.1),  # accel→decel
                blend=0.06,
            ),
            Segment(
                name="Wave",
                waypoints=wave_pts,
                speed=self._scaled_speed(b_speed * 1.1),
                accel=self._capped_accel(b_accel * 1.0),
                blend=0.10,
            ),
            Segment(
                name="Sweep",
                waypoints=sweep_pts,
                speed=self._scaled_speed(b_speed * 1.4),  # fast cruise
                accel=self._capped_accel(b_accel * 1.4),  # strong accel + decel
                blend=0.12,
            ),
            Segment(
                name="Flourish",
                waypoints=flourish_pts,
                speed=self._scaled_speed(b_speed * 1.0),
                accel=self._capped_accel(b_accel * 1.0),
                blend=0.10,
            ),
            Segment(
                name="Bow",
                waypoints=bow_pts,
                speed=self._scaled_speed(b_speed * 0.7),  # slow controlled
                accel=self._capped_accel(b_accel * 0.6),  # gentle decel into deep stop
                blend=0.05,
            ),
            Segment(
                name="Recover",
                waypoints=recover_pts,
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
                self.logger.warning("Wave demo not started: motion controller not connected")
                return

            self._notify("Starting")
            self.logger.info(
                "Wave & Greet showcase started: speed_scale=%.2f, audience_offset=%.3f rad",
                self.speed_scale, self.audience_offset_rad,
            )

            ctrl = self.motion_controller
            has_loop = hasattr(ctrl, "move_joint_program_loop")
            has_program = hasattr(ctrl, "move_joint_program")
            has_stop = hasattr(ctrl, "stop_motion")

            segments = self._build_segments()
            seg_durations = []
            for seg in segments:
                raw = self._estimate_duration(seg.waypoints, seg.speed)
                if seg.blend > 0 and len(seg.waypoints) >= 2:
                    raw *= 0.35
                seg_durations.append(max(0.35, raw + 0.1))

            # Build the entire cycle as a flat per-waypoint param list.
            big_path = []
            last_seg_idx = len(segments) - 1
            for i, seg in enumerate(segments):
                last_wp_idx = len(seg.waypoints) - 1
                for j, wp in enumerate(seg.waypoints):
                    if j == last_wp_idx and i == last_seg_idx:
                        # Small blend (not precise stop) so the cycle end blends
                        # into the start of the next iteration -- no zero-velocity
                        # moment, no brake engagement.
                        r = 0.05
                    elif j == last_wp_idx:
                        r = max(0.05, seg.blend * 0.6)
                    else:
                        r = seg.blend
                    big_path.append([*wp, seg.speed, seg.accel, r])

            if has_loop:
                # Send infinite-loop URScript; runs on the robot until stopj.
                ok = ctrl.move_joint_program_loop(big_path, self.cycle_delay_s)
                if not ok:
                    final_msg = "Command failed"
                    return
                # Worker just runs the notify clock; no further URScript sends.
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
                        time.sleep(0.6)  # let stopj decelerate cleanly before next move
                    except Exception as e:
                        self.logger.debug("stop_motion failed: %s", e)
            elif has_program:
                # Per-cycle program (one brake click per cycle, but no per-segment clicks)
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
                    except Exception as e:
                        self.logger.debug("stop_motion failed: %s", e)
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

            # Graceful return to home (slow, no blend) so the demo always ends at home.
            try:
                self.motion_controller.move_joint(
                    self.home_joints,
                    self._scaled_speed(self.joint_speed * 0.7),
                    self._capped_accel(self.joint_acceleration * 0.7),
                    0.0,
                )
            except Exception as e:
                self.logger.debug("Return-to-home on stop failed: %s", e)
        finally:
            # Mark completed BEFORE the final notify so the UI's is_running() returns
            # False the moment it processes the "Stopped" status update.
            self._completed = True
            self._notify(final_msg)
            self.logger.info("Wave & Greet showcase stopped")

    def _send_path(self, path, speed, accel, blend):
        """Send the entire path as ONE URScript program (single moveJ-with-blend chain).
        Falls back to per-waypoint move_joint if the controller has no batch path API."""
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
        """Conservative estimate: sum of dominant-axis times across segments."""
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

    def _segment_sleep(self, seg):
        """Wait for a segment to finish, correcting for URScript blend compression.

        We estimate only the intra-segment travel (seg.waypoints), because the
        robot is already at or near the first waypoint when we call this — it
        arrived there at the end of the previous segment. Prepending home_joints
        would add a phantom leading leg and over-estimate by 3-6 s.
        When blend > 0 and there are 2+ waypoints the URScript blending typically
        compresses real motion to ~55 % of the naive distance-over-speed sum.
        """
        raw = self._estimate_duration(seg.waypoints, seg.speed)
        if seg.blend > 0 and len(seg.waypoints) >= 2:
            raw *= 0.35
        duration = max(0.35, raw + 0.1)
        self._sleep_interruptible(duration)

    # -------------------------------- public API ----------------------------

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        if len(self.home_joints) != 6:
            self.logger.error("home_joints must have 6 elements")
            return False
        self._stop_requested = False
        self._completed = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_requested = True

    def is_running(self) -> bool:
        if getattr(self, "_completed", True):
            return False
        return self._thread is not None and self._thread.is_alive()
