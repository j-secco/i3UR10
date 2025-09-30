# UR10 Movement Modes Guide

## 🎯 **Cartesian Mode**

**What it controls:** Tool position and orientation in 3D space

### Coordinates:
- **X**: Left/Right movement (meters)
- **Y**: Forward/Backward movement (meters) 
- **Z**: Up/Down movement (meters)
- **Rx**: Roll rotation around X-axis (radians/degrees)
- **Ry**: Pitch rotation around Y-axis (radians/degrees)
- **Rz**: Yaw rotation around Z-axis (radians/degrees)

### Use Cases:
- ✅ Following straight-line paths
- ✅ Precise positioning tasks
- ✅ Pick and place operations
- ✅ Surface following

### Behavior:
- Tool moves in **straight lines** through space
- Robot automatically calculates joint movements needed
- May not be possible if target is out of reach or causes joint limits

---

## 🦾 **Joint Mode**

**What it controls:** Individual robot joint angles directly

### Coordinates:
- **J1**: Base rotation (shoulder pan)
- **J2**: Shoulder lift  
- **J3**: Elbow movement
- **J4**: Wrist 1 rotation
- **J5**: Wrist 2 rotation
- **J6**: Wrist 3 rotation (tool flange)

### Use Cases:
- ✅ Getting around obstacles
- ✅ Reaching specific joint configurations
- ✅ Moving when Cartesian path is blocked
- ✅ Teaching specific poses

### Behavior:
- Each joint moves **independently**
- Tool follows curved/arc paths
- More flexible for avoiding workspace limitations
- Direct control over robot posture

---

## 📊 **Live Position Display**

The TCP Position and Joint Angles now show **real-time values** that update as the robot moves:

- **TCP Position**: Current tool location in millimeters (X,Y,Z) and degrees (Rx,Ry,Rz)
- **Joint Angles**: Current joint positions in degrees
- **Updates**: Refreshes 10 times per second when connected

---

## 🔄 **When to Use Each Mode**

| Task | Recommended Mode | Why |
|------|------------------|-----|
| Moving in straight line | Cartesian | Direct path control |
| Precise positioning | Cartesian | Exact spatial control |
| Around obstacles | Joint | More flexibility |
| Teaching positions | Joint | Direct joint access |
| Following surfaces | Cartesian | Maintains orientation |
| Complex rotations | Joint | Individual joint control |

**Author**: jsecco ®
**Updated**: September 2024
