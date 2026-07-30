"""
RTDE Motion Controller for UR10 Robot

Wraps ur_rtde RTDEControlInterface to provide the same motion API as WebSocketController,
so jog and demos can use either Primary (30001) or RTDE (30004) as the motion backend.
TCP position and joint angles for the UI continue to come from WebSocketReceiver (30003).

RTDE enables reliable emergency stop (stopScript) and works with Dashboard for
protective stop recovery (unlock protective stop, close safety popup).

Author: jsecco (R)
"""

import logging
from typing import List, Optional, Any

try:
    import rtde_control
    RTDE_AVAILABLE = True
except ImportError:
    RTDE_AVAILABLE = False
    rtde_control = None

# Default RTDE frequency (Hz). UR e-Series/CB3 use 125 Hz on port 30004.
DEFAULT_RTDE_FREQUENCY = 125.0


class RTDEController:
    """
    Motion controller using RTDE (port 30004). Same interface as WebSocketController
    for move_joint, move_linear, speed_joint, speed_linear, stop_joint, stop_linear,
    and emergency_stop. Position data is not provided here; use WebSocketReceiver (30003).
    """

    def __init__(self, hostname: str, port: int = 30004, frequency: float = DEFAULT_RTDE_FREQUENCY):
        """
        Initialize RTDE controller. Does not connect until connect() is called.

        Args:
            hostname: Robot IP address
            port: RTDE port (default 30004)
            frequency: RTDE communication frequency in Hz (default 125)
        """
        self.hostname = hostname
        self.port = port
        self.frequency = frequency
        self._rtde: Any = None
        self.connected = False
        self.logger = logging.getLogger(self.__class__.__name__)
        self.last_joint_angles = [0.0] * 6
        self.last_position = [0.0] * 6

    def connect(self) -> bool:
        """
        Connect to the robot via RTDE.

        Returns:
            True if connection successful, False otherwise
        """
        if not RTDE_AVAILABLE:
            self.logger.error("ur_rtde not available; install with: pip install ur_rtde")
            return False
        try:
            self._rtde = rtde_control.RTDEControlInterface(
                self.hostname,
                frequency=self.frequency
            )
            if self._rtde.isConnected():
                self.connected = True
                self.logger.info("Connected to UR10 via RTDE at %s:%s", self.hostname, self.port)
                return True
            self.logger.error("RTDE connection failed: isConnected() returned False")
            return False
        except Exception as e:
            self.logger.error("Failed to connect via RTDE: %s", e)
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the robot."""
        self.connected = False
        if self._rtde:
            try:
                self._rtde.disconnect()
            except Exception as e:
                self.logger.debug("RTDE disconnect: %s", e)
            finally:
                self._rtde = None
        self.logger.info("Disconnected from RTDE")

    def is_connected(self) -> bool:
        """Return True if RTDE connection is active."""
        if self._rtde is None:
            return False
        try:
            return self.connected and self._rtde.isConnected()
        except Exception:
            return False

    def move_joint(
        self,
        joints: List[float],
        speed: float = 1.05,
        acceleration: float = 1.4,
        blend: float = 0.0
    ) -> bool:
        """
        Move to joint position (moveJ). Blend is ignored for single-waypoint RTDE moveJ.

        Args:
            joints: Target joint angles [j1..j6] in radians
            speed: Joint speed rad/s
            acceleration: Joint acceleration rad/s^2
            blend: Ignored (RTDE single moveJ has no blend; demos send waypoints in sequence)

        Returns:
            True if command accepted, False on error
        """
        if not self._rtde or not self.is_connected():
            self.logger.error("RTDE not connected")
            return False
        try:
            result = self._rtde.moveJ(joints, speed, acceleration, asynchronous=True)
            if not result:
                self.logger.warning("moveJ returned False")
            return result
        except Exception as e:
            self.logger.error("moveJ failed: %s", e)
            return False

    def move_linear(
        self,
        pose: List[float],
        speed: float = 0.1,
        acceleration: float = 1.2,
        blend: float = 0.0
    ) -> bool:
        """
        Move to pose (moveL). Blend is ignored for single-waypoint RTDE moveL.

        Args:
            pose: Target pose [x, y, z, rx, ry, rz] in m and rad
            speed: Tool speed m/s
            acceleration: Tool acceleration m/s^2
            blend: Ignored

        Returns:
            True if command accepted, False on error
        """
        if not self._rtde or not self.is_connected():
            self.logger.error("RTDE not connected")
            return False
        try:
            result = self._rtde.moveL(pose, speed, acceleration, asynchronous=True)
            if not result:
                self.logger.warning("moveL returned False")
            return result
        except Exception as e:
            self.logger.error("moveL failed: %s", e)
            return False

    def speed_joint(
        self,
        joint_speeds: List[float],
        acceleration: float = 1.4,
        time_limit: float = 0.0
    ) -> bool:
        """
        Joint speed command (speedJ).

        Args:
            joint_speeds: [j1..j6] rad/s
            acceleration: rad/s^2
            time_limit: Seconds (0 = unlimited)

        Returns:
            True if command accepted
        """
        if not self._rtde or not self.is_connected():
            self.logger.error("RTDE not connected")
            return False
        try:
            return self._rtde.speedJ(joint_speeds, acceleration, time_limit)
        except Exception as e:
            self.logger.error("speedJ failed: %s", e)
            return False

    def speed_linear(
        self,
        velocities: List[float],
        acceleration: float = 1.2,
        time_limit: float = 0.0
    ) -> bool:
        """
        Linear speed command (speedL).

        Args:
            velocities: [vx, vy, vz, vrx, vry, vrz] m/s and rad/s
            acceleration: m/s^2
            time_limit: Seconds (0 = unlimited)

        Returns:
            True if command accepted
        """
        if not self._rtde or not self.is_connected():
            self.logger.error("RTDE not connected")
            return False
        try:
            return self._rtde.speedL(velocities, acceleration, time_limit)
        except Exception as e:
            self.logger.error("speedL failed: %s", e)
            return False

    def stop_joint(self, deceleration: float = 10.0) -> bool:
        """Stop joint motion (stopJ)."""
        if not self._rtde or not self.is_connected():
            return False
        try:
            self._rtde.stopJ(deceleration, asynchronous=True)
            return True
        except Exception as e:
            self.logger.error("stopJ failed: %s", e)
            return False

    def stop_linear(self, deceleration: float = 10.0) -> bool:
        """Stop linear motion (stopL)."""
        if not self._rtde or not self.is_connected():
            return False
        try:
            self._rtde.stopL(deceleration, asynchronous=True)
            return True
        except Exception as e:
            self.logger.error("stopL failed: %s", e)
            return False

    def emergency_stop(self) -> bool:
        """
        Execute emergency stop: stop script and decelerate (stopJ + stopL).
        Call dashboard_client.emergency_stop() from JogController for full e-stop.
        """
        if not self._rtde or not self.is_connected():
            return False
        try:
            self._rtde.stopScript()
            self._rtde.stopL(10.0, asynchronous=True)
            self._rtde.stopJ(2.0, asynchronous=True)
            self.logger.warning("RTDE emergency stop executed")
            return True
        except Exception as e:
            self.logger.error("RTDE emergency stop failed: %s", e)
            return False

    def get_joint_angles(self) -> List[float]:
        """Return last known joint angles. Position comes from WebSocketReceiver; this is a stub."""
        return self.last_joint_angles.copy()

    def get_tcp_pose(self) -> List[float]:
        """Return last known TCP pose. Position comes from WebSocketReceiver; this is a stub."""
        return self.last_position.copy()

    def has_valid_position(self) -> bool:
        """Always False; position is provided by WebSocketReceiver (30003)."""
        return False

    def request_joint_positions(self, wait_s: float = 1.5) -> Optional[List[float]]:
        """
        Not supported when using RTDE. Position is obtained from WebSocketReceiver only.
        Returns None so JogController uses only the receiver for position after connect.
        """
        return None
