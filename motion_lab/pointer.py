"""
Point at a spot in the cell and send the tool there.

WHY
---
Every earlier tool in motion_lab specified poses in joint space, so none of
them could be checked against reality: if the arm ends up somewhere odd you
cannot tell whether the model is wrong or the request was. exp05 made that
concrete -- it optimised the clearance of the FOREARM and left the tool
unconstrained, so the tool wandered between 0.39 m and 0.88 m from the base
while every reported number was true.

This closes the loop. You click a point, the server solves inverse kinematics
for it, runs the same guards as everything else, moves, and then compares the
point you asked for against the position the ROBOT reports having reached.
That last number is the honest one: it is measured, not modelled, and it is
what tells you whether the model is accurate.

DESIGN
------
All kinematics stay in Python. The browser never computes a joint angle or a
link position; it asks for them and draws them. One forward model, already
verified against the robot to about 5 mm, with no chance of a second
implementation in JavaScript drifting away from it.

SAFETY
------
  - clicking only PLANS. Nothing moves until you press Go.
  - without --confirm the server will plan but refuse to move at all.
  - every pose clears self-collision, the measured solids and the envelope,
    and so does the interpolated path taken to reach it.
  - solutions are unwound to the turn each joint is already in, and refused
    outright past +/-350 deg, because a joint driven past +/-360 puts the
    robot into a recovery mode that only the pendant can clear.
  - Stop is always live, and sends stopj plus a Dashboard stop.

This is NOT a safety function. It is a Python pre-check on the control PC.
The robot's own safety configuration is the thing that protects the cell.

Usage:
    venv/bin/python motion_lab/pointer.py                 # plan only, no motion
    venv/bin/python motion_lab/pointer.py --confirm       # motion enabled

then, from your own machine:
    ssh -L 8765:localhost:8765 ur10-wifi
    open http://localhost:8765

Author: jsecco (R)
"""

import argparse
import json
import math
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import yaml  # noqa: E402

from control import pose_guard  # noqa: E402
from control.ur_kinematics import joint_distance, solve_position  # noqa: E402
from envelope import Envelope  # noqa: E402
from lab import Lab, LabError  # noqa: E402
from obstacles import ObstacleSet, link_radii  # noqa: E402
from telemetry import read_once  # noqa: E402

# A joint past +/-360 deg leaves the robot in a recovery mode that survives a
# power cycle and can only be cleared at the pendant. Refuse well short of it.
JOINT_LIMIT_RAD = math.radians(350.0)

DEFAULT_SPEED = 0.25
DEFAULT_ACCEL = 0.6


