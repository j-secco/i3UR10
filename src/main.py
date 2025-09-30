#!/usr/bin/env python3
"""
UR10 WebSocket Jog Control Interface - Main Application
Touch-optimized PyQt6 interface for Elo i3 touchscreen devices

Author: jsecco ®
"""

import sys
import os
import logging
import signal
import argparse
import yaml
from pathlib import Path
from typing import Dict, Any

# Ensure src directory is in path for imports
script_dir = Path(__file__).parent.parent
src_dir = Path(__file__).parent
sys.path.insert(0, str(src_dir))

# PyQt6 imports
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont

# Local imports
try:
    from control.jog_controller import JogController
    from ui.main_window_professional import ProfessionalMainWindow as MainWindow
except ImportError as e:
    print(f"Import error: {e}")
    print("Please ensure all modules are properly installed")
    sys.exit(1)


def setup_logging(config: Dict[str, Any]) -> None:
    """
    Set up application logging.
    
    Args:
        config: Application configuration dictionary
    """
    # Get logging configuration
    log_config = config.get('logging', {})
    log_level = log_config.get('level', 'INFO')
    
    # Ensure logs directory exists
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        datefmt=log_config.get('date_format', '%Y-%m-%d %H:%M:%S'),
        handlers=[
            logging.FileHandler(log_config.get('files', {}).get('main', 'logs/ur10_jog_control.log')),
            logging.StreamHandler(sys.stdout)
        ],
        force=True  # Force reconfiguration
    )
    
    # Set up rotating file handler if configured
    try:
        from logging.handlers import RotatingFileHandler
        
        rotation_config = log_config.get('rotation', {})
        max_size = rotation_config.get('max_size', '10MB')
        backup_count = rotation_config.get('backup_count', 5)
        
        # Convert size string to bytes
        size_map = {'KB': 1024, 'MB': 1024*1024, 'GB': 1024*1024*1024}
        size_bytes = 10 * 1024 * 1024  # Default 10MB
        
        for suffix, multiplier in size_map.items():
            if max_size.endswith(suffix):
                size_bytes = int(max_size[:-2]) * multiplier
                break
        
        # Replace file handler with rotating handler
        root_logger = logging.getLogger()
        file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler) and not isinstance(h, RotatingFileHandler)]
        
        for handler in file_handlers:
            root_logger.removeHandler(handler)
                
        rotating_handler = RotatingFileHandler(
            log_config.get('files', {}).get('main', 'logs/ur10_jog_control.log'),
            maxBytes=size_bytes,
            backupCount=backup_count
        )
        rotating_handler.setFormatter(logging.Formatter(
            log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
            log_config.get('date_format', '%Y-%m-%d %H:%M:%S')
        ))
        root_logger.addHandler(rotating_handler)
        
    except ImportError:
        logging.warning("Could not set up log rotation - continuing with basic logging")


def load_configuration() -> Dict[str, Any]:
    """
    Load application configuration.
    
    Returns:
        Configuration dictionary
    """
    config_file = Path('config/robot_config.yaml')
    
    if not config_file.exists():
        logging.warning(f"Configuration file not found: {config_file}")
        logging.info("Using default configuration")
        return get_default_config()
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        logging.info(f"Loaded configuration from {config_file}")
        return config
        
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
        logging.info("Using default configuration")
        return get_default_config()


def get_default_config() -> Dict[str, Any]:
    """
    Get default configuration if config file is not available.
    
    Returns:
        Default configuration dictionary
    """
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
            'default_speed': 0.1,
            'step_size': 0.01,
            'max_speed': 0.5,
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
        },
        'safety': {
            'enable_emergency_monitoring': True,
            'connection_timeout': 5.0
        },
        'ui': {
            'window': {
                'title': 'UR10 Jog Control Interface',
                'width': 1024,
                'height': 768,
                'fullscreen': False
            },
            'colors': {
                'primary': '#2196F3',
                'secondary': '#FFC107',
                'success': '#4CAF50',
                'warning': '#FF9800',
                'danger': '#F44336',
                'background': '#FAFAFA'
            },
            'touch': {
                'button_size': 80,
                'touch_margin': 10,
                'hold_time': 150
            },
            'feedback': {
                'position_update_rate': 10,
                'status_update_rate': 5
            }
        },
        'logging': {
            'level': 'INFO',
            'files': {
                'main': 'logs/ur10_jog_control.log'
            }
        }
    }


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating shutdown...")
        QApplication.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def setup_application(config: Dict[str, Any]) -> QApplication:
    """
    Set up the PyQt6 application.
    
    Args:
        config: Application configuration
        
    Returns:
        Configured QApplication instance
    """
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("UR10 Jog Control Interface")
    app.setApplicationVersion("1.3.0")
    app.setOrganizationName("jsecco ®")
    
    # Set up application font for touch interface
    touch_config = config.get('ui', {}).get('touch', {})
    font = QFont()
    font.setPointSize(12)  # Larger font for touch interface
    app.setFont(font)
    
    # Set application style for touch
    app.setStyleSheet("""
        QToolTip {
            background-color: #FFFFCC;
            border: 1px solid #999999;
            padding: 5px;
            border-radius: 3px;
            font-size: 12px;
        }
    """)
    
    return app


