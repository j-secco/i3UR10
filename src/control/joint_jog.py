"""
Joint Jog Control for UR10 Robot

This module provides Joint space jogging functionality using
UR10 speedj() commands for real-time movement control.

Author: jsecco ®
"""

import logging
import threading
import time
from typing import List, Dict, Any, Optional

class JointJog:
    """
    Joint space jogging controller using UR10 speedj() commands.
    """
    
    def __init__(self, websocket_controller, config: Dict[str, Any]):
        """
        Initialize Joint jog controller.
        
        Args:
            websocket_controller: WebSocket communication interface
            config: Joint jogging configuration
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
        self.max_joint_speed = config.get('max_joint_speed', 1.05)  # rad/s
        self.joint_acceleration = config.get('joint_acceleration', 1.4)  # rad/s^2
        
        # Step sizes for step jogging
        self.joint_step_sizes = config.get('joint_step_sizes', [0.017, 0.087, 0.175, 0.524, 1.047])  # radians
        
        # Threading for continuous jog monitoring
        self.jog_thread = None
        self.stop_event = threading.Event()
        
        self.logger.info("JointJog initialized")
    
    def start_continuous(self, axis: int, direction: int, speed_scale: float = 1.0) -> bool:
        """
        Start continuous Joint jogging.
        
        Args:
            axis: Joint index (0-5: J1-J6)
            direction: Direction (-1 or +1)  
            speed_scale: Speed scaling factor (0.0 to 1.0)
            
        Returns:
            True if started successfully, False otherwise
        """
        if not self.websocket_controller:
            self.logger.error("WebSocket controller not available")
            return False
        
        if self.active:
            self.logger.warning("Joint jog already active - stopping current jog first")
            self.stop()
            
        try:
            # Calculate joint speed vector
            joint_speeds = [0.0] * 6  # [j1_speed, j2_speed, ..., j6_speed]
            
            # Set speed for the specified joint
            joint_speeds[axis] = direction * self.max_joint_speed * speed_scale
            
            # Send speedj command
            success = self.websocket_controller.speed_joint(joint_speeds, self.joint_acceleration, 0.0)
            
            if success:
                self.active = True
                self.current_axis = axis
                self.current_direction = direction
                self.current_speed_scale = speed_scale
                
                # Start monitoring thread to keep jog active
                self.stop_event.clear()
                self.jog_thread = threading.Thread(target=self._continuous_jog_loop, daemon=True)
                self.jog_thread.start()
                
                joint_names = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6']
                self.logger.info(f"Started Joint continuous jog: {joint_names[axis]}{'+' if direction > 0 else '-'}, speed={speed_scale:.2f}")
                return True
            else:
                self.logger.error("Failed to send speedj command")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to start Joint jog: {e}")
            return False
    
    def execute_step(self, axis: int, direction: int, step_index: int = 2) -> bool:
        """
        Execute single step Joint jog movement.
        
        Args:
            axis: Joint index (0-5: J1-J6)
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
            if step_index < len(self.joint_step_sizes):
                step_size = self.joint_step_sizes[step_index]
            else:
                step_size = self.joint_step_sizes[-1]
            
            # Get current joint positions
            # Note: This would normally come from robot state, using zeros for now
            current_joints = [0.0] * 6
            
            # Calculate target joint positions
            target_joints = current_joints.copy()
            target_joints[axis] += direction * step_size
            
            # Use movej for step movement with moderate speed
            step_speed = 0.5  # rad/s
            
            success = self.websocket_controller.move_joint(target_joints, step_speed, self.joint_acceleration, 0.0)
            
            if success:
                joint_names = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6']
                step_deg = step_size * 180 / 3.14159  # Convert to degrees for display
                self.logger.info(f"Executed Joint step jog: {joint_names[axis]}{'+' if direction > 0 else '-'} {step_deg:.1f}°")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to execute Joint step: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop Joint jogging.
        
        Returns:
            True if stopped successfully, False otherwise
        """
        try:
            # Signal stop to monitoring thread
            self.stop_event.set()
            
            # Send stop command
            if self.websocket_controller:
                success = self.websocket_controller.stop_joint(8.0)  # 8 rad/s^2 deceleration
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
                self.logger.info("Stopped Joint jog")
            else:
                self.logger.warning("Failed to send stop command, but marked as stopped")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to stop Joint jog: {e}")
            return False
    
    def _continuous_jog_loop(self):
        """
        Monitoring loop for continuous jogging.
        Resends speedj commands periodically to maintain movement.
        """
        while not self.stop_event.is_set() and self.active:
            try:
                # Resend speedj command every 100ms to maintain movement
                # This is necessary because UR robots expect regular speed commands
                if self.current_axis is not None:
                    joint_speeds = [0.0] * 6
                    joint_speeds[self.current_axis] = self.current_direction * self.max_joint_speed * self.current_speed_scale
                    
                    # Send speedj command with 0.2s time limit
                    self.websocket_controller.speed_joint(joint_speeds, self.joint_acceleration, 0.2)
                
                # Wait 100ms before next command
                time.sleep(0.1)
                
            except Exception as e:
                self.logger.error(f"Error in continuous jog loop: {e}")
                break
        
        self.logger.debug("Continuous jog loop ended")
    
    def is_active(self) -> bool:
        """Check if Joint jogging is active."""
        return self.active
    
    def get_status(self) -> Dict[str, Any]:
        """Get current jog status."""
        joint_names = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6']
        return {
            'active': self.active,
            'axis': self.current_axis,
            'axis_name': joint_names[self.current_axis] if self.current_axis is not None else None,
            'direction': self.current_direction,
            'speed_scale': self.current_speed_scale
        }
