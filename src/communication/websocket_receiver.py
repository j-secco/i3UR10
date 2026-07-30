"""
WebSocket Receiver for UR10 Robot

This module handles the real-time data reception from the Universal Robot UR10
using the real-time interface (port 30003). Provides high-frequency robot state
monitoring for position feedback and safety status.

Packet format (UR Primary/Secondary Client Interface, see ClientInterfaces_Primary.pdf):
- Message: 4 bytes length (big-endian uint32) + payload. Payload: 1 byte message_type (16 = Robot State).
- Robot State subpackages: each 4 bytes length + 1 byte type + payload. Type 1 = JointData
  (6 x 41 bytes per joint; first 8 bytes of each joint = q_actual in rad). Type 4 = CartesianInfo
  (12 doubles; first 6 = X,Y,Z,Rx,Ry,Rz in m and rad).

Based on Universal Robots Socket Communication documentation.
Author: jsecco ®
"""

import socket
import time
import threading
import logging
import struct
import numpy as np
from typing import List, Dict, Optional, Callable, Any

try:
    from scipy.spatial.transform import Rotation as R
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    # Optional: records protective/emergency stops with context. The receiver
    # must keep working even if this module is missing, so the import is guarded.
    from .safety_event_logger import SafetyEventLogger
except Exception:
    SafetyEventLogger = None

