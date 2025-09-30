# UR10 WebSocket Jog Control Interface

A comprehensive WebSocket-based jogging control interface for Universal Robots UR10, optimized for touch-screen operation on Elo i3 devices.

**Author:** jsecco ®  
**Version:** 1.0.0  
**License:** MIT  

## 🚀 Features

### WebSocket Communication
- **Primary Interface (Port 30001)**: Command execution and program control
- **Real-time Data (Port 30003)**: High-frequency robot state monitoring
- **Dashboard Client (Port 29999)**: Power control and safety management

### Robot Control
- **Cartesian Jogging**: X, Y, Z, Rx, Ry, Rz with configurable speeds
- **Joint Jogging**: Individual joint control (J1-J6)
- **Step & Continuous Modes**: Precise positioning or smooth continuous movement
- **Speed Scaling**: Configurable velocity limits for safety
- **Emergency Stop**: Immediate robot stopping with safety monitoring

### Safety Features
- Real-time safety status monitoring
- Emergency stop integration
- Robot state validation
- Connection health monitoring
- Automatic reconnection handling

### User Interface
- Touch-optimized PyQt6 interface
- Designed for Elo i3 touchscreen devices
- Real-time position feedback
- Visual safety status indicators
- Responsive button layout for industrial use

## 📋 Requirements

### Hardware
- Universal Robots UR10 with network connectivity
- Elo i3 touchscreen device (or compatible Linux system)
- Network connection to robot controller

### Software
- Ubuntu 20.04+ (recommended)
- Python 3.12+
- Qt6 libraries (installed automatically)

## ⚡ Quick Installation

### 1. Clone or Download
```bash
# If using git
git clone <repository-url>
cd ur10-websocket-jog-control

# Or download and extract the project files
```

### 2. Run Installation Script
```bash
chmod +x install.sh
./install.sh
```

The installation script will:
- ✅ Create Python virtual environment
- ✅ Install all required dependencies  
- ✅ Set up project directories
- ✅ Create run scripts and desktop launcher
- ✅ Generate systemd service file (optional)

### 3. Configure Robot Connection
Edit the configuration file with your UR10's IP address:

```bash
nano config/robot_config.yaml
```

```yaml
robot:
  ip_address: "192.168.10.24"  # Replace with your UR10 IP
  ports:
    primary: 30001      # Primary interface
    realtime: 30003     # Real-time data
    dashboard: 29999    # Dashboard commands
  
jogging:
  default_speed: 0.1    # m/s for Cartesian, rad/s for joints
  step_size: 0.01       # Default step size
  max_speed: 0.5        # Safety speed limit
  
safety:
  enable_emergency_monitoring: true
  connection_timeout: 5.0
```

### 4. Run the Application
```bash
# Simple run
./run.sh

# Or manually
source venv/bin/activate
python src/main.py
```

## 📱 Usage

### Starting the Interface
1. Ensure UR10 is powered and network-accessible
2. Run the application using `./run.sh`
3. The touch interface will open automatically
4. Connection status is displayed in the top bar

### Basic Jogging
1. **Select Mode**: Choose Cartesian or Joint jogging
2. **Choose Direction**: Select axis or joint to move
3. **Set Speed**: Use speed slider for velocity control
4. **Jog**: 
   - **Step Mode**: Single click for precise steps
   - **Continuous Mode**: Hold button for continuous movement

### Safety Controls
- **Emergency Stop**: Large red button for immediate stopping
- **Reset**: Clear emergency states and reconnect
- **Connection Status**: Live indicator of robot communication

## 🔧 Advanced Configuration

### Custom Speed Profiles
```yaml
speed_profiles:
  precise:
    cartesian: 0.05  # m/s
    joint: 0.1       # rad/s
  normal:
    cartesian: 0.1
    joint: 0.2
  fast:
    cartesian: 0.25
    joint: 0.5
```

### Network Settings
```yaml
network:
  connection_retries: 3
  retry_delay: 2.0
  keepalive_interval: 30.0
  receive_timeout: 1.0
```

## 🛠️ Architecture

```
ur10-websocket-jog-control/
├── src/
│   ├── communication/
│   │   ├── websocket_controller.py  # Primary WebSocket client
│   │   ├── websocket_receiver.py    # Real-time data receiver  
│   │   └── dashboard_client.py      # Dashboard commands
│   ├── control/
│   │   └── jog_controller.py        # Main jogging logic
│   ├── ui/                          # PyQt6 interface (to be added)
│   └── main.py                      # Application entry point
├── config/
│   └── robot_config.yaml           # Robot configuration
├── logs/                            # Application logs
├── docs/                            # Documentation
├── install.sh                       # Installation script
├── uninstall.sh                     # Uninstallation script  
├── requirements.txt                 # Python dependencies
└── README.md                        # This file
```

## 🔌 WebSocket Protocol Details

### Primary Interface (Port 30001)
Used for sending commands and receiving responses:
```python
# Example jogging command
"movej([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], a=0.1, v=0.1)\n"
```

### Real-time Interface (Port 30003)  
Provides high-frequency robot state data:
- TCP pose (position and orientation)
- Joint angles and velocities
- Safety mode and robot state
- I/O states and tool data

### Dashboard Interface (Port 29999)
Robot control and status queries:
- `power on` / `power off`
- `brake release` / `brake engage`
- `get robot model` / `get serial number`
- `is in remote control` / `get program state`

## 📊 Logging and Monitoring

All application activities are logged to:
- `logs/ur10_jog_control.log` - General application log
- `logs/websocket_communication.log` - WebSocket traffic
- `logs/safety_events.log` - Safety-related events

Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## 🚨 Safety Considerations

⚠️ **CRITICAL SAFETY NOTES:**

1. **Always ensure proper safety measures** when operating the robot
2. **Verify workspace clearance** before jogging movements  
3. **Keep emergency stop accessible** at all times
4. **Test in low-speed mode** before increasing velocities
5. **Understand robot coordinate systems** (Base vs Tool frames)
6. **Monitor safety status** indicators continuously
7. **Never bypass safety systems** or protective measures

## 🔧 Troubleshooting

### Connection Issues
```bash
# Check network connectivity
ping 192.168.10.24  # Replace with your robot IP

# Verify ports are accessible
telnet 192.168.10.24 30001
telnet 192.168.10.24 29999
```

### Robot Not Responding
1. Check robot power and initialization
2. Ensure robot is in remote control mode
3. Verify no protective stops are active
4. Check emergency stop status

### GUI Display Issues
```bash
# For headless systems, ensure X11 forwarding or display server
export DISPLAY=:0

# Install Qt platform plugins if missing  
sudo apt-get install qt6-base-dev
```

### Performance Issues
- Monitor CPU usage during operation
- Check network latency to robot
- Review log files for bottlenecks
- Consider reducing real-time data frequency

## 🗂️ Uninstallation

To remove the application while preserving configuration and logs:

```bash
./uninstall.sh
```

For complete removal:
```bash
rm -rf /path/to/ur10-websocket-jog-control
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/new-feature`)
3. Commit changes (`git commit -am 'Add new feature'`)
4. Push to branch (`git push origin feature/new-feature`)
5. Create Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🐛 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review log files in `logs/` directory
3. Open an issue on the project repository
4. Contact: jsecco ®

## 🔄 Version History

- **v1.0.0** (2024) - Initial release
  - WebSocket communication layer
  - Dashboard client implementation  
  - Jog control logic
  - Safety monitoring
  - Installation/deployment scripts
  - Touch-optimized PyQt6 interface (in progress)

---

**⚡ Ready to control your UR10 with WebSockets!**

*Built with ❤️ for industrial automation*
