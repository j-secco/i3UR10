"""
Single demo runner for UR10: joint-space loop from home through offset waypoints.

Uses the same motion API as jog (move_joint with speed, acceleration, blend)
so it works with either WebSocketController (Primary 30001) or RTDEController (RTDE 30004).
Waypoints are sent at send_interval_s so the controller can blend; cycle_delay_s
is the pause between full loops. Requires a saved home position (Safety: Save as home).

Design follows ur_rtde moveJ usage and the pattern from examples/rtde-2.7.12
(control loop sends setpoints in sequence; with async moves we send next waypoint
before the robot finishes the previous for smooth blending).

Author: jsecco (R)
"""

import logging
import math
import threading
import time
from typing import List, Optional, Callable, Any

# Defaults (aligned with config and safe for UR10)
DEFAULT_JOINT_SPEED = 0.35
DEFAULT_JOINT_ACCELERATION = 0.5
DEFAULT_BLEND_RADIUS = 0.02
DEFAULT_SEND_INTERVAL_S = 0.08
DEFAULT_CYCLE_DELAY_S = 1.0


class DemoRunner:
    """
    Runs a repeating joint-space path: home -> waypoint_1 -> ... -> waypoint_n -> home.
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
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            motion_controller: Object with move_joint(joints, speed, accel, blend) -> bool.
            home_joints: Six joint angles in radians (start and end of loop).
            audience_offset_rad: Added to J2 for first waypoint (audience direction).
            speed_scale: Multiplier for joint speed (0..1 typical).
            send_interval_s: Time between sending consecutive waypoints (for blending).
            cycle_delay_s: Pause between full loops.
            joint_speed: Base joint speed (rad/s).
            joint_acceleration: Base joint acceleration (rad/s^2).
            blend_radius: Blend radius in radians for movej.
            status_callback: Called with status strings (thread-safe; can use QTimer.singleShot).
        """
        self.motion_controller = motion_controller
        self.home_joints = list(home_joints)
        self.audience_offset_rad = audience_offset_rad
        self.speed_scale = max(0.01, min(1.0, speed_scale))
        self.send_interval_s = max(0.02, send_interval_s)
        self.cycle_delay_s = max(0.0, cycle_delay_s)
        self.joint_speed = joint_speed
        self.joint_acceleration = joint_acceleration
        self.blend_radius = blend_radius
        self.status_callback = status_callback
        self.logger = logging.getLogger(self.__class__.__name__)

        self._stop_requested = False
        self._thread: Optional[threading.Thread] = None

    def _notify(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.debug("Status callback error: %s", e)

    def _build_waypoints(self) -> List[List[float]]:
        """Build path: home, then one or two offsets (J2 audience), then back to home."""
        if len(self.home_joints) != 6:
            return []
        j1, j2, j3, j4, j5, j6 = self.home_joints
        waypoints = [self.home_joints]
        if abs(self.audience_offset_rad) > 1e-6:
            waypoints.append([j1, j2 + self.audience_offset_rad, j3, j4, j5, j6])
            waypoints.append([j1, j2 - self.audience_offset_rad, j3, j4, j5, j6])
        waypoints.append(self.home_joints)
        return waypoints

    def _run_loop(self) -> None:
        waypoints = self._build_waypoints()
        if len(waypoints) < 2:
            self._notify("Invalid waypoints")
            return
        speed = self.joint_speed * self.speed_scale
        accel = self.joint_acceleration
        blend = self.blend_radius

        ctrl = self.motion_controller
        if hasattr(ctrl, "is_connected") and not ctrl.is_connected():
            self._notify("Disconnected")
            self.logger.warning("Demo not started: motion controller not connected")
            return
        if hasattr(ctrl, "connected") and not getattr(ctrl, "connected", True):
            self._notify("Disconnected")
            self.logger.warning("Demo not started: motion controller.connected is False")
            return
        self._notify("Running")
        self.logger.info("Demo started: %d waypoints, speed=%.3f, send_interval=%.2fs",
                         len(waypoints), speed, self.send_interval_s)

        while not self._stop_requested:
            ok = self._send_path(waypoints, speed, accel, blend)
            if not ok:
                self._notify("Command failed")
                return
            duration = self._estimate_duration(waypoints, speed) + 0.3
            self._sleep_interruptible(duration)
            if self._stop_requested:
                break
            if self.cycle_delay_s > 0:
                self._sleep_interruptible(self.cycle_delay_s)

        self._notify("Stopped")
        self.logger.info("Demo stopped")


    def _send_path(self, path, speed, accel, blend):
        """Send the entire path as ONE URScript program (single moveJ-with-blend chain).
        Falls back to per-waypoint move_joint if the controller has no batch path API."""
        ctrl = self.motion_controller
        if hasattr(ctrl, "move_joint_path"):
            return ctrl.move_joint_path(path, speed, accel, blend)
        # Fallback: per-waypoint, slower but at least functional
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
    def start(self) -> bool:
        """Start the demo in a background thread. Returns True if started."""
        if self._thread is not None and self._thread.is_alive():
            return False
        if len(self.home_joints) != 6:
            self.logger.error("home_joints must have 6 elements")
            return False
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Request the demo loop to stop (non-blocking)."""
        self._stop_requested = True

    def is_running(self) -> bool:
        """True if the demo thread is running."""
        return self._thread is not None and self._thread.is_alive()
