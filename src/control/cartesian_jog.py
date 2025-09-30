"""
Cartesian Jog Control for UR10 Robot

This module provides Cartesian space jogging functionality using
UR10 speedl() commands for real-time movement control.

Author: jsecco ®
"""

import logging
import threading
import time
from typing import List, Dict, Any, Optional

class CartesianJog:
    """
    Cartesian space jogging controller using UR10 speedl() commands.
    """
    
    def __init__(self, websocket_controller, config: Dict[str, Any]):
        """
        Initialize Cartesian jog controller.
        
        Args:
            websocket_controller: WebSocket communication interface
            config: Cartesian jogging configuration
        """
        self.websocket_controller = websocket_controller
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Jogging state
        self.active = False
        self.current_axis = None
        self.current_direction = None
        self.current_speed_scale = 1.0
        
        # Configuration parameters
        self.max_linear_speed = config.get('max_linear_speed', 0.25)  # m/s
        self.max_angular_speed = config.get('max_angular_speed', 0.75)  # rad/s
        self.linear_acceleration = config.get('linear_acceleration', 1.2)  # m/s^2
        self.angular_acceleration = config.get('angular_acceleration', 3.14)  # rad/s^2
        
        # Step sizes for step jogging
        self.linear_step_sizes = config.get('linear_step_sizes', [0.001, 0.005, 0.01, 0.05, 0.1])  # meters
        self.angular_step_sizes = config.get('angular_step_sizes', [0.017, 0.087, 0.175, 0.524, 1.047])  # radians
        
        # Threading for continuous jog monitoring
        self.jog_thread = None
        self.stop_event = threading.Event()
        
        self.logger.info("CartesianJog initialized")
    
    def start_continuous(self, axis: int, direction: int, speed_scale: float = 1.0) -> bool:
        """
        Start continuous Cartesian jogging.
        
        Args:
            axis: Axis index (0-5: X,Y,Z,Rx,Ry,Rz)
            direction: Direction (-1 or +1)  
            speed_scale: Speed scaling factor (0.0 to 1.0)
            
        Returns:
            True if started successfully, False otherwise
        """
        if not self.websocket_controller:
            self.logger.error("WebSocket controller not available")
            return False
        
        if self.active:
            self.logger.warning("Cartesian jog already active - stopping current jog first")
            self.stop()
            
        try:
            # Calculate velocity vector
            velocities = [0.0] * 6  # [vx, vy, vz, vrx, vry, vrz]
            
            if axis < 3:  # Linear axes (X, Y, Z)
                max_speed = self.max_linear_speed
                acceleration = self.linear_acceleration
            else:  # Angular axes (Rx, Ry, Rz)
                max_speed = self.max_angular_speed  
                acceleration = self.angular_acceleration
            
            # Set velocity for the specified axis
            velocities[axis] = direction * max_speed * speed_scale
            
            # Send speedl command
            success = self.websocket_controller.speed_linear(velocities, acceleration, 0.0)
            
            if success:
                self.active = True
                self.current_axis = axis
                self.current_direction = direction
                self.current_speed_scale = speed_scale
                
                # Start monitoring thread to keep jog active
                self.stop_event.clear()
                self.jog_thread = threading.Thread(target=self._continuous_jog_loop, daemon=True)
                self.jog_thread.start()
                
                axis_names = ['X', 'Y', 'Z', 'Rx', 'Ry', 'Rz']
                self.logger.info(f"Started Cartesian continuous jog: {axis_names[axis]}{'+' if direction > 0 else '-'}, speed={speed_scale:.2f}")
                return True
            else:
                self.logger.error("Failed to send speedl command")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to start Cartesian jog: {e}")
            return False
    
    def execute_step(self, axis: int, direction: int, step_index: int = 2) -> bool:
        """
        Execute single step Cartesian jog movement.
        
        Args:
            axis: Axis index (0-5: X,Y,Z,Rx,Ry,Rz)
            direction: Direction (-1 or +1)
            step_index: Step size index (0=smallest, 4=largest)
            
        Returns:
            True if step executed successfully, False otherwise
        """
        if not self.websocket_controller:
            self.logger.error("WebSocket controller not available")
            return False
        
        if self.active:
            self.logger.warning("Cannot execute step jog while continuous jog is active")
            return False
            
        try:
            # Get step size
            if axis < 3:  # Linear axes
                if step_index < len(self.linear_step_sizes):
                    step_size = self.linear_step_sizes[step_index]
                else:
                    step_size = self.linear_step_sizes[-1]
            else:  # Angular axes
                if step_index < len(self.angular_step_sizes):
                    step_size = self.angular_step_sizes[step_index]
                else:
                    step_size = self.angular_step_sizes[-1]
            
            # Get current TCP pose first
            # Note: This would normally come from robot state, using zeros for now
            current_pose = [0.0] * 6
            
            # Calculate target pose
            target_pose = current_pose.copy()
            target_pose[axis] += direction * step_size
            
            # Use movel for step movement with moderate speed
            step_speed = 0.1 if axis < 3 else 0.5  # m/s for linear, rad/s for angular
            acceleration = self.linear_acceleration if axis < 3 else self.angular_acceleration
            
            success = self.websocket_controller.move_linear(target_pose, step_speed, acceleration, 0.0)
            
            if success:
                axis_names = ['X', 'Y', 'Z', 'Rx', 'Ry', 'Rz']
                step_str = f"{step_size:.3f}" + ("m" if axis < 3 else "rad")
                self.logger.info(f"Executed Cartesian step jog: {axis_names[axis]}{'+' if direction > 0 else '-'} {step_str}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to execute Cartesian step: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop Cartesian jogging.
        
        Returns:
            True if stopped successfully, False otherwise
        """
        try:
            # Signal stop to monitoring thread
            self.stop_event.set()
            
            # Send stop command
            if self.websocket_controller:
                success = self.websocket_controller.stop_linear(10.0)  # 10 m/s^2 deceleration
            else:
                success = False
            
            # Wait for jog thread to finish
            if self.jog_thread and self.jog_thread.is_alive():
                self.jog_thread.join(timeout=1.0)
            
            # Reset state
            self.active = False
            self.current_axis = None
            self.current_direction = None
            self.current_speed_scale = 1.0
            
            if success:
                self.logger.info("Stopped Cartesian jog")
            else:
                self.logger.warning("Failed to send stop command, but marked as stopped")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to stop Cartesian jog: {e}")
            return False
    
    def _continuous_jog_loop(self):
        """
        Monitoring loop for continuous jogging.
        Resends speedl commands periodically to maintain movement.
        """
        while not self.stop_event.is_set() and self.active:
            try:
                # Resend speedl command every 100ms to maintain movement
                # This is necessary because UR robots expect regular speed commands
                if self.current_axis is not None:
                    velocities = [0.0] * 6
                    
                    if self.current_axis < 3:  # Linear
                        max_speed = self.max_linear_speed
                        acceleration = self.linear_acceleration
                    else:  # Angular
                        max_speed = self.max_angular_speed
                        acceleration = self.angular_acceleration
                    
                    velocities[self.current_axis] = self.current_direction * max_speed * self.current_speed_scale
                    
                    # Send speedl command
                    self.websocket_controller.speed_linear(velocities, acceleration, 0.2)
                
                # Wait 100ms before next command
                time.sleep(0.1)
                
            except Exception as e:
                self.logger.error(f"Error in continuous jog loop: {e}")
                break
        
        self.logger.debug("Continuous jog loop ended")
    
    def is_active(self) -> bool:
        """Check if Cartesian jogging is active."""
        return self.active
    
    def get_status(self) -> Dict[str, Any]:
        """Get current jog status."""
        axis_names = ['X', 'Y', 'Z', 'Rx', 'Ry', 'Rz']
        return {
            'active': self.active,
            'axis': self.current_axis,
            'axis_name': axis_names[self.current_axis] if self.current_axis is not None else None,
            'direction': self.current_direction,
            'speed_scale': self.current_speed_scale
        }
