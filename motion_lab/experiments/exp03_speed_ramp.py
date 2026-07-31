"""
Experiment 03 - find the real speed ceiling by measuring, not guessing.

MOVES THE ROBOT, progressively faster. Requires --confirm and a person
watching the cell.

Method: run the repaired choreography at increasing speed multipliers and
compare COMMANDED peak joint speed against ACHIEVED peak joint speed from the
125 Hz telemetry. While the two track, there is headroom. When achieved stops
following commanded, something is clamping us -- the safety limiter, the
torque limiter, or the joints themselves -- and that is the ceiling.

This distinguishes the three reasons the arm might not go faster, which
otherwise look identical from across the room:
  - we are not asking for more (software caps)
  - we are asking and being refused (safety/torque scaling)
  - we are asking and physically cannot (joint limits)

Stops early and automatically on: safety leaving NORMAL, a stall appearing,
or achieved speed failing to track commanded.

Usage:
    venv/bin/python motion_lab/experiments/exp03_speed_ramp.py --confirm
    venv/bin/python motion_lab/experiments/exp03_speed_ramp.py --confirm --demo wave
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(HERE))

import yaml  # noqa: E402

import blend  # noqa: E402
from exp02_blend_ab import DEMOS, capture  # noqa: E402
from lab import LAB_MAX_ACCEL_RAD_S2, LAB_MAX_SPEED_RAD_S, Lab, LabError  # noqa: E402

# Below this ratio of achieved-to-commanded we are being clamped, not driven.
TRACKING_THRESHOLD = 0.90


def scaled(path, v_factor, a_factor):
    """Scale speed and acceleration independently, leaving geometry alone."""
    out = []
    for wp in path:
        wp = list(wp)
        wp[6] = min(LAB_MAX_SPEED_RAD_S, wp[6] * v_factor)
        wp[7] = min(LAB_MAX_ACCEL_RAD_S2, wp[7] * a_factor)
        out.append(wp)
    return out


def reachable_speed(path, closed=True):
    """Fastest speed the leading joint can actually reach on this path.

    A joint accelerating at `a` over a leg of `d` radians tops out at
    sqrt(a*d) before it must brake for the corner, so commanding more than
    that is asking for a speed the geometry cannot deliver. This is why
    raising the speed cap alone changed nothing: the binding constraint was
    acceleration, not velocity.
    """
    best = 0.0
    n = len(path)
    count = n if closed else n - 1
    for i in range(count):
        j = (i + 1) % n
        d = max(abs(a - b) for a, b in zip(path[i][:6], path[j][:6]))
        best = max(best, (path[i][7] * d) ** 0.5)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="required: moves the robot")
    ap.add_argument("--demo", default="sprint", choices=sorted(DEMOS))
    ap.add_argument("--seconds", type=float, default=10.0,
                    help="run time per speed step")
    ap.add_argument("--steps", default="1.0,1.25,1.5,1.75",
                    help="comma-separated multipliers")
    ap.add_argument("--mode", default="accel", choices=("accel", "speed", "both"),
                    help="which axis to ramp. Default 'accel': on short legs the "
                         "arm is acceleration-limited, so speed alone changes nothing.")
    ap.add_argument("--settle", type=float, default=3.0)
    args = ap.parse_args()

    factors = [float(s) for s in args.steps.split(",")]
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]

    base = blend.repair(capture(args.demo, home, cfg["demo"]), closed=True)
    if blend.problems(base, closed=True):
        raise SystemExit("repaired path still violates the blend rule; fix that first")

    def factors_for(f):
        return (f, f) if args.mode == "both" else \
               (f, 1.0) if args.mode == "speed" else (1.0, f)

    print(f"=== {args.demo}: ramping {args.mode} over {factors} ===")
    print(f"{'factor':>7} {'cmd v':>7} {'accel':>7} {'reachable':>10}  limited by")
    for f in factors:
        vf, af = factors_for(f)
        p = scaled(base, vf, af)
        cmd_v = max(w[6] for w in p)
        reach = reachable_speed(p)
        limiter = "acceleration" if reach < cmd_v else "commanded speed"
        print(f"  x{f:<5.2f} {cmd_v:>6.2f} {max(w[7] for w in p):>7.2f} "
              f"{reach:>10.2f}  {limiter}")
    print("\n  'reachable' is sqrt(accel x leg) for the longest leg: the fastest the "
          "\n  leading joint can get before it must brake. Commanding above it is wasted.")
    print(f"  UR10 joint ceilings: 2.09 rad/s base/shoulder, 3.14 rad/s elbow/wrists.")

    if not args.confirm:
        print("\nAnalysis only. Re-run with --confirm to measure on the robot.")
        return

    lab = Lab()
    try:
        lab.preflight()
    except LabError as exc:
        raise SystemExit(f"not ready: {exc}")

    print(f"\n{'factor':>7} {'cmd rad/s':>10} {'got rad/s':>10} {'track':>7} "
          f"{'TCP m/s':>8} {'stalls':>7}")
    rows = []
    ceiling = None

    for f in factors:
        vf, af = factors_for(f)
        path = scaled(base, vf, af)
        # Compare against what the geometry allows, not what we typed: if the
        # commanded speed is unreachable the tracking ratio is meaningless.
        commanded = min(max(w[6] for w in path), reachable_speed(path))
        try:
            lab.check_waypoints(path, closed=True)
        except LabError as exc:
            print(f"  x{f}: refused by guard -> {exc}")
            break

        trace = lab.run_program(lab.loop_program(path), seconds=args.seconds,
                                confirm=True, label=f"{args.demo} x{f}")
        achieved = trace.peak_joint_speed()
        ratio = achieved / commanded if commanded else 0.0
        stalls = len(trace.stalls())
        print(f"{f:>7.2f} {commanded:>10.2f} {achieved:>10.2f} {ratio:>6.0%} "
              f"{trace.peak_tcp_speed():>8.3f} {stalls:>7}")
        rows.append((f, commanded, achieved, ratio, trace.peak_tcp_speed(), stalls))

        if trace.faulted():
            print("  -> safety left NORMAL; stopping the ramp here")
            ceiling = f
            break
        if ratio < TRACKING_THRESHOLD:
            print(f"  -> achieved only {ratio:.0%} of commanded; something is clamping us")
            ceiling = f
            break
        if stalls:
            print("  -> stalls appeared at this speed; stopping")
            ceiling = f
            break
        time.sleep(args.settle)

    print("\n=== VERDICT ===")
    if not rows:
        print("  no runs completed")
        return
    clean = [r for r in rows if r[3] >= TRACKING_THRESHOLD and r[5] == 0]
    if clean:
        best = clean[-1]
        print(f"  highest clean multiplier: x{best[0]:.2f} "
              f"-> {best[2]:.2f} rad/s achieved ({best[2] * 57.29578:.0f} deg/s), "
              f"TCP {best[4]:.3f} m/s")
    if ceiling is None:
        print(f"  never hit a ceiling up to x{rows[-1][0]:.2f}; there is more headroom, "
              f"extend --steps to keep going")
    else:
        print(f"  ceiling at x{ceiling:.2f}. Below that the arm tracks what it is told.")
    print("  TCP figures are worth comparing against the pendant Speed limit: if peak "
          "TCP sits just under it, that limit is the binding constraint.")


if __name__ == "__main__":
    main()
