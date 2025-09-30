"""
WebSocket Controller for UR10 Robot

This module handles the primary WebSocket communication for sending URScript commands 
to the Universal Robot UR10. Uses the primary interface (port 30001) for bidirectional
communication including robot state data and command execution.

Based on Universal Robots Socket Communication documentation.
Author: jsecco ®
"""

import socket
import time
import threading
import logging
import json
from typing import List, Dict, Optional, Callable, Any

class WebSocketController:
    """
    Primary WebSocket controller for UR10 robot communication.
    Handles URScript command sending and robot state monitoring via primary interface.
    """
    
    def __init__(self, hostname: str, port: int = 30001, timeout: float = 5.0):
        """
        Initialize WebSocket controller.
        
        Args:
            hostname: Robot IP address
            port: Communication port (30001 for primary interface)
            timeout: Socket timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.timeout = timeout
        
        # Connection management
        self.socket = None
        self.connected = False
        self.reconnect_attempts = 5
        self.reconnect_delay = 2.0
        
        # Threading for continuous data reception
        self.receive_thread = None
        self.should_stop = threading.Event()
        
        # Robot state data
        self.robot_state = {}
        self.last_position = [0.0] * 6
        self.last_joint_angles = [0.0] * 6
        self.robot_mode = "UNKNOWN"
        self.safety_status = "UNKNOWN"
        
        # Callbacks for state updates
        self.state_callbacks: List[Callable[[Dict], None]] = []
        
        # Logging
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def connect(self) -> bool:
        """
        Establish connection to UR10 primary interface.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.hostname, self.port))
            
            self.connected = True
            self.logger.info(f"Connected to UR10 at {self.hostname}:{self.port}")
            
            # Start receiving thread
            self.should_stop.clear()
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to UR10: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from robot and cleanup resources."""
        self.should_stop.set()
        self.connected = False
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
            
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            finally:
                self.socket = None
                
        self.logger.info("Disconnected from UR10")
    
    def reconnect(self) -> bool:
        """
        Attempt to reconnect to robot with retry logic.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        self.disconnect()
        
        for attempt in range(self.reconnect_attempts):
            self.logger.info(f"Reconnection attempt {attempt + 1}/{self.reconnect_attempts}")
            
            if self.connect():
                return True
                
            if attempt < self.reconnect_attempts - 1:
                time.sleep(self.reconnect_delay)
                
        self.logger.error("Failed to reconnect after all attempts")
        return False
    
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self.connected and self.socket is not None
    
    def send_command(self, command: str) -> bool:
        """
        Send URScript command to robot.
        
        Args:
            command: URScript command string
            
        Returns:
            True if command sent successfully, False otherwise
        """
        if not self.is_connected():
            self.logger.error("Cannot send command: not connected")
            return False
        
        try:
            # Format command with newline (required by UR)
            formatted_command = f"{command}\n"
            self.socket.send(formatted_command.encode('utf-8'))
            
            self.logger.debug(f"Sent command: {command}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send command '{command}': {e}")
            self.connected = False
            return False
    
    def move_linear(self, pose: List[float], speed: float = 0.1, 
                   acceleration: float = 1.2, blend: float = 0.0) -> bool:
        """
        Send linear movement command (movel).
        
        Args:
            pose: Target pose [x, y, z, rx, ry, rz] in meters and radians
            speed: Tool speed in m/s
            acceleration: Tool acceleration in m/s^2
            blend: Blend radius in meters
            
        Returns:
            True if command sent successfully
        """
        pose_str = f"[{', '.join(map(str, pose))}]"
        command = f"movel({pose_str}, a={acceleration}, v={speed}, r={blend})"
        return self.send_command(command)
    
    def move_joint(self, joints: List[float], speed: float = 1.05, 
                  acceleration: float = 1.4, blend: float = 0.0) -> bool:
        """
        Send joint movement command (movej).
        
        Args:
            joints: Target joint angles [j1, j2, j3, j4, j5, j6] in radians
            speed: Joint speed in rad/s
            acceleration: Joint acceleration in rad/s^2
            blend: Blend radius in radians
            
        Returns:
            True if command sent successfully
        """
        joints_str = f"[{', '.join(map(str, joints))}]"
        command = f"movej({joints_str}, a={acceleration}, v={speed}, r={blend})"
        return self.send_command(command)
    
    def speed_linear(self, velocities: List[float], acceleration: float = 1.2, 
                    time_limit: float = 0.0) -> bool:
        """
        Send linear speed command (speedl).
        
        Args:
            velocities: Velocity vector [vx, vy, vz, vrx, vry, vrz] in m/s and rad/s
            acceleration: Acceleration in m/s^2
            time_limit: Time limit in seconds (0 = unlimited)
            
        Returns:
            True if command sent successfully
        """
        vel_str = f"[{', '.join(map(str, velocities))}]"
        command = f"speedl({vel_str}, a={acceleration}, t={time_limit})"
        return self.send_command(command)
    
    def speed_joint(self, joint_speeds: List[float], acceleration: float = 1.4, 
                   time_limit: float = 0.0) -> bool:
        """
        Send joint speed command (speedj).
        
        Args:
            joint_speeds: Joint speeds [j1, j2, j3, j4, j5, j6] in rad/s
            acceleration: Joint acceleration in rad/s^2
            time_limit: Time limit in seconds (0 = unlimited)
            
        Returns:
            True if command sent successfully
        """
        speeds_str = f"[{', '.join(map(str, joint_speeds))}]"
        command = f"speedj({speeds_str}, a={acceleration}, t={time_limit})"
        return self.send_command(command)
    
    def stop_linear(self, deceleration: float = 10.0) -> bool:
        """
        Stop linear movement (stopl).
        
        Args:
            deceleration: Deceleration in m/s^2
            
        Returns:
            True if command sent successfully
        """
        command = f"stopl({deceleration})"
        return self.send_command(command)
    
    def stop_joint(self, deceleration: float = 10.0) -> bool:
        """
        Stop joint movement (stopj).
        
        Args:
            deceleration: Joint deceleration in rad/s^2
            
        Returns:
            True if command sent successfully
        """
        command = f"stopj({deceleration})"
        return self.send_command(command)
    
    def emergency_stop(self) -> bool:
        """
        Execute emergency stop sequence.
        
        Returns:
            True if emergency stop initiated successfully
        """
        # Send both linear and joint stops with maximum deceleration
        linear_stop = self.stop_linear(10.0)
        joint_stop = self.stop_joint(10.0)
        
        self.logger.warning("Emergency stop executed")
        return linear_stop and joint_stop
    
    def get_robot_state(self) -> Dict[str, Any]:
        """
        Get current robot state data.
        
        Returns:
            Dictionary containing latest robot state information
        """
        return self.robot_state.copy()
    
    def get_tcp_pose(self) -> List[float]:
        """Get current TCP pose [x, y, z, rx, ry, rz]."""
        return self.last_position.copy()
    
    def get_joint_angles(self) -> List[float]:
        """Get current joint angles [j1, j2, j3, j4, j5, j6]."""
        return self.last_joint_angles.copy()
    
    def add_state_callback(self, callback: Callable[[Dict], None]):
        """Add callback function for robot state updates."""
        self.state_callbacks.append(callback)
    
    def remove_state_callback(self, callback: Callable[[Dict], None]):
        """Remove callback function."""
        if callback in self.state_callbacks:
            self.state_callbacks.remove(callback)
    
    def _receive_loop(self):
        """
        Continuous loop for receiving robot state data.
        Runs in separate thread to process incoming data.
        """
        buffer = b""
        
        while not self.should_stop.is_set() and self.connected:
            try:
                # Receive data from socket
                data = self.socket.recv(4096)
                if not data:
                    self.logger.warning("No data received, connection may be lost")
                    self.connected = False
                    break
                
                buffer += data
                
                # Process complete messages (separated by newlines)
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if line:
                        try:
                            decoded_line = line.decode('utf-8').strip()
                            self._process_robot_data(decoded_line)
                        except UnicodeDecodeError:
                            # Robot sends binary data, try latin-1 or skip
                            try:
                                decoded_line = line.decode('latin-1').strip()
                                if decoded_line.isprintable():
                                    self._process_robot_data(decoded_line)
                            except:
                                # Skip non-decodable data
                                pass
                        
            except socket.timeout:
                # Timeout is normal, just continue
                continue
            except Exception as e:
                self.logger.error(f"Error in receive loop: {e}")
                self.connected = False
                break
    
    def _process_robot_data(self, data: str):
        """
        Process incoming robot state data.
        
        Args:
            data: Raw robot state data string
        """
        try:
            # Parse robot state data (format depends on UR version)
            # This is a simplified parser - actual implementation would need
            # to handle the specific data format from the UR robot
            
            if "(" in data and ")" in data:
                # Extract position data if present
                self._parse_position_data(data)
            
            # Update robot state
            self.robot_state['timestamp'] = time.time()
            self.robot_state['raw_data'] = data
            
            # Notify callbacks
            for callback in self.state_callbacks:
                try:
                    callback(self.robot_state)
                except Exception as e:
                    self.logger.error(f"Error in state callback: {e}")
                    
        except Exception as e:
            self.logger.debug(f"Error processing robot data: {e}")
    
    def _parse_position_data(self, data: str):
        """
        Parse position data from robot state string.
        
        Args:
            data: Raw robot data containing position information
        """
        try:
            # Simplified position parsing - actual implementation would need
            # to handle the specific format used by the UR robot
            
            if "actual_TCP_pose" in data or "tcp" in data.lower():
                # Extract TCP position (example parsing)
                # Real implementation would parse the actual data format
                pass
            
            if "actual_q" in data or "joint" in data.lower():
                # Extract joint angles (example parsing)
                # Real implementation would parse the actual data format
                pass
                
        except Exception as e:
            self.logger.debug(f"Error parsing position data: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
