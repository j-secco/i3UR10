"""
Experiment 05 - drive the arm to positions around the cart and check the
model's predicted clearance against what you can see.

MOVES THE ROBOT, deliberately close to an obstacle. Requires --confirm and a
person watching. Nothing here is fast: the point is to stop at each position
and look.

The model claims a clearance in millimetres at every pose. That claim is only
worth what it predicts in the real cell, so this walks the arm around the cart
at a chosen standoff, prints what the model expects before each move, and
waits for you to confirm what you actually see.

Method
------
Poses are found by search, not by inverse kinematics: for each bearing round
the base, J2 and J3 are swept and the pose kept whose closest approach to the
cart lands nearest the requested standoff. Every candidate must clear
self-collision, the measured solids, and the ground, and the interpolated
transit from the previous pose must clear them too -- a safe start and a safe
end do not make a safe path between.

Safety
------
  - very slow moves, and the arm stops dead between positions
  - you press Enter for each one, so nothing moves while you are looking
  - 'q' aborts, returns home, and clears the program off the controller
  - Ctrl-C sends stopj immediately

Usage:
    venv/bin/python motion_lab/experiments/exp05_probe_cart.py             # plan only
    venv/bin/python motion_lab/experiments/exp05_probe_cart.py --confirm
    venv/bin/python motion_lab/experiments/exp05_probe_cart.py --confirm --standoff 0.20
"""

import argparse
import math
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(HERE))

import yaml  # noqa: E402

from control.pose_guard import tcp_xyz, validate_path as self_collision  # noqa: E402
from envelope import Envelope  # noqa: E402
from lab import Lab, LabError  # noqa: E402
from obstacles import ObstacleSet  # noqa: E402

DASHBOARD_PORT = 29999


def dashboard(host, cmd):
    with socket.create_connection((host, DASHBOARD_PORT), timeout=4) as s:
        s.recv(4096)
        s.sendall((cmd + "\n").encode())
        return s.recv(4096).decode().strip()


