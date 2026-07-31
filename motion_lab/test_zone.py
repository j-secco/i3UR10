"""Verify taught zones: a per-sector limit recorded by sweeping along an
obstacle, tightening the inferred bins where it is stricter. No robot I/O."""
import math
import os
import sys
import tempfile

sys.path.insert(0, "src")
sys.path.insert(0, "motion_lab")

from envelope import FLOOR_SECTORS, RING_WIDTH_M, Dome, Envelope, Zone

failures = []
STEP = 360 // FLOOR_SECTORS

# A dome taught loosely: floor at -0.40 m in every direction.
pts = []
for deg in range(0, 360, 5):
    a = math.radians(deg)
    for z in (-0.40, 0.30, 0.90):
        pts.append([0.9 * math.cos(a), 0.9 * math.sin(a), z])
dome = Dome.from_points(pts)

def at(deg, r=0.9):
    a = math.radians(deg)
    return r * math.cos(a), r * math.sin(a)

# A front zone swept across three sectors, TIGHTER at one end than the other --
# the case that a single-floor zone could not express.
RING = int(0.9 // RING_WIDTH_M)          # the ring the probe points sit in
LAST = FLOOR_SECTORS - 1
front = Zone(name="front", floors={f"0,{RING}": 0.30, f"1,{RING}": 0.10,
                                  f"{LAST},{RING}": 0.05})
dome.zones = [front]
print(f"zone 'front' covers sectors {front.sectors} with varying floor")

# 1. Each sector keeps its own limit.
for sec, expect in ((0, 0.30), (1, 0.10), (LAST, 0.05)):
    x, y = at(sec * STEP + STEP / 2)
    if abs(dome.floor_at(x, y) - expect) > 1e-9:
        failures.append(f"sector {sec} floor {dome.floor_at(x, y)}, expected {expect}")
        break
else:
    print("OK  varying clearance preserved per sector")

# 2. The tight end really is tighter than the roomy end.
tx, ty = at(15)          # sector 0, floor 0.30
rx, ry = at(360 - (360 // FLOOR_SECTORS) / 2)   # last sector, floor 0.05
if dome.outside([tx, ty, 0.20]) is not None and dome.outside([rx, ry, 0.20]) is None:
    print("OK  same height refused at the tight end, allowed at the roomy end")
else:
    failures.append("zone did not discriminate between its own ends")

# 3. Sectors the sweep never covered are untouched.
bx, by = at(180)
if abs(dome.floor_at(bx, by) + 0.40) < 1e-6:
    print("OK  uncovered bearings keep the inferred floor")
else:
    failures.append(f"floor outside the zone changed to {dome.floor_at(bx, by)}")

# 4. A zone overrides the inferred bin in its own sectors, in both directions:
#    a bin built from a handful of poses can be spuriously high, and careful
#    re-teaching has to be able to correct it.
dome.zones = [Zone(name="corrected", floors={f"6,{RING}": -0.90})]
lx, ly = at(6 * STEP + STEP / 2)
if abs(dome.floor_at(lx, ly) + 0.90) < 1e-6:
    print("OK  a zone overrides the inferred bin, downward as well as up")
else:
    failures.append(f"zone did not override the bin: {dome.floor_at(lx, ly)}")

# 4b. Overlapping zones: the tighter one wins.
dome.zones = [Zone(name="a", floors={f"6,{RING}": -0.50}),
              Zone(name="b", floors={f"6,{RING}": 0.10})]
if abs(dome.floor_at(lx, ly) - 0.10) < 1e-9:
    print("OK  where zones overlap, the tighter wins")
else:
    failures.append(f"overlap resolved to {dome.floor_at(lx, ly)}, expected 0.10")

# 5. The refusal names the zone and the bearing, so it is actionable.
dome.zones = [front]
why = dome.outside([tx, ty, 0.20])
if why and "front" in why and "bearing" in why:
    print(f"OK  refusal is specific: {why[:70]}")
else:
    failures.append(f"refusal not specific enough: {why}")

# 6. A zone straddling 0 degrees needs no arc arithmetic -- sectors 11 and 0
#    are simply both present, so there is no wrap to get wrong.
if (front.covers(*at(360 - (360 // FLOOR_SECTORS) / 2)) and front.covers(*at(5))
        and not front.covers(*at(180))):
    print("OK  zone spanning 0 deg works without wrap arithmetic")
else:
    failures.append("sector membership across 0 deg is wrong")

# 7. Reach cap applies only where the zone covers.
dome.zones = [Zone(name="tight", floors={f"0,{RING}": -1.0}, r_max=0.5)]
if dome.outside([*at(15), 0.3]) is not None and dome.outside([*at(180), 0.3]) is None:
    print("OK  zone reach cap stays inside its own sectors")
else:
    failures.append("zone reach cap leaked outside its sectors")

# 8. Round-trip, including unlimited reach that JSON cannot represent.
env = Envelope.from_samples([[0.0] * 6])
env.dome = dome
env.dome.zones = [front, Zone(name="tight", floors={f"0,{RING}": -1.0}, r_max=0.5)]
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "e.json")
    env.save(p)
    zs = {z.name: z for z in Envelope.load(p).dome.zones}
    if (len(zs) == 2 and zs["front"].r_max == math.inf
            and abs(zs["tight"].r_max - 0.5) < 1e-9
            and abs(zs["front"].floors[f"0,{RING}"] - 0.30) < 1e-9
            and zs["front"].sectors == sorted([0, 1, LAST])):
        print("OK  zones round-trip with their per-sector profile intact")
    else:
        failures.append(f"zones did not round-trip: {zs}")

print()
if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
