"""
Read-only capture of the UR10's current state from the realtime interface.
Commands NO motion. Run from i3UR10 project root:  python read_state.py
"""
import sys, os, time, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from communication.websocket_receiver import WebSocketReceiver

ROBOT_IP = "192.168.10.24"

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 30001
rx = WebSocketReceiver(ROBOT_IP, PORT)
print("connecting on port", PORT)
if not rx.connect():
    print("ERROR: could not connect to realtime interface")
    sys.exit(1)

# Wait for at least one valid position frame.
for _ in range(80):
    if rx.has_valid_position():
        break
    time.sleep(0.1)

time.sleep(0.5)  # let a few frames accumulate

q = rx.get_joint_angles()
tcp = rx.get_tcp_pose()
print("joint_angles_rad  =", [round(v, 6) for v in q])
print("joint_angles_deg  =", [round(math.degrees(v), 2) for v in q])
print("tcp_pose          =", [round(v, 4) for v in tcp])
print("protective_stop   =", rx.is_protective_stopped())
print("emergency_stop    =", rx.is_emergency_stopped())
print("robot_mode        =", rx.get_robot_mode())
print("safety_mode       =", rx.get_safety_mode())
print("valid_position    =", rx.has_valid_position())

rx.disconnect()
