"""
Main Jog Controller for UR10 Robot

This module provides the main controller that coordinates Cartesian and Joint jogging
operations using WebSocket communication with the Universal Robot UR10.

Author: jsecco ®
"""

import time
import threading
import logging
import yaml
from enum import Enum
from typing import List, Dict, Optional, Callable, Any, Union
from pathlib import Path

# Use absolute imports when run as module, fallback to relative for direct execution
try:
    from communication import WebSocketController, WebSocketReceiver, DashboardClient
    from control.cartesian_jog import CartesianJog
    from control.joint_jog import JointJog
    from control.safety_monitor import SafetyMonitor
    try:
        from communication.rtde_controller import RTDEController, RTDE_AVAILABLE
    except ImportError:
        RTDEController = None
        RTDE_AVAILABLE = False
except ImportError:
    try:
        from ..communication import WebSocketController, WebSocketReceiver, DashboardClient
        from .cartesian_jog import CartesianJog
        from .joint_jog import JointJog  
        from .safety_monitor import SafetyMonitor
        try:
            from ..communication.rtde_controller import RTDEController, RTDE_AVAILABLE
        except ImportError:
            RTDEController = None
            RTDE_AVAILABLE = False
    except ImportError:
        # Fallback to direct imports if running from src directory
        import sys
        from pathlib import Path
        src_path = Path(__file__).parent.parent
        sys.path.insert(0, str(src_path))
        
        from communication import WebSocketController, WebSocketReceiver, DashboardClient
        from control.cartesian_jog import CartesianJog
        from control.joint_jog import JointJog
        from control.safety_monitor import SafetyMonitor
        try:
            from communication.rtde_controller import RTDEController, RTDE_AVAILABLE
        except ImportError:
            RTDEController = None
            RTDE_AVAILABLE = False

class JogMode(Enum):
    """Jogging mode enumeration."""
    CARTESIAN = "cartesian"
    JOINT = "joint"

class JogType(Enum):
    """Jogging type enumeration."""
    STEP = "step"
    CONTINUOUS = "continuous"

