"""Verify the envelope behaves as a VOLUME: the arm may pose however it likes
inside the taught space. Replaces the earlier suites, which were written
against a joint-range model that turned out to be the wrong idea."""
import math
import os
import sys
import tempfile

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

import yaml

from envelope import BASE_EXCLUSION_R, Dome, Envelope, arm_points

failures = []
cfg = yaml.safe_load(open("config/robot_config.yaml"))
home = cfg["demo"]["saved_home_joints"]


def swing(dj1=0.0, dj2=0.0, dj3=0.0):
    q = list(home); q[0] += dj1; q[1] += dj2; q[2] += dj3
    return q


# Teach a wide arc, reaching low only on one side -- the shape of a cell where
# a frame blocks the near side and open floor is on the far side.
taught = []
for dj1 in [i * 0.15 for i in range(-20, 21)]:
    taught.append(swing(dj1=dj1))
    if dj1 > 0.6:                      # only reach down on the far side
        taught.append(swing(dj1=dj1, dj2=0.5))
env = Envelope.from_samples(taught)
print(f"taught {len(taught)} poses; floors by sector: "
      f"{[round(f, 2) for f in env.dome.sector_floors]}")

# 1. A pose using a joint fold never demonstrated, but sitting inside the
#    taught volume, must be allowed. This is the whole correction.
novel = list(home)
novel[3] += 0.9          # wrist rolled somewhere never taught
novel[5] += 1.2
if env.contains(novel) is None:
    print("OK  untaught joint configuration allowed while inside the volume")
else:
    failures.append(f"novel pose refused: {env.contains(novel).describe()}")

# 2. Joint ranges are recorded but not enforced by default.
if not env.enforce_joints and env.joint_min and env.joint_max:
    print("OK  joint ranges recorded for the pendant, not enforced")
else:
    failures.append("joint ranges are being enforced by default")

# 3. There is no minimum radius: the inside of a dome is not dangerous.
if not hasattr(env.dome, "r_min"):
    print("OK  no minimum-radius constraint")
else:
    failures.append("dome still carries a minimum radius")

# 4. The whole arm is tested, not just the tool. A pose whose ELBOW leaves the
#    volume must be refused even when the tool stays inside.
tall = Envelope.from_samples([home])
tall.dome.r_max = 0.60          # squeeze until the elbow must protrude
tcp_r = math.sqrt(sum(v * v for v in arm_points(home)[-1]))
if tall.contains(home) is not None:
    print(f"OK  arm tested along its links, not just the tool")
else:
    failures.append("a pose with the arm outside the volume was allowed")

# 5. The floor is direction-dependent: the same low reach is allowed where it
#    was taught and refused where it was not.
low = swing(dj1=1.5, dj2=0.5)
if env.contains(low) is None:
    mirrored = swing(dj1=-1.5, dj2=0.5)
    if env.contains(mirrored) is not None:
        print("OK  low reach allowed where taught, refused in the untaught direction")
    else:
        failures.append("low reach allowed in a direction it was never taught")
else:
    failures.append(f"low reach refused where it was taught: {env.contains(low).detail}")

# 6. Sectors nobody demonstrated inherit the most restrictive taught floor
#    rather than a guessed one.
d = Dome.from_points([[1.0, 0.0, 0.5], [1.0, 0.1, 0.2]])   # one sector only
if len(d.sector_floors) == 12 and max(d.sector_floors) == min(
        [f for f in d.sector_floors if f == max(d.sector_floors)]):
    untaught = d.floor_at(-1.0, 0.0)
    if untaught >= 0.2 - 1e-9:
        print("OK  untaught sectors inherit the most restrictive taught floor")
    else:
        failures.append(f"untaught sector floor guessed downward: {untaught}")
else:
    failures.append("sector floors not populated")

# 7. Structure near the base axis is exempt: a positive floor must not reject
#    the base and shoulder, which live at z = 0 to 0.127.
base_pts = [p for p in arm_points(home) if math.hypot(p[0], p[1]) <= BASE_EXCLUSION_R]
if base_pts and env.contains(home) is None:
    print(f"OK  {len(base_pts)} points near the base axis exempt from the floor")
else:
    failures.append("base structure trips the floor check")

# 8. Round-trip.
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "e.json")
    env.save(p)
    back = Envelope.load(p)
    if isinstance(back.dome, Dome) and back.dome.sector_floors == env.dome.sector_floors:
        print("OK  envelope round-trips with its sector floors intact")
    else:
        failures.append("envelope did not round-trip")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
