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

FLOOR_SECTORS = 12          # 30 degrees each
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
class Dome:
    """The taught volume: a solid dome with a bearing-dependent floor."""
    r_max: float = 0.0
    z_ceiling: float = 0.0
    sector_floors: List[float] = field(default_factory=list)   # len == FLOOR_SECTORS

    @staticmethod
    def _sector(x: float, y: float) -> int:
        az = math.degrees(math.atan2(y, x)) % 360.0
        return min(FLOOR_SECTORS - 1, int(az // (360.0 / FLOOR_SECTORS)))

    @classmethod
    def from_points(cls, points: Sequence[Sequence[float]]) -> "Dome":
        buckets: Dict[int, List[float]] = {i: [] for i in range(FLOOR_SECTORS)}
        r_max = 0.0
        z_ceiling = -math.inf
        for p in points:
            r_max = max(r_max, math.sqrt(sum(v * v for v in p)))
            z_ceiling = max(z_ceiling, p[2])
            buckets[cls._sector(p[0], p[1])].append(p[2])

        taught = [min(v) for v in buckets.values() if v]
        # A sector nobody demonstrated gets the most restrictive floor that
        # was demonstrated anywhere. Refusing to guess downward is the whole
        # point of teaching.
        fallback = max(taught) if taught else 0.0
        floors = [min(buckets[i]) if buckets[i] else fallback
                  for i in range(FLOOR_SECTORS)]
        return cls(r_max=r_max, z_ceiling=z_ceiling, sector_floors=floors)

    def floor_at(self, x: float, y: float) -> float:
        if not self.sector_floors:
            return -math.inf
        return self.sector_floors[self._sector(x, y)]

    def outside(self, point: Sequence[float], tol_m: float = 0.01) -> Optional[str]:
        x, y, z = point
        r = math.sqrt(x * x + y * y + z * z)
        if r > self.r_max + tol_m:
            return f"{r:.3f} m from the base, beyond the taught {self.r_max:.3f} m"
        if z > self.z_ceiling + tol_m:
            return f"z {z:.3f} m, above the taught ceiling {self.z_ceiling:.3f} m"
        if math.hypot(x, y) > BASE_EXCLUSION_R:
            floor = self.floor_at(x, y)
            if z < floor - tol_m:
                bearing = math.degrees(math.atan2(y, x)) % 360.0
                return (f"z {z:.3f} m at bearing {bearing:.0f} deg, below the "
                        f"{floor:.3f} m taught in that direction")
        return None

    def describe(self) -> List[str]:
        step = 360 // FLOOR_SECTORS
        lines = [f"  reach     out to {self.r_max:.3f} m from the base",
                 f"  ceiling   {self.z_ceiling:.3f} m",
                 f"  floor     varies with bearing:"]
        for i, f in enumerate(self.sector_floors):
            lines.append(f"      {i * step:>3}-{(i + 1) * step:<3} deg   {f:>7.3f} m")
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
        with open(path, "w") as fh:
            json.dump(asdict(self), fh, indent=2)
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
                sector_floors=d.get("sector_floors", []),
            ) if "sector_floors" in d else None
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
            spread = max(self.dome.sector_floors) - min(self.dome.sector_floors)
            if spread > 0.10:
                lines.append(f"\n  the floor varies by {spread:.2f} m with bearing -- a single")
                lines.append("  global floor would be permissive where the obstacles are")

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