def find_pose(env, obs, home, bearing_rad, standoff, tol=0.03):
    """Pose approaching the cart at this bearing, standing off by `standoff`.

    Searched in joint space rather than solved by inverse kinematics: this
    stays inside the representation everything else has been validated in,
    and it cannot return an unreachable or elbow-flipped solution.
    """
    best = None
    for d2 in [i * 0.06 for i in range(-6, 26)]:
        for d3 in [i * 0.06 for i in range(-26, 14)]:
            q = list(home)
            q[0] = home[0] + bearing_rad
            q[1] += d2
            q[2] += d3
            w = obs.worst(q)
            if w is None:
                continue
            gap = w[0]
            if gap < standoff - tol:            # too close to the cart
                continue
            if env.contains(q) is not None:     # outside the model
                continue
            if self_collision([q], closed=False) is not None:
                continue
            err = abs(gap - standoff)
            if best is None or err < best[0]:
                best = (err, gap, q, w)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="required: moves the robot")
    ap.add_argument("--standoff", type=float, default=0.15,
                    help="how close to the cart to approach, metres (default 0.15)")
    ap.add_argument("--bearings", type=int, default=8,
                    help="how many positions round the cart (default 8)")
    ap.add_argument("--speed", type=float, default=0.15, help="rad/s (default 0.15)")
    ap.add_argument("--accel", type=float, default=0.4, help="rad/s^2 (default 0.4)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]
    env = Envelope.load()
    obs = ObstacleSet.from_json(env.obstacles)
    if not obs.solids:
        raise SystemExit("no measured solids in the envelope; nothing to probe against")

    print(f"=== probing the cart at {args.standoff * 1000:.0f} mm standoff ===")
    print(f"solids: {', '.join(s.name for s in obs.solids)}")
    # Where the gap IS matters as much as how big it is. On most of these
    # poses the tool is half a metre clear while the elbow or forearm is the
    # part actually close to the cart, and an operator watching the tool would
    # see nothing to check.
    print(f"\n{'#':>2} {'bearing':>8} {'gap':>8} {'to':>6}   closest point of the arm")

    poses = []
    for i in range(args.bearings):
        b = (i / args.bearings) * 2 * math.pi
        found = find_pose(env, obs, home, b, args.standoff)
        if found is None:
            print(f"{i + 1:>2} {math.degrees(b):>7.0f}°  no pose found at this standoff")
            continue
        _, gap, q, w = found
        t = tcp_xyz(q)
        poses.append((i + 1, b, gap, q, w))
        cp = w[2]
        tool_gap = math.dist(cp, t)
        where = "at the tool" if tool_gap < 0.08 else f"{tool_gap * 100:.0f} cm back from the tool"
        print(f"{i + 1:>2} {math.degrees(b):>7.0f}° {gap * 1000:>7.0f}mm {w[1]:>6}   "
              f"({cp[0]:+.3f}, {cp[1]:+.3f}, {cp[2]:+.3f}) — {where}")

    if not poses:
        raise SystemExit("no reachable positions at that standoff; try --standoff 0.25")
    margin = obs.solids[0].margin
    print(f"\n{len(poses)} positions found.")
    print(f"\nReading the numbers: 'gap' is clearance BEYOND the {margin * 1000:.0f} mm safety")
    print(f"margin, and is measured to the arm's surface rather than its centreline. So at")
    print(f"a {args.standoff * 1000:.0f} mm gap you should see roughly "
          f"{(args.standoff + margin) * 1000:.0f} mm of actual air. If a ruler says")
    print(f"{(args.standoff + margin) * 1000:.0f} mm, the model is right; if it says "
          f"{args.standoff * 1000:.0f} mm, the margin is not being applied and I want to know.")

    if not args.confirm:
        print("\nPlan only. Re-run with --confirm to move the robot.")
        return

    lab = Lab()
    try:
        lab.preflight()
    except LabError as exc:
        raise SystemExit(f"not ready: {exc}")

    print("\nEach move is slow and stops dead. Look at the gap, then press Enter for")
    print("the next one. 'q' returns home and stops.\n")
    current = home
    try:
        for idx, b, gap, q, w in poses:
            # A safe start and a safe end do not make a safe path between them.
            leg = [list(current) + [args.speed, args.accel, 0.0],
                   list(q) + [args.speed, args.accel, 0.0]]
            bad = env.validate_path(leg, closed=False)
            if bad is not None:
                print(f"  {idx}: transit refused -> {bad.detail}")
                continue
            try:
                lab.check_waypoints(leg, closed=False)
            except LabError as exc:
                print(f"  {idx}: refused by guard -> {exc}")
                continue

            cp = w[2]
            print(f"  {idx}/{len(poses)}  bearing {math.degrees(b):.0f}°  "
                  f"model predicts {gap * 1000:.0f} mm to the {w[1]}")
            print(f"       look here: ({cp[0]:+.3f}, {cp[1]:+.3f}, {cp[2]:+.3f}) m — "
                  f"{'the tool' if math.dist(cp, tcp_xyz(q)) < 0.08 else 'NOT the tool, further up the arm'}")
            print(f"       expect about {(gap + obs.solids[0].margin) * 1000:.0f} mm of visible air")
            lab._send(lab.oneshot_program(leg, name="lab_probe"))
            time.sleep(0.4)
            deadline = time.time() + 25
            while time.time() < deadline:
                time.sleep(0.25)
                s = lab.dashboard("running")
                if "false" in s.lower():
                    break
            try:
                ans = input("     look at the gap, then Enter to continue ('q' to stop): ")
            except EOFError:
                ans = "q"
            if ans.strip().lower().startswith("q"):
                break
            current = q
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        lab.stop()
        time.sleep(0.3)
        print("\nreturning home...")
        try:
            lab._send(lab.oneshot_program(
                [list(current) + [args.speed, args.accel, 0.0],
                 list(home) + [args.speed, args.accel, 0.0]], name="lab_home"))
            time.sleep(1.0)
            for _ in range(40):
                if "false" in lab.dashboard("running").lower():
                    break
                time.sleep(0.5)
        except Exception as exc:
            print(f"  could not send the return move: {exc}")
        # Leave the controller idle, or the pendant Freedrive button stays dead.
        print("clearing the program off the controller:", dashboard(lab.host, "stop"))


if __name__ == "__main__":
    main()
