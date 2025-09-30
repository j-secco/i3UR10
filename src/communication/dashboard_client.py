"""
Dashboard Client for UR10 Robot

This module handles the dashboard server communication for Universal Robot UR10.
The dashboard interface (port 29999) provides robot program control, power management,
and basic robot status information.

Based on Universal Robots Dashboard Server documentation.
Author: jsecco ®
"""

import socket
import time
import threading
import logging
from typing import Dict, Optional, Tuple, Any

class DashboardClient:
    """
    Dashboard client for UR10 robot control and status management.
    Handles basic robot operations like power control, program management, and status queries.
    """
    
    def __init__(self, hostname: str, port: int = 29999, timeout: float = 5.0):
        """
        Initialize dashboard client.
        
        Args:
            hostname: Robot IP address
            port: Dashboard server port (29999)
            timeout: Socket timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.timeout = timeout
        
        # Connection management
        self.socket = None
        self.connected = False
        self.lock = threading.Lock()
        
        # Robot status cache
        self.robot_status = {
            'robot_model': 'UR10',
            'polyscope_version': 'Unknown',
            'program_state': 'STOPPED',
            'robot_mode': 'DISCONNECTED',
            'safety_mode': 'NORMAL',
            'program_running': False,
            'program_saved': True,
            'remote_control': False,
            'power_on': False,
            'brakes_released': False
        }
        
        # Logging
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Dashboard command responses
        self.ROBOT_MODES = {
            'DISCONNECTED': -1,
            'CONFIRM_SAFETY': 0,
            'BOOTING': 1,
            'POWER_OFF': 2,
            'POWER_ON': 3,
            'IDLE': 4,
            'BACKDRIVE': 5,
            'RUNNING': 6,
            'UPDATING_FIRMWARE': 7
        }
        
        self.SAFETY_MODES = {
            'NORMAL': 1,
            'REDUCED': 2,
            'PROTECTIVE_STOP': 3,
            'RECOVERY': 4,
            'SAFEGUARD_STOP': 5,
            'SYSTEM_EMERGENCY_STOP': 6,
            'ROBOT_EMERGENCY_STOP': 7,
            'VIOLATION': 8,
            'FAULT': 9,
            'AUTOMATIC_MODE_SAFEGUARD_STOP': 10,
            'SYSTEM_THREE_POSITION_ENABLING': 11
        }
        
        self.PROGRAM_STATES = {
            'STOPPED': 0,
            'PLAYING': 1,
            'PAUSED': 2
        }
    
    def connect(self) -> bool:
        """
        Connect to UR10 dashboard server.
        
        Returns:
            True if connection successful, False otherwise
        """
        with self.lock:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                self.socket.connect((self.hostname, self.port))
                
                # Read welcome message
                welcome = self._receive_response()
                if welcome and "Connected" in welcome:
                    self.connected = True
                    self.logger.info(f"Connected to UR10 Dashboard at {self.hostname}:{self.port}")
                    return True
                else:
                    self.logger.warning(f"Unexpected welcome message: {welcome}")
                    
            except Exception as e:
                self.logger.error(f"Failed to connect to Dashboard: {e}")
                
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return False
    
    def disconnect(self):
        """Disconnect from dashboard server."""
        with self.lock:
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                finally:
                    self.socket = None
            self.logger.info("Disconnected from UR10 Dashboard")
    
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self.connected and self.socket is not None
    
    def _send_command(self, command: str) -> Optional[str]:
        """
        Send command to dashboard server and get response.
        
        Args:
            command: Dashboard command to send
            
        Returns:
            Response string or None if failed
        """
        if not self.is_connected():
            self.logger.error("Dashboard not connected")
            return None
        
        try:
            with self.lock:
                # Send command
                full_command = f"{command}\n"
                self.socket.send(full_command.encode('utf-8'))
                
                # Receive response
                response = self._receive_response()
                
                self.logger.debug(f"Dashboard command: {command} -> {response}")
                return response
                
        except Exception as e:
            self.logger.error(f"Dashboard command failed '{command}': {e}")
            self.connected = False
            return None
    
    def _receive_response(self) -> Optional[str]:
        """
        Receive response from dashboard server.
        
        Returns:
            Response string or None if failed
        """
        try:
            response = ""
            while True:
                data = self.socket.recv(1024).decode('utf-8')
                if not data:
                    break
                response += data
                if response.endswith('\n'):
                    break
            return response.strip()
        except Exception as e:
            self.logger.debug(f"Error receiving dashboard response: {e}")
            return None
    
    # Power Control Commands
    
    def power_on(self) -> bool:
        """
        Turn robot power on.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("power on")
        success = response and "Powering on" in response
        if success:
            self.robot_status['power_on'] = True
        return success
    
    def power_off(self) -> bool:
        """
        Turn robot power off.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("power off")
        success = response and "Powering off" in response
        if success:
            self.robot_status['power_on'] = False
            self.robot_status['brakes_released'] = False
        return success
    
    def brake_release(self) -> bool:
        """
        Release robot brakes.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("brake release")
        success = response and "Brake releasing" in response
        if success:
            self.robot_status['brakes_released'] = True
        return success
    
    # Program Control Commands
    
    def load_program(self, program_path: str) -> bool:
        """
        Load a robot program.
        
        Args:
            program_path: Path to the .urp program file
            
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command(f"load {program_path}")
        success = response and ("Loading program" in response or "File loaded" in response)
        return success
    
    def play(self) -> bool:
        """
        Start program execution.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("play")
        success = response and ("Starting program" in response or "Program running" in response)
        if success:
            self.robot_status['program_running'] = True
            self.robot_status['program_state'] = 'PLAYING'
        return success
    
    def stop(self) -> bool:
        """
        Stop program execution.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("stop")
        success = response and ("Stopped" in response or "Program stopped" in response)
        if success:
            self.robot_status['program_running'] = False
            self.robot_status['program_state'] = 'STOPPED'
        return success
    
    def pause(self) -> bool:
        """
        Pause program execution.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("pause")
        success = response and ("Pausing program" in response or "Program paused" in response)
        if success:
            self.robot_status['program_state'] = 'PAUSED'
        return success
    
    # Safety and Recovery Commands
    
    def unlock_protective_stop(self) -> bool:
        """
        Clear protective stop condition.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("unlock protective stop")
        return response and "Protective stop releasing" in response
    
    def close_safety_popup(self) -> bool:
        """
        Close safety popup dialog.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("close safety popup")
        return response and "closing safety popup" in response
    
    def close_popup(self) -> bool:
        """
        Close any popup dialog.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("close popup")
        return response and "closing popup" in response
    
    def restart_safety(self) -> bool:
        """
        Restart safety system.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("restart safety")
        return response and "Restarting safety" in response
    
    # Status Query Commands
    
    def get_robot_model(self) -> Optional[str]:
        """
        Get robot model information.
        
        Returns:
            Robot model string or None if failed
        """
        response = self._send_command("get robot model")
        if response:
            self.robot_status['robot_model'] = response
        return response
    
    def get_program_state(self) -> Optional[str]:
        """
        Get current program execution state.
        
        Returns:
            Program state string or None if failed
        """
        response = self._send_command("programState")
        if response:
            self.robot_status['program_state'] = response
            self.robot_status['program_running'] = response == "PLAYING"
        return response
    
    def get_robot_mode(self) -> Optional[str]:
        """
        Get current robot mode.
        
        Returns:
            Robot mode string or None if failed
        """
        response = self._send_command("robotmode")
        if response:
            self.robot_status['robot_mode'] = response
        return response
    
    def get_safety_mode(self) -> Optional[str]:
        """
        Get current safety mode.
        
        Returns:
            Safety mode string or None if failed
        """
        response = self._send_command("safetymode")
        if response:
            self.robot_status['safety_mode'] = response
        return response
    
    def get_polyscope_version(self) -> Optional[str]:
        """
        Get Polyscope software version.
        
        Returns:
            Version string or None if failed
        """
        response = self._send_command("version")
        if response:
            self.robot_status['polyscope_version'] = response
        return response
    
    def is_program_running(self) -> bool:
        """
        Check if program is currently running.
        
        Returns:
            True if program is running, False otherwise
        """
        state = self.get_program_state()
        return state == "PLAYING"
    
    def is_program_saved(self) -> bool:
        """
        Check if program is saved.
        
        Returns:
            True if program is saved, False otherwise
        """
        response = self._send_command("isProgramSaved")
        saved = response and response.lower() == "true"
        self.robot_status['program_saved'] = saved
        return saved
    
    def is_in_remote_control(self) -> bool:
        """
        Check if robot is in remote control mode.
        
        Returns:
            True if in remote control, False otherwise
        """
        response = self._send_command("is in remote control")
        remote = response and response.lower() == "true"
        self.robot_status['remote_control'] = remote
        return remote
    
    # Utility Methods
    
    def update_status(self) -> Dict[str, Any]:
        """
        Update all robot status information.
        
        Returns:
            Dictionary containing current robot status
        """
        if not self.is_connected():
            return self.robot_status
        
        try:
            self.get_robot_model()
            self.get_program_state()
            self.get_robot_mode()
            self.get_safety_mode()
            self.get_polyscope_version()
            self.is_program_saved()
            self.is_in_remote_control()
            
        except Exception as e:
            self.logger.error(f"Error updating dashboard status: {e}")
        
        return self.robot_status.copy()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get cached robot status.
        
        Returns:
            Dictionary containing robot status information
        """
        return self.robot_status.copy()
    
    def emergency_stop(self) -> bool:
        """
        Execute emergency stop via dashboard (if available).
        Note: This may not be available on all UR versions via dashboard.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("stop")
        return response and "stop" in response.lower()
    
    def shutdown(self) -> bool:
        """
        Shutdown the robot controller.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("shutdown")
        return response and "Shutting down" in response
    
    def quit_dashboard(self) -> bool:
        """
        Close dashboard connection gracefully.
        
        Returns:
            True if successful, False otherwise
        """
        response = self._send_command("quit")
        success = response and ("Disconnected" in response or "Goodbye" in response)
        if success:
            self.disconnect()
        return success
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
