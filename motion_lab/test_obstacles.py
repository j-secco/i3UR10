"""Verify measured keep-out solids. No robot I/O.

The scenario is this cell: a cart under the robot, the arm mounted above it.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

import yaml

from control.pose_guard import joint_origins
from envelope import Envelope
from obstacles import ObstacleSet, Prism, link_radii, point_in_polygon

failures = []
cfg = yaml.safe_load(open("config/robot_config.yaml"))
home = cfg["demo"]["saved_home_joints"]

# A cart roughly under the base: 0.8 x 0.6 m, top 0.10 m below the base plane.
cart = Prism(name="cart",
             polygon=[[-0.40, -0.30], [0.40, -0.30], [0.40, 0.30], [-0.40, 0.30]],
             z_top=-0.10, margin=0.05)
obs = ObstacleSet(solids=[cart])

# 1. Home must be clear. Note the robot is BOLTED to the cart, so its base
#    column is permanently inside the solid; only links that can actually move
#    are tested, or every pose would be a collision.
if obs.blocked(home) is None:
    w = obs.worst(home)
    print(f"OK  home clear of the cart, closest approach {w[0] * 1000:.0f} mm")
else:
    failures.append(f"home reported as hitting the cart: {obs.blocked(home)}")

# 2. Fold the arm back down over the cart -- it must be refused. Found by
#    sweeping J2/J3 for the deepest intrusion; the surface of the upper arm
#    comes within the margin of the cart top while its centreline is still
#    clear, which is exactly the case a point test would miss.
into = list(home)
into[1] += 1.8        # shoulder over
into[2] -= 1.8        # elbow back down toward the cart
hit = obs.blocked(into)
if hit is not None:
    print(f"OK  arm driven into the cart refused: {hit[:60]}")
else:
    failures.append("arm inside the cart was allowed")

# 3. The refusal has to name the solid and the depth, or it is not actionable.
if hit and "cart" in hit and "mm" in hit:
    print("OK  refusal names the solid and how deep")
else:
    failures.append(f"refusal not actionable: {hit}")

# 4. Capsule awareness: a pose whose link CENTRELINE clears the solid but whose
#    surface does not must still be refused. Squeeze the margin to zero and put
#    the test point exactly one radius outside.
bare = ObstacleSet(solids=[Prism(name="edge", polygon=cart.polygon,
                                 z_top=-0.10, margin=0.0)])
r_upper = link_radii()[1]
just_outside = [0.40 + r_upper * 0.5, 0.0, -0.20]     # centreline clear, surface not
if bare.solids[0].clearance(just_outside, 0.0) > 0 and \
        bare.solids[0].clearance(just_outside, r_upper) < 0:
    print(f"OK  link radius {r_upper * 1000:.0f} mm is what gets tested, not the centreline")
else:
    failures.append("capsule radius is not being applied")

# 5. Height band: well above the top is clear, inside the band is not.
if cart.clearance([0.0, 0.0, 0.60]) > 0 and cart.clearance([0.0, 0.0, -0.30]) < 0:
    print("OK  solid bounded in height, clear above its top")
else:
    failures.append("height band wrong")

# 6. Footprint is not assumed axis-aligned: a rotated cart still works.
ang = math.radians(30)
rot = [[x * math.cos(ang) - y * math.sin(ang), x * math.sin(ang) + y * math.cos(ang)]
       for x, y in cart.polygon]
tilted = Prism(name="tilted", polygon=rot, z_top=-0.10, margin=0.05)
inside_pt = [0.0, 0.0, -0.20]
outside_pt = [0.0, 0.75, -0.20]
if tilted.hits(inside_pt) and not tilted.hits(outside_pt):
    print("OK  rotated footprint handled without axis alignment")
else:
    failures.append("rotated footprint mishandled")

# 7. Nothing measured means nothing blocked -- the guard must not invent solids.
if ObstacleSet().blocked(home) is None:
    print("OK  an empty obstacle set blocks nothing")
else:
    failures.append("empty obstacle set refused a pose")

# 8. Round-trip through the envelope.
env = Envelope.from_samples([home])
env.obstacles = ObstacleSet(solids=[cart]).to_json()
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "e.json")
    env.save(p)
    back = Envelope.load(p)
    got = ObstacleSet.from_json(back.obstacles)
    if len(got.solids) == 1 and got.solids[0].name == "cart" \
            and got.solids[0].polygon == cart.polygon:
        print("OK  measured solids round-trip through the envelope")
    else:
        failures.append("solids did not round-trip")
    if back.contains(into) is not None and "cart" in back.contains(into).detail:
        print("OK  a reloaded envelope enforces its solids")
    else:
        failures.append("reloaded envelope did not enforce its solids")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