def main():
    """Main application entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="UR10 WebSocket Jog Control Interface")
    parser.add_argument("--config", "-c", type=str, help="Configuration file path")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug mode")
    parser.add_argument("--simulate", "-s", action="store_true", help="Simulation mode (no robot required)")
    parser.add_argument("--fullscreen", "-f", action="store_true", help="Start in fullscreen mode")
    args = parser.parse_args()
    
    # Load configuration
    config = load_configuration()
    
    # Override config with command line arguments
    if args.debug:
        config['logging']['level'] = 'DEBUG'
        config['debug'] = {'enabled': True}
    
    if args.simulate:
        config.setdefault('debug', {})['simulate_robot'] = True
        
    if args.fullscreen:
        config['ui']['window']['fullscreen'] = True
    
    # Set up logging
    setup_logging(config)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("UR10 WebSocket Jog Control Interface Starting")
    logger.info("Author: jsecco ®")
    logger.info("Version: 1.3.0")
    logger.info("=" * 60)
    
    # Log configuration
    robot_ip = config.get('robot', {}).get('ip_address', 'Not Set')
    logger.info(f"Robot IP: {robot_ip}")
    logger.info(f"Debug Mode: {config.get('debug', {}).get('enabled', False)}")
    logger.info(f"Simulation Mode: {config.get('debug', {}).get('simulate_robot', False)}")
    
    # Set up signal handlers
    setup_signal_handlers()
    
    # Initialize variables
    jog_controller = None
    main_window = None
    
    try:
        # Create PyQt6 application
        app = setup_application(config)
        logger.info("PyQt6 application initialized")
        
        # Create main window
        main_window = MainWindow(config)
        logger.info("Main window created")
        
        # Create and configure jog controller with error handling
        try:
            jog_controller = JogController(config)
            main_window.set_jog_controller(jog_controller)
            logger.info("Jog controller created and connected")
        except Exception as e:
            logger.error(f"Failed to create jog controller: {e}")
            # Continue without jog controller - UI should handle this gracefully
            main_window.add_log_message(f"Jog controller initialization failed: {str(e)}", "ERROR")
        
        # Show main window
        main_window.show()
        logger.info("Main window displayed")
        
        # Add welcome message to UI
        main_window.add_log_message("UR10 Jog Control Interface Started", "SUCCESS")
        main_window.add_log_message(f"Robot IP: {robot_ip}", "INFO")
        
        if config.get('debug', {}).get('simulate_robot', False):
            main_window.add_log_message("Running in SIMULATION mode - no robot required", "WARNING")
        
        # Start the application event loop
        logger.info("Starting application event loop...")
        exit_code = app.exec()
        
        logger.info(f"Application exited with code: {exit_code}")
        return exit_code
        
    except Exception as e:
        logger.error(f"Fatal error during application startup: {e}", exc_info=True)
        
        # Try to show error dialog if possible
        try:
            error_app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "UR10 Jog Control - Fatal Error",
                f"A fatal error occurred during startup:\n\n{str(e)}\n\nCheck the logs for more details."
            )
        except Exception as dialog_error:
            logger.error(f"Could not show error dialog: {dialog_error}")
            
        return 1
    
    finally:
        # Cleanup
        logger.info("Performing cleanup...")
        try:
            if jog_controller:
                jog_controller.disconnect()
                logger.info("Jog controller disconnected")
        except Exception as e:
            logger.error(f"Error during jog controller cleanup: {e}")
        
        try:
            if main_window:
                main_window.close()
                logger.info("Main window closed")
        except Exception as e:
            logger.error(f"Error during main window cleanup: {e}")
        
        logger.info("UR10 WebSocket Jog Control Interface Shutdown Complete")
        logger.info("=" * 60)


if __name__ == "__main__":
    # Ensure we can import required modules
    missing_modules = []
    try:
        import PyQt6
    except ImportError:
        missing_modules.append("PyQt6")
    
    try:
        import yaml
    except ImportError:
        missing_modules.append("yaml")
    
    try:
        import websockets
    except ImportError:
        missing_modules.append("websockets")
    
    if missing_modules:
        print(f"Error: Required modules not found: {', '.join(missing_modules)}")
        print("Please run the installation script first: ./install.sh")
        sys.exit(1)
    
    # Change to script directory
    if script_dir.exists():
        os.chdir(script_dir)
    
    # Run main application
    sys.exit(main())
