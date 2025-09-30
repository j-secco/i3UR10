# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UR10 WebSocket Jog Control Interface - A comprehensive PyQt6-based touch-optimized jogging control interface for Universal Robots UR10, designed specifically for Elo i3 touchscreen devices in industrial environments.

**Version:** 1.3.0 (Single UI Implementation)

## Development Commands

### Installation & Setup
```bash
# Install dependencies and setup environment
chmod +x install.sh
./install.sh

# Manual virtual environment setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running the Application
```bash
# Primary method - uses run script
./run.sh

# Manual execution
source venv/bin/activate
python src/main.py

# For debugging - single position read
python position_reader.py 192.168.10.24 --single --verbose

# Continuous position monitoring
python position_reader.py 192.168.10.24 --rate 2.0
```

### Testing & Debugging
```bash
# Debug robot connection
python position_reader.py <robot_ip> --single --verbose

# Monitor real-time data
python position_reader.py <robot_ip> --rate 1.0

# Check network connectivity
ping <robot_ip>
telnet <robot_ip> 30001  # Primary interface
telnet <robot_ip> 29999  # Dashboard
```

### Cleanup
```bash
# Remove installation while preserving config
./uninstall.sh
```

## Architecture Overview

### Three-Tier WebSocket Communication Layer
- **Primary Interface (Port 30001)**: URScript command execution and bidirectional communication
- **Real-time Data (Port 30003)**: High-frequency robot state monitoring for position feedback
- **Dashboard Client (Port 29999)**: Power control, safety management, and robot status queries

### Core Module Structure

#### Communication Layer (`src/communication/`)
- **WebSocketController**: Primary command interface for URScript execution
- **WebSocketReceiver**: Real-time data receiver for continuous robot state monitoring
- **DashboardClient**: Robot power and safety control interface

#### Control Layer (`src/control/`)
- **JogController**: Main orchestrator coordinating all jogging operations
- **CartesianJog**: Cartesian space movement control (X,Y,Z + Rx,Ry,Rz)
- **JointJog**: Individual joint movement control (J1-J6)
- **SafetyMonitor**: Real-time safety status monitoring and emergency handling

#### UI Layer (`src/ui/`)
- **MainWindow**: Touch-optimized PyQt6 main interface for Elo i3 touchscreen
- **widgets/**: Complete set of touch-friendly control panels and status displays
  - **MultiTouchJogPanel**: Advanced multi-touch jogging controls
  - **AnimatedStatusWidget**: Real-time robot status visualization
  - **ConfigDialog**: Robot configuration management
- **styles/**: Modern Material Design-inspired styling system

### Configuration System
Robot and UI settings are centralized in `config/robot_config.yaml`:
- Robot network configuration (IP, ports)
- Jogging parameters (speeds, accelerations, step sizes)
- Safety limits and monitoring settings
- UI layout and touch optimization parameters

### Design Patterns
- **Observer Pattern**: Real-time data updates from WebSocket receivers to UI components
- **Command Pattern**: URScript command generation and execution
- **State Machine**: Robot state monitoring and safety management
- **MVC Architecture**: Clear separation between UI, control logic, and robot communication

### Threading Architecture
- **Main Thread**: PyQt6 UI and user interactions
- **WebSocket Threads**: Separate threads for each WebSocket connection type
- **Safety Monitor Thread**: Continuous safety status monitoring
- **Real-time Data Thread**: High-frequency position updates

### Key Integration Points
- Robot state changes trigger UI updates through Qt signals
- Safety events immediately halt all operations and update UI status
- Touch interactions are debounced and validated before sending robot commands
- Position feedback creates closed-loop verification of command execution

## Configuration Notes

### Robot Connection
Update `config/robot_config.yaml` with your UR10's network settings:
```yaml
robot:
  ip_address: "192.168.10.24"  # Replace with actual robot IP
```

### Touch Interface Optimization
The UI is specifically optimized for Elo i3 touchscreens:
- Button sizes: 120px minimum for reliable touch interaction
- Emergency stop: 150px for safety-critical operations
- Touch margins: 10px spacing prevents accidental activation

### Safety Configuration
Critical safety parameters in config:
- `max_speed`: Velocity limits for safe operation
- `enable_emergency_monitoring`: Real-time safety status checking
- `connection_timeout`: Network failure detection threshold

### Development Mode
Enable debug features in config:
```yaml
development:
  debug_mode: true
  mock_robot_data: true  # For testing without robot hardware
```

## Important Implementation Details

- All robot commands are sent as URScript strings through the primary interface
- Position data parsing handles binary protocol from real-time interface (port 30003)
- Emergency stop functionality requires immediate socket communication to dashboard interface
- UI responsiveness is maintained through Qt signal/slot threading architecture
- Touch input is optimized with debouncing and visual feedback for industrial use