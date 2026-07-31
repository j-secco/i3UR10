"""
Pull every production demo's program out without a robot, and report it.

Demos build their choreography and hand it to a controller. Swapping in a
controller that only records what it was given lets the whole catalogue be
analysed offline: no robot, no motion, no risk, and the exact waypoints the
real controller would have received.

    venv/bin/python motion_lab/demos.py           # speed and safety report
    venv/bin/python motion_lab/demos.py --blends  # blend legality as well

Author: jsecco (R)
"""

import os
import sys
import time
from typing import Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import yaml  # noqa: E402

import blend  # noqa: E402
import choreography  # noqa: E402
from envelope import Envelope  # noqa: E402
from obstacles import ObstacleSet  # noqa: E402


class CaptureController:
    """Stands in for WebSocketController: records what a demo would send."""

    def __init__(self):
        self.rows: Optional[List[List[float]]] = None

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


def demo_classes() -> List[type]:
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
    return [BowDemo, IndustrialDemo, JuggleDemo, PendulumDemo, PlungeDemo,
            ReachDemo, SortingDemo, SprintDemo, StackingDemo, TechnicalDemo,
            WaveDemo]


def capture(cls, home: Sequence[float], cfg: dict,
            speed_scale: float = 1.0) -> Optional[List[List[float]]]:
    """Start a demo against a fake controller and grab the program it emits."""
    ctrl = CaptureController()
    demo = cls(ctrl, home,
               speed_scale=speed_scale,
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


def capture_all(speed_scale: float = 1.0) -> Dict[str, List[List[float]]]:
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = cfg["demo"]["saved_home_joints"]
    out = {}
    for cls in demo_classes():
        try:
            rows = capture(cls, home, cfg["demo"], speed_scale)
        except Exception as exc:                          # noqa: BLE001
            print(f"  {cls.__name__}: could not capture ({exc})", file=sys.stderr)
            continue
        if rows:
            out[cls.__name__] = rows
    return out


def main():
    show_blends = "--blends" in sys.argv
    env = Envelope.load_if_present(os.path.join(HERE, "workspace_envelope.json"))
    obs = ObstacleSet.from_json(env.obstacles) if env else ObstacleSet()

    programs = capture_all()
    reports = []
    for name, rows in programs.items():
        rep = choreography.analyse(name, rows, closed=True, obstacles=obs)
        reports.append(rep)
        print()
        print(choreography.describe(rep))
        if show_blends:
            bad = blend.problems(rows, closed=True)
            print(f"  blends         {len(bad)} of {len(rows)} legs overlap"
                  if bad else "  blends         all legal")

    print("\n\n=== how fast each demo can actually go ===")
    print(f"{'demo':<17}{'lead':<13}{'cmd':>6}{'able':>7}{'% ceil':>8}  limited by")
    for rep in sorted(reports, key=lambda r: r.fraction):
        print(f"{rep.name:<17}{choreography.JOINT_NAME[rep.lead_joint]:<13}"
              f"{rep.v_cmd:>6.2f}{rep.v_possible:>7.2f}"
              f"{rep.fraction * 100:>7.0f}%  {rep.limited_by}")

    hurt = [r for r in reports if r.limited_by == "geometry"]
    slow = [r for r in reports if r.limited_by == "accel"]
    print()
    if slow:
        print(f"raise acceleration: {', '.join(r.name for r in slow)}")
    if hurt:
        print(f"needs choreography changes, acceleration will not help: "
              f"{', '.join(r.name for r in hurt)}")

    risky = [r for r in reports if r.self_collision]
    if risky:
        print(f"\nSELF-COLLISION in: {', '.join(r.name for r in risky)}")
    close = [r for r in reports
             if r.clearance_m is not None and r.clearance_m < 0.05]
    if close:
        print("close to a measured solid: " +
              ", ".join(f"{r.name} ({r.clearance_m * 1000:.0f} mm)" for r in close))


if __name__ == "__main__":
    main()
