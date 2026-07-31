"""
Experiment 04 - measure the real speed ceiling of EACH joint on this robot.

MOVES THE ROBOT. Requires --confirm and a person watching the cell.

Why: Sprint is base-led, so everything exp03 measured was J1, which UR rates
at 120 deg/s. The elbow and wrists are rated 180 deg/s -- 50% more that no
demo has ever used. This isolates one joint at a time and ramps it until
achieved speed stops tracking commanded, giving a per-joint ceiling measured
on THIS arm rather than taken from a datasheet.

The choreography is deliberately trivial: from the saved home, swing one
joint to -amplitude, to +amplitude, and back, looping. Nothing else moves.

SAFETY -- read before running
-----------------------------
pose_guard checks the arm against ITSELF. It does not know about your table,
fixtures, or the floor. A large J2 (shoulder) or J3 (elbow) swing is exactly
the motion that finds them. This experiment therefore also enforces a TCP
height floor, and defaults to conservative amplitudes.

Order of testing, easiest to riskiest:
    wrists (J4 J5 J6) - the TCP barely translates, low risk, and these are
                        the joints rated highest, so most of the unexplored
                        headroom lives here
    elbow  (J3)       - moderate arm motion
    base   (J1)       - already characterised by exp03
    shoulder (J2)     - largest swept volume, test last and with the smallest
                        amplitude you can still reach speed with

Usage:
    venv/bin/python motion_lab/experiments/exp04_joint_ceilings.py            # analysis
    venv/bin/python motion_lab/experiments/exp04_joint_ceilings.py --confirm --joints 4,5,6
    venv/bin/python motion_lab/experiments/exp04_joint_ceilings.py --confirm --joints 3 --amplitude 0.6
"""

import argparse
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(HERE))

import yaml  # noqa: E402

from control.pose_guard import tcp_xyz  # noqa: E402
from lab import LAB_MAX_ACCEL_RAD_S2, LAB_MAX_SPEED_RAD_S, Lab, LabError  # noqa: E402

# UR10 published joint maxima (rad/s): base and shoulder 120 deg/s,
# elbow and all three wrists 180 deg/s.
RATED = {1: 2.09, 2: 2.09, 3: 3.14, 4: 3.14, 5: 3.14, 6: 3.14}
NAMES = {1: "base", 2: "shoulder", 3: "elbow", 4: "wrist1", 5: "wrist2", 6: "wrist3"}

TRACKING_THRESHOLD = 0.90
DEFAULT_TCP_FLOOR_M = 0.20   # refuse any pose with the TCP below this height


def swing(home, joint, amplitude, speed, accel, blend):
    """Waypoints for a single-joint oscillation about home."""
    def pose(delta):
        q = list(home)
        q[joint - 1] += delta
        return q
    return [pose(-amplitude) + [speed, accel, blend],
            pose(+amplitude) + [speed, accel, blend]]


def lowest_tcp(path):
    return min(tcp_xyz(wp[:6])[2] for wp in path)


