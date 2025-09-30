# UR10 Robot Jogging Interface Guide

## 🚀 **Real Robot Movement Implementation Complete**

The UR10 WebSocket Jog Control Interface now includes **full robot movement functionality**:

### ✅ **What's Now Working**

1. **Real Robot Communication**: Uses UR10's native socket interface (ports 30001, 30003, 29999)
2. **Cartesian Jogging**: Uses `speedl()` commands for X, Y, Z, Rx, Ry, Rz movement
3. **Joint Jogging**: Uses `speedj()` commands for J1-J6 joint movement  
4. **Continuous Movement**: Press and hold buttons for smooth continuous jogging
5. **Emergency Stop**: Uses `stopl()` and `stopj()` commands to halt movement immediately
6. **Speed Control**: UI slider controls movement speed from 1% to 100%
7. **Safety Monitoring**: Checks robot safety status before allowing movement

---

## 🎮 **How to Use the Interface**

### **1. Configure Robot Connection**
- Click the **⚙️ Settings** button in the header
- Enter your robot's IP address (e.g., `192.168.10.24`)
- Configure communication ports (defaults: 30001, 30003, 29999)
- Save configuration

### **2. Connect to Robot**
- Click **"Connect to Robot"** button in the center panel
- Status will show "Connected" when successful
- Robot IP will display in green when configured correctly

### **3. Select Jogging Mode**
- **Cartesian Mode**: Move in X, Y, Z linear directions and Rx, Ry, Rz rotations
- **Joint Mode**: Move individual joints J1-J6 directly

### **4. Adjust Speed** 
- Use the speed slider (1-100%) to control movement speed
- Lower speeds (10-20%) recommended for initial testing
- Higher speeds (50-100%) for normal operation

### **5. Jog the Robot**
- **Press and Hold** jog buttons to move the robot
- **Release** the button to stop movement immediately
- **Emergency Stop** button available at all times (right panel)

---

## ⚙️ **Technical Implementation**

### **Movement Commands Used**
- **Cartesian Continuous**: `speedl([vx, vy, vz, vrx, vry, vrz], a, t)`
- **Joint Continuous**: `speedj([j1_speed, j2_speed, j3_speed, j4_speed, j5_speed, j6_speed], a, t)`  
- **Emergency Stop**: `stopl(deceleration)` and `stopj(deceleration)`

### **Safety Features**
- Connection status monitoring
- Emergency stop detection
- Safety mode checking  
- Protective stop handling
- Speed and acceleration limits

### **Real-time Operation**
- Commands sent every 100ms during continuous jogging
- Automatic stop when button is released
- Thread-safe operation with proper locking

---

## 🔧 **Troubleshooting**

### **Robot Not Moving**
1. **Check Connection Status**: 
   - Ensure "Connected" shows in green in header
   - Verify robot IP address is correct in settings
   
2. **Check Robot State**:
   - Robot must be in "Running" mode (not stopped or protective stop)
   - Check UR10 teach pendant for any error messages
   - Ensure robot is not in protective stop mode

3. **Check Safety Status**:
   - Emergency stop must be cleared
   - Safety systems must show "Normal" status
   - Remote control must be enabled on robot

4. **Check Network**:
   - Robot and computer must be on same network
   - Ping the robot IP address: `ping 192.168.10.24`
   - Check firewall settings (ports 30001, 30003, 29999)

### **Connection Issues**
1. **IP Address**: Verify robot IP in UR10 teach pendant → Settings → System → Network
2. **Ports**: Standard UR ports should work (30001, 30003, 29999)  
3. **Robot Mode**: Robot should be in "Remote Control" mode
4. **Firewall**: Ensure ports are not blocked

### **Movement Issues**
1. **Speed Too Low**: Increase speed slider above 10%
2. **Safety Limits**: Check if robot is near workspace limits
3. **Joint Limits**: Verify joints are not at software/hardware limits
4. **Program Running**: Ensure no other program is controlling the robot

---

## 📋 **Command Line Testing**

To test the application from command line:
```bash
cd /home/ur10/Documents/assistant-from-jsecco
./launch_kiosk.sh
```

Check logs for debugging:
```bash
tail -f logs/ur10_jog_control.log
```

---

## 🚨 **Safety Notes**

1. **Always be ready to hit Emergency Stop**
2. **Start with low speeds (10-20%) for testing**
3. **Ensure clear workspace around robot** 
4. **Monitor robot behavior closely during operation**
5. **Keep UR10 teach pendant accessible for manual control**
6. **Follow all UR10 safety procedures and guidelines**

---

## 📞 **Support**

If you continue to experience issues:

1. **Check System Logs**: Look at the log messages in the right panel
2. **Check Robot Status**: Verify all status indicators are green/normal
3. **Network Connectivity**: Ensure stable network connection to robot
4. **Robot Configuration**: Verify robot is properly configured for external control

**Author**: jsecco ® 
**Version**: 1.0.0
**Last Updated**: September 2024