class JogController:
    """
    Main controller for UR10 robot jogging operations.
    Coordinates between Cartesian and Joint jogging modes with safety monitoring.
    """
    
    def __init__(self, config: Union[str, Dict[str, Any], None] = None):
        """
        Initialize jog controller.
        
        Args:
            config: Configuration dictionary, file path, or None for default config
        """
        # Initialize logger first
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Load configuration
        if isinstance(config, dict):
            self.config = config
        else:
            self.config = self._load_config(config)
        
        # Get robot configuration
        robot_config = self.config.get('robot', {})
        hostname = robot_config.get('ip_address', '192.168.1.100')
        ports = robot_config.get('ports', {})
        use_rtde_for_motion = robot_config.get('use_rtde_for_motion', False)
        rtde_port = ports.get('rtde', 30004)

        # Check if we're in simulation mode
        self.simulation_mode = self.config.get('debug', {}).get('simulate_robot', False)

        # Communication interfaces
        if self.simulation_mode:
            # Simulation mode - don't create real connections
            self.logger.info("Running in SIMULATION MODE - no robot connection required")
            self.websocket_controller = None
            self.websocket_receiver = None
            self.dashboard_client = None
            self._use_rtde_motion = False
        else:
            # Normal mode - create real connections
            try:
                if use_rtde_for_motion and RTDE_AVAILABLE and RTDEController:
                    self.websocket_controller = RTDEController(
                        hostname,
                        port=rtde_port,
                        frequency=125.0
                    )
                    self._use_rtde_motion = True
                    self.logger.info("Using RTDE for motion (port %s)", rtde_port)
                else:
                    if use_rtde_for_motion and not (RTDE_AVAILABLE and RTDEController):
                        self.logger.warning(
                            "use_rtde_for_motion is True but ur_rtde not available; using Primary (30001)"
                        )
                    self.websocket_controller = WebSocketController(
                        hostname,
                        port=ports.get('primary', 30001),
                        timeout=robot_config.get('websocket_timeout', 5.0)
                    )
                    self._use_rtde_motion = False
                self.websocket_receiver = WebSocketReceiver(
                    hostname,
                    port=ports.get('realtime', 30003),
                    timeout=1.0
                )
                self.dashboard_client = DashboardClient(
                    hostname,
                    port=ports.get('dashboard', 29999),
                    timeout=robot_config.get('websocket_timeout', 5.0)
                )

                self.logger.info(f"Communication interfaces initialized for {hostname}")

            except Exception as e:
                self.logger.error(f"Failed to initialize communication interfaces: {e}")
                # Initialize with None for now, will be handled gracefully
                self.websocket_controller = None
                self.websocket_receiver = None
                self.dashboard_client = None
                self._use_rtde_motion = False
        
        # Jog controllers - will be initialized when communication is available
        self.cartesian_jog = None
        self.joint_jog = None
        self.safety_monitor = None
        
        # State management
        self.current_mode = JogMode.CARTESIAN
        self.current_type = JogType.CONTINUOUS
        self.connected = False
        self.jogging_active = False
        self.emergency_stop_active = False
        
        # Threading
        self.control_lock = threading.Lock()
        self.status_thread = None
        self.should_stop = threading.Event()
        
        # Callbacks
        self.position_callbacks: List[Callable[[List[float], List[float]], None]] = []
        self.status_callbacks: List[Callable[[Dict], None]] = []
        self.safety_callbacks: List[Callable[[Dict], None]] = []
        self.connection_callbacks: List[Callable[[bool], None]] = []
        self.position_fetched_callbacks: List[Callable[[], None]] = []
        
        # Status data
        self.robot_status = {
            'tcp_pose': [0.0] * 6,
            'joint_angles': [0.0] * 6,
            'tcp_speed': [0.0] * 6,
            'joint_speeds': [0.0] * 6,
            'robot_mode': 'UNKNOWN',
            'safety_mode': 'UNKNOWN',
            'program_running': False,
            'emergency_stopped': False,
            'protective_stopped': False,
            'connection_status': 'DISCONNECTED',
            'robot_error': '',
            'robot_warning': '',
            'jog_mode': self.current_mode.value,
            'jog_type': self.current_type.value,
            'jogging_active': False
        }
        
        self.logger.info("JogController initialized successfully")
    
    def _load_config(self, config_file: str = None) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if config_file is None:
            config_file = Path(__file__).parent.parent.parent / "config" / "robot_config.yaml"
        
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            if hasattr(self, 'logger'):
                self.logger.info(f"Loaded configuration from {config_file}")
            return config
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Failed to load configuration: {e}")
            else:
                print(f"Failed to load configuration: {e}")
            
            # Return default configuration
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'robot': {
                'ip_address': '192.168.10.24',
                'ports': {
                    'primary': 30001,
                    'realtime': 30003,
                    'dashboard': 29999
                },
                'websocket_timeout': 5.0
            },
            'jogging': {
                'cartesian': {
                    'max_linear_speed': 0.25,
                    'max_angular_speed': 0.75,
                    'linear_acceleration': 1.2,
                    'angular_acceleration': 3.14,
                    'linear_step_sizes': [0.001, 0.005, 0.01, 0.05, 0.1],
                    'angular_step_sizes': [0.017, 0.087, 0.175, 0.524, 1.047]
                },
                'joint': {
                    'max_joint_speed': 1.05,
                    'joint_acceleration': 1.4,
                    'joint_step_sizes': [0.017, 0.087, 0.175, 0.524, 1.047]
                },
                'safety': {
                    'enable_workspace_limits': True,
                    'emergency_stop_deceleration': 10.0,
                    'protective_stop_timeout': 5.0,
                    'max_jog_time': 30.0
                }
            }
        }
    
    def _initialize_jog_controllers(self):
        """Initialize jog controllers after communication interfaces are ready."""
        if not self.websocket_controller or not self.websocket_receiver or not self.dashboard_client:
            self.logger.error("Cannot initialize jog controllers - communication interfaces not available")
            return False
        
        try:
            jogging_config = self.config.get('jogging', {})

            # Jog controllers need receiver for step jog (current position)
            self.cartesian_jog = CartesianJog(
                self.websocket_controller,
                jogging_config.get('cartesian', {}),
                self.websocket_receiver
            )
            self.joint_jog = JointJog(
                self.websocket_controller,
                jogging_config.get('joint', {}),
                self.websocket_receiver
            )
            
            # Safety monitor
            self.safety_monitor = SafetyMonitor(
                self.websocket_receiver,
                self.dashboard_client,
                jogging_config.get('safety', {})
            )
            
            # Setup callbacks
            self._setup_callbacks()
            
            self.logger.info("Jog controllers initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize jog controllers: {e}")
            return False

    def _ensure_robot_position_available(self) -> None:
        """
        On connect: wait briefly for position from realtime stream, then if still no position
        request once from primary interface so the app has current robot position (e.g. for Save as home).
        When using RTDE for motion, primary is not connected; position comes only from receiver.
        """
        if not self.websocket_receiver or not self.websocket_controller:
            return
        wait_s = 3.0
        poll_interval = 0.2
        elapsed = 0.0
        while elapsed < wait_s:
            if self.websocket_receiver.has_valid_position():
                self.logger.info("Robot position received from realtime stream")
                return
            time.sleep(poll_interval)
            elapsed += poll_interval
        if getattr(self, '_use_rtde_motion', False):
            self.logger.warning("No position from realtime within %.1fs (RTDE mode; position from receiver only)", wait_s)
            return
        self.logger.info("No position from realtime within %.1fs, requesting from primary", wait_s)
        joints = self.websocket_controller.request_joint_positions(wait_s=1.5)
        if joints and len(joints) == 6 and any(abs(q) >= 0.01 for q in joints):
            self.websocket_receiver.set_joint_angles(joints)
            self.robot_status['joint_angles'] = joints
            self.logger.info("Robot position set from primary interface")
        else:
            self.logger.warning("Could not get robot position from primary interface")

    def _fetch_position_after_connect(self) -> None:
        """
        Run in background after connect: pull position from robot.
        First wait briefly for realtime (30003); if no position and using Primary,
        use primary (30001) binary robot state stream. When using RTDE, position
        comes only from realtime stream.
        """
        if not self.websocket_receiver or not self.websocket_controller:
            return
        time.sleep(0.3)
        wait_realtime_s = 1.0
        poll_interval = 0.2
        elapsed = 0.0
        while elapsed < wait_realtime_s and self.connected:
            if self.websocket_receiver.has_valid_position():
                self.logger.info("Robot position received from realtime stream (port 30003)")
                self._notify_position_fetched()
                return
            time.sleep(poll_interval)
            elapsed += poll_interval
        if getattr(self, '_use_rtde_motion', False):
            self._notify_position_fetched()
            return
        if self.websocket_controller.has_valid_position():
            joints = self.websocket_controller.get_joint_angles()
            if joints and len(joints) == 6:
                self.websocket_receiver.set_joint_angles(joints, notify=False)
                self.robot_status["joint_angles"] = joints
                self.logger.info("Robot position updated from primary interface (port 30001)")
        else:
            joints = self.websocket_controller.request_joint_positions(wait_s=2.0)
            if joints and len(joints) == 6 and any(abs(q) >= 0.01 for q in joints):
                self.websocket_receiver.set_joint_angles(joints, notify=False)
                self.robot_status["joint_angles"] = joints
                self.logger.info("Robot position updated from primary interface (port 30001)")
        self._notify_position_fetched()

    def _notify_position_fetched(self) -> None:
        """Call registered callbacks so UI can update on main thread."""
        for cb in self.position_fetched_callbacks:
            try:
                cb()
            except Exception as e:
                self.logger.error("Position fetched callback error: %s", e)

    def add_position_fetched_callback(self, callback: Callable[[], None]) -> None:
        """Register callback to run when position has been fetched from robot (e.g. to refresh UI on main thread)."""
        self.position_fetched_callbacks.append(callback)

    def _setup_callbacks(self):
        """Setup callbacks for communication interfaces."""
        if not all([self.websocket_receiver, self.safety_monitor]):
            return
            
        try:
            # WebSocket receiver callbacks
            self.websocket_receiver.add_position_callback(self._on_position_update)
            self.websocket_receiver.add_safety_callback(self._on_safety_update)
            self.websocket_receiver.add_data_callback(self._on_data_update)
            
            # Safety monitor callbacks
            self.safety_monitor.add_emergency_callback(self._on_emergency_stop)
            self.safety_monitor.add_protective_callback(self._on_protective_stop)
            
        except Exception as e:
            self.logger.error(f"Error setting up callbacks: {e}")
    
    # Connection Management
    
    def connect(self) -> bool:
        """
        Connect to UR10 robot interfaces.

        Returns:
            True if all connections successful, False otherwise
        """
        with self.control_lock:
            try:
                # Handle simulation mode
                if self.simulation_mode:
                    self.logger.info("Simulation mode - skipping robot connection")
                    self.connected = True
                    self.robot_status['connection_status'] = 'SIMULATED'
                    self._notify_connection_callbacks(True)
                    return True

                # Initialize communication interfaces if needed
                if not self.websocket_controller:
                    self.logger.error("WebSocket controller not available")
                    return False

                # Connect order: when using RTDE, connect receiver and dashboard first;
                # when using Primary, connect primary then receiver then dashboard.
                use_rtde = getattr(self, '_use_rtde_motion', False)

                if use_rtde:
                    if not self.websocket_receiver.connect():
                        self.logger.error("Failed to connect to real-time interface")
                        return False
                    if not self.dashboard_client.connect():
                        self.logger.warning("Dashboard connection failed (non-critical)")
                    if not self.websocket_controller.connect():
                        self.logger.error("Failed to connect to RTDE interface")
                        if self.websocket_receiver:
                            self.websocket_receiver.disconnect()
                        return False
                else:
                    if not self.websocket_controller.connect():
                        self.logger.error("Failed to connect to primary interface")
                        return False
                    if not self.websocket_receiver.connect():
                        self.logger.error("Failed to connect to real-time interface")
                        self.websocket_controller.disconnect()
                        return False
                    if not self.dashboard_client.connect():
                        self.logger.warning("Dashboard connection failed (non-critical)")
                
                # Initialize jog controllers
                if not self._initialize_jog_controllers():
                    self.logger.error("Failed to initialize jog controllers")
                    self.disconnect()
                    return False

                # Start safety monitoring
                if self.safety_monitor:
                    self.safety_monitor.start()
                
                # Start status monitoring thread
                self.should_stop.clear()
                self.status_thread = threading.Thread(target=self._status_loop, daemon=True)
                self.status_thread.start()
                
                self.connected = True
                self.robot_status['connection_status'] = 'CONNECTED'
                
                # Immediate safety/status read so UI sees protective stop right after connect
                # (status loop may take ~0.5s before first Dashboard poll)
                self._update_status_from_dashboard_once()
                
                self.logger.info("Successfully connected to UR10")
                self._notify_connection_callbacks(True)

                # Pull position from robot in background so UI does not lag
                threading.Thread(target=self._fetch_position_after_connect, daemon=True).start()

                return True
                
            except Exception as e:
                self.logger.error(f"Connection error: {e}")
                self.disconnect()
                return False
    
    def disconnect(self):
        """Disconnect from all robot interfaces."""
        with self.control_lock:
            self.connected = False
            self.should_stop.set()
            
            # Stop any active jogging
            if self.jogging_active:
                self._stop_current_jog()
            
            # Stop safety monitoring
            if self.safety_monitor:
                self.safety_monitor.stop()
            
            # Disconnect communication interfaces
            if self.websocket_controller:
                self.websocket_controller.disconnect()
            if self.websocket_receiver:
                self.websocket_receiver.disconnect()
            if self.dashboard_client:
                self.dashboard_client.disconnect()
            
            # Wait for status thread to stop
            if self.status_thread and self.status_thread.is_alive():
                self.status_thread.join(timeout=2.0)
            
            self.robot_status['connection_status'] = 'DISCONNECTED'
            
            self.logger.info("Disconnected from UR10")
            self._notify_connection_callbacks(False)
    
    def disconnect_all(self):
        """Disconnect from all interfaces - alias for compatibility."""
        self.disconnect()
    
    def is_connected(self) -> bool:
        """Check if connected to robot."""
        return self.connected
    
    # Mode and Type Management
    
    def set_jog_mode(self, mode: Union[JogMode, str]):
        """
        Set jogging mode (Cartesian or Joint).
        
        Args:
            mode: JogMode enum or string ('cartesian' or 'joint')
        """
        if isinstance(mode, str):
            mode = JogMode(mode)
        
        with self.control_lock:
            if self.jogging_active:
                self.logger.warning("Cannot change mode while jogging active")
                return
            
            self.current_mode = mode
            self.robot_status['jog_mode'] = mode.value
            
            self.logger.info(f"Jog mode set to: {mode.value}")
    
    def set_jog_type(self, jog_type: Union[JogType, str]):
        """
        Set jogging type (Step or Continuous).
        
        Args:
            jog_type: JogType enum or string ('step' or 'continuous')
        """
        if isinstance(jog_type, str):
            jog_type = JogType(jog_type)
        
        with self.control_lock:
            self.current_type = jog_type
            self.robot_status['jog_type'] = jog_type.value
            
            self.logger.info(f"Jog type set to: {jog_type.value}")
    
    def get_jog_mode(self) -> JogMode:
        """Get current jogging mode."""
        return self.current_mode
    
    def get_jog_type(self) -> JogType:
        """Get current jogging type."""
        return self.current_type
    
    # Jogging Operations (stub implementations for now)
    
    def start_jog(self, axis: int, direction: int, speed_scale: float = 1.0) -> bool:
        """
        Start jogging in specified axis and direction.
        
        Args:
            axis: Axis index (0-5 for Cartesian: X,Y,Z,Rx,Ry,Rz or Joint: J1-J6)
            direction: Direction (-1 or +1)
            speed_scale: Speed scaling factor (0.0 to 1.0)
            
        Returns:
            True if jog started successfully, False otherwise
        """
        if not self.connected:
            self.logger.error("Cannot jog: not connected")
            return False
        
        if self.emergency_stop_active:
            self.logger.error("Cannot jog: emergency stop active")
            return False
        
        if not self.safety_monitor or not self.safety_monitor.is_safe_to_jog():
            self.logger.error("Cannot jog: safety conditions not met")
            return False
        
        with self.control_lock:
            try:
                if self.current_type == JogType.CONTINUOUS:
                    # Continuous jogging
                    if self.current_mode == JogMode.CARTESIAN:
                        success = self.cartesian_jog.start_continuous(axis, direction, speed_scale)
                    else:  # JogMode.JOINT
                        success = self.joint_jog.start_continuous(axis, direction, speed_scale)
                else:
                    # Step jogging - use default step index
                    if self.current_mode == JogMode.CARTESIAN:
                        success = self.cartesian_jog.execute_step(axis, direction, 2)
                    else:  # JogMode.JOINT
                        success = self.joint_jog.execute_step(axis, direction, 2)
                
                if success:
                    if self.current_type == JogType.CONTINUOUS:
                        self.jogging_active = True
                        self.robot_status['jogging_active'] = True
                    self.logger.info(f"Started {self.current_mode.value} {self.current_type.value} jog: axis={axis}, direction={direction}")
                
                return success
                
            except Exception as e:
                self.logger.error(f"Error starting jog: {e}")
                return False
    
    def stop_jog(self) -> bool:
        """
        Stop current jogging operation.
        
        Returns:
            True if stop command sent successfully, False otherwise
        """
        with self.control_lock:
            if not self.jogging_active:
                return True  # Already stopped
            
            try:
                success = self._stop_current_jog()
                if success:
                    self.jogging_active = False
                    self.robot_status['jogging_active'] = False
                    self.logger.info("Stopped jogging")
                
                return success
                
            except Exception as e:
                self.logger.error(f"Error stopping jog: {e}")
                return False
    
    def emergency_stop(self) -> bool:
        """
        Execute emergency stop sequence.
        
        Returns:
            True if emergency stop initiated successfully, False otherwise
        """
        self.emergency_stop_active = True
        self.robot_status['emergency_stopped'] = True
        
        try:
            # Stop via primary interface
            if self.websocket_controller:
                success = self.websocket_controller.emergency_stop()
            else:
                success = False
            
            # Also try via dashboard if available
            if self.dashboard_client and self.dashboard_client.is_connected():
                self.dashboard_client.emergency_stop()
            
            # Mark jogging as stopped
            self.jogging_active = False
            self.robot_status['jogging_active'] = False
            
            self.logger.critical("EMERGENCY STOP EXECUTED")
            return success
            
        except Exception as e:
            self.logger.critical(f"EMERGENCY STOP ERROR: {e}")
            return False
    
    def _stop_current_jog(self) -> bool:
        """Stop current jog operation."""
        try:
            if self.current_mode == JogMode.CARTESIAN and self.cartesian_jog:
                return self.cartesian_jog.stop()
            elif self.current_mode == JogMode.JOINT and self.joint_jog:
                return self.joint_jog.stop()
            else:
                self.logger.warning("No active jog controller to stop")
                return True
        except Exception as e:
            self.logger.error(f"Error stopping current jog: {e}")
            return False

    def _update_status_from_dashboard_once(self):
        """Run one Dashboard poll and update robot_status. Used right after connect so the UI sees protective stop immediately."""
        if not self.dashboard_client or not self.dashboard_client.is_connected():
            return
        try:
            safety_str = self.dashboard_client.get_safety_mode()
            mode_str = self.dashboard_client.get_robot_mode()
            if safety_str is not None:
                self.robot_status['safety_mode'] = safety_str
                s = (safety_str or "").upper()
                # PROTECTIVE_STOP = 3; response may be "PROTECTIVE_STOP" or "Safetymode: 3" etc.
                self.robot_status['protective_stopped'] = (
                    "PROTECTIVE_STOP" in s or "PROTECTIVE" in s or ": 3" in s or s.strip() == "3"
                )
            if mode_str is not None:
                self.robot_status['robot_mode'] = mode_str
            self.robot_status['remote_control'] = self.dashboard_client.is_in_remote_control()
            err = self.dashboard_client.get_error()
            if err is not None:
                self.robot_status['robot_error'] = err
            warn = self.dashboard_client.get_warning()
            if warn is not None:
                self.robot_status['robot_warning'] = warn
        except Exception as e:
            self.logger.debug("Initial dashboard status: %s", e)

    def _status_loop(self):
        """Status monitoring loop running in separate thread."""
        status_counter = 0
        last_status_log = 0
        
        self.logger.info("Status loop started")
        
        while not self.should_stop.is_set() and self.connected:
            try:
                # Update position data by requesting from robot
                if self.websocket_controller and self.websocket_controller.is_connected():
                    # Simulate getting current robot position
                    # In a real implementation, we'd parse responses from get_actual_tcp_pose()
                    # For now, we'll generate demo data to show the display is working
                    import time
                    import math
                    
                    # Get real robot position data from websocket receiver
                    try:
                        # Query current TCP pose and joint angles from robot
                        if self.websocket_receiver and self.websocket_receiver.is_connected():
                            tcp_pose = self.websocket_receiver.get_tcp_pose()
                            joint_angles = self.websocket_receiver.get_joint_angles()
                            
                            # Always use real robot data (no demo fallback)
                            self.robot_status['tcp_pose'] = tcp_pose
                            self.robot_status['joint_angles'] = joint_angles
                            self.logger.debug(f"Using real robot data - TCP: {tcp_pose[:3]}")
                        else:
                            # WebSocket not connected, keep last known position
                            self.logger.debug("WebSocket disconnected, keeping last known position")
                        
                    except Exception as e:
                        # If real data fails, keep last known position
                        self.logger.warning(f"Failed to get robot position: {e}")
                        # Don't update position - keep showing last known values
                
                # Update status from dashboard if available (safety mode, robot mode, errors)
                if self.dashboard_client and self.dashboard_client.is_connected():
                    try:
                        if status_counter % 2 == 0:
                            safety_str = self.dashboard_client.get_safety_mode()
                            mode_str = self.dashboard_client.get_robot_mode()
                            if safety_str is not None:
                                self.robot_status['safety_mode'] = safety_str
                                was_protective = self.robot_status.get('protective_stopped', False)
                                s = (safety_str or "").upper()
                                self.robot_status['protective_stopped'] = (
                                    "PROTECTIVE_STOP" in s or "PROTECTIVE" in s or ": 3" in s or s.strip() == "3"
                                )
                                if self.robot_status['protective_stopped'] and not was_protective:
                                    self._on_protective_stop()
                            if mode_str is not None:
                                self.robot_status['robot_mode'] = mode_str
                            remote = self.dashboard_client.is_in_remote_control()
                            self.robot_status['remote_control'] = remote
                            err = self.dashboard_client.get_error()
                            if err is not None:
                                self.robot_status['robot_error'] = err
                            warn = self.dashboard_client.get_warning()
                            if warn is not None:
                                self.robot_status['robot_warning'] = warn
                    except Exception as e:
                        self.logger.debug("Dashboard status update: %s", e)
                
                # Notify status callbacks
                self._notify_status_callbacks()
                
                # Periodic status logging (every 5 seconds)
                status_counter += 1
                if status_counter - last_status_log >= 10:  # 10 * 0.5s = 5 seconds
                    last_status_log = status_counter
                    connection_status = "Connected" if self.connected else "Disconnected"
                    self.logger.info(f"Status: {connection_status} | Updates: {status_counter} | "
                                   f"TCP: {self.robot_status.get('tcp_pose', [0,0,0])[:3]} | "
                                   f"Mode: {self.robot_status.get('jog_mode', 'Unknown')}")
                
                # Sleep for status update interval (reduced to prevent UI flickering)
                time.sleep(0.5)  # 2 Hz status updates (reduced from 10 Hz)
                
            except Exception as e:
                self.logger.error(f"Error in status loop: {e}")
                time.sleep(1.0)
    
    def _generate_demo_position_data(self):
        """Generate demo position data for display testing when no real robot data available."""
        import time
        import math
        
        # Generate some realistic demo position data that changes over time
        t = time.time() * 0.1  # Slow oscillation
        self.logger.debug(f"Generating demo data at time t={t:.3f}")
        
        # Demo TCP pose with RPY angles (to match teach pendant format)
        demo_tcp_pose = [
            0.3 + 0.05 * math.sin(t),      # X position (meters)
            0.2 + 0.03 * math.cos(t),      # Y position (meters)
            0.4 + 0.02 * math.sin(t*0.7),  # Z position (meters)
            1.707 + 0.1 * math.sin(t*0.7), # Rx RPY rotation (radians) - realistic robot orientation
            3.654 + 0.05 * math.cos(t*0.8), # Ry RPY rotation (radians) - matches typical UR10 pose
            -0.579 + 0.1 * math.sin(t*0.6) # Rz RPY rotation (radians) - similar to teach pendant values
        ]
        
        demo_joint_angles = [
            0.1 * math.sin(t*0.5),          # J1 (radians)
            -1.57 + 0.2 * math.cos(t*0.6),  # J2 (radians)
            1.57 + 0.15 * math.sin(t*0.7),  # J3 (radians)
            0.05 * math.cos(t*0.8),         # J4 (radians)
            1.57 + 0.1 * math.sin(t*0.9),   # J5 (radians)
            0.03 * math.cos(t)              # J6 (radians)
        ]
        
        return demo_tcp_pose, demo_joint_angles
                
    def _on_position_update(self, tcp_pose: List[float], joint_angles: List[float]):
        """Handle position updates from WebSocket receiver."""
        self.robot_status['tcp_pose'] = tcp_pose
        self.robot_status['joint_angles'] = joint_angles
        
        # Debug level logging - only visible with --debug flag
        self.logger.debug(f"Position update: TCP={tcp_pose[:3]}, Joints={joint_angles[:3]}")
        
        for callback in self.position_callbacks:
            try:
                callback(tcp_pose, joint_angles)
            except Exception as e:
                self.logger.error(f"Error in position callback: {e}")
    
    def _on_safety_update(self, safety_data: Dict[str, Any]):
        """Handle safety updates from WebSocket receiver."""
        self.robot_status.update(safety_data)
        
        for callback in self.safety_callbacks:
            try:
                callback(safety_data)
            except Exception as e:
                self.logger.error(f"Error in safety callback: {e}")
    
    def _on_data_update(self, robot_data: Dict[str, Any]):
        """Handle complete data updates from WebSocket receiver."""
        # Update speeds
        self.robot_status['tcp_speed'] = robot_data.get('tcp_speed', [0.0] * 6)
        self.robot_status['joint_speeds'] = robot_data.get('joint_speeds', [0.0] * 6)
    
    def _on_emergency_stop(self):
        """Handle emergency stop from safety monitor."""
        self.emergency_stop()
    
    def _on_protective_stop(self):
        """Handle protective stop from safety monitor."""
        self.stop_jog()
        self.logger.warning("Protective stop detected - jogging stopped")
    
    def _notify_status_callbacks(self):
        """Notify all status callbacks."""
        for callback in self.status_callbacks:
            try:
                callback(self.robot_status.copy())
            except Exception as e:
                self.logger.error(f"Error in status callback: {e}")
    
    def _notify_connection_callbacks(self, connected: bool):
        """Notify connection status callbacks."""
        for callback in self.connection_callbacks:
            try:
                callback(connected)
            except Exception as e:
                self.logger.error(f"Error in connection callback: {e}")
    
    # Public Callback Management
    
    def add_position_callback(self, callback: Callable[[List[float], List[float]], None]):
        """Add position update callback."""
        self.position_callbacks.append(callback)
        self.logger.info(f"Position callback added, total callbacks: {len(self.position_callbacks)}")
    
    def add_status_callback(self, callback: Callable[[Dict], None]):
        """Add status update callback."""
        self.status_callbacks.append(callback)
    
    def add_safety_callback(self, callback: Callable[[Dict], None]):
        """Add safety update callback."""
        self.safety_callbacks.append(callback)
    
    def add_connection_callback(self, callback: Callable[[bool], None]):
        """Add connection status callback."""
        self.connection_callbacks.append(callback)
    
    def remove_callback(self, callback):
        """Remove callback from all callback lists."""
        for callback_list in [self.position_callbacks, self.status_callbacks, 
                             self.safety_callbacks, self.connection_callbacks]:
            if callback in callback_list:
                callback_list.remove(callback)
    
    # Status Access
    
    def get_robot_status(self) -> Dict[str, Any]:
        """Get complete robot status."""
        return self.robot_status.copy()
    
    def get_tcp_pose(self) -> List[float]:
        """Get current TCP pose."""
        return self.robot_status['tcp_pose'].copy()
    
    def get_joint_angles(self) -> List[float]:
        """Get current joint angles."""
        return self.robot_status['joint_angles'].copy()
    
    def is_jogging_active(self) -> bool:
        """Check if jogging is currently active."""
        return self.jogging_active
    
    def is_emergency_stopped(self) -> bool:
        """Check if emergency stop is active."""
        return self.emergency_stop_active
    
    # Context Manager
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
