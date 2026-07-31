"""
Taught workspace envelope: the volume the operator demonstrated is clear.

NOT A SAFETY FUNCTION. This is a software pre-check running on the control
PC. It can crash, lag, or be skipped, and nothing certifies it. Its job is to
(a) stop the lab from ever *commanding* a path outside the region you taught,
and (b) produce numbers for the PolyScope Safety configuration, which IS
enforced by the robot's separate safety processor.

WHAT THIS MODELS, AND WHY
-------------------------
A dome, not a set of joint limits. The arm may move however it likes inside
the taught volume; the only questions are "is every part of the arm inside
it?" and "does the arm hit itself?" (the latter is pose_guard's job).

An earlier version also derived per-joint ranges from the teaching session
and enforced them. That was wrong. The same point in space is reachable with
many elbow and shoulder configurations, so recording the ones that happened
to occur while hand-guiding constrains *how* the arm may pose rather than
*where* it may go. It rejected the home pose, which is obviously fine, purely
because the operator never folded the elbow that far while walking the arm
around. Joint ranges are still recorded and reported -- they are what the
pendant's Joint Limits screen wants -- but they are not enforced unless
`enforce_joints` is set.

For the same reason there is no minimum radius. The inside of a dome is not
dangerous; "the closest I happened to reach" is not a constraint.

THE FLOOR IS PER-SECTOR, AND THAT MATTERS
-----------------------------------------
Measured on this cell, the lowest safely-taught height varies by 0.58 m with
bearing: the arm can drop to -0.43 m over open floor but only to +0.15 m
where the frame is. A single global floor is therefore not conservative, it
is permissive in exactly the direction where the obstacle lives. The floor is
binned by azimuth so it tightens where the cart is.
"""

import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from control.pose_guard import joint_origins, tcp_xyz

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "workspace_envelope.json")

# 15 degrees each. The floor within a sector is the lowest the arm reached
# anywhere in it, so a sector straddling the edge of an obstacle takes the
# open-side value and would allow the arm down on the tight side too. The
# resolution has to be finer than the features it is meant to describe.
FLOOR_SECTORS = 24
RING_WIDTH_M = 0.20         # radial resolution of the floor grid
SAMPLES_PER_LINK = 6        # points sampled along each link when testing the arm

# Inside this horizontal distance of the base axis the arm is structurally
# fixed and cannot swing into anything the base is not already touching, so
# the floor does not apply there. Without this the base and shoulder, which
# sit at z = 0 to 0.127, would violate any positive sector floor.
BASE_EXCLUSION_R = 0.25


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def spherical(point: Sequence[float]) -> tuple:
    """(radius, azimuth, elevation) about the robot base origin."""
    x, y, z = point
    r = math.sqrt(x * x + y * y + z * z)
    if r < 1e-9:
        return 0.0, 0.0, 0.0
    return r, math.atan2(y, x), math.asin(max(-1.0, min(1.0, z / r)))


def arm_points(joints: Sequence[float],
               per_link: int = SAMPLES_PER_LINK) -> List[List[float]]:
    """Every part of the arm, sampled along the links.

    Checking only the tool would miss the elbow swinging into something, which
    on a UR10 is the more common way to hit an obstacle.
    """
    chain = joint_origins(joints)
    pts = []
    for a, b in zip(chain, chain[1:]):
        for k in range(per_link + 1):
            t = k / per_link
            pts.append([a[i] + (b[i] - a[i]) * t for i in range(3)])
    return pts


