"""
Safety Monitor for UR10 Robot

This module provides safety monitoring and emergency stop functionality.

Author: jsecco ®
"""

import logging
import threading
import time
from typing import List, Dict, Any, Optional, Callable

class SafetyMonitor:
    """
    Safety monitoring system for UR10 robot operations.
    """
    
    def __init__(self, websocket_receiver, dashboard_client, config: Dict[str, Any]):
        """
        Initialize Safety monitor.
        
        Args:
            websocket_receiver: WebSocket receiver for real-time data
            dashboard_client: Dashboard client for robot status
            config: Safety monitoring configuration
        """
        self.websocket_receiver = websocket_receiver
        self.dashboard_client = dashboard_client
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Monitoring state
        self.active = False
        self.monitoring_thread = None
        self.should_stop = threading.Event()
        
        # Safety status
        self.safety_status = {
            'emergency_stopped': False,
            'protective_stopped': False,
            'safe_to_jog': True,
            'robot_mode': 'UNKNOWN',
            'safety_mode': 'UNKNOWN'
        }
        
        # Callbacks
        self.emergency_callbacks: List[Callable[[], None]] = []
        self.protective_callbacks: List[Callable[[], None]] = []
        
        self.logger.info("SafetyMonitor initialized")
    
    def start(self):
        """Start safety monitoring."""
        if self.active:
            self.logger.warning("Safety monitor already active")
            return
            
        self.active = True
        self.should_stop.clear()
        self.monitoring_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitoring_thread.start()
        
        self.logger.info("Safety monitoring started")
    
    def stop(self):
        """Stop safety monitoring."""
        if not self.active:
            return
            
        self.active = False
        self.should_stop.set()
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=2.0)
        
        self.logger.info("Safety monitoring stopped")
    
    def is_safe_to_jog(self) -> bool:
        """Check if it's safe to start jogging."""
        return (self.safety_status['safe_to_jog'] and 
                not self.safety_status['emergency_stopped'] and
                not self.safety_status['protective_stopped'])
    
    def is_emergency_stop_cleared(self) -> bool:
        """Check if emergency stop condition is cleared."""
        return not self.safety_status['emergency_stopped']
    
    def add_emergency_callback(self, callback: Callable[[], None]):
        """Add emergency stop callback."""
        self.emergency_callbacks.append(callback)
    
    def add_protective_callback(self, callback: Callable[[], None]):
        """Add protective stop callback."""
        self.protective_callbacks.append(callback)
    
    def _monitor_loop(self):
        """Safety monitoring loop running in separate thread."""
        while not self.should_stop.is_set() and self.active:
            try:
                # Check robot status
                self._check_robot_status()
                
                # Check for emergency conditions
                self._check_emergency_conditions()
                
                # Check for protective stop conditions
                self._check_protective_conditions()
                
                # Sleep for monitoring interval
                time.sleep(0.1)  # 10 Hz monitoring
                
            except Exception as e:
                self.logger.error(f"Error in safety monitoring loop: {e}")
                time.sleep(1.0)
    
    def _check_robot_status(self):
        """Check robot status from dashboard."""
        if not self.dashboard_client:
            return
            
        try:
            # Get robot status (stub implementation)
            self.safety_status['robot_mode'] = 'RUNNING'
            self.safety_status['safety_mode'] = 'NORMAL'
            self.safety_status['safe_to_jog'] = True
            
        except Exception as e:
            self.logger.error(f"Error checking robot status: {e}")
            self.safety_status['safe_to_jog'] = False
    
    def _check_emergency_conditions(self):
        """Check for emergency stop conditions."""
        try:
            # Check for emergency conditions (stub implementation)
            emergency_detected = False
            
            if emergency_detected and not self.safety_status['emergency_stopped']:
                self.safety_status['emergency_stopped'] = True
                self.logger.critical("EMERGENCY CONDITION DETECTED")
                self._notify_emergency_callbacks()
                
        except Exception as e:
            self.logger.error(f"Error checking emergency conditions: {e}")
    
    def _check_protective_conditions(self):
        """Check for protective stop conditions."""
        try:
            # Check for protective stop conditions (stub implementation)
            protective_stop_detected = False
            
            if protective_stop_detected and not self.safety_status['protective_stopped']:
                self.safety_status['protective_stopped'] = True
                self.logger.warning("PROTECTIVE STOP DETECTED")
                self._notify_protective_callbacks()
                
        except Exception as e:
            self.logger.error(f"Error checking protective conditions: {e}")
    
    def _notify_emergency_callbacks(self):
        """Notify emergency stop callbacks."""
        for callback in self.emergency_callbacks:
            try:
                callback()
            except Exception as e:
                self.logger.error(f"Error in emergency callback: {e}")
    
    def _notify_protective_callbacks(self):
        """Notify protective stop callbacks."""
        for callback in self.protective_callbacks:
            try:
                callback()
            except Exception as e:
                self.logger.error(f"Error in protective callback: {e}")
    
    def get_safety_status(self) -> Dict[str, Any]:
        """Get current safety status."""
        return self.safety_status.copy()
