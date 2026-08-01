"""Verify demo amplitude fitting. No robot I/O.

The guard used to refuse an unsafe demo outright, which turned six of the
eleven touchscreen buttons into no-ops. Now it shrinks the choreography about
home until it fits. The behaviour that must hold: safe demos are returned
untouched, unsafe ones come back smaller but genuinely safe, blend radii
shrink with the legs, and something too dangerous to scale is still refused.
"""
import math
import os
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

import yaml

import demos
from control import amplitude, pose_guard

failures = []
cfg = yaml.safe_load(open("config/robot_config.yaml"))
HOME = list(cfg["demo"]["saved_home_joints"])


def prog(deltas, r=0.05, joint=2):
    """A loop that pushes `joint` out by each delta and returns."""
    rows = [list(HOME) + [1.0, 2.0, r]]
    for d in deltas:
        q = list(HOME)
        q[joint] += d
        rows.append(q + [1.0, 2.0, r])
    return rows


# 1. A safe program must come back byte-identical in the joints. Any drift
#    here would silently reshape the five demos that already work.
safe = prog([0.05, -0.05])
out, s = amplitude.fit(safe, HOME, closed=True)
if s == 1.0 and out is not None and \
        all(abs(a[j] - b[j]) < 1e-12 for a, b in zip(safe, out) for j in range(9)):
    print("OK  a safe program is returned unchanged at full amplitude")
else:
    failures.append(f"safe program was altered (scale {s})")

# 2. An unsafe program must come back smaller AND actually safe -- the point
#    is a demo that runs, not a smaller number in a log line.
unsafe = prog([0.55])          # drives the elbow into the shoulder
if pose_guard.validate_path(unsafe, closed=True) is None:
    failures.append("test fixture is not actually unsafe; test is vacuous")
else:
    out, s = amplitude.fit(unsafe, HOME, closed=True)
    if out is not None and 0 < s < 1.0 and \
            pose_guard.validate_path(out, closed=True) is None:
        print(f"OK  an unsafe program is shrunk to {s*100:.0f}% and validates")
    else:
        failures.append(f"unsafe program not made safe (scale {s})")

# 3. Blend radii scale with the geometry. Halving a demo halves its legs; if
#    the radii stayed put they would overlap and the controller would start
#    SKIPPING waypoints, so a shrunken demo would also be the wrong shape.
scaled = amplitude.scale_waypoints(safe, HOME, 0.5)
if all(abs(w[8] - o[8] * 0.5) < 1e-12 for w, o in zip(scaled, safe)):
    print("OK  blend radii scale with the legs they sit in")
else:
    failures.append("blend radii did not scale")

# 4. Speeds and accelerations are limits, not geometry, and must not scale.
if all(abs(w[6] - o[6]) < 1e-12 and abs(w[7] - o[7]) < 1e-12
       for w, o in zip(scaled, safe)):
    print("OK  speed and acceleration are left alone")
else:
    failures.append("speed/accel were scaled")

# 5. Scaling is about home, so home itself never moves however small it gets.
for s_ in (1.0, 0.5, 0.1):
    got = amplitude.scale_waypoints(safe, HOME, s_)[0]
    if max(abs(got[j] - HOME[j]) for j in range(6)) > 1e-12:
        failures.append(f"home moved at scale {s_}")
        break
else:
    print("OK  home is the fixed point of the scaling")

# 6. Something unsafe even when tiny must still be refused, and a program with
#    no home to shrink towards cannot be scaled at all.
out, s = amplitude.fit(unsafe, None, closed=True)
if out is None and s == 0.0:
    print("OK  without a home there is nothing to shrink towards, so refused")
else:
    failures.append("scaled without a home")

# 7. Bare 6-element waypoints (move_joint_path) must survive scaling; that
#    call site has no v/a/r columns at all.
bare = [list(HOME), [HOME[0], HOME[1], HOME[2] + 0.2] + HOME[3:]]
got = amplitude.scale_waypoints(bare, HOME, 0.5)
if len(got[1]) == 6 and abs(got[1][2] - (HOME[2] + 0.1)) < 1e-12:
    print("OK  waypoints without speed columns scale correctly")
else:
    failures.append(f"bare waypoints mishandled: {got[1]}")

# 8. The real catalogue: every demo must now be sendable, and the ones that
#    already worked must not have been touched.
print()
was_refused = {"BowDemo", "IndustrialDemo", "SortingDemo",
               "StackingDemo", "TechnicalDemo", "WaveDemo"}
for name, rows in demos.capture_all().items():
    out, s = amplitude.fit(rows, HOME, closed=True)
    if out is None:
        failures.append(f"{name} still cannot be sent")
        continue
    if pose_guard.validate_path(out, closed=True) is not None:
        failures.append(f"{name} was scaled but is still unsafe")
        continue
    if name in was_refused and s >= 1.0:
        failures.append(f"{name} was refused before but was not scaled")
    if name not in was_refused and s < 1.0:
        failures.append(f"{name} worked before but got shrunk to {s*100:.0f}%")
    print(f"    {name:<16} {s*100:>3.0f}%  "
          f"{'was refused, now runs' if name in was_refused else 'unchanged'}")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
