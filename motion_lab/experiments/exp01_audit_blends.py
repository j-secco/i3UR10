"""
Experiment 01 - audit every production demo's blend radii offline.

Commands NO motion. Answers: which demos contain waypoints the controller
will silently SKIP because their blend spheres overlap (URScript 3.13, movej:
"this move will be skipped ... 'Overlapping Blends'").

Note what this does NOT tell you. A legal blend says the waypoint will be
visited, not that the motion is quick: shrinking radii to satisfy the rule
makes the arm decelerate into every corner, which measurably tamed Sprint
(peak TCP 0.67 -> 0.55 m/s). For whether a demo can go fast at all, see
`motion_lab/demos.py`.

Run from the project root:  venv/bin/python motion_lab/experiments/exp01_audit_blends.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(HERE))

import blend  # noqa: E402
import demos  # noqa: E402


def main():
    summary = []
    for name, rows in demos.capture_all().items():
        print()
        print(blend.report(rows, closed=True, title=name))
        summary.append((name, len(blend.problems(rows, closed=True)), len(rows)))

    print("\n\n=== SUMMARY: waypoints the controller would skip ===")
    for name, bad, total in summary:
        state = "CLEAN" if bad == 0 else f"{bad}/{total} legs OVERLAP"
        print(f"  {name:16s} {state}")


if __name__ == "__main__":
    main()
