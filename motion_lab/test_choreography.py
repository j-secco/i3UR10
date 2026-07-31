"""Verify the speed analysis. No robot I/O.

The claims under test are physical: a joint that starts and stops inside a leg
of length d at acceleration a peaks at sqrt(a*d), and blending lets it carry
that speed across consecutive legs instead of restarting each time. Both are
the basis for every choreography change, so both get checked against cases
whose answers are known by hand.
"""
import math
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

from choreography import (GEOMETRY_LIMIT_RAD, JOINT_CEILING, analyse,
                          legs_of, runs_of)

failures = []
HOME = [0.0, -1.2, 1.4, -1.7, -1.57, 0.0]


def path(deltas, joint=2, v=3.0, a=4.0, r=0.05):
    """A path that walks `joint` through the given signed deltas."""
    w, q = [], list(HOME)
    w.append(list(q) + [v, a, r])
    for d in deltas:
        q[joint] += d
        w.append(list(q) + [v, a, r])
    return w


# 1. sqrt(a*d) on a single isolated leg. d = 1.0 rad at a = 4.0 -> 2.0 rad/s.
w = path([1.0], v=10.0, a=4.0, r=0.0)
r0 = runs_of(legs_of(w, closed=False), closed=False)
got = [x for x in r0 if x.joint == 2][0]
if abs(got.v_geo - 2.0) < 1e-9:
    print(f"OK  sqrt(a*d): 1.00 rad at 4.0 rad/s^2 peaks at {got.v_geo:.2f} rad/s")
else:
    failures.append(f"v_geo {got.v_geo}, expected 2.0")

# 2. Blends chain legs. Five 0.2 rad legs the same way = one 1.0 rad run, so
#    the same peak as case 1 -- this is the whole reason blends matter to speed.
w = path([0.2] * 5, v=10.0, a=4.0, r=0.05)
runs = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2]
if len(runs) == 1 and abs(runs[0].distance - 1.0) < 1e-9 \
        and abs(runs[0].v_geo - 2.0) < 1e-9:
    print(f"OK  blends chain: 5 x 0.2 rad legs behave as one {runs[0].distance:.2f} rad run")
else:
    failures.append(f"chaining wrong: {[(x.distance, x.v_geo) for x in runs]}")

# 3. A zero blend forces a stop, so the same five legs become five runs and the
#    peak collapses. This is the cost of "repairing" blends down to zero.
w = path([0.2] * 5, v=10.0, a=4.0, r=0.0)
runs = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2]
if len(runs) == 5 and abs(runs[0].v_geo - math.sqrt(4.0 * 0.2)) < 1e-9:
    print(f"OK  r=0 breaks the chain: 5 runs, each peaking at "
          f"{runs[0].v_geo:.2f} rad/s instead of 2.00")
else:
    failures.append(f"zero blend did not break the run: {len(runs)} runs")

# 4. A reversal ends a run even when blended: the joint has to stop to turn.
w = path([0.3, 0.3, -0.3, -0.3], v=10.0, a=4.0, r=0.05)
runs = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2]
if len(runs) == 2 and all(abs(x.distance - 0.6) < 1e-9 for x in runs):
    print("OK  a direction reversal ends a run")
else:
    failures.append(f"reversal not handled: {[x.distance for x in runs]}")

# 5. The joint ceiling is respected: no run reports more than the hardware
#    allows, whatever is commanded. J1 is held to 2.09 rad/s.
w = path([4.0], joint=0, v=10.0, a=20.0, r=0.0)
run = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 0][0]
if abs(run.v_peak - JOINT_CEILING[0]) < 1e-9 and run.limited_by == "ceiling":
    print(f"OK  base is held to its {JOINT_CEILING[0]} rad/s ceiling")
else:
    failures.append(f"ceiling not applied: {run.v_peak} {run.limited_by}")

# 6. Classification. A short leg must be called geometry-limited, because
#    telling someone to raise acceleration there wastes their time.
w = path([0.05], v=10.0, a=4.0, r=0.0)
run = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2][0]
short_ok = run.limited_by == "geometry"
w = path([1.5], v=10.0, a=1.0, r=0.0)
run2 = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2][0]
accel_ok = run2.limited_by == "accel"
w = path([2.0], v=0.5, a=20.0, r=0.0)
run3 = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2][0]
speed_ok = run3.limited_by == "speed"
if short_ok and accel_ok and speed_ok:
    print("OK  legs classified as geometry / accel / speed limited")
else:
    failures.append(f"classification wrong: {run.limited_by} {run2.limited_by} "
                    f"{run3.limited_by}")

# 7. accel_for inverts sqrt(a*d) -- the number we act on when raising a.
w = path([0.8], v=10.0, a=1.0, r=0.0)
run = [x for x in runs_of(legs_of(w, closed=False), closed=False) if x.joint == 2][0]
need = run.accel_for(3.14)
if abs(need - 3.14 * 3.14 / 0.8) < 1e-9 and abs(math.sqrt(need * 0.8) - 3.14) < 1e-9:
    print(f"OK  acceleration needed for a target speed inverts cleanly "
          f"({need:.1f} rad/s^2 for 3.14 rad/s over 0.8 rad)")
else:
    failures.append(f"accel_for wrong: {need}")

# 8. Whole-demo verdict picks the joint that does the most work, not whichever
#    joint happens to lead a single leg.
w = []
q = list(HOME)
for i in range(6):
    q[0] += 0.5                 # base does the real work
    q[5] += 0.05 if i % 2 else -0.05
    w.append(list(q) + [3.0, 4.0, 0.05])
rep = analyse("synthetic", w, closed=False)
if rep.lead_joint == 0:
    print(f"OK  demo verdict follows the joint doing the work "
          f"({rep.v_possible:.2f} rad/s, {rep.limited_by}-limited)")
else:
    failures.append(f"lead joint {rep.lead_joint}, expected 0")

# 9. Notes must call out the things a person would otherwise have to spot by
#    reading a table of numbers.
w = path([0.001, 0.001, 0.4], v=3.0, a=4.0, r=0.0)
rep = analyse("stubby", w, closed=False)
if any("essentially nothing" in n for n in rep.notes) and \
        any("full stop" in n for n in rep.notes):
    print("OK  dead legs and forced stops are reported")
else:
    failures.append(f"notes missing: {rep.notes}")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
