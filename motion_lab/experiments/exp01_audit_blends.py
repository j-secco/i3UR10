"""
Experiment 01 - audit every production demo's blend radii offline.

Commands NO motion. Answers: which demos contain waypoints the controller
will silently SKIP because their blend spheres overlap (URScript 3.13, movej:
"this move will be skipped ... 'Overlapping Blends'").

Run from the project root:  venv/bin/python motion_lab/experiments/exp01_audit_blends.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(HERE))

import yaml  # noqa: E402

import blend  # noqa: E402


class CaptureController:
    """Stands in for WebSocketController: records what a demo would send."""

    def __init__(self):
        self.rows = None

    def is_connected(self):
        return True

    def move_joint_program_loop(self, waypoints, *a, **k):
        self.rows = [list(r) for r in waypoints]
        return True

    def move_joint_program(self, waypoints, *a, **k):
        return self.move_joint_program_loop(waypoints)

    def move_joint_path(self, path, *a, **k):
        self.rows = [list(r) for r in path]
        return True

    def move_joint(self, *a, **k):
        return True

    def stop_motion(self, *a, **k):
        return True

    def send_command(self, *a, **k):
        return True


def capture(cls, home, cfg):
    """Start a demo against a fake controller and grab the program it emits."""
    ctrl = CaptureController()
    demo = cls(ctrl, home,
               speed_scale=1.0,
               joint_speed=float(cfg["joint_speed"]),
               joint_acceleration=float(cfg["joint_acceleration"]))
    demo.start()
    for _ in range(100):
        if ctrl.rows is not None:
            break
        time.sleep(0.05)
    demo.stop()
    time.sleep(0.2)
    return ctrl.rows


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]

    from control.bow_demo import BowDemo
    from control.industrial_demo import IndustrialDemo
    from control.juggle_demo import JuggleDemo
    from control.pendulum_demo import PendulumDemo
    from control.plunge_demo import PlungeDemo
    from control.reach_demo import ReachDemo
    from control.sorting_demo import SortingDemo
    from control.sprint_demo import SprintDemo
    from control.stacking_demo import StackingDemo
    from control.technical_demo import TechnicalDemo
    from control.wave_demo import WaveDemo

    demos = [BowDemo, IndustrialDemo, JuggleDemo, PendulumDemo, PlungeDemo,
             ReachDemo, SortingDemo, SprintDemo, StackingDemo, TechnicalDemo,
             WaveDemo]

    summary = []
    for cls in demos:
        name = cls.__name__
        try:
            rows = capture(cls, home, cfg["demo"])
        except Exception as exc:
            print(f"\n### {name}: could not capture ({exc})")
            summary.append((name, None, None))
            continue
        if not rows:
            print(f"\n### {name}: emitted no program")
            summary.append((name, None, None))
            continue
        print()
        print(blend.report(rows, closed=True, title=name))
        bad = blend.problems(rows, closed=True)
        summary.append((name, len(bad), len(rows)))

    print("\n\n=== SUMMARY: waypoints the controller would skip ===")
    for name, bad, total in summary:
        if bad is None:
            print(f"  {name:16s} (not analysed)")
        else:
            state = "CLEAN" if bad == 0 else f"{bad}/{total} legs OVERLAP"
            print(f"  {name:16s} {state}")


if __name__ == "__main__":
    main()