class Pointer:
    def __init__(self, host: str, allow_motion: bool,
                 speed: float, accel: float):
        self.lab = Lab(host)
        self.host = host
        self.allow_motion = allow_motion
        self.speed = speed
        self.accel = accel
        self.env = Envelope.load(os.path.join(HERE, "workspace_envelope.json"))
        self.obs = ObstacleSet.from_json(self.env.obstacles)
        cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
        self.config_home = list(cfg["demo"]["saved_home_joints"])
        # Where "Home" sends the arm. Defaults to the configured home but is
        # session-only: the production config is never written from here,
        # because demo choreographies apply fixed offsets to it and a changed
        # home has silently pushed them into self-collision before.
        self.home = list(self.config_home)
        self.lock = threading.Lock()
        self.moving = False
        self.last_move = None
        self.last_error = None

    # ---------------------------------------------------------------- state

    def state(self) -> dict:
        s = read_once(self.host)
        if s is None:
            return {"online": False, "moving": self.moving,
                    "last_move": self.last_move, "error": self.last_error}
        q = list(s.q)
        return {
            "online": True,
            "joints": q,
            "joints_deg": [math.degrees(a) for a in q],
            "origins": [p.tolist() for p in pose_guard.joint_origins(q)],
            "tcp": list(s.tcp)[:3],
            "tcp_model": pose_guard.tcp_xyz(q),
            "speed": s.joint_speed_max,
            "robot_mode": s.robot_mode,
            "safety_mode": s.safety_mode,
            "normal": s.safety_mode == 1.0 and s.robot_mode == 7.0,
            "moving": self.moving,
            "clearance": self._clearance(q),
            "last_move": self.last_move,
            "error": self.last_error,
            "motion_enabled": self.allow_motion,
        }

    def _clearance(self, q: Sequence[float]) -> Optional[dict]:
        w = self.obs.worst(q)
        if w is None:
            return None
        return {"m": w[0], "solid": w[1], "point": list(w[2])}

    def scene(self) -> dict:
        return {
            "solids": self.obs.to_json(),
            "link_radii": link_radii(),
            "home": self.home,
            "home_origins": [p.tolist() for p in pose_guard.joint_origins(self.home)],
            "reach": 1.30,
            "base_structure_r": 0.15,
            "motion_enabled": self.allow_motion,
        }

    # ----------------------------------------------------------------- plan

    def plan(self, x: float, y: float, z: float,
             reference: Optional[Sequence[float]] = None) -> dict:
        """Solve for a clicked point and run every guard against the result."""
        if reference is None:
            s = read_once(self.host)
            if s is None:
                return {"ok": False, "reason": "no telemetry from the robot"}
            reference = list(s.q)

        sols = solve_position(x, y, z, reference)
        if not sols:
            return {"ok": False, "reason":
                    "out of reach: no arm configuration puts the tool there",
                    "tried": 0}

        rejected = []
        for sol in sols:
            why = self._why_not(sol, reference)
            if why is None:
                leg = [list(reference) + [self.speed, self.accel, 0.0],
                       list(sol) + [self.speed, self.accel, 0.0]]
                w = self.obs.worst(sol)
                return {
                    "ok": True,
                    "joints": sol,
                    "joints_deg": [math.degrees(a) for a in sol],
                    "origins": [p.tolist() for p in pose_guard.joint_origins(sol)],
                    "tcp": pose_guard.tcp_xyz(sol),
                    "target": [x, y, z],
                    "travel_rad": joint_distance(sol, reference),
                    "clearance": ({"m": w[0], "solid": w[1], "point": list(w[2])}
                                  if w else None),
                    "considered": len(sols),
                    "rejected": rejected[:6],
                }
            rejected.append(why)

        return {"ok": False, "considered": len(sols), "rejected": rejected[:6],
                "reason": f"all {len(sols)} arm configurations for that point "
                          f"were refused"}

    def _why_not(self, sol: Sequence[float],
                 reference: Sequence[float]) -> Optional[str]:
        """None if this solution is usable, else why it is not."""
        for i, a in enumerate(sol):
            if abs(a) > JOINT_LIMIT_RAD:
                return f"J{i + 1} would wind to {math.degrees(a):.0f} deg"
        if pose_guard.validate_path([sol], closed=False) is not None:
            return "arm collides with itself"
        v = self.env.contains(sol)
        if v is not None:
            return v.describe() if hasattr(v, "describe") else str(v)
        leg = [list(reference) + [self.speed, self.accel, 0.0],
               list(sol) + [self.speed, self.accel, 0.0]]
        v = self.env.validate_path(leg, closed=False)
        if v is not None:
            return f"path there is blocked: {v.detail}"
        if pose_guard.validate_path([list(reference), list(sol)],
                                    closed=False) is not None:
            return "arm would collide with itself on the way"
        try:
            self.lab.check_waypoints(leg, closed=False)
        except LabError as exc:
            return str(exc)
        return None

    # ------------------------------------------------------------------ go

    def go(self, x: float, y: float, z: float) -> dict:
        if not self.allow_motion:
            return {"ok": False, "reason":
                    "motion is disabled: restart the server with --confirm"}
        with self.lock:
            if self.moving:
                return {"ok": False, "reason": "already moving"}
            s = read_once(self.host)
            if s is None:
                return {"ok": False, "reason": "no telemetry from the robot"}
            if s.safety_mode != 1.0 or s.robot_mode != 7.0:
                return {"ok": False, "reason":
                        f"robot not ready (mode {s.robot_mode:.0f}, "
                        f"safety {s.safety_mode:.0f})"}
            if s.joint_speed_max > 0.01:
                return {"ok": False, "reason": "robot is already moving"}
            start = list(s.q)
            p = self.plan(x, y, z, reference=start)
            if not p.get("ok"):
                return p
            self.moving = True
        threading.Thread(target=self._run, args=(start, p), daemon=True).start()
        return {"ok": True, "started": True, "plan": p}

    def _run(self, start: Sequence[float], p: dict) -> None:
        """Move, then report what the ROBOT says it reached."""
        try:
            leg = [list(start) + [self.speed, self.accel, 0.0],
                   list(p["joints"]) + [self.speed, self.accel, 0.0]]
            self.lab._send(self.lab.oneshot_program(leg, name="lab_point"))
            time.sleep(0.5)
            # Done when the controller says the program has ended AND the arm
            # has actually stopped. Waiting on joint error alone would hang
            # forever on a move that stops short, which is precisely the case
            # worth reporting rather than hiding behind a timeout.
            deadline = time.time() + 60
            while time.time() < deadline:
                time.sleep(0.2)
                s = read_once(self.host)
                if s is not None and s.safety_mode != 1.0:
                    self.last_error = "protective stop during the move"
                    break
                if "false" in self.lab.dashboard("running").lower() and \
                        s is not None and s.joint_speed_max < 0.01:
                    break
            else:
                self.last_error = "move did not finish within 60 s"
            time.sleep(0.3)
            s = read_once(self.host)
            if s is not None:
                reached = list(s.tcp)[:3]
                target = p["target"]
                self.last_move = {
                    "target": target,
                    "reached": reached,
                    "error_mm": math.dist(reached, target) * 1000.0,
                    "commanded": p["tcp"],
                    "joint_error_deg": max(
                        abs(math.degrees(a - b))
                        for a, b in zip(list(s.q), p["joints"])),
                }
                self.last_error = None
        except Exception as exc:                      # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.moving = False

    def go_home(self) -> dict:
        if not self.allow_motion:
            return {"ok": False, "reason": "motion is disabled"}
        t = pose_guard.tcp_xyz(self.home)
        with self.lock:
            if self.moving:
                return {"ok": False, "reason": "already moving"}
            s = read_once(self.host)
            if s is None:
                return {"ok": False, "reason": "no telemetry"}
            start = list(s.q)
            leg = [list(start) + [self.speed, self.accel, 0.0],
                   list(self.home) + [self.speed, self.accel, 0.0]]
            if self.env.validate_path(leg, closed=False) is not None or \
                    pose_guard.validate_path([start, list(self.home)],
                                             closed=False) is not None:
                return {"ok": False, "reason": "path home is not clear from here"}
            self.moving = True
        threading.Thread(
            target=self._run, args=(start, {"joints": list(self.home),
                                            "target": t, "tcp": t}),
            daemon=True).start()
        return {"ok": True, "started": True}

    def set_home(self) -> dict:
        """Adopt the current pose as this session's home. Not written to the
        production config: demos apply fixed offsets to the configured home."""
        s = read_once(self.host)
        if s is None:
            return {"ok": False, "reason": "no telemetry"}
        self.home = list(s.q)
        return {"ok": True, "home_deg": [math.degrees(a) for a in self.home],
                "note": "session only, config/robot_config.yaml unchanged"}

    def stop(self) -> dict:
        try:
            self.lab.stop()
            with socket.create_connection((self.host, 29999), timeout=4) as s:
                s.recv(4096)
                s.sendall(b"stop\n")
                s.recv(4096)
            self.moving = False
            return {"ok": True}
        except Exception as exc:                      # noqa: BLE001
            return {"ok": False, "reason": str(exc)}


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    pointer: Pointer = None       # set on the class before serving

    def log_message(self, *a):    # keep the console for real events
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            # Read fresh so the page can be edited without a restart.
            body = open(os.path.join(HERE, "pointer.html")).read().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/state":
            self._json(self.pointer.state())
        elif self.path == "/scene":
            self._json(self.pointer.scene())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}")
        p = self.pointer
        if self.path == "/plan":
            self._json(p.plan(data["x"], data["y"], data["z"]))
        elif self.path == "/go":
            self._json(p.go(data["x"], data["y"], data["z"]))
        elif self.path == "/home":
            self._json(p.go_home())
        elif self.path == "/sethome":
            self._json(p.set_home())
        elif self.path == "/stop":
            self._json(p.stop())
        else:
            self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="allow the robot to move (otherwise plan only)")
    ap.add_argument("--robot", default="192.168.10.24")
    ap.add_argument("--host", default="127.0.0.1",
                    help="interface to serve on (default loopback; reach it "
                         "with ssh -L 8765:localhost:8765)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    ap.add_argument("--accel", type=float, default=DEFAULT_ACCEL)
    args = ap.parse_args()

    pointer = Pointer(args.robot, args.confirm, args.speed, args.accel)
    Handler.pointer = pointer
    open(os.path.join(HERE, "pointer.html")).close()   # fail now, not on first GET

    print(f"cell model: {', '.join(s.name for s in pointer.obs.solids) or 'none'}")
    print(f"robot     : {args.robot}")
    print(f"motion    : {'ENABLED' if args.confirm else 'disabled (plan only)'}")
    if args.confirm:
        print(f"            {args.speed} rad/s, {args.accel} rad/s^2")
    print(f"\n  http://localhost:{args.port}")
    if args.host == "127.0.0.1":
        print("  from your own machine:  ssh -L "
              f"{args.port}:localhost:{args.port} ur10-wifi")
    print("\nCtrl-C to stop serving.\n")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
        if args.confirm:
            pointer.stop()


if __name__ == "__main__":
    main()
