"""
Configuration Dialog Widget
Robot connection and settings configuration for UR10

Author: jsecco ®
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


class ConfigDialog(QDialog):
    """
    Configuration dialog for robot settings and connection parameters.
    """
    
    # Signal emitted when configuration is saved
    config_saved = pyqtSignal(dict)
    
    def __init__(self, config: Dict[str, Any], parent: Optional[QWidget] = None):
        """
        Initialize the configuration dialog.
        
        Args:
            config: Current configuration dictionary
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self.config = config.copy()
        self.logger = logging.getLogger(__name__)
        
        self._setup_ui()
        self._setup_styling()
        self._load_current_config()
        
    def _setup_ui(self):
        """Set up the configuration dialog UI."""
        self.setWindowTitle("UR10 Robot Configuration")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Create tabs
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Robot Connection Tab
        self._create_connection_tab(tab_widget)
        
        # Jogging Settings Tab
        self._create_jogging_tab(tab_widget)
        
        # Safety Settings Tab
        self._create_safety_tab(tab_widget)
        
        # UI Settings Tab
        self._create_ui_tab(tab_widget)
        
        # Buttons
        self._create_buttons(layout)
        
    def _create_connection_tab(self, tab_widget: QTabWidget):
        """Create the robot connection configuration tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "🤖 Robot Connection")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Robot Connection Group
        conn_group = QGroupBox("Robot Connection Settings")
        layout.addWidget(conn_group)
        
        form_layout = QFormLayout(conn_group)
        form_layout.setSpacing(15)
        
        # Robot IP Address
        self.ip_input = QLineEdit()
        self.ip_input.setMinimumHeight(50)
        self.ip_input.setFont(QFont("monospace", 14))
        self.ip_input.setPlaceholderText("192.168.10.24")
        form_layout.addRow("🌐 Robot IP Address:", self.ip_input)
        
        # Ports Group
        ports_group = QGroupBox("Communication Ports")
        layout.addWidget(ports_group)
        
        ports_layout = QFormLayout(ports_group)
        ports_layout.setSpacing(15)
        
        # Primary Port
        self.primary_port = QSpinBox()
        self.primary_port.setRange(1, 65535)
        self.primary_port.setValue(30001)
        self.primary_port.setMinimumHeight(50)
        self.primary_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("🔌 Primary WebSocket:", self.primary_port)
        
        # Real-time Port
        self.realtime_port = QSpinBox()
        self.realtime_port.setRange(1, 65535)
        self.realtime_port.setValue(30003)
        self.realtime_port.setMinimumHeight(50)
        self.realtime_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("⚡ Real-time Data:", self.realtime_port)
        
        # Dashboard Port
        self.dashboard_port = QSpinBox()
        self.dashboard_port.setRange(1, 65535)
        self.dashboard_port.setValue(29999)
        self.dashboard_port.setMinimumHeight(50)
        self.dashboard_port.setFont(QFont("monospace", 12))
        ports_layout.addRow("🎛️  Dashboard:", self.dashboard_port)
        
        # Test Connection Button
        self.test_button = QPushButton("🔍 Test Connection")
        self.test_button.setMinimumHeight(60)
        self.test_button.clicked.connect(self._test_connection)
        layout.addWidget(self.test_button)
        
        layout.addStretch()
        
    def _create_jogging_tab(self, tab_widget: QTabWidget):
        """Create the jogging settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "🎮 Jogging")
        
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
        self.default_speed.setMinimumHeight(50)
        speed_layout.addRow("⚡ Default Speed:", self.default_speed)
        
        # Max Speed
        self.max_speed = QDoubleSpinBox()
        self.max_speed.setRange(0.01, 2.0)
        self.max_speed.setSingleStep(0.01)
        self.max_speed.setSuffix(" m/s")
        self.max_speed.setDecimals(2)
        self.max_speed.setMinimumHeight(50)
        speed_layout.addRow("🚀 Maximum Speed:", self.max_speed)
        
        # Step Size
        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.001, 0.1)
        self.step_size.setSingleStep(0.001)
        self.step_size.setSuffix(" m")
        self.step_size.setDecimals(3)
        self.step_size.setMinimumHeight(50)
        speed_layout.addRow("📏 Step Size:", self.step_size)
        
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
        self.default_accel.setMinimumHeight(50)
        accel_layout.addRow("🏃 Default Acceleration:", self.default_accel)
        
        layout.addStretch()
        
    def _create_safety_tab(self, tab_widget: QTabWidget):
        """Create the safety settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "🔒 Safety")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Safety Monitoring
        monitor_group = QGroupBox("Safety Monitoring")
        layout.addWidget(monitor_group)
        
        monitor_layout = QFormLayout(monitor_group)
        monitor_layout.setSpacing(15)
        
        # Enable Emergency Monitoring
        self.enable_emergency = QCheckBox("Enable emergency stop monitoring")
        self.enable_emergency.setMinimumHeight(50)
        monitor_layout.addRow("🚨 Emergency Monitoring:", self.enable_emergency)
        
        # Connection Timeout
        self.conn_timeout = QDoubleSpinBox()
        self.conn_timeout.setRange(1.0, 30.0)
        self.conn_timeout.setSingleStep(0.5)
        self.conn_timeout.setSuffix(" seconds")
        self.conn_timeout.setDecimals(1)
        self.conn_timeout.setMinimumHeight(50)
        monitor_layout.addRow("⏱️  Connection Timeout:", self.conn_timeout)
        
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
        self.max_cart_speed.setMinimumHeight(50)
        limits_layout.addRow("🛡️  Max Cartesian Speed:", self.max_cart_speed)
        
        # Max Joint Speed
        self.max_joint_speed = QDoubleSpinBox()
        self.max_joint_speed.setRange(0.1, 6.0)
        self.max_joint_speed.setSingleStep(0.1)
        self.max_joint_speed.setSuffix(" rad/s")
        self.max_joint_speed.setDecimals(1)
        self.max_joint_speed.setMinimumHeight(50)
        limits_layout.addRow("🛡️  Max Joint Speed:", self.max_joint_speed)
        
        layout.addStretch()
        
    def _create_ui_tab(self, tab_widget: QTabWidget):
        """Create the UI settings tab."""
        tab = QWidget()
        tab_widget.addTab(tab, "🖥️ Interface")
        
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Display Settings
        display_group = QGroupBox("Display Settings")
        layout.addWidget(display_group)
        
        display_layout = QFormLayout(display_group)
        display_layout.setSpacing(15)
        
        # Fullscreen Mode
        self.fullscreen_mode = QCheckBox("Start in fullscreen mode (recommended for kiosk)")
        self.fullscreen_mode.setMinimumHeight(50)
        display_layout.addRow("📺 Fullscreen:", self.fullscreen_mode)
        
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
        self.button_size.setMinimumHeight(50)
        touch_layout.addRow("🔘 Button Size:", self.button_size)
        
        # Touch Margin
        self.touch_margin = QSpinBox()
        self.touch_margin.setRange(5, 50)
        self.touch_margin.setSuffix(" pixels")
        self.touch_margin.setMinimumHeight(50)
        touch_layout.addRow("📏 Touch Margin:", self.touch_margin)
        
        # Update Rates
        update_group = QGroupBox("Update Rates")
        layout.addWidget(update_group)
        
        update_layout = QFormLayout(update_group)
        update_layout.setSpacing(15)
        
        # Position Update Rate
        self.pos_update_rate = QSpinBox()
        self.pos_update_rate.setRange(1, 50)
        self.pos_update_rate.setSuffix(" Hz")
        self.pos_update_rate.setMinimumHeight(50)
        update_layout.addRow("📍 Position Updates:", self.pos_update_rate)
        
        # Status Update Rate
        self.status_update_rate = QSpinBox()
        self.status_update_rate.setRange(1, 20)
        self.status_update_rate.setSuffix(" Hz")
        self.status_update_rate.setMinimumHeight(50)
        update_layout.addRow("📊 Status Updates:", self.status_update_rate)
        
        layout.addStretch()
        
    def _create_buttons(self, layout: QVBoxLayout):
        """Create dialog buttons."""
        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)
        
        # Cancel Button
        cancel_button = QPushButton("❌ Cancel")
        cancel_button.setMinimumHeight(60)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        button_layout.addStretch()
        
        # Save Button
        save_button = QPushButton("💾 Save & Apply")
        save_button.setMinimumHeight(60)
        save_button.clicked.connect(self._save_config)
        save_button.setDefault(True)
        button_layout.addWidget(save_button)
        
    def _setup_styling(self):
        """Set up dialog styling for touch interface."""
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5F5;
            }
            
            QTabWidget::pane {
                border: 2px solid #BDBDBD;
                border-radius: 8px;
                margin-top: 5px;
            }
            
            QTabWidget::tab-bar {
                alignment: center;
            }
            
            QTabBar::tab {
                background-color: #E0E0E0;
                border: 2px solid #BDBDBD;
                border-bottom-color: #BDBDBD;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 120px;
                min-height: 50px;
                padding: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
                border-bottom-color: #2196F3;
            }
            
            QTabBar::tab:hover {
                background-color: #BBDEFB;
            }
            
            QGroupBox {
                font-weight: bold;
                border: 2px solid #BDBDBD;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                font-size: 14px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                background-color: #F5F5F5;
                color: #2196F3;
            }
            
            QLineEdit, QSpinBox, QDoubleSpinBox {
                border: 2px solid #BDBDBD;
                border-radius: 6px;
                padding: 8px;
                font-size: 14px;
                background-color: white;
            }
            
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #2196F3;
            }
            
            QPushButton {
                background-color: #2196F3;
                border: none;
                color: white;
                padding: 12px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: #1976D2;
            }
            
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            
            QCheckBox {
                font-size: 14px;
                spacing: 8px;
            }
            
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border-color: #1976D2;
            }
            
            QLabel {
                font-size: 14px;
                color: #424242;
            }
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
        """Save configuration and emit signal."""
        try:
            # Update configuration with form values
            self.config['robot'] = {
                'ip_address': self.ip_input.text().strip(),
                'ports': {
                    'primary': self.primary_port.value(),
                    'realtime': self.realtime_port.value(),
                    'dashboard': self.dashboard_port.value()
                },
                'model': 'UR10'
            }
            
            self.config['jogging'] = {
                'default_speed': self.default_speed.value(),
                'max_speed': self.max_speed.value(),
                'step_size': self.step_size.value(),
                'default_acceleration': self.default_accel.value(),
                'modes': ['cartesian', 'joint'],
                'coordinate_frames': ['base', 'tool']
            }
            
            self.config['safety'] = {
                'enable_emergency_monitoring': self.enable_emergency.isChecked(),
                'connection_timeout': self.conn_timeout.value(),
                'safety_limits': {
                    'max_cartesian_speed': self.max_cart_speed.value(),
                    'max_joint_speed': self.max_joint_speed.value(),
                    'max_acceleration': 2.0
                }
            }
            
            # Update UI config
            if 'ui' not in self.config:
                self.config['ui'] = {}
                
            self.config['ui'].update({
                'window': {
                    'title': 'UR10 Jog Control Interface',
                    'width': 1024,
                    'height': 768,
                    'fullscreen': self.fullscreen_mode.isChecked()
                },
                'touch': {
                    'button_size': self.button_size.value(),
                    'touch_margin': self.touch_margin.value(),
                    'hold_time': 150
                },
                'feedback': {
                    'position_update_rate': self.pos_update_rate.value(),
                    'status_update_rate': self.status_update_rate.value()
                },
                'colors': {
                    'primary': '#2196F3',
                    'secondary': '#FFC107',
                    'success': '#4CAF50',
                    'warning': '#FF9800',
                    'danger': '#F44336',
                    'background': '#FAFAFA'
                }
            })
            
            # Save to file
            config_file = Path('config/robot_config.yaml')
            config_file.parent.mkdir(exist_ok=True)
            
            with open(config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, indent=2)
                
            self.logger.info("Configuration saved successfully")
            
            # Emit signal and close dialog
            self.config_saved.emit(self.config)
            
            # Show success message
            QMessageBox.information(
                self, 
                "Configuration Saved", 
                "Configuration has been saved successfully!\n\nPlease restart the application for all changes to take effect."
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
            
            self.test_button.setText("🔄 Testing...")
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
                        f"✅ Successfully connected to {ip}:{primary_port}\n\nRobot appears to be reachable!"
                    )
                else:
                    QMessageBox.warning(
                        self, 
                        "Connection Test", 
                        f"❌ Could not connect to {ip}:{primary_port}\n\nPlease check:\n- Robot is powered on\n- IP address is correct\n- Network connectivity"
                    )
            finally:
                sock.close()
                
        except Exception as e:
            QMessageBox.critical(self, "Connection Test", f"Connection test failed: {e}")
            
        finally:
            self.test_button.setText("🔍 Test Connection")
            self.test_button.setEnabled(True)