class WebSocketReceiver:
    """
    Real-time WebSocket receiver for UR10 robot state data.
    Handles continuous monitoring of robot position, status, and safety information.
    """
    
    def __init__(self, hostname: str, port: int = 30003, timeout: float = 1.0):
        """
        Initialize WebSocket receiver for real-time data.
        
        Args:
            hostname: Robot IP address
            port: Communication port (30003 for real-time interface)
            timeout: Socket timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.timeout = timeout
        
        # Connection management
        self.socket = None
        self.connected = False
        self.reconnect_attempts = 3
        self.reconnect_delay = 1.0
        
        # Threading for continuous data reception
        self.receive_thread = None
        self.should_stop = threading.Event()
        
        # Robot state data
        self.robot_state = {
            'timestamp': 0.0,
            'tcp_pose': [0.0] * 6,           # [x, y, z, rx, ry, rz]
            'joint_angles': [0.0] * 6,      # [j1, j2, j3, j4, j5, j6]
            'tcp_speed': [0.0] * 6,         # TCP velocity
            'joint_speeds': [0.0] * 6,      # Joint velocities
            'joint_currents': [0.0] * 6,    # Joint currents
            'tcp_force': [0.0] * 6,         # TCP force/torque
            'robot_mode': 0,                 # Robot operation mode
            'safety_mode': 0,                # Safety system mode
            'program_running': False,        # Program execution status
            'emergency_stopped': False,      # Emergency stop status
            'protective_stopped': False,     # Protective stop status
            'speed_scaling': 1.0,           # Current speed scaling factor
            'digital_inputs': 0,            # Digital input states
            'digital_outputs': 0,           # Digital output states
            'analog_inputs': [0.0, 0.0],    # Analog input values
            'analog_outputs': [0.0, 0.0],   # Analog output values
            'joint_temperatures': [0.0] * 6, # Joint temperatures
            'controller_time': 0.0,         # Controller internal time
            'execution_time': 0.0,          # Program execution time
            'connection_quality': 100       # Connection quality percentage
        }
        
        # Data update callbacks
        self.data_callbacks: List[Callable[[Dict], None]] = []
        self.position_callbacks: List[Callable[[List[float], List[float]], None]] = []
        self.safety_callbacks: List[Callable[[Dict], None]] = []
        
        # Statistics
        self.messages_received = 0
        self.last_message_time = 0.0
        self.message_frequency = 0.0

        # True after at least one parsed update where joint_angles were not all zero
        self._position_received = False
        
        # Logging
        self.logger = logging.getLogger(self.__class__.__name__)

        # Safety event logger: records protective/emergency stops with the
        # joint config, TCP and controller messages. Optional and isolated --
        # its absence or failure must never affect robot communication.
        self.safety_logger = None
        if SafetyEventLogger is not None:
            try:
                self.safety_logger = SafetyEventLogger()
            except Exception as exc:
                self.logger.debug("SafetyEventLogger init failed: %s", exc)

        # Test conversion with known values on startup (only in debug mode)
        root_logger = logging.getLogger()
        if root_logger.level <= logging.DEBUG:
            self._test_conversion_with_known_values()
    
    def connect(self) -> bool:
        """
        Establish connection to UR10 real-time interface.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.hostname, self.port))
            
            self.connected = True
            self.logger.info(f"Connected to UR10 real-time interface at {self.hostname}:{self.port}")
            
            # Start receiving thread
            self.should_stop.clear()
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to UR10 real-time interface: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from robot and cleanup resources."""
        self.should_stop.set()
        self.connected = False
        self._position_received = False

        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
            
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            finally:
                self.socket = None
                
        self.logger.info("Disconnected from UR10 real-time interface")
    
    def reconnect(self) -> bool:
        """
        Attempt to reconnect to robot with retry logic.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        self.disconnect()
        
        for attempt in range(self.reconnect_attempts):
            self.logger.info(f"Real-time reconnection attempt {attempt + 1}/{self.reconnect_attempts}")
            
            if self.connect():
                return True
                
            if attempt < self.reconnect_attempts - 1:
                time.sleep(self.reconnect_delay)
                
        self.logger.error("Failed to reconnect real-time interface after all attempts")
        return False
    
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self.connected and self.socket is not None
    
    def get_robot_state(self) -> Dict[str, Any]:
        """
        Get complete robot state data.
        
        Returns:
            Dictionary containing all robot state information
        """
        state_copy = self.robot_state.copy()
        state_copy['messages_received'] = self.messages_received
        state_copy['message_frequency'] = self.message_frequency
        return state_copy
    
    def get_tcp_pose(self) -> List[float]:
        """
        Get current TCP pose.
        
        Returns:
            TCP pose [x, y, z, rx, ry, rz] in meters and radians
        """
        return self.robot_state['tcp_pose'].copy()
    
    def get_joint_angles(self) -> List[float]:
        """
        Get current joint angles.
        
        Returns:
            Joint angles [j1, j2, j3, j4, j5, j6] in radians
        """
        return self.robot_state['joint_angles'].copy()

    def has_valid_position(self) -> bool:
        """
        Return True if we have received at least one position update where
        joint angles were not all zero (i.e. real data from the robot).
        """
        return getattr(self, '_position_received', False)

    def set_joint_angles(self, joints: List[float], notify: bool = True) -> None:
        """
        Set joint angles from an external source (e.g. primary interface request).
        Use when realtime stream is not providing data so the app has current position.
        If notify is False, callbacks are not invoked (use when updating from background thread).
        """
        if joints and len(joints) == 6 and all(-7.0 < q < 7.0 for q in joints):
            self.robot_state['joint_angles'] = list(joints)
            self._position_received = True
            if notify:
                self._notify_callbacks()

    def get_tcp_speed(self) -> List[float]:
        """
        Get current TCP velocity.
        
        Returns:
            TCP velocity [vx, vy, vz, vrx, vry, vrz] in m/s and rad/s
        """
        return self.robot_state['tcp_speed'].copy()
    
    def get_joint_speeds(self) -> List[float]:
        """
        Get current joint velocities.
        
        Returns:
            Joint velocities [j1, j2, j3, j4, j5, j6] in rad/s
        """
        return self.robot_state['joint_speeds'].copy()
    
    def is_emergency_stopped(self) -> bool:
        """Check if robot is in emergency stop state."""
        return self.robot_state['emergency_stopped']
    
    def is_protective_stopped(self) -> bool:
        """Check if robot is in protective stop state."""
        return self.robot_state['protective_stopped']
    
    def is_program_running(self) -> bool:
        """Check if robot program is currently running."""
        return self.robot_state['program_running']
    
    def get_robot_mode(self) -> int:
        """Get current robot operation mode."""
        return self.robot_state['robot_mode']
    
    def get_safety_mode(self) -> int:
        """Get current safety system mode."""
        return self.robot_state['safety_mode']
    
    def get_speed_scaling(self) -> float:
        """Get current speed scaling factor (0.0 to 1.0)."""
        return self.robot_state['speed_scaling']
    
    def get_message_frequency(self) -> float:
        """Get current message reception frequency in Hz."""
        return self.message_frequency
    
    def add_data_callback(self, callback: Callable[[Dict], None]):
        """Add callback for complete robot state updates."""
        self.data_callbacks.append(callback)
    
    def add_position_callback(self, callback: Callable[[List[float], List[float]], None]):
        """Add callback for position updates (TCP pose, joint angles)."""
        self.position_callbacks.append(callback)
    
    def add_safety_callback(self, callback: Callable[[Dict], None]):
        """Add callback for safety status updates."""
        self.safety_callbacks.append(callback)
    
    def remove_callback(self, callback):
        """Remove callback from all callback lists."""
        for callback_list in [self.data_callbacks, self.position_callbacks, self.safety_callbacks]:
            if callback in callback_list:
                callback_list.remove(callback)
    
    def _receive_loop(self):
        """
        Continuous loop for receiving real-time robot data.
        Runs in separate thread to process incoming data at high frequency.
        """
        while not self.should_stop.is_set() and self.connected:
            try:
                # Read message header (message length)
                header_data = self._recv_exact(4)
                if not header_data:
                    continue
                
                # Unpack message length (big-endian integer)
                message_length = struct.unpack('>I', header_data)[0]
                
                if message_length > 10000:  # Sanity check
                    self.logger.warning(f"Unusually large message length: {message_length}")
                    continue
                
                # Read complete message
                message_data = self._recv_exact(message_length - 4)
                if not message_data:
                    continue
                
                # Process the message
                self._process_realtime_data(message_data)
                
                # Update statistics
                self.messages_received += 1
                current_time = time.time()
                if self.last_message_time > 0:
                    time_diff = current_time - self.last_message_time
                    if time_diff > 0:
                        # Simple moving average for frequency calculation
                        alpha = 0.1  # Smoothing factor
                        instant_freq = 1.0 / time_diff
                        self.message_frequency = (alpha * instant_freq + 
                                                (1 - alpha) * self.message_frequency)
                self.last_message_time = current_time
                
            except socket.timeout:
                # Timeout is normal for real-time interface
                continue
            except Exception as e:
                self.logger.error(f"Error in real-time receive loop: {e}")
                self.connected = False
                break
    
    def _recv_exact(self, length: int) -> Optional[bytes]:
        """
        Receive exactly the specified number of bytes.
        
        Args:
            length: Number of bytes to receive
            
        Returns:
            Received data or None if connection lost
        """
        data = b''
        while len(data) < length:
            try:
                if not self.socket:
                    self.logger.debug("Socket not available")
                    self.connected = False
                    return None
                
                chunk = self.socket.recv(length - len(data))
                if not chunk:
                    self.logger.warning("Connection lost during data reception")
                    self.connected = False
                    return None
                data += chunk
            except socket.timeout:
                continue
            except Exception as e:
                self.logger.error(f"Error receiving data: {e}")
                self.connected = False
                return None
        return data
    
    def _process_realtime_data(self, data: bytes):
        """
        Process incoming real-time robot data.
        Data is the payload after the 4-byte message length (i.e. first byte is message type).

        Packet structure (UR Primary/Secondary Client Interface):
        - Byte 0: message_type (16 = Robot State on some interfaces; 30003 may differ)
        - From byte 1: subpackages, each: 4 bytes length, 1 byte type, (length-5) bytes payload
        """
        try:
            self.robot_state['timestamp'] = time.time()

            if len(data) < 6:
                return

            message_type = data[0]
            if message_type == 20:
                # Robot Message packet: controller text (protective-stop
                # reasons, popups, key/error messages). No robot state here --
                # route to the safety logger and stop.
                self._handle_robot_message(data)
                return
            if message_type != 16:
                self.logger.debug("Robot state message type %s (expected 16), trying to parse anyway", message_type)

            # Parse subpackages starting at byte 1 (try even if message type != 16 for port 30003 variants)
            self._parse_robot_state_subpackages(data, 1)
            self._notify_callbacks()
            self._update_safety_logger()

        except Exception as e:
            self.logger.debug(f"Error processing real-time data: {e}")

    def _handle_robot_message(self, data: bytes) -> None:
        """Extract human-readable text from a UR Robot Message (type 20) packet
        and buffer it in the safety logger. Heuristic and fully defensive: we
        scan for printable-ASCII runs rather than decoding every message
        subtype, so it cannot crash on an unexpected layout."""
        if not self.safety_logger:
            return
        try:
            import re
            for match in re.findall(rb'[\x20-\x7e]{4,}', data[1:]):
                text = match.decode('ascii', errors='ignore').strip()
                if len(text) >= 4:
                    self.safety_logger.note_robot_message(text)
        except Exception as e:
            self.logger.debug("robot message parse failed: %s", e)

    def _update_safety_logger(self) -> None:
        """Feed current safety state to the safety logger. It writes a log
        block only on a transition into a protective/emergency stop."""
        if not self.safety_logger:
            return
        try:
            self.safety_logger.on_state(
                protective=self.robot_state.get('protective_stopped', False),
                emergency=self.robot_state.get('emergency_stopped', False),
                robot_mode=self.robot_state.get('robot_mode'),
                joints=self.robot_state.get('joint_angles'),
                tcp=self.robot_state.get('tcp_pose'),
            )
        except Exception as e:
            self.logger.debug("safety logger update failed: %s", e)
    
    def _convert_axis_angle_to_rpy(self, axis_angle_pose: List[float]) -> List[float]:
        """
        Convert axis-angle representation to RPY angles to match UR teach pendant.
        
        Args:
            axis_angle_pose: [x, y, z, rx_aa, ry_aa, rz_aa] where rx_aa, ry_aa, rz_aa are axis-angle
            
        Returns:
            [x, y, z, rx_rpy, ry_rpy, rz_rpy] where rx_rpy, ry_rpy, rz_rpy are RPY angles
        """
        if not SCIPY_AVAILABLE:
            self.logger.warning("SciPy not available, cannot convert axis-angle to RPY")
            return axis_angle_pose
        
        try:
            # Extract position and axis-angle rotation
            position = axis_angle_pose[:3]
            axis_angle = axis_angle_pose[3:6]
            
            # Log original axis-angle data for comparison
            self.logger.debug(f"Converting axis-angle to RPY: input=[{axis_angle[0]:.6f}, {axis_angle[1]:.6f}, {axis_angle[2]:.6f}]")
            
            # Check if the axis-angle values look reasonable (should be within ±2π for most cases)
            if any(abs(val) > 10 for val in axis_angle):
                self.logger.warning(f"Suspicious axis-angle values: {axis_angle} - might not be orientation data")
                # Return original data if values seem wrong
                return axis_angle_pose
            
            # Convert axis-angle to rotation vector format
            # UR uses axis-angle representation where the magnitude is the angle
            rotation_vector = np.array(axis_angle)
            
            # Create rotation object from rotation vector (axis-angle)
            rotation = R.from_rotvec(rotation_vector)
            
            # Convert to RPY angles (XYZ convention to match UR teach pendant)
            # Try different conventions to see which matches better
            rpy_xyz = rotation.as_euler('XYZ', degrees=False)  # Roll, Pitch, Yaw order
            rpy_zyx = rotation.as_euler('ZYX', degrees=False)  # Yaw, Pitch, Roll order
            
            # Log both conventions for comparison
            self.logger.debug(f"RPY XYZ: [{rpy_xyz[0]:.6f}, {rpy_xyz[1]:.6f}, {rpy_xyz[2]:.6f}]")
            self.logger.debug(f"RPY ZYX: [{rpy_zyx[0]:.6f}, {rpy_zyx[1]:.6f}, {rpy_zyx[2]:.6f}]")
            
            # Use XYZ convention (Roll, Pitch, Yaw) as it's more common for UR robots
            rx_rpy, ry_rpy, rz_rpy = rpy_xyz[0], rpy_xyz[1], rpy_xyz[2]
            
            # Log final result for verification
            self.logger.debug(f"Final RPY: Rx={rx_rpy:.6f}, Ry={ry_rpy:.6f}, Rz={rz_rpy:.6f}")
            
            # Return position + RPY angles
            return [position[0], position[1], position[2], rx_rpy, ry_rpy, rz_rpy]
            
        except Exception as e:
            self.logger.debug(f"Error converting axis-angle to RPY: {e}")
            return axis_angle_pose

    def _test_conversion_with_known_values(self):
        """Test the conversion with known values to verify it works correctly."""
        if not SCIPY_AVAILABLE:
            return
            
        try:
            # Expected teach pendant values: Rx: 1.707 rad, Ry: 3.654 rad, Rz: -0.579 rad
            # Let's reverse-engineer what axis-angle values would produce these RPY values
            expected_rpy = [1.707, 3.654, -0.579]  # Rx, Ry, Rz from teach pendant
            
            # UR robots typically use ZYX Euler convention (yaw-pitch-roll)
            # Try different conventions to find the right one
            self.logger.info(f"=== CONVERSION TEST ===")
            self.logger.info(f"Expected RPY: Rx={expected_rpy[0]:.6f}, Ry={expected_rpy[1]:.6f}, Rz={expected_rpy[2]:.6f}")
            
            best_match = None
            best_diff = float('inf')
            
            for convention, desc in [('XYZ', 'Roll-Pitch-Yaw'), ('ZYX', 'Yaw-Pitch-Roll'), ('ZXY', 'Alt convention')]:
                try:
                    rotation = R.from_euler(convention, expected_rpy, degrees=False)
                    axis_angle = rotation.as_rotvec()
                    
                    # Test our conversion
                    test_pose = [0.0, 0.0, 0.0, axis_angle[0], axis_angle[1], axis_angle[2]]
                    converted_pose = self._convert_axis_angle_to_rpy(test_pose)
                    
                    # Check if conversion is accurate
                    rpy_diff = [abs(converted_pose[3] - expected_rpy[0]), 
                               abs(converted_pose[4] - expected_rpy[1]), 
                               abs(converted_pose[5] - expected_rpy[2])]
                    total_diff = sum(rpy_diff)
                    
                    self.logger.info(f"Convention {convention} ({desc}):")
                    self.logger.info(f"  Generated axis-angle: [{axis_angle[0]:.6f}, {axis_angle[1]:.6f}, {axis_angle[2]:.6f}]")
                    self.logger.info(f"  Converted back RPY: Rx={converted_pose[3]:.6f}, Ry={converted_pose[4]:.6f}, Rz={converted_pose[5]:.6f}")
                    self.logger.info(f"  Differences: {rpy_diff}, Total: {total_diff:.6f}")
                    
                    if total_diff < best_diff:
                        best_diff = total_diff
                        best_match = convention
                except Exception as e:
                    self.logger.warning(f"Convention {convention} failed: {e}")
            
            if best_match and best_diff < 0.01:
                self.logger.info(f"✅ Best match: {best_match} convention (diff: {best_diff:.6f})")
            else:
                self.logger.warning(f"❌ No good conversion found. Best was {best_match} with diff {best_diff:.6f}")
            self.logger.info(f"======================")
            
        except Exception as e:
            self.logger.error(f"Error in conversion test: {e}")

    def _parse_robot_state_subpackages(self, data: bytes, start: int):
        """
        Parse Robot State message subpackages (UR Primary/Secondary spec).
        Subpackage: 4 bytes length (big-endian uint32), 1 byte type, then payload.
        - Type 1 or 2 (JointData): 6 joints, 41 bytes each. First 8 bytes per joint = q_actual (rad).
        - Type 4, 5 or 6 (CartesianInfo): 12 doubles or first 6 = TCP. Position can be in m or mm.
        If no known subpackage is found, fallback: scan for 6 consecutive doubles in joint range.
        """
        try:
            pos = start
            joint_updated = False
            tcp_updated = False
            while pos + 5 <= len(data):
                sub_len = struct.unpack('>I', data[pos:pos + 4])[0]
                sub_type = data[pos + 4]
                if sub_len < 5 or pos + sub_len > len(data):
                    break
                payload_start = pos + 5
                payload = data[payload_start:pos + sub_len]

                # Robot Mode Data (type 0): the real safety flags + robot mode.
                # Payload layout: uint64 timestamp, then bools isRealRobotConnected/
                # Enabled/PowerOn/EmergencyStopped/ProtectiveStopped/ProgramRunning/
                # ProgramPaused, then uint8 robotMode.
                if sub_type == 0 and len(payload) >= 16:
                    self.robot_state['emergency_stopped'] = payload[11] != 0
                    self.robot_state['protective_stopped'] = payload[12] != 0
                    self.robot_state['program_running'] = payload[13] != 0
                    self.robot_state['robot_mode'] = payload[15]

                # Joint data: types 1 (Primary/Secondary) or 2 (some RT interfaces)
                if sub_type in (1, 2) and len(payload) >= 246:
                    joint_angles = []
                    for i in range(6):
                        j_start = i * 41
                        if j_start + 8 <= len(payload):
                            q_actual = struct.unpack('>d', payload[j_start:j_start + 8])[0]
                            joint_angles.append(q_actual)
                    if len(joint_angles) == 6 and all(-7.0 < q < 7.0 for q in joint_angles):
                        self.robot_state['joint_angles'] = joint_angles
                        joint_updated = True
                        if any(abs(q) >= 0.01 for q in joint_angles):
                            self._position_received = True

                # Cartesian / TCP: types 4, 5 or 6; first 6 doubles = X,Y,Z,Rx,Ry,Rz
                elif sub_type in (4, 5, 6) and len(payload) >= 48:
                    tcp_pose = list(struct.unpack('>6d', payload[0:48]))
                    # Position may be in meters or mm (robot screen often shows mm, e.g. -622, 470, 52)
                    px, py, pz = tcp_pose[0], tcp_pose[1], tcp_pose[2]
                    max_pos = max(abs(px), abs(py), abs(pz))
                    if max_pos >= 0.02 and max_pos <= 5000.0:
                        if max_pos > 5.0:
                            # Values in hundreds/thousands -> mm
                            tcp_pose[0] = px / 1000.0
                            tcp_pose[1] = py / 1000.0
                            tcp_pose[2] = pz / 1000.0
                    if all(-5.0 < tcp_pose[i] < 5.0 for i in range(3)):
                        self.robot_state['tcp_pose'] = tcp_pose
                        tcp_updated = True

                pos += sub_len

            # Fallback: if no joint subpackage found, scan for 6 consecutive doubles in joint range (rad)
            if not joint_updated and len(data) >= start + 48:
                for scan in range(start, min(len(data) - 48, start + 2000), 8):
                    try:
                        six = list(struct.unpack('>6d', data[scan:scan + 48]))
                        if all(-4.0 < q < 4.0 for q in six) and not any(abs(q) > 1e6 for q in six):
                            self.robot_state['joint_angles'] = six
                            if any(abs(q) >= 0.01 for q in six):
                                self._position_received = True
                            break
                    except struct.error:
                        continue

            self.robot_state['timestamp'] = time.time()
        except struct.error as e:
            self.logger.debug(f"Error unpacking UR subpackages: {e}")
        except Exception as e:
            self.logger.debug(f"Error parsing robot state subpackages: {e}")

    def _parse_safety_message(self, data: bytes, offset: int):
        """
        Parse safety status message from binary data.
        
        Args:
            data: Binary message data
            offset: Current parsing offset
        """
        try:
            # Placeholder for actual safety data parsing
            # Real implementation would decode safety status from binary data
            
            # For demonstration, use some default safety values
            self.robot_state['robot_mode'] = 7  # RUNNING mode
            self.robot_state['safety_mode'] = 1  # NORMAL mode
            self.robot_state['emergency_stopped'] = False
            self.robot_state['protective_stopped'] = False
            self.robot_state['program_running'] = True
            self.robot_state['speed_scaling'] = 1.0
            
        except Exception as e:
            self.logger.debug(f"Error parsing safety message: {e}")
    
    def _notify_callbacks(self):
        """Notify all registered callbacks with updated data."""
        try:
            # Notify complete data callbacks
            for callback in self.data_callbacks:
                try:
                    callback(self.robot_state)
                except Exception as e:
                    self.logger.error(f"Error in data callback: {e}")
            
            # Notify position callbacks
            for callback in self.position_callbacks:
                try:
                    callback(self.robot_state['tcp_pose'], self.robot_state['joint_angles'])
                except Exception as e:
                    self.logger.error(f"Error in position callback: {e}")
            
            # Notify safety callbacks
            safety_data = {
                'robot_mode': self.robot_state['robot_mode'],
                'safety_mode': self.robot_state['safety_mode'],
                'emergency_stopped': self.robot_state['emergency_stopped'],
                'protective_stopped': self.robot_state['protective_stopped'],
                'program_running': self.robot_state['program_running'],
                'speed_scaling': self.robot_state['speed_scaling']
            }
            
            for callback in self.safety_callbacks:
                try:
                    callback(safety_data)
                except Exception as e:
                    self.logger.error(f"Error in safety callback: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error notifying callbacks: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