def reachable(amplitude, accel):
    """Peak the joint can reach over one half-swing before it must brake.

    The leg is 2*amplitude, but the joint must also stop at the far end, so
    the usable distance for acceleration is half the leg.
    """
    return math.sqrt(accel * amplitude)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="required: moves the robot")
    ap.add_argument("--joints", default="4,5,6",
                    help="comma-separated joint numbers 1-6 (default: the wrists)")
    ap.add_argument("--amplitude", type=float, default=0.7,
                    help="radians either side of home (default 0.7)")
    ap.add_argument("--steps", default="1.0,1.4,1.8,2.2",
                    help="speed/accel multipliers applied to a conservative base")
    # Top of the default ladder is 1.5 x 2.2 = 3.3 rad/s, just above the
    # 3.14 rad/s rating of the elbow and wrists, so the ladder itself is
    # never the thing that limits the result.
    ap.add_argument("--base-speed", type=float, default=1.5)
    ap.add_argument("--base-accel", type=float, default=2.5)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--tcp-floor", type=float, default=DEFAULT_TCP_FLOOR_M,
                    help="refuse poses whose TCP sits below this height (m)")
    args = ap.parse_args()

    joints = [int(j) for j in args.joints.split(",")]
    factors = [float(s) for s in args.steps.split(",")]
    for j in joints:
        if j not in RATED:
            raise SystemExit(f"joint {j} out of range 1-6")

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]

    top_a = min(LAB_MAX_ACCEL_RAD_S2, args.base_accel * max(factors))
    top_v = min(LAB_MAX_SPEED_RAD_S, args.base_speed * max(factors))

    print(f"=== per-joint ceilings, amplitude +/-{args.amplitude} rad about home ===")
    print(f"top of ladder: v {top_v:.2f} rad/s, a {top_a:.2f} rad/s^2 "
          f"(lab caps {LAB_MAX_SPEED_RAD_S}/{LAB_MAX_ACCEL_RAD_S2})")
    print(f"\n{'joint':>10} {'rated':>7} {'reachable':>10} {'need amp':>9} "
          f"{'TCP low':>8}  verdict")
    for j in joints:
        reach = reachable(args.amplitude, top_a)
        # amplitude that would let this joint hit its rating at top_a
        need_amp = RATED[j] ** 2 / top_a
        probe = swing(home, j, args.amplitude, top_v, top_a, 0.0)
        floor = lowest_tcp(probe)
        if top_v < RATED[j] * 0.95:
            verdict = f"speed ladder tops out below rating (raise --base-speed)"
        elif reach < RATED[j] * 0.95:
            verdict = f"swing too short (need +/-{need_amp:.2f} rad)"
        else:
            verdict = "can reach rating"
        print(f"{NAMES[j]:>10} {RATED[j]:>7.2f} {reach:>10.2f} {need_amp:>9.2f} "
              f"{floor:>8.3f}  {verdict}")

    if not args.confirm:
        print("\nAnalysis only. Re-run with --confirm to measure on the robot.")
        print("'need amp' is the swing required to reach the rating at the top of "
              "the\nladder. 'TCP low' is the lowest the tool would sit -- check it "
              "against\nyour table before raising the amplitude.")
        return

    lab = Lab()
    try:
        lab.preflight()
    except LabError as exc:
        raise SystemExit(f"not ready: {exc}")

    results = {}
    for j in joints:
        print(f"\n=== J{j} ({NAMES[j]}), rated {RATED[j]:.2f} rad/s "
              f"({RATED[j] * 57.29578:.0f} deg/s) ===")
        print(f"{'factor':>7} {'cmd':>7} {'got':>7} {'track':>7} {'% rated':>8} {'stalls':>7}")
        best = 0.0
        for f in factors:
            speed = min(LAB_MAX_SPEED_RAD_S, args.base_speed * f)
            accel = min(LAB_MAX_ACCEL_RAD_S2, args.base_accel * f)
            path = swing(home, j, args.amplitude, speed, accel, blend=0.0)

            floor = lowest_tcp(path)
            if floor < args.tcp_floor:
                print(f"  refused: TCP would drop to {floor:.3f} m, below the "
                      f"{args.tcp_floor:.2f} m floor. Lower --amplitude.")
                break
            try:
                lab.check_waypoints(path, closed=True)
            except LabError as exc:
                print(f"  refused by guard: {exc}")
                break

            commanded = min(speed, reachable(args.amplitude, accel))
            trace = lab.run_program(lab.loop_program(path), seconds=args.seconds,
                                    confirm=True, label=f"J{j} x{f}")
            got = max(abs(s.qd[j - 1]) for s in trace.samples) if trace.samples else 0.0
            ratio = got / commanded if commanded else 0.0
            print(f"{f:>7.2f} {commanded:>7.2f} {got:>7.2f} {ratio:>6.0%} "
                  f"{got / RATED[j]:>7.0%} {len(trace.stalls()):>7}")
            best = max(best, got)

            if trace.faulted():
                print("  -> safety left NORMAL; stopping this joint")
                break
            if ratio < TRACKING_THRESHOLD:
                print("  -> stopped tracking; ceiling found")
                break
            time.sleep(args.settle)
        results[j] = best

    print("\n=== PER-JOINT CEILINGS MEASURED ===")
    print(f"{'joint':>10} {'measured':>9} {'rated':>7} {'of rated':>9}")
    for j, got in results.items():
        print(f"{NAMES[j]:>10} {got:>9.2f} {RATED[j]:>7.2f} {got / RATED[j]:>8.0%}")
    print("\nA joint well under its rating usually means the swing was too short "
          "to\nreach speed, not that the joint is weak. Check 'reachable' above "
          "before\nconcluding anything about the hardware.")


if __name__ == "__main__":
    main()
