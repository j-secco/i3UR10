"""
Configuration Dialog Widget
Robot connection and settings configuration for UR10

Author: jsecco (R)
"""

import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox,
    QGroupBox, QTabWidget, QWidget, QCheckBox, QMessageBox,
    QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

# Professional theme for consistency with main app
try:
    from ui.styles.professional_theme import create_professional_stylesheet, ProfessionalColors
except ImportError:
    create_professional_stylesheet = None
    ProfessionalColors = None

# Touch-friendly sizes (match main window)
TOUCH_CONTROL_HEIGHT = 56
TOUCH_CONTROL_MIN_WIDTH = 140
TOUCH_BTN_HEIGHT = 60
TOUCH_ACTION_BTN_HEIGHT = 64
TOUCH_TAB_MIN_WIDTH = 140
TOUCH_TAB_MIN_HEIGHT = 52
TOUCH_LABEL_FONT = "font-size: 18px;"


class ConfigDialog(QDialog):
    """
    Configuration dialog for robot settings and connection parameters.
    """
    
    # Signal emitted when configuration is saved
    config_saved = pyqtSignal(dict)
    
    def __init__(self, config: Dict[str, Any], parent: Optional[QWidget] = None, jog_controller: Optional[Any] = None):
        """
        Initialize the configuration dialog.

        Args:
            config: Current configuration dictionary
            parent: Parent widget (optional)
            jog_controller: Optional JogController for Error recovery tab (Dashboard commands)
        """
        super().__init__(parent)
        self.config = config.copy()
        self.jog_controller = jog_controller
        self.logger = logging.getLogger(__name__)
        self._config_file_path: Optional[Path] = None

        self._setup_ui()
        self._setup_styling()
        self._load_current_config()

    def get_config(self) -> Dict[str, Any]:
        """Return the current config (after save, contains updated values). Used by main window after Accepted."""
        return self.config

    def _setup_ui(self):
        """Set up the configuration dialog UI."""
        self.setWindowTitle("UR10 Robot Configuration")
        self.setModal(True)
        self.setMinimumSize(860, 640)

        # Config file path: resolve relative to project root so save works from any cwd
        try:
            self._config_file_path = Path(__file__).resolve().parent.parent.parent / "config" / "robot_config.yaml"
        except Exception:
            self._config_file_path = Path("config/robot_config.yaml")

        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        self._create_connection_tab(tab_widget)
        self._create_jogging_tab(tab_widget)
        self._create_safety_tab(tab_widget)
        self._create_ui_tab(tab_widget)
        self._create_recovery_tab(tab_widget)
        self._create_buttons(layout)
        
    def _create_connection_tab(self, tab_widget: QTabWidget):
        """Create the robot connection configuration tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "Robot Connection")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Robot Connection Group
        conn_group = QGroupBox("Robot Connection Settings")
        layout.addWidget(conn_group)
        
        form_layout = QFormLayout(conn_group)
        form_layout.setSpacing(15)
        
        # Robot IP Address
        self.ip_input = QLineEdit()
        self.ip_input.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.ip_input.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        self.ip_input.setFont(QFont("monospace", 14))
        self.ip_input.setPlaceholderText("192.168.10.24")
        form_layout.addRow("Robot IP Address:", self.ip_input)
        
        # Ports Group
        ports_group = QGroupBox("Communication Ports")
        layout.addWidget(ports_group)
        
        ports_layout = QFormLayout(ports_group)
        ports_layout.setSpacing(15)
        
        # Primary Port
        self.primary_port = QSpinBox()
        self.primary_port.setRange(1, 65535)
        self.primary_port.setValue(30001)
        self.primary_port.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.primary_port.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        self.primary_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("Primary WebSocket:", self.primary_port)

        # Real-time Port
        self.realtime_port = QSpinBox()
        self.realtime_port.setRange(1, 65535)
        self.realtime_port.setValue(30003)
        self.realtime_port.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.realtime_port.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        self.realtime_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("Real-time Data:", self.realtime_port)

        # Dashboard Port
        self.dashboard_port = QSpinBox()
        self.dashboard_port.setRange(1, 65535)
        self.dashboard_port.setValue(29999)
        self.dashboard_port.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.dashboard_port.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        self.dashboard_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("Dashboard:", self.dashboard_port)

        # Test Connection Button
        self.test_button = QPushButton("Test Connection")
        self.test_button.setMinimumHeight(TOUCH_BTN_HEIGHT)
        self.test_button.clicked.connect(self._test_connection)
        layout.addWidget(self.test_button)
        
        layout.addStretch()
        
    def _create_jogging_tab(self, tab_widget: QTabWidget):
        """Create the jogging settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "Jogging")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Speed Settings
        speed_group = QGroupBox("Speed Settings")
        layout.addWidget(speed_group)
        
        speed_layout = QFormLayout(speed_group)
        speed_layout.setSpacing(15)
        
        # Default Speed
        self.default_speed = QDoubleSpinBox()
        self.default_speed.setRange(0.01, 2.0)
        self.default_speed.setSingleStep(0.01)
        self.default_speed.setSuffix(" m/s")
        self.default_speed.setDecimals(2)
        self.default_speed.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.default_speed.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        speed_layout.addRow("Default Speed:", self.default_speed)

        # Max Speed
        self.max_speed = QDoubleSpinBox()
        self.max_speed.setRange(0.01, 2.0)
        self.max_speed.setSingleStep(0.01)
        self.max_speed.setSuffix(" m/s")
        self.max_speed.setDecimals(2)
        self.max_speed.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.max_speed.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        speed_layout.addRow("Maximum Speed:", self.max_speed)

        # Step Size
        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.001, 0.1)
        self.step_size.setSingleStep(0.001)
        self.step_size.setSuffix(" m")
        self.step_size.setDecimals(3)
        self.step_size.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.step_size.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        speed_layout.addRow("Step Size:", self.step_size)

        # Acceleration
        accel_group = QGroupBox("Acceleration Settings")
        layout.addWidget(accel_group)

        accel_layout = QFormLayout(accel_group)
        accel_layout.setSpacing(15)

        # Default Acceleration
        self.default_accel = QDoubleSpinBox()
        self.default_accel.setRange(0.01, 5.0)
        self.default_accel.setSingleStep(0.01)
        self.default_accel.setSuffix(" m/s²")
        self.default_accel.setDecimals(2)
        self.default_accel.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.default_accel.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        accel_layout.addRow("Default Acceleration:", self.default_accel)
        
        layout.addStretch()
        
    def _create_safety_tab(self, tab_widget: QTabWidget):
        """Create the safety settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "Safety")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Safety Monitoring
        monitor_group = QGroupBox("Safety Monitoring")
        layout.addWidget(monitor_group)
        
        monitor_layout = QFormLayout(monitor_group)
        monitor_layout.setSpacing(15)
        
        # Enable Emergency Monitoring
        self.enable_emergency = QCheckBox("Enable emergency stop monitoring")
        self.enable_emergency.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        monitor_layout.addRow("Emergency Monitoring:", self.enable_emergency)

        # Connection Timeout
        self.conn_timeout = QDoubleSpinBox()
        self.conn_timeout.setRange(1.0, 30.0)
        self.conn_timeout.setSingleStep(0.5)
        self.conn_timeout.setSuffix(" seconds")
        self.conn_timeout.setDecimals(1)
        self.conn_timeout.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.conn_timeout.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        monitor_layout.addRow("Connection Timeout:", self.conn_timeout)

        # Speed Limits
        limits_group = QGroupBox("Safety Limits")
        layout.addWidget(limits_group)

        limits_layout = QFormLayout(limits_group)
        limits_layout.setSpacing(15)

        # Max Cartesian Speed
        self.max_cart_speed = QDoubleSpinBox()
        self.max_cart_speed.setRange(0.01, 2.0)
        self.max_cart_speed.setSingleStep(0.01)
        self.max_cart_speed.setSuffix(" m/s")
        self.max_cart_speed.setDecimals(2)
        self.max_cart_speed.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.max_cart_speed.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        limits_layout.addRow("Max Cartesian Speed:", self.max_cart_speed)

        # Max Joint Speed
        self.max_joint_speed = QDoubleSpinBox()
        self.max_joint_speed.setRange(0.1, 6.0)
        self.max_joint_speed.setSingleStep(0.1)
        self.max_joint_speed.setSuffix(" rad/s")
        self.max_joint_speed.setDecimals(1)
        self.max_joint_speed.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.max_joint_speed.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        limits_layout.addRow("Max Joint Speed:", self.max_joint_speed)
        
        layout.addStretch()
        
    def _create_ui_tab(self, tab_widget: QTabWidget):
        """Create the UI settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "Interface")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Display Settings
        display_group = QGroupBox("Display Settings")
        layout.addWidget(display_group)
        
        display_layout = QFormLayout(display_group)
        display_layout.setSpacing(15)
        
        # Fullscreen Mode
        self.fullscreen_mode = QCheckBox("Start in fullscreen mode (recommended for kiosk)")
        self.fullscreen_mode.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        display_layout.addRow("Fullscreen:", self.fullscreen_mode)

        # Touch Settings
        touch_group = QGroupBox("Touch Interface Settings")
        layout.addWidget(touch_group)

        touch_layout = QFormLayout(touch_group)
        touch_layout.setSpacing(15)

        # Button Size
        self.button_size = QSpinBox()
        self.button_size.setRange(60, 200)
        self.button_size.setSingleStep(10)
        self.button_size.setSuffix(" pixels")
        self.button_size.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.button_size.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        touch_layout.addRow("Button Size:", self.button_size)

        # Touch Margin
        self.touch_margin = QSpinBox()
        self.touch_margin.setRange(5, 50)
        self.touch_margin.setSuffix(" pixels")
        self.touch_margin.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.touch_margin.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        touch_layout.addRow("Touch Margin:", self.touch_margin)

        # Update Rates
        update_group = QGroupBox("Update Rates")
        layout.addWidget(update_group)

        update_layout = QFormLayout(update_group)
        update_layout.setSpacing(15)

        # Position Update Rate
        self.pos_update_rate = QSpinBox()
        self.pos_update_rate.setRange(1, 50)
        self.pos_update_rate.setSuffix(" Hz")
        self.pos_update_rate.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.pos_update_rate.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        update_layout.addRow("Position Updates:", self.pos_update_rate)

        # Status Update Rate
        self.status_update_rate = QSpinBox()
        self.status_update_rate.setRange(1, 20)
        self.status_update_rate.setSuffix(" Hz")
        self.status_update_rate.setMinimumHeight(TOUCH_CONTROL_HEIGHT)
        self.status_update_rate.setMinimumWidth(TOUCH_CONTROL_MIN_WIDTH)
        update_layout.addRow("Status Updates:", self.status_update_rate)
        
        layout.addStretch()

    def _create_recovery_tab(self, tab_widget: QTabWidget):
        """Create the Error recovery tab (Dashboard commands to clear protective stop, popups, violations)."""
        tab = QWidget()
        tab_widget.addTab(tab, "Error recovery")

        layout = QVBoxLayout(tab)
        layout.setSpacing(20)

        desc = QLabel(
            "Use these actions to recover from protective stop, safety violations (e.g. C 1983 DCP speed limit violated), "
            "or other robot dialogs. To save a log report: close this dialog and use the main screen (System Logs > Save log snapshot)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(TOUCH_LABEL_FONT)
        layout.addWidget(desc)

        recovery_group = QGroupBox("Recovery actions")
        layout.addWidget(recovery_group)
        recovery_layout = QVBoxLayout(recovery_group)
        recovery_layout.setSpacing(12)

        self._recovery_status_label = QLabel("Connect to the robot to use recovery actions.")
        self._recovery_status_label.setWordWrap(True)
        self._recovery_status_label.setStyleSheet("font-size: 13px; color: #6C757D;")
        recovery_layout.addWidget(self._recovery_status_label)

        self.btn_unlock_protective = QPushButton("Unlock protective stop")
        self.btn_unlock_protective.setObjectName("warningButton")
        self.btn_unlock_protective.setMinimumHeight(TOUCH_BTN_HEIGHT)
        self.btn_unlock_protective.setToolTip("Send 'unlock protective stop' to the robot (Dashboard)")
        self.btn_unlock_protective.clicked.connect(lambda: self._run_recovery("unlock_protective_stop"))
        recovery_layout.addWidget(self.btn_unlock_protective)

        self.btn_close_safety_popup = QPushButton("Close safety popup")
        self.btn_close_safety_popup.setMinimumHeight(TOUCH_BTN_HEIGHT)
        self.btn_close_safety_popup.setToolTip("Dismiss safety popup on the robot (e.g. after violations)")
        self.btn_close_safety_popup.clicked.connect(lambda: self._run_recovery("close_safety_popup"))
        recovery_layout.addWidget(self.btn_close_safety_popup)

        self.btn_close_popup = QPushButton("Close popup")
        self.btn_close_popup.setMinimumHeight(TOUCH_BTN_HEIGHT)
        self.btn_close_popup.setToolTip("Dismiss any popup dialog on the robot")
        self.btn_close_popup.clicked.connect(lambda: self._run_recovery("close_popup"))
        recovery_layout.addWidget(self.btn_close_popup)

        self.btn_restart_safety = QPushButton("Restart safety")
        self.btn_restart_safety.setMinimumHeight(TOUCH_BTN_HEIGHT)
        self.btn_restart_safety.setToolTip("Restart the robot safety system (use only if advised)")
        self.btn_restart_safety.clicked.connect(lambda: self._run_recovery("restart_safety"))
        recovery_layout.addWidget(self.btn_restart_safety)

        self._update_recovery_buttons_state()
        layout.addStretch()

    def _update_recovery_buttons_state(self):
        """Enable or disable recovery buttons based on Dashboard connection."""
        connected = bool(
            self.jog_controller
            and getattr(self.jog_controller, "dashboard_client", None)
            and self.jog_controller.dashboard_client.is_connected()
        )
        for btn in (
            getattr(self, "btn_unlock_protective", None),
            getattr(self, "btn_close_safety_popup", None),
            getattr(self, "btn_close_popup", None),
            getattr(self, "btn_restart_safety", None),
        ):
            if btn:
                btn.setEnabled(connected)
        if hasattr(self, "_recovery_status_label") and self._recovery_status_label:
            self._recovery_status_label.setText(
                "Dashboard connected. Use the buttons above to send recovery commands."
                if connected
                else "Connect to the robot to use recovery actions."
            )

    def _run_recovery(self, action: str):
        """Run a Dashboard recovery command and show result."""
        if not self.jog_controller or not getattr(self.jog_controller, "dashboard_client", None):
            QMessageBox.warning(self, "Error recovery", "Robot not configured.")
            return
        dc = self.jog_controller.dashboard_client
        if not dc.is_connected():
            QMessageBox.warning(self, "Error recovery", "Dashboard not connected. Connect to the robot first.")
            return
        labels = {
            "unlock_protective_stop": ("Unlock protective stop", dc.unlock_protective_stop),
            "close_safety_popup": ("Close safety popup", dc.close_safety_popup),
            "close_popup": ("Close popup", dc.close_popup),
            "restart_safety": ("Restart safety", dc.restart_safety),
        }
        if action not in labels:
            return
        name, cmd = labels[action]
        try:
            ok = cmd()
            if ok:
                QMessageBox.information(self, "Error recovery", f"{name} command sent successfully.")
            else:
                QMessageBox.warning(
                    self,
                    "Error recovery",
                    f"{name} may have failed or the robot did not accept it. Check the teach pendant."
                )
        except Exception as e:
            self.logger.error("Recovery command %s failed: %s", action, e)
            QMessageBox.critical(self, "Error recovery", f"Command failed: {e}")
        
    def _create_buttons(self, layout: QVBoxLayout):
        """Create dialog buttons."""
        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)
        
        # Cancel Button
        cancel_button = QPushButton("Cancel")
        cancel_button.setMinimumHeight(TOUCH_ACTION_BTN_HEIGHT)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        button_layout.addStretch()

        # Save Button
        save_button = QPushButton("Save & Apply")
        save_button.setMinimumHeight(TOUCH_ACTION_BTN_HEIGHT)
        save_button.clicked.connect(self._save_config)
        save_button.setDefault(True)
        button_layout.addWidget(save_button)
        
    def _setup_styling(self):
        """Set up dialog styling using professional theme; touch-friendly tab and controls."""
        if create_professional_stylesheet and ProfessionalColors:
            base = create_professional_stylesheet()
            dialog_overrides = f"""
            QDialog {{
                background-color: {ProfessionalColors.BACKGROUND_MAIN};
            }}
            QTabBar::tab {{
                min-width: {TOUCH_TAB_MIN_WIDTH}px;
                min-height: {TOUCH_TAB_MIN_HEIGHT}px;
            }}
            QFormLayout QLabel {{
                {TOUCH_LABEL_FONT}
            }}
            """
            self.setStyleSheet(base + dialog_overrides)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #F8F9FA; }
                QTabBar::tab { min-width: 140px; min-height: 52px; padding: 12px 24px; }
                QPushButton { min-height: 56px; padding: 12px 24px; }
                QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 56px; padding: 8px; }
                QCheckBox { min-height: 56px; }
            """)

    def _load_current_config(self):
        """Load current configuration values into the form."""
        try:
            # Robot settings
            robot_config = self.config.get('robot', {})
            self.ip_input.setText(robot_config.get('ip_address', '192.168.10.24'))
            
            ports = robot_config.get('ports', {})
            self.primary_port.setValue(ports.get('primary', 30001))
            self.realtime_port.setValue(ports.get('realtime', 30003))
            self.dashboard_port.setValue(ports.get('dashboard', 29999))
            
            # Jogging settings
            jog_config = self.config.get('jogging', {})
            self.default_speed.setValue(jog_config.get('default_speed', 0.1))
            self.max_speed.setValue(jog_config.get('max_speed', 0.5))
            self.step_size.setValue(jog_config.get('step_size', 0.01))
            self.default_accel.setValue(jog_config.get('default_acceleration', 0.1))
            
            # Safety settings
            safety_config = self.config.get('safety', {})
            self.enable_emergency.setChecked(safety_config.get('enable_emergency_monitoring', True))
            self.conn_timeout.setValue(safety_config.get('connection_timeout', 5.0))
            
            safety_limits = safety_config.get('safety_limits', {})
            self.max_cart_speed.setValue(safety_limits.get('max_cartesian_speed', 1.0))
            self.max_joint_speed.setValue(safety_limits.get('max_joint_speed', 3.14))
            
            # UI settings
            ui_config = self.config.get('ui', {})
            window_config = ui_config.get('window', {})
            self.fullscreen_mode.setChecked(window_config.get('fullscreen', False))
            
            touch_config = ui_config.get('touch', {})
            self.button_size.setValue(touch_config.get('button_size', 80))
            self.touch_margin.setValue(touch_config.get('touch_margin', 10))
            
            feedback_config = ui_config.get('feedback', {})
            self.pos_update_rate.setValue(feedback_config.get('position_update_rate', 10))
            self.status_update_rate.setValue(feedback_config.get('status_update_rate', 5))
            
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            QMessageBox.warning(self, "Configuration Error", f"Error loading configuration: {e}")
            
    def _save_config(self):
        """Save configuration: merge form values into existing config so sections not in the dialog (demo, logging, robot.rtde, etc.) are preserved."""
        try:
            # Merge robot connection (preserve use_rtde_for_motion, ports.rtde)
            self.config.setdefault('robot', {})
            self.config['robot']['ip_address'] = self.ip_input.text().strip()
            self.config['robot'].setdefault('ports', {})
            self.config['robot']['ports']['primary'] = self.primary_port.value()
            self.config['robot']['ports']['realtime'] = self.realtime_port.value()
            self.config['robot']['ports']['dashboard'] = self.dashboard_port.value()
            if 'model' not in self.config['robot']:
                self.config['robot']['model'] = 'UR10'

            # Merge jogging (preserve coordinate_frames, modes, cartesian/joint subsections)
            self.config.setdefault('jogging', {})
            self.config['jogging']['default_speed'] = self.default_speed.value()
            self.config['jogging']['max_speed'] = self.max_speed.value()
            self.config['jogging']['step_size'] = self.step_size.value()
            self.config['jogging']['default_acceleration'] = self.default_accel.value()
            self.config['jogging'].setdefault('modes', ['cartesian', 'joint'])
            self.config['jogging'].setdefault('coordinate_frames', ['base', 'tool'])

            # Merge safety (preserve safety_limits.max_acceleration etc.)
            self.config.setdefault('safety', {})
            self.config['safety']['enable_emergency_monitoring'] = self.enable_emergency.isChecked()
            self.config['safety']['connection_timeout'] = self.conn_timeout.value()
            self.config['safety'].setdefault('safety_limits', {})
            self.config['safety']['safety_limits']['max_cartesian_speed'] = self.max_cart_speed.value()
            self.config['safety']['safety_limits']['max_joint_speed'] = self.max_joint_speed.value()
            if 'max_acceleration' not in self.config['safety']['safety_limits']:
                self.config['safety']['safety_limits']['max_acceleration'] = 2.0

            # Merge UI (preserve theme, refresh, buttons, colors, etc.)
            self.config.setdefault('ui', {})
            self.config['ui'].setdefault('window', {})
            self.config['ui']['window'].update({
                'title': self.config['ui']['window'].get('title', 'UR10 Jog Control Interface'),
                'width': self.config['ui']['window'].get('width', 1024),
                'height': self.config['ui']['window'].get('height', 768),
                'fullscreen': self.fullscreen_mode.isChecked()
            })
            self.config['ui'].setdefault('touch', {})
            self.config['ui']['touch']['button_size'] = self.button_size.value()
            self.config['ui']['touch']['touch_margin'] = self.touch_margin.value()
            if 'hold_time' not in self.config['ui']['touch']:
                self.config['ui']['touch']['hold_time'] = 150
            self.config['ui'].setdefault('feedback', {})
            self.config['ui']['feedback']['position_update_rate'] = self.pos_update_rate.value()
            self.config['ui']['feedback']['status_update_rate'] = self.status_update_rate.value()

            # Save full config to file (demo, logging, development, websocket, robot.use_rtde_for_motion, etc. unchanged)
            config_file = self._config_file_path or Path('config/robot_config.yaml')
            config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, indent=2)

            self.logger.info("Configuration saved successfully")

            self.config_saved.emit(self.config)

            QMessageBox.information(
                self,
                "Configuration Saved",
                "Configuration has been saved successfully.\n\nRestart the application for connection and safety changes to take effect."
            )

            self.accept()

        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            QMessageBox.critical(self, "Save Error", f"Error saving configuration: {e}")
            
    def _test_connection(self):
        """Test connection to robot."""
        try:
            import socket
            
            ip = self.ip_input.text().strip()
            if not ip:
                QMessageBox.warning(self, "Test Connection", "Please enter a robot IP address.")
                return
                
            # Test primary port
            primary_port = self.primary_port.value()
            
            self.test_button.setText("Testing...")
            self.test_button.setEnabled(False)
            
            # Simple socket connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            
            try:
                result = sock.connect_ex((ip, primary_port))
                if result == 0:
                    QMessageBox.information(
                        self,
                        "Connection Test",
                        f"Successfully connected to {ip}:{primary_port}\n\nRobot appears to be reachable."
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Connection Test",
                        f"Could not connect to {ip}:{primary_port}\n\nPlease check:\n- Robot is powered on\n- IP address is correct\n- Network connectivity"
                    )
            finally:
                sock.close()
                
        except Exception as e:
            QMessageBox.critical(self, "Connection Test", f"Connection test failed: {e}")
            
        finally:
            self.test_button.setText("Test Connection")
            self.test_button.setEnabled(True)
