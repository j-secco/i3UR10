"""Verify taught zones: a deliberate limit over a bearing arc, beating the
inferred sector bins where they overlap. No robot I/O."""
import math
import os
import sys
import tempfile

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

from envelope import Dome, Envelope, Zone

failures = []

# A dome taught loosely: floor at -0.40 m everywhere.
pts = []
for deg in range(0, 360, 5):
    a = math.radians(deg)
    for z in (-0.40, 0.30, 0.90):
        pts.append([0.9 * math.cos(a), 0.9 * math.sin(a), z])
dome = Dome.from_points(pts)
print(f"base floors: {[round(f, 2) for f in dome.sector_floors]}")

# Now teach a front zone: bearings 330 to 30 deg may not go below +0.10 m.
front = Zone(name="front", az_center=0.0,
             az_lo=math.radians(-30), az_hi=math.radians(30), floor=0.10)
dome.zones = [front]

# 1. The zone tightens its own arc.
if abs(dome.floor_at(1.0, 0.0) - 0.10) < 1e-9:
    print("OK  zone raises the floor inside its arc")
else:
    failures.append(f"floor in the zone is {dome.floor_at(1.0, 0.0)}, expected 0.10")

# 2. And leaves the rest alone.
back = dome.floor_at(-1.0, 0.0)
if abs(back + 0.40) < 1e-6:
    print("OK  bearings outside the zone keep the taught floor")
else:
    failures.append(f"floor outside the zone changed to {back}")

# 3. A point low at the front is refused; the same height at the back is fine.
if dome.outside([0.9, 0.0, -0.20]) is not None and dome.outside([-0.9, 0.0, -0.20]) is None:
    print("OK  same height refused at the front, allowed at the back")
else:
    failures.append("zone did not discriminate front from back")

# 4. The refusal names the zone, so the message is actionable.
why = dome.outside([0.9, 0.0, -0.20])
if why and "front" in why:
    print(f"OK  refusal names the zone: {why[:64]}")
else:
    failures.append(f"refusal did not name the zone: {why}")

# 5. A zone never loosens an already-tighter bin. Teach one at -0.9 where the
#    bins say -0.40; the bin must win.
dome.zones = [Zone(name="loose", az_center=math.pi, az_lo=-0.3, az_hi=0.3, floor=-0.90)]
if abs(dome.floor_at(-1.0, 0.0) + 0.40) < 1e-6:
    print("OK  a looser zone cannot undercut the inferred floor")
else:
    failures.append(f"loose zone undercut the bin: {dome.floor_at(-1.0, 0.0)}")

# 6. Arc wrapping across 0/360 works (the front usually straddles it).
dome.zones = [front]
for deg in (350, 355, 0, 5, 20):
    a = math.radians(deg)
    if not front.covers(math.cos(a), math.sin(a)):
        failures.append(f"zone arc missed bearing {deg}")
        break
else:
    if not front.covers(math.cos(math.radians(180)), math.sin(math.radians(180))):
        print("OK  arc wraps across 0 deg and excludes the opposite side")
    else:
        failures.append("zone arc wrapped all the way round")

# 7. Optional reach cap applies only inside the zone.
capped = Zone(name="tight", az_center=0.0, az_lo=-0.3, az_hi=0.3, floor=-1.0, r_max=0.5)
dome.zones = [capped]
if dome.outside([0.9, 0.0, 0.3]) is not None and dome.outside([-0.9, 0.0, 0.3]) is None:
    print("OK  zone reach cap applies only within its arc")
else:
    failures.append("zone reach cap leaked outside its arc")

# 8. Round-trip, including the unlimited reach that JSON cannot hold.
env = Envelope.from_samples([[0.0] * 6])
env.dome = dome
env.dome.zones = [front, capped]
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "e.json")
    env.save(p)
    back_env = Envelope.load(p)
    zs = {z.name: z for z in back_env.dome.zones}
    if (len(zs) == 2 and zs["front"].r_max == math.inf
            and abs(zs["tight"].r_max - 0.5) < 1e-9
            and abs(zs["front"].floor - 0.10) < 1e-9):
        print("OK  zones round-trip, unlimited reach preserved as infinity")
    else:
        failures.append(f"zones did not round-trip: {zs}")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