@dataclass
class Zone:
    """A deliberately taught limit, held per grid cell.

    Keyed the same way as the dome's floor grid -- bearing sector AND radial
    ring -- because a limit recorded per bearing alone repeats the mistake the
    grid exists to fix: the deep reach available far out gets authorised close
    in, where the cart is.
    """
    name: str = ""
    floors: Dict[str, float] = field(default_factory=dict)   # "sector,ring" -> floor
    r_max: float = math.inf

    @staticmethod
    def _key(x: float, y: float) -> str:
        az = math.degrees(math.atan2(y, x)) % 360.0
        sec = min(FLOOR_SECTORS - 1, int(az // (360.0 / FLOOR_SECTORS)))
        return f"{sec},{int(math.hypot(x, y) // RING_WIDTH_M)}"

    def covers(self, x: float, y: float) -> bool:
        return self._key(x, y) in self.floors

    def floor_at(self, x: float, y: float) -> Optional[float]:
        return self.floors.get(self._key(x, y))

    @property
    def sectors(self) -> List[int]:
        return sorted({int(k.split(",")[0]) for k in self.floors})

    def describe(self) -> str:
        rr = "" if self.r_max == math.inf else f"  reach {self.r_max:.3f} m"
        vals = list(self.floors.values())
        return (f"{self.name:<12} {len(self.floors)} cells across "
                f"{len(self.sectors)} bearings, floor "
                f"{min(vals):+.3f} to {max(vals):+.3f} m{rr}")


@dataclass
class Dome:
    """The taught volume. The floor is a polar GRID, not a profile.

    An earlier version varied the floor with bearing alone. That is wrong
    wherever the obstacle is near the base, which is the usual case: this arm
    sits on a cart, so it cannot descend close in but can drop far below the
    base plane once it reaches past the cart's edge. Recording only bearing
    took the deep reach demonstrated at 1.2 m and authorised the same depth at
    0.3 m -- straight into the cart.

    Measured on this cell, the lowest the arm was ever taken runs -0.018 m at
    0.2-0.4 m from the base axis, -0.161 m at 0.6-0.8 m, and -0.435 m at
    1.0-1.2 m. The floor is a function of both bearing and radius, so the grid
    is indexed by both.
    """
    r_max: float = 0.0
    z_ceiling: float = 0.0
    cells: Dict[str, float] = field(default_factory=dict)   # "sector,ring" -> floor
    zones: List["Zone"] = field(default_factory=list)

    @staticmethod
    def _key(x: float, y: float) -> str:
        az = math.degrees(math.atan2(y, x)) % 360.0
        sec = min(FLOOR_SECTORS - 1, int(az // (360.0 / FLOOR_SECTORS)))
        ring = int(math.hypot(x, y) // RING_WIDTH_M)
        return f"{sec},{ring}"

    @staticmethod
    def _parts(key: str) -> tuple:
        a, b = key.split(",")
        return int(a), int(b)

    @classmethod
    def from_points(cls, points: Sequence[Sequence[float]]) -> "Dome":
        cells: Dict[str, float] = {}
        r_max, z_ceiling = 0.0, -math.inf
        for p in points:
            r_max = max(r_max, math.sqrt(sum(v * v for v in p)))
            z_ceiling = max(z_ceiling, p[2])
            if math.hypot(p[0], p[1]) <= BASE_EXCLUSION_R:
                continue
            k = cls._key(p[0], p[1])
            cells[k] = min(cells.get(k, math.inf), p[2])
        return cls(r_max=r_max, z_ceiling=z_ceiling,
                   cells={k: round(v, 4) for k, v in cells.items()})

    def floor_at(self, x: float, y: float) -> float:
        """Lowest height allowed here. Zones win; then the demonstrated cell;
        then the most restrictive thing known further in.

        A cell nobody demonstrated inherits from the nearest INNER ring in the
        same bearing sector, because the floor rises as the arm comes closer to
        the base and inheriting inward is therefore the conservative direction.
        """
        zoned = [f for f in (z.floor_at(x, y) for z in self.zones) if f is not None]
        if zoned:
            return max(zoned)          # where zones overlap, the tighter wins
        if not self.cells:
            return -math.inf
        sec, ring = self._parts(self._key(x, y))
        if f"{sec},{ring}" in self.cells:
            return self.cells[f"{sec},{ring}"]
        inner = [self.cells[f"{sec},{r}"] for r in range(ring, -1, -1)
                 if f"{sec},{r}" in self.cells]
        if inner:
            return inner[0]
        return max(self.cells.values())

    def reach_at(self, x: float, y: float) -> float:
        r = self.r_max
        for z in self.zones:
            if z.covers(x, y):
                r = min(r, z.r_max)
        return r

    def zone_at(self, x: float, y: float) -> Optional["Zone"]:
        for z in self.zones:
            if z.covers(x, y):
                return z
        return None

    def outside(self, point: Sequence[float], tol_m: float = 0.01) -> Optional[str]:
        x, y, z = point
        r = math.sqrt(x * x + y * y + z * z)
        zone = self.zone_at(x, y)
        where = f" in zone '{zone.name}'" if zone else ""
        reach = self.reach_at(x, y)
        if r > reach + tol_m:
            return f"{r:.3f} m from the base, beyond the {reach:.3f} m allowed{where}"
        if z > self.z_ceiling + tol_m:
            return f"z {z:.3f} m, above the taught ceiling {self.z_ceiling:.3f} m"
        hr = math.hypot(x, y)
        if hr > BASE_EXCLUSION_R:
            floor = self.floor_at(x, y)
            if z < floor - tol_m:
                bearing = math.degrees(math.atan2(y, x)) % 360.0
                return (f"z {z:.3f} m at bearing {bearing:.0f} deg and {hr:.2f} m out, "
                        f"below the {floor:.3f} m taught there{where}")
        return None

    def describe(self) -> List[str]:
        step = 360 // FLOOR_SECTORS
        rings = sorted({self._parts(k)[1] for k in self.cells})
        lines = [f"  reach     out to {self.r_max:.3f} m from the base",
                 f"  ceiling   {self.z_ceiling:.3f} m",
                 f"  floor     grid of {len(self.cells)} taught cells "
                 f"({FLOOR_SECTORS} bearings x {len(rings)} rings of "
                 f"{RING_WIDTH_M:.2f} m)",
                 "            lowest demonstrated height by distance out:"]
        for ring in rings:
            vals = [v for k, v in self.cells.items() if self._parts(k)[1] == ring]
            lines.append(f"              {ring * RING_WIDTH_M:.1f}-"
                         f"{(ring + 1) * RING_WIDTH_M:.1f} m   "
                         f"{min(vals):>+7.3f} to {max(vals):>+7.3f} m  "
                         f"({len(vals)} of {FLOOR_SECTORS} bearings)")
        if self.zones:
            lines.append("  taught zones:")
            for z in self.zones:
                lines.append("      " + z.describe())
        return lines


@dataclass
class Violation:
    kind: str
    detail: str
    joints: List[float]

    def describe(self) -> str:
        deg = [round(math.degrees(q), 1) for q in self.joints]
        return f"{self.kind} outside taught envelope: {self.detail} at {deg} deg"


@dataclass
class Envelope:
    joint_min: List[float] = field(default_factory=list)
    joint_max: List[float] = field(default_factory=list)
    samples: int = 0
    marks: List[Dict] = field(default_factory=list)
    note: str = ""
    dome: Optional[Dome] = None

    # Joint ranges are RECORDED for the pendant's Joint Limits screen but not
    # enforced: they describe how the arm was posed while teaching, not where
    # it is safe. Set True only if you genuinely want to forbid configurations
    # that were never demonstrated.
    enforce_joints: bool = False
    joint_margin_rad: float = 0.05
    cartesian_tolerance_m: float = 0.01
    free_joints: List[int] = field(default_factory=list)

    @classmethod
    def from_samples(cls, joint_samples: Sequence[Sequence[float]],
                     note: str = "") -> "Envelope":
        if not joint_samples:
            raise ValueError("no samples recorded")
        qs = np.asarray(joint_samples, dtype=float)
        # Build the dome from every part of the arm at every taught pose, so
        # the volume covers where the elbow went and not just the tool.
        cloud = []
        for q in joint_samples:
            cloud.extend(arm_points(q))
        return cls(joint_min=qs.min(axis=0).tolist(),
                   joint_max=qs.max(axis=0).tolist(),
                   dome=Dome.from_points(cloud),
                   samples=len(joint_samples), note=note)

    # ------------------------------------------------------------ checking

    def contains(self, joints: Sequence[float]) -> Optional[Violation]:
        if self.enforce_joints:
            for i, q in enumerate(joints):
                if (i + 1) in self.free_joints:
                    continue
                lo_t, hi_t = self.joint_min[i], self.joint_max[i]
                margin = min(self.joint_margin_rad, (hi_t - lo_t) / 4.0)
                if not (lo_t + margin <= q <= hi_t - margin):
                    return Violation("joint",
                                     f"J{i + 1} at {math.degrees(q):.1f} deg, taught "
                                     f"{math.degrees(lo_t):.1f} to {math.degrees(hi_t):.1f}",
                                     list(joints))
        if self.dome is None:
            return None
        for p in arm_points(joints):
            why = self.dome.outside(p, tol_m=self.cartesian_tolerance_m)
            if why is not None:
                return Violation("arm", why, list(joints))
        return None

    def validate_path(self, waypoints: Sequence[Sequence[float]],
                      closed: bool = True,
                      samples_per_leg: int = 8) -> Optional[Violation]:
        poses = [list(wp[:6]) for wp in waypoints]
        if not poses:
            return None
        legs = list(zip(poses, poses[1:] + ([poses[0]] if closed and len(poses) > 1 else [])))
        for a, b in legs:
            av, bv = np.asarray(a), np.asarray(b)
            for k in range(samples_per_leg + 1):
                v = self.contains(list(av + (bv - av) * (k / samples_per_leg)))
                if v is not None:
                    return v
        return None

    # --------------------------------------------------------------- io

    def save(self, path: str = DEFAULT_PATH) -> str:
        data = asdict(self)
        # JSON has no infinity; an unlimited zone reach is stored as null.
        for z in (data.get("dome") or {}).get("zones", []):
            if z.get("r_max") == math.inf:
                z["r_max"] = None
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)
        return path

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Envelope":
        with open(path) as fh:
            data = json.load(fh)
        for gone in ("tcp_min", "tcp_max", "elbow_min", "elbow_max", "elbow_dome"):
            data.pop(gone, None)
        if isinstance(data.get("dome"), dict):
            d = data["dome"]
            data["dome"] = Dome(
                r_max=d.get("r_max", d.get("rmax", 0.0)),
                z_ceiling=d.get("z_ceiling", 0.0),
                cells=d.get("cells", {}),
                zones=[Zone(name=z.get("name", ""),
                            floors={str(k): v for k, v in (z.get("floors") or {}).items()},
                            r_max=(math.inf if z.get("r_max") is None else z["r_max"]))
                       for z in d.get("zones", []) if z.get("floors")],
            ) if "cells" in d else None
        return cls(**data)

    @classmethod
    def load_if_present(cls, path: str = DEFAULT_PATH) -> Optional["Envelope"]:
        try:
            return cls.load(path)
        except (OSError, TypeError, ValueError, KeyError):
            return None

    # ------------------------------------------------------------ reporting

    def narrow_joints(self, threshold_rad: float = 0.10) -> List[int]:
        return [i + 1 for i in range(6)
                if (self.joint_max[i] - self.joint_min[i]) < threshold_rad]

    def report(self) -> str:
        lines = [f"=== taught envelope ({self.samples} poses) ==="]
        if self.note:
            lines.append(f"note: {self.note}")
        if self.dome is not None:
            lines.append("\nTaught volume (this is what is enforced):")
            lines.extend(self.dome.describe())
            if self.dome.cells:
                spread = max(self.dome.cells.values()) - min(self.dome.cells.values())
                lines.append(f"\n  the floor varies by {spread:.2f} m across the grid -- it depends")
                lines.append("  on how far out the arm is, not only which way it points")

        lines.append("\nJoint ranges observed while teaching. NOT enforced (the arm may")
        lines.append("pose however it likes inside the volume). Useful for the pendant:")
        lines.append(f"  {'joint':>8} {'min deg':>9} {'max deg':>9}")
        for i in range(6):
            lines.append(f"  {'J' + str(i + 1):>8} {math.degrees(self.joint_min[i]):>9.1f} "
                         f"{math.degrees(self.joint_max[i]):>9.1f}")

        if self.marks:
            lines.append("\nMarked points:")
            for m in self.marks:
                deg = [round(math.degrees(q), 1) for q in m["joints"]]
                lines.append(f"  {m['name']:<20} {deg}")

        lines.append("\nSite pendant safety planes a little OUTSIDE these numbers and keep")
        lines.append("this envelope as the tighter software check in front of them.")
        return "\n".join(lines)
