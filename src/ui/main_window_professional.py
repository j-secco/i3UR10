"""
Professional Main Window for UR10 WebSocket Jog Control Interface
Clean, modern, professional UI design for industrial robot control

Author: jsecco ®
"""

import sys
import logging
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSlider, QFrame, QGroupBox, QTextEdit,
    QButtonGroup, QScrollArea, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
from datetime import datetime

# Import jog controller
from control.jog_controller import JogController
from ui.widgets.config_dialog import ConfigDialog

# Import new professional styling
from ui.styles.professional_theme import (
    create_professional_stylesheet,
    create_jog_mode_buttons_style,
    create_connection_status_style
)


class ProfessionalMainWindow(QMainWindow):
    """
    Professional main window for UR10 jog control interface.
    Clean, modern design optimized for industrial touchscreen use.
    """

    # Signals for UI updates
    position_updated = pyqtSignal(dict)
    safety_status_changed = pyqtSignal(dict)
    connection_status_changed = pyqtSignal(bool, str)

    def __init__(self, config: Dict[str, Any], parent: Optional[QWidget] = None):
        """Initialize the professional main window."""
        super().__init__(parent)
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize jog controller
        self.jog_controller: Optional[JogController] = None

        # Current jog mode
        self.current_jog_mode = "cartesian"

        # UI update timers
        self.position_timer = QTimer()
        self.status_timer = QTimer()

        # Position data storage
        self.current_position = {
            'cartesian': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'rx': 0.0, 'ry': 0.0, 'rz': 0.0},
            'joint': {'j1': 0.0, 'j2': 0.0, 'j3': 0.0, 'j4': 0.0, 'j5': 0.0, 'j6': 0.0}
        }

        # Setup UI
        self._setup_ui()
        self._apply_styling()
        self._setup_timers()
        self._connect_signals()

        self.logger.info("Professional main window initialized")

    def _setup_ui(self):
        """Set up the main user interface layout."""
        # Window configuration
        window_config = self.config.get('ui', {}).get('window', {})
        self.setWindowTitle(window_config.get('title', 'UR10 Jog Control Interface'))

        width = window_config.get('width', 1400)  # Wider for better layout
        height = window_config.get('height', 900)
        fullscreen = window_config.get('fullscreen', False)

        if fullscreen:
            self.showFullScreen()
        else:
            self.resize(width, height)

        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Main layout with proper spacing
        main_layout = QHBoxLayout(main_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Left Panel - Jog Controls
        self._create_jog_controls_panel(main_layout)

        # Center Panel - Position Display
        self._create_position_panel(main_layout)

        # Right Panel - Emergency and Safety
        self._create_safety_panel(main_layout)

    def _create_jog_controls_panel(self, layout: QHBoxLayout):
        """Create the left panel with jog controls."""
        # Jog controls group
        jog_group = QGroupBox("Jog Controls")
        jog_group.setMinimumWidth(350)
        jog_group.setMaximumWidth(350)
        layout.addWidget(jog_group)

        jog_layout = QVBoxLayout(jog_group)
        jog_layout.setSpacing(16)

        # Jog Mode Selection
        self._create_jog_mode_section(jog_layout)

        # Jog Speed Control
        self._create_speed_control_section(jog_layout)

        # Jog Direction Controls
        self._create_jog_buttons_section(jog_layout)

    def _create_jog_mode_section(self, layout: QVBoxLayout):
        """Create jog mode selection section."""
        mode_frame = QFrame()
        layout.addWidget(mode_frame)

        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setSpacing(8)

        # Title
        mode_title = QLabel("Jog Mode")
        mode_title.setObjectName("titleLabel")
        mode_layout.addWidget(mode_title)

        # Mode buttons
        button_layout = QHBoxLayout()
        mode_layout.addLayout(button_layout)

        self.cartesian_button = QPushButton("Cartesian")
        self.cartesian_button.setObjectName("jogModeButton")
        self.cartesian_button.setCheckable(True)
        self.cartesian_button.setChecked(True)
        self.cartesian_button.clicked.connect(lambda: self._set_jog_mode("cartesian"))

        self.joint_button = QPushButton("Joint")
        self.joint_button.setObjectName("jogModeButton")
        self.joint_button.setCheckable(True)
        self.joint_button.clicked.connect(lambda: self._set_jog_mode("joint"))

        # Create button group for exclusive selection
        self.mode_button_group = QButtonGroup()
        self.mode_button_group.addButton(self.cartesian_button)
        self.mode_button_group.addButton(self.joint_button)

        button_layout.addWidget(self.cartesian_button)
        button_layout.addWidget(self.joint_button)

    def _create_speed_control_section(self, layout: QVBoxLayout):
        """Create speed control section."""
        speed_frame = QFrame()
        layout.addWidget(speed_frame)

        speed_layout = QVBoxLayout(speed_frame)
        speed_layout.setSpacing(8)

        # Title
        speed_title = QLabel("Jog Speed")
        speed_title.setObjectName("titleLabel")
        speed_layout.addWidget(speed_title)

        # Speed slider
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(100)
        self.speed_slider.setValue(45)  # Default to 45%
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self.speed_slider)

        # Speed display
        self.speed_label = QLabel("Current Speed: 0.45 m/s")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_layout.addWidget(self.speed_label)

    def _create_jog_buttons_section(self, layout: QVBoxLayout):
        """Create jog direction buttons."""
        buttons_frame = QFrame()
        layout.addWidget(buttons_frame)

        buttons_layout = QVBoxLayout(buttons_frame)
        buttons_layout.setSpacing(8)

        # Title
        buttons_title = QLabel("Jog Direction")
        buttons_title.setObjectName("titleLabel")
        buttons_layout.addWidget(buttons_title)

        # Create 6x2 grid for jog buttons
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        buttons_layout.addLayout(grid_layout)

        # Define jog buttons (axis, negative, positive)
        jog_axes = [
            ("X", "X-", "X+"),
            ("Y", "Y-", "Y+"),
            ("Z", "Z-", "Z+"),
            ("Rx", "Rx-", "Rx+"),
            ("Ry", "Ry-", "Ry+"),
            ("Rz", "Rz-", "Rz+")
        ]

        for i, (axis, neg_label, pos_label) in enumerate(jog_axes):
            # Negative button
            neg_btn = QPushButton(neg_label)
            neg_btn.setObjectName("jogButton")
            neg_btn.pressed.connect(lambda a=axis, d=-1: self._start_jog(a.lower(), d))
            neg_btn.released.connect(self._stop_jog)
            grid_layout.addWidget(neg_btn, i, 0)

            # Positive button
            pos_btn = QPushButton(pos_label)
            pos_btn.setObjectName("jogButton")
            pos_btn.pressed.connect(lambda a=axis, d=1: self._start_jog(a.lower(), d))
            pos_btn.released.connect(self._stop_jog)
            grid_layout.addWidget(pos_btn, i, 1)

    def _create_position_panel(self, layout: QHBoxLayout):
        """Create the center panel with position displays."""
        center_widget = QWidget()
        center_widget.setMinimumWidth(400)
        layout.addWidget(center_widget, 1)  # Expandable

        center_layout = QVBoxLayout(center_widget)
        center_layout.setSpacing(16)

        # TCP Position
        self._create_tcp_position_section(center_layout)

        # Joint Angles
        self._create_joint_angles_section(center_layout)

        # Connection Status
        self._create_connection_status_section(center_layout)

    def _create_tcp_position_section(self, layout: QVBoxLayout):
        """Create TCP position display section."""
        tcp_group = QGroupBox("TCP Position")
        layout.addWidget(tcp_group)

        tcp_layout = QGridLayout(tcp_group)
        tcp_layout.setSpacing(12)

        # Position labels and values
        positions = [
            ("X:", "x", "mm"), ("Y:", "y", "mm"),
            ("Z:", "z", "mm"), ("Rx:", "rx", "°"),
            ("Ry:", "ry", "°"), ("Rz:", "rz", "°")
        ]

        self.tcp_labels = {}
        for i, (label_text, key, unit) in enumerate(positions):
            row = i // 2
            col = (i % 2) * 3

            # Label
            label = QLabel(label_text)
            tcp_layout.addWidget(label, row, col)

            # Value
            value_label = QLabel("+0.0")
            value_label.setObjectName("valueLabel")
            value_label.setMinimumWidth(100)
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tcp_layout.addWidget(value_label, row, col + 1)
            self.tcp_labels[key] = value_label

            # Unit
            unit_label = QLabel(unit)
            tcp_layout.addWidget(unit_label, row, col + 2)

    def _create_joint_angles_section(self, layout: QVBoxLayout):
        """Create joint angles display section."""
        joint_group = QGroupBox("Joint Angles")
        layout.addWidget(joint_group)

        joint_layout = QGridLayout(joint_group)
        joint_layout.setSpacing(12)

        # Joint labels and values
        joints = [
            ("J1:", "j1"), ("J2:", "j2"), ("J3:", "j3"),
            ("J4:", "j4"), ("J5:", "j5"), ("J6:", "j6")
        ]

        self.joint_labels = {}
        for i, (label_text, key) in enumerate(joints):
            row = i // 2
            col = (i % 2) * 3

            # Label
            label = QLabel(label_text)
            joint_layout.addWidget(label, row, col)

            # Value
            value_label = QLabel("+0.0°")
            value_label.setObjectName("valueLabel")
            value_label.setMinimumWidth(100)
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            joint_layout.addWidget(value_label, row, col + 1)
            self.joint_labels[key] = value_label

    def _create_connection_status_section(self, layout: QVBoxLayout):
        """Create connection status section."""
        conn_group = QGroupBox("Connection Status")
        layout.addWidget(conn_group)

        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setSpacing(12)

        # Robot IP
        ip_layout = QHBoxLayout()
        ip_label = QLabel("Robot IP:")
        self.ip_value_label = QLabel("192.168.10.24")
        self.ip_value_label.setObjectName("connectionIP")
        ip_layout.addWidget(ip_label)
        ip_layout.addWidget(self.ip_value_label)
        ip_layout.addStretch()
        conn_layout.addLayout(ip_layout)

        # Status
        status_layout = QHBoxLayout()
        status_label = QLabel("Status:")
        self.status_value_label = QLabel("Disconnected")
        self.status_value_label.setObjectName("connectionStatus")
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_value_label)
        status_layout.addStretch()
        conn_layout.addLayout(status_layout)

        # Connection buttons layout
        button_layout = QHBoxLayout()

        # Connect/Disconnect button
        self.connection_button = QPushButton("Connect")
        self.connection_button.setObjectName("connectButton")  # Green styling for initial state
        self.connection_button.clicked.connect(self._toggle_connection)
        button_layout.addWidget(self.connection_button)

        # Settings button
        self.settings_button = QPushButton("⚙️ Settings")
        self.settings_button.setObjectName("secondaryButton")
        self.settings_button.clicked.connect(self._show_settings)
        button_layout.addWidget(self.settings_button)

        conn_layout.addLayout(button_layout)

    def _create_safety_panel(self, layout: QHBoxLayout):
        """Create the right panel with safety controls."""
        safety_widget = QWidget()
        safety_widget.setMinimumWidth(350)
        safety_widget.setMaximumWidth(350)
        layout.addWidget(safety_widget)

        safety_layout = QVBoxLayout(safety_widget)
        safety_layout.setSpacing(16)

        # Emergency Control
        self._create_emergency_section(safety_layout)

        # Safety Status
        self._create_safety_status_section(safety_layout)

        # Robot Control
        self._create_robot_control_section(safety_layout)

        # System Logs
        self._create_logs_section(safety_layout)

    def _create_emergency_section(self, layout: QVBoxLayout):
        """Create emergency control section."""
        emergency_group = QGroupBox("Emergency Control")
        layout.addWidget(emergency_group)

        emergency_layout = QVBoxLayout(emergency_group)
        emergency_layout.setSpacing(16)

        # Emergency stop button
        self.emergency_button = QPushButton("EMERGENCY\\nSTOP")
        self.emergency_button.setObjectName("emergencyButton")
        self.emergency_button.clicked.connect(self._emergency_stop)
        emergency_layout.addWidget(self.emergency_button)

    def _create_safety_status_section(self, layout: QVBoxLayout):
        """Create safety status section."""
        safety_group = QGroupBox("Safety Status")
        layout.addWidget(safety_group)

        safety_layout = QGridLayout(safety_group)
        safety_layout.setSpacing(8)

        # Safety status items
        safety_items = [
            ("Robot Mode:", "robot_mode"),
            ("Safety Mode:", "safety_mode"),
            ("Protective Stop:", "protective_stop"),
            ("Remote Control:", "remote_control")
        ]

        self.safety_labels = {}
        for i, (label_text, key) in enumerate(safety_items):
            label = QLabel(label_text)
            safety_layout.addWidget(label, i, 0)

            value_label = QLabel("0")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            safety_layout.addWidget(value_label, i, 1)
            self.safety_labels[key] = value_label

    def _create_robot_control_section(self, layout: QVBoxLayout):
        """Create robot control section."""
        control_group = QGroupBox("Robot Control")
        layout.addWidget(control_group)

        control_layout = QVBoxLayout(control_group)
        control_layout.setSpacing(8)

        # Control buttons
        self.reset_safety_button = QPushButton("Reset Safety")
        self.reset_safety_button.setObjectName("secondaryButton")
        self.reset_safety_button.clicked.connect(self._reset_safety)

        self.power_on_button = QPushButton("Power On")
        self.power_on_button.setObjectName("secondaryButton")
        self.power_on_button.clicked.connect(self._power_on_robot)

        self.power_off_button = QPushButton("Power Off")
        self.power_off_button.setObjectName("secondaryButton")
        self.power_off_button.clicked.connect(self._power_off_robot)

        control_layout.addWidget(self.reset_safety_button)
        control_layout.addWidget(self.power_on_button)
        control_layout.addWidget(self.power_off_button)

    def _create_logs_section(self, layout: QVBoxLayout):
        """Create system logs section."""
        logs_group = QGroupBox("System Logs")
        layout.addWidget(logs_group, 1)  # Expandable

        logs_layout = QVBoxLayout(logs_group)

        # Log display
        self.log_display = QTextEdit()
        self.log_display.setMaximumHeight(200)
        self.log_display.setReadOnly(True)
        logs_layout.addWidget(self.log_display)

    def _apply_styling(self):
        """Apply the professional styling to the window."""
        # Combine all stylesheets
        main_style = create_professional_stylesheet()
        mode_style = create_jog_mode_buttons_style()
        connection_style = create_connection_status_style()

        complete_style = main_style + mode_style + connection_style
        self.setStyleSheet(complete_style)

    def _setup_timers(self):
        """Set up update timers."""
        # Position update timer
        self.position_timer.timeout.connect(self._update_position_display)
        self.position_timer.start(100)  # 10 Hz

        # Status update timer
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(200)  # 5 Hz

    def _connect_signals(self):
        """Connect internal signals."""
        pass

    # Event Handlers
    def _set_jog_mode(self, mode: str):
        """Set the jog mode (cartesian or joint)."""
        self.current_jog_mode = mode
        if self.jog_controller:
            self.jog_controller.set_jog_mode(mode)
        self.logger.info(f"Jog mode set to: {mode}")

    def _on_speed_changed(self, value: int):
        """Handle speed slider changes."""
        speed = value / 100.0  # Convert to 0.0-1.0 range
        self.speed_label.setText(f"Current Speed: {speed:.2f} m/s")
        # Note: JogController doesn't have set_jog_speed method
        # Speed is handled by the speed_scale parameter in start_jog()

    def _start_jog(self, axis: str, direction: int):
        """Start jogging in specified direction."""
        if self.jog_controller:
            # Map axis names to indices
            axis_map = {'x': 0, 'y': 1, 'z': 2, 'rx': 3, 'ry': 4, 'rz': 5,
                       'j1': 0, 'j2': 1, 'j3': 2, 'j4': 3, 'j5': 4, 'j6': 5}
            axis_index = axis_map.get(axis, 0)
            self.jog_controller.start_jog(axis_index, direction)
        self.logger.debug(f"Started jogging {axis} in direction {direction}")

    def _stop_jog(self):
        """Stop all jogging motion."""
        if self.jog_controller:
            self.jog_controller.stop_jog()
        self.logger.debug("Stopped jogging")

    def _emergency_stop(self):
        """Execute emergency stop."""
        if self.jog_controller:
            self.jog_controller.emergency_stop()
        self.logger.warning("Emergency stop activated")

    def _toggle_connection(self):
        """Toggle robot connection."""
        if self.jog_controller:
            if hasattr(self.jog_controller, 'connected') and self.jog_controller.connected:
                # Disconnect
                self.jog_controller.disconnect()
                self.connection_button.setText("Connect")
                self.status_value_label.setText("Disconnected")
                self.logger.info("Disconnected from robot")
            else:
                # Connect
                try:
                    success = self.jog_controller.connect()
                    if success:
                        self.connection_button.setText("Disconnect")
                        self.status_value_label.setText("Connected")
                        self.logger.info("Connected to robot")
                    else:
                        self.logger.error("Failed to connect to robot")
                        self.add_log_message("Connection failed", "ERROR")
                except Exception as e:
                    self.logger.error(f"Connection error: {e}")
                    self.add_log_message(f"Connection error: {str(e)}", "ERROR")

    def _show_settings(self):
        """Show configuration settings dialog."""
        try:
            from ui.widgets.config_dialog import ConfigDialog
            dialog = ConfigDialog(self.config, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                # Update configuration
                new_config = dialog.get_config()
                if new_config:
                    self.config.update(new_config)
                    # Update displayed IP address
                    robot_ip = self.config.get('robot', {}).get('ip_address', 'Unknown')
                    self.ip_value_label.setText(robot_ip)
                    self.logger.info("Configuration updated")
                    self.add_log_message("Configuration updated", "INFO")
        except ImportError:
            self.logger.warning("Config dialog not available")
            self.add_log_message("Settings dialog not available", "WARNING")

    def _reset_safety(self):
        """Reset safety system."""
        if self.jog_controller:
            # JogController doesn't have reset_safety method
            # Safety is managed internally by the robot
            self.add_log_message("Safety reset not available in controller", "WARNING")
        self.logger.info("Safety system reset requested")

    def _power_on_robot(self):
        """Power on the robot."""
        if self.jog_controller:
            # JogController doesn't have power_on method
            # Power control would be through dashboard client
            self.add_log_message("Power control not available in controller", "WARNING")
        self.logger.info("Robot power on requested")

    def _power_off_robot(self):
        """Power off the robot."""
        if self.jog_controller:
            # JogController doesn't have power_off method
            # Power control would be through dashboard client
            self.add_log_message("Power control not available in controller", "WARNING")
        self.logger.info("Robot power off requested")

    # Update Methods
    def _update_position_display(self):
        """Update position displays from stored position data."""
        try:
            # Update TCP position
            cartesian = self.current_position.get('cartesian', {})
            for key, label in self.tcp_labels.items():
                value = cartesian.get(key, 0.0)
                if key.startswith('r'):  # Rotation values
                    label.setText(f"{value:+.1f}")
                else:  # Position values
                    label.setText(f"{value:+.1f}")

            # Update joint angles
            joint = self.current_position.get('joint', {})
            for key, label in self.joint_labels.items():
                value = joint.get(key, 0.0)
                label.setText(f"{value:+.1f}°")

        except Exception as e:
            self.logger.error(f"Error updating position display: {e}")

    def _update_status_display(self):
        """Update status displays."""
        if not self.jog_controller:
            return

        try:
            # For now, show basic connection status
            if hasattr(self.jog_controller, 'connected') and self.jog_controller.connected:
                self._on_connection_status_changed(True)
            else:
                self._on_connection_status_changed(False)

            # Update safety status with defaults for now
            safety_defaults = {
                "robot_mode": "0",
                "safety_mode": "0",
                "protective_stop": "No",
                "remote_control": "No"
            }

            for key, label in self.safety_labels.items():
                value = safety_defaults.get(key, "0")
                label.setText(str(value))

        except Exception as e:
            self.logger.error(f"Error updating status display: {e}")

    def add_log_message(self, message: str, level: str = "INFO"):
        """Add a message to the log display."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}"
        self.log_display.append(formatted_message)

        # Limit log display to prevent memory issues
        if self.log_display.document().blockCount() > 1000:
            cursor = self.log_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()

    def set_jog_controller(self, controller: JogController):
        """Set the jog controller instance."""
        self.jog_controller = controller
        if controller:
            # Update initial status
            robot_ip = controller.config.get('robot', {}).get('ip_address', 'Unknown')
            self.ip_value_label.setText(robot_ip)

            # Add position callback
            controller.add_position_callback(self._on_position_updated)

    def _on_position_updated(self, tcp_pose, joint_angles):
        """Handle position updates from controller."""
        # Convert callback data to our expected format
        if tcp_pose and len(tcp_pose) >= 6:
            self.current_position['cartesian'] = {
                'x': tcp_pose[0] * 1000,  # Convert to mm
                'y': tcp_pose[1] * 1000,  # Convert to mm
                'z': tcp_pose[2] * 1000,  # Convert to mm
                'rx': tcp_pose[3] * 57.2958,  # Convert to degrees
                'ry': tcp_pose[4] * 57.2958,  # Convert to degrees
                'rz': tcp_pose[5] * 57.2958   # Convert to degrees
            }
            self.logger.debug(f"TCP position updated: {self.current_position['cartesian']}")

        if joint_angles and len(joint_angles) >= 6:
            self.current_position['joint'] = {
                'j1': joint_angles[0] * 57.2958,  # Convert to degrees
                'j2': joint_angles[1] * 57.2958,  # Convert to degrees
                'j3': joint_angles[2] * 57.2958,  # Convert to degrees
                'j4': joint_angles[3] * 57.2958,  # Convert to degrees
                'j5': joint_angles[4] * 57.2958,  # Convert to degrees
                'j6': joint_angles[5] * 57.2958   # Convert to degrees
            }
            self.logger.debug(f"Joint angles updated: {self.current_position['joint']}")

        # Immediately trigger display update
        self._update_position_display()

    def _on_status_updated(self, status_data):
        """Handle status updates from controller."""
        pass  # Handled in _update_status_display

    def _on_connection_status_changed(self, connected: bool, message: str = ""):
        """Handle connection status changes."""
        if connected:
            self.status_value_label.setText("Connected")
            self.status_value_label.setObjectName("connectionStatus")

            # Update connection button to show "Disconnect" in red
            self.connection_button.setText("Disconnect")
            self.connection_button.setObjectName("disconnectButton")
        else:
            self.status_value_label.setText("Disconnected")
            self.status_value_label.setObjectName("connectionStatus")

            # Update connection button to show "Connect" in green
            self.connection_button.setText("Connect")
            self.connection_button.setObjectName("connectButton")

        # Re-apply style to update colors
        self.status_value_label.style().unpolish(self.status_value_label)
        self.status_value_label.style().polish(self.status_value_label)

        self.connection_button.style().unpolish(self.connection_button)
        self.connection_button.style().polish(self.connection_button)

    def closeEvent(self, event):
        """Handle window close event."""
        self.logger.info("Main window closing")
        if self.jog_controller:
            self.jog_controller.disconnect()
        event.accept()