"""
Experiment 02 - does fixing the blend radii actually make the motion smooth?

MOVES THE ROBOT. Requires --confirm and a person watching the cell.

Method: take the program a demo really emits, run it as-is, then run the same
choreography with only the corner geometry repaired (degenerate waypoints
dropped, blend radii reduced to satisfy r[i] + r[i+1] <= tcp_leg_length).
Speeds and accelerations are identical between the two runs, so any
difference is attributable to blending alone.

Measured, not judged by ear:
  - mid-motion stalls: intervals where every joint is below 0.02 rad/s while
    the choreography is still running. A skipped waypoint or a program
    boundary shows up here.
  - peak joint speed and peak TCP speed actually achieved.
  - whether safety stayed NORMAL.

Usage from the project root:
    venv/bin/python motion_lab/experiments/exp02_blend_ab.py --confirm
    venv/bin/python motion_lab/experiments/exp02_blend_ab.py --confirm --demo wave
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
from lab import Lab, LabError  # noqa: E402

DEMOS = {
    "sprint": ("control.sprint_demo", "SprintDemo"),
    "wave": ("control.wave_demo", "WaveDemo"),
    "bow": ("control.bow_demo", "BowDemo"),
    "plunge": ("control.plunge_demo", "PlungeDemo"),
    "pendulum": ("control.pendulum_demo", "PendulumDemo"),
    "industrial": ("control.industrial_demo", "IndustrialDemo"),
}


class CaptureController:
    def __init__(self):
        self.rows = None

    def is_connected(self):
        return True

    def move_joint_program_loop(self, waypoints, *a, **k):
        self.rows = [list(r) for r in waypoints]
        return True

    move_joint_program = move_joint_program_loop

    def move_joint_path(self, path, *a, **k):
        self.rows = [list(r) for r in path]
        return True

    def move_joint(self, *a, **k):
        return True

    def stop_motion(self, *a, **k):
        return True

    def send_command(self, *a, **k):
        return True


def capture(demo_key, home, cfg):
    import importlib
    mod_path, cls_name = DEMOS[demo_key]
    cls = getattr(importlib.import_module(mod_path), cls_name)
    ctrl = CaptureController()
    demo = cls(ctrl, home, speed_scale=1.0,
               joint_speed=float(cfg["joint_speed"]),
               joint_acceleration=float(cfg["joint_acceleration"]))
    demo.start()
    for _ in range(100):
        if ctrl.rows is not None:
            break
        time.sleep(0.05)
    demo.stop()
    time.sleep(0.2)
    if not ctrl.rows:
        raise SystemExit(f"{demo_key}: captured no program")
    return ctrl.rows


def summarise(label, trace):
    print(f"\n--- {label} ---")
    print(trace.summary())
    return {
        "stalls": len(trace.stalls()),
        "stall_time": sum(d for _, _, d in trace.stalls()),
        "peak_joint": trace.peak_joint_speed(),
        "peak_tcp": trace.peak_tcp_speed(),
        "faulted": trace.faulted(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="required: this moves the robot")
    ap.add_argument("--demo", default="sprint", choices=sorted(DEMOS))
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--settle", type=float, default=4.0,
                    help="pause between the two runs")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]

    original = capture(args.demo, home, cfg["demo"])
    repaired = blend.repair(original, closed=True)

    print(f"=== {args.demo}: {len(original)} waypoints -> {len(repaired)} after dedupe ===")
    print("\nBEFORE:")
    print(blend.report(original, closed=True))
    print("\nAFTER:")
    print(blend.report(repaired, closed=True))

    speeds_before = [(round(w[6], 3), round(w[7], 3)) for w in original]
    speeds_after = [(round(w[6], 3), round(w[7], 3)) for w in repaired]
    print(f"\nspeed/accel unchanged for retained waypoints: "
          f"{set(speeds_after).issubset(set(speeds_before))}")

    if not args.confirm:
        print("\nAnalysis only. Re-run with --confirm to measure on the robot.")
        return

    lab = Lab()
    try:
        lab.preflight()
    except LabError as exc:
        raise SystemExit(f"not ready: {exc}")

    results = {}
    for label, path in (("BEFORE (as shipped)", original), ("AFTER (repaired)", repaired)):
        try:
            lab.check_waypoints(path, closed=True)
        except LabError as exc:
            print(f"\n{label}: refused by guard -> {exc}")
            continue
        program = lab.loop_program(path)
        trace = lab.run_program(program, seconds=args.seconds,
                                confirm=True, label=label)
        results[label] = summarise(label, trace)
        time.sleep(args.settle)

    if len(results) == 2:
        a, b = results["BEFORE (as shipped)"], results["AFTER (repaired)"]
        print("\n=== VERDICT ===")
        print(f"  stalls        {a['stalls']:>3}  ->{b['stalls']:>4}")
        print(f"  stalled time  {a['stall_time']:>6.2f}s ->{b['stall_time']:>6.2f}s")
        print(f"  peak joint    {a['peak_joint']:>6.2f} ->{b['peak_joint']:>6.2f} rad/s")
        print(f"  peak TCP      {a['peak_tcp']:>6.3f} ->{b['peak_tcp']:>6.3f} m/s")
        if b["stalls"] < a["stalls"] or b["stall_time"] < a["stall_time"] * 0.5:
            print("  -> blend repair improved continuity")
        elif b["stalls"] == a["stalls"] == 0:
            print("  -> both continuous; blending was not the limiting factor here")
        else:
            print("  -> no clear improvement; investigate before promoting to src/")


if __name__ == "__main__":
    main()
