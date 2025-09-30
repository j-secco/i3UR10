# UR10 API Reference Documentation

**Author**: jsecco ®  
**Based on**: Universal Robots official documentation and ur_rtde 1.5.8 library

## RTDE (Real-Time Data Exchange) Overview

The Real-Time Data Exchange (RTDE) interface provides synchronization between external applications and the UR controller over TCP/IP without breaking real-time properties.

### Key RTDE Features
- **Real-time synchronization**: Typically generates output messages at 125 Hz
- **Bidirectional communication**: Send inputs and receive outputs
- **Runtime environment**: Can run on Control Box PC or external PC
- **Protocol versioning**: Supports version negotiation for compatibility

### RTDE Ports and Interfaces
```
Interface Type    | Port  | Purpose
------------------|-------|------------------------------------------
Primary           | 30001 | Robot state data + URScript commands (10Hz)
Secondary         | 30002 | Robot state data only (10Hz) 
Real-time         | 30003 | Real-time robot state data
RTDE              | 30004 | Real-Time Data Exchange (125Hz)
Dashboard         | 29999 | Robot program control and status
```

## ur_rtde Library Classes

### RTDEControlInterface
Primary class for robot control and movement execution.

**Key Methods**:
- `moveJ()` - Joint space movement
- `moveL()` - Linear movement in Cartesian space
- `speedJ()` - Joint space velocity control
- `speedL()` - Cartesian space velocity control
- `servoJ()` - Joint space real-time control
- `servoL()` - Cartesian space real-time control
- `stopL()` / `stopJ()` - Emergency stop functions
- `isProgramRunning()` - Check robot program status
- `isConnected()` - Connection status

**Constructor**:
```python
RTDEControlInterface(hostname, frequency=-1.0, flags=FLAGS_DEFAULT)
```

### RTDEReceiveInterface
Class for receiving real-time robot data.

**Key Methods**:
- `getActualTCPPose()` - Current TCP position and orientation
- `getActualQ()` - Current joint positions
- `getActualTCPSpeed()` - Current TCP velocity
- `getActualQd()` - Current joint velocities
- `getRobotMode()` / `getSafetyMode()` - Robot status
- `isEmergencyStopped()` / `isProtectiveStopped()` - Safety status
- `getTimestamp()` - Controller timestamp

### DashboardClient
Interface for robot state management and program control.

**Key Methods**:
- `connect()` / `disconnect()` - Connection management
- `powerOn()` / `powerOff()` - Robot power control
- `brakeRelease()` - Release robot brakes
- `play()` / `stop()` / `pause()` - Program control
- `getRobotModel()` - Get robot model information
- `safetymode()` / `safetystatus()` - Safety information

## RTDE Data Types

### Robot Controller Outputs (Receive Data)
Essential data fields for jog control interface:

```python
# Position and Movement Data
actual_TCP_pose     # VECTOR6D - Current TCP position/orientation
target_TCP_pose     # VECTOR6D - Target TCP position/orientation
actual_q           # VECTOR6D - Current joint positions
target_q           # VECTOR6D - Target joint positions
actual_TCP_speed   # VECTOR6D - Current TCP velocity
actual_qd          # VECTOR6D - Current joint velocities

# Robot Status
robot_mode         # INT32 - Robot operational mode
safety_mode        # INT32 - Safety system mode
runtime_state      # UINT32 - Program execution state
robot_status_bits  # UINT32 - Robot status flags
safety_status_bits # UINT32 - Safety status flags

# Timing and Control
timestamp          # DOUBLE - Controller time
actual_execution_time # DOUBLE - Real-time thread execution time
speed_scaling      # DOUBLE - Current speed scaling factor
```

### Robot Controller Inputs (Send Data)
Control inputs for robot jogging:

```python
# Speed Control
speed_slider_mask     # UINT32 - Enable speed slider control
speed_slider_fraction # DOUBLE - Speed slider value [0..1]

# Digital I/O Control
standard_digital_output_mask # UINT8 - Digital output mask
standard_digital_output      # UINT8 - Digital output values

# External Force Control
external_force_torque # VECTOR6D - External wrench input
```

## Robot Modes and Status

### Robot Mode Values
```python
ROBOT_MODE_DISCONNECTED = -1
ROBOT_MODE_CONFIRM_SAFETY = 0
ROBOT_MODE_BOOTING = 1
ROBOT_MODE_POWER_OFF = 2
ROBOT_MODE_POWER_ON = 3
ROBOT_MODE_IDLE = 4
ROBOT_MODE_BACKDRIVE = 5
ROBOT_MODE_RUNNING = 6
ROBOT_MODE_UPDATING_FIRMWARE = 7
```

### Safety Mode Values
```python
SAFETY_MODE_NORMAL = 1
SAFETY_MODE_REDUCED = 2
SAFETY_MODE_PROTECTIVE_STOP = 3
SAFETY_MODE_RECOVERY = 4
SAFETY_MODE_SAFEGUARD_STOP = 5
SAFETY_MODE_SYSTEM_EMERGENCY_STOP = 6
SAFETY_MODE_ROBOT_EMERGENCY_STOP = 7
SAFETY_MODE_VIOLATION = 8
SAFETY_MODE_FAULT = 9
```

## Jog Control Implementation Guidelines

### Cartesian Jogging
Use `speedL()` for continuous jogging or `moveL()` for step jogging:

```python
# Continuous cartesian jog
speed_vector = [vx, vy, vz, vrx, vry, vrz]  # m/s and rad/s
rtde_control.speedL(speed_vector, acceleration, time)

# Step cartesian jog
target_pose = current_pose.copy()
target_pose[axis] += step_size
rtde_control.moveL(target_pose, speed, acceleration)
```

### Joint Jogging
Use `speedJ()` for continuous jogging or `moveJ()` for step jogging:

```python
# Continuous joint jog
joint_speeds = [0, 0, speed, 0, 0, 0]  # rad/s for each joint
rtde_control.speedJ(joint_speeds, acceleration, time)

# Step joint jog
target_joints = current_joints.copy()
target_joints[joint_index] += step_size
rtde_control.moveJ(target_joints, speed, acceleration)
```

### Emergency Stop Implementation
```python
# Immediate stop
rtde_control.stopL(deceleration=10.0, asynchronous=True)  # Linear stop
rtde_control.stopJ(deceleration=10.0, asynchronous=True)  # Joint stop

# Check for protective stops
if rtde_receive.isProtectiveStopped():
    # Handle protective stop condition
    pass

if rtde_receive.isEmergencyStopped():
    # Handle emergency stop condition
    pass
```

## Safety Considerations

1. **Always monitor safety status** before and during robot movement
2. **Implement proper emergency stop handling** with immediate response
3. **Validate workspace limits** before executing movements
4. **Use appropriate acceleration/deceleration values** for safety
5. **Monitor connection status** continuously during operation
6. **Implement timeout mechanisms** for all robot commands

## Connection Management Best Practices

```python
# Robust connection with retry logic
def connect_with_retry(rtde_control, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            if rtde_control.isConnected():
                return True
            rtde_control.reconnect()
            if rtde_control.isConnected():
                return True
        except Exception as e:
            print(f"Connection attempt {attempt + 1} failed: {e}")
            time.sleep(2.0)
    return False
```

This reference is based on the official Universal Robots documentation and ur_rtde 1.5.8 library specifications.
