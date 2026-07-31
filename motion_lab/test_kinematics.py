"""Verify the closed-form IK against the forward kinematics. No robot I/O.

The test that matters is the round trip: take a random pose, run FK, solve IK
from the resulting matrix, and check every returned solution reproduces that
matrix. A sign error anywhere in the derivation breaks this immediately, which
is the point -- the formulae have too many sign conventions to eyeball.
"""
import math
import os
import random
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

import numpy as np

from control.pose_guard import tcp_xyz
from control.ur_kinematics import (fk_matrix, ik, joint_distance,
                                   nearest_turn, solve_position, unwind_to)

failures = []
random.seed(20260731)          # fixed: a flaky geometry test is worthless


def pose_error(Ta, Tb):
    """(position error in m, orientation error in rad)."""
    dp = float(np.linalg.norm(Ta[:3, 3] - Tb[:3, 3]))
    Rd = Ta[:3, :3].T @ Tb[:3, :3]
    cos = (np.trace(Rd) - 1.0) / 2.0
    return dp, abs(math.acos(max(-1.0, min(1.0, cos))))


# 1. Round trip over random reachable configurations. Joint 1 and 5 are kept
#    off their singular values, where the branch structure legitimately
#    collapses and no solver can split J4 from J6.
tested = worst_p = worst_r = 0
missing = 0
for _ in range(2000):
    q = [random.uniform(-math.pi, math.pi),
         random.uniform(-2.6, -0.5),
         random.uniform(-2.6, 2.6),
         random.uniform(-math.pi, math.pi),
         random.choice([1.0, -1.0]) * random.uniform(0.25, math.pi - 0.25),
         random.uniform(-math.pi, math.pi)]
    T = fk_matrix(q)
    sols = ik(T)
    if not sols:
        missing += 1
        continue
    tested += 1
    for s in sols:
        dp, dr = pose_error(T, fk_matrix(s))
        worst_p, worst_r = max(worst_p, dp), max(worst_r, dr)
        if dp > 1e-6 or dr > 1e-6:
            failures.append(f"round trip off by {dp*1e3:.3f} mm / "
                            f"{math.degrees(dr):.4f} deg from q={q}")
            break
    # The original configuration must be among the solutions, or we are
    # silently unable to command poses the robot can actually hold.
    if not any(joint_distance(unwind_to(s, q), q) < 1e-6 for s in sols):
        failures.append(f"original configuration not returned for q={q}")

if not failures:
    print(f"OK  {tested} random poses round trip, worst error "
          f"{worst_p*1e6:.3f} um / {math.degrees(worst_r)*3600:.3f} arcsec")
if missing:
    print(f"    ({missing} poses returned no solution)")
if missing > tested * 0.02:
    failures.append(f"{missing} of {tested + missing} reachable poses unsolved")

# 2. Eight branches for a comfortably reachable, non-singular pose.
q = [0.0, -1.2, 1.4, -1.7, -1.57, 0.3]
n = len(ik(fk_matrix(q)))
if n == 8:
    print("OK  all 8 branches found for a general pose")
else:
    failures.append(f"expected 8 branches, got {n}")

# 3. Out of reach must return nothing, not a wrong answer.
T = fk_matrix(q).copy()
T[:3, 3] = [3.0, 0.0, 0.5]
if ik(T) == []:
    print("OK  an unreachable point returns no solution")
else:
    failures.append("unreachable point produced a solution")

# 4. Unwinding: a joint parked past a full turn must not be commanded the
#    long way round. J4 sits near -238 deg on this robot in practice.
ref = math.radians(-238.0)
got = nearest_turn(math.radians(122.0), ref)      # same angle, wrapped
if abs(got - ref) < 1e-9:
    print("OK  solutions unwind to the turn the joint is already in")
else:
    failures.append(f"unwind put the joint at {math.degrees(got):.1f} deg, "
                    f"expected {math.degrees(ref):.1f}")

# 5. Position solve actually lands the tool on the requested point.
ref_q = [-0.77, -1.44, 2.54, -4.09, -1.51, 0.40]
for target in ([-0.60, 0.30, 0.40], [0.50, -0.50, 0.20], [0.0, 0.70, 0.60]):
    sols = solve_position(*target, reference=ref_q)
    if not sols:
        failures.append(f"no solution for {target}")
        continue
    err = max(math.dist(tcp_xyz(s), target) for s in sols)
    if err > 1e-6:
        failures.append(f"tool missed {target} by {err*1e3:.3f} mm")
if not failures:
    print("OK  clicked positions are reached by every returned solution")

# 6. Nearest-first ordering, so the caller taking the first workable solution
#    gets the smallest move rather than an arbitrary elbow flip.
sols = solve_position(-0.60, 0.30, 0.40, reference=ref_q)
d = [joint_distance(s, ref_q) for s in sols]
if d == sorted(d):
    print(f"OK  solutions ordered by travel ({d[0]:.2f} rad nearest, "
          f"{d[-1]:.2f} rad furthest of {len(d)})")
else:
    failures.append("solutions not ordered by joint travel")

# 7. FK agreement with the model everything else already uses.
q = [0.1, -1.3, 1.5, -1.8, -1.5, 0.2]
if math.dist(fk_matrix(q)[:3, 3], tcp_xyz(q)) < 1e-12:
    print("OK  IK module and pose_guard share one forward model")
else:
    failures.append("fk_matrix disagrees with pose_guard.tcp_xyz")

print()
if failures:
    for f in failures[:10]:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
