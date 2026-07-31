"""
Taught workspace envelope: what the operator demonstrated is safe.

NOT A SAFETY FUNCTION. This is a software pre-check running on the control
PC. It can crash, lag, or be skipped, and nothing certifies it. Its job is to
(a) stop the lab from ever *commanding* a path outside the region you taught,
and (b) produce the numbers to enter into the PolyScope Safety configuration,
which IS enforced by the robot's separate safety processor.

Treat the pendant as the fence and this as the guard rail before it.

The envelope records more than a TCP box, because the tool is not the only
part of the arm that can hit something:
  - per-joint minimum and maximum (these map straight onto the pendant's
    Joint Limits tab)
  - TCP bounding box and floor
  - elbow bounding box -- the elbow swings wide on a UR10 and is the classic
    thing to forget; UR's own safety system monitors it separately
"""

import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from control.pose_guard import joint_origins, tcp_xyz

ELBOW_INDEX = 2   # frame origin P2 in the DH chain is the elbow

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "workspace_envelope.json")


def _wrap(angle: float) -> float:
    """Map an angle into (-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def spherical(point: Sequence[float]) -> tuple:
    """(radius, azimuth, elevation) of a point about the robot base origin.

    azimuth is the compass bearing in the base XY plane; elevation is the
    angle above (positive) or below (negative) that plane.
    """
    x, y, z = point
    r = math.sqrt(x * x + y * y + z * z)
    if r < 1e-9:
        return 0.0, 0.0, 0.0
    return r, math.atan2(y, x), math.asin(max(-1.0, min(1.0, z / r)))


@dataclass
class Dome:
    """The reachable region as a spherical shell sector about the base.

    An arm's workspace is a dome, not a box. Describing it as "this far out,
    this high, this low, through this arc" is both a far tighter fit than six
    flat planes and the way an operator actually thinks about it: a box drawn
    around a swung arm contains large corners the arm can never occupy, and
    declaring those safe is exactly the wrong error.
    """
    r_min: float = 0.0
    r_max: float = 0.0
    elevation_min: float = 0.0
    elevation_max: float = 0.0
    azimuth_center: float = 0.0
    azimuth_lo: float = 0.0      # signed offset from centre, radians
    azimuth_hi: float = 0.0
    z_floor: float = 0.0

    @classmethod
    def from_points(cls, points: Sequence[Sequence[float]]) -> "Dome":
        rs, els, azs, zs = [], [], [], []
        for p in points:
            r, az, el = spherical(p)
            rs.append(r); azs.append(az); els.append(el); zs.append(p[2])
        # Circular mean, so a sector spanning the +/-pi seam is handled
        # without the min/max of raw angles collapsing to the whole circle.
        cx = sum(math.cos(a) for a in azs) / len(azs)
        cy = sum(math.sin(a) for a in azs) / len(azs)
        centre = math.atan2(cy, cx)
        deltas = [_wrap(a - centre) for a in azs]
        return cls(r_min=min(rs), r_max=max(rs),
                   elevation_min=min(els), elevation_max=max(els),
                   azimuth_center=centre,
                   azimuth_lo=min(deltas), azimuth_hi=max(deltas),
                   z_floor=min(zs))

    def outside(self, point: Sequence[float], tol_m: float = 0.01,
                tol_rad: float = 0.02) -> Optional[str]:
        r, az, el = spherical(point)
        if r < self.r_min - tol_m:
            return f"radius {r:.3f} m, inside the taught {self.r_min:.3f} m"
        if r > self.r_max + tol_m:
            return f"radius {r:.3f} m, beyond the taught {self.r_max:.3f} m"
        if point[2] < self.z_floor - tol_m:
            return f"z {point[2]:.3f} m, below the taught floor {self.z_floor:.3f} m"
        if not (self.elevation_min - tol_rad <= el <= self.elevation_max + tol_rad):
            return (f"elevation {math.degrees(el):.1f} deg, taught "
                    f"{math.degrees(self.elevation_min):.1f} to "
                    f"{math.degrees(self.elevation_max):.1f}")
        d = _wrap(az - self.azimuth_center)
        if not (self.azimuth_lo - tol_rad <= d <= self.azimuth_hi + tol_rad):
            return (f"bearing {math.degrees(az):.1f} deg, taught arc "
                    f"{math.degrees(self.azimuth_center + self.azimuth_lo):.1f} to "
                    f"{math.degrees(self.azimuth_center + self.azimuth_hi):.1f}")
        return None

    def describe(self) -> List[str]:
        return [
            f"  reach      {self.r_min:.3f} to {self.r_max:.3f} m from the base",
            f"  bearing    {math.degrees(self.azimuth_center + self.azimuth_lo):>7.1f} to "
            f"{math.degrees(self.azimuth_center + self.azimuth_hi):>7.1f} deg "
            f"(arc {math.degrees(self.azimuth_hi - self.azimuth_lo):.0f} deg)",
            f"  elevation  {math.degrees(self.elevation_min):>7.1f} to "
            f"{math.degrees(self.elevation_max):>7.1f} deg about the base plane",
            f"  floor      {self.z_floor:.3f} m",
        ]


@dataclass
class Violation:
    kind: str          # "joint" | "tcp" | "elbow"
    detail: str
    joints: List[float]

    def describe(self) -> str:
        deg = [round(math.degrees(q), 1) for q in self.joints]
        return f"{self.kind} outside taught envelope: {self.detail} at {deg} deg"


@dataclass
class Envelope:
    """Bounds derived from a hand-guided teaching session."""
    joint_min: List[float] = field(default_factory=list)
    joint_max: List[float] = field(default_factory=list)
    tcp_min: List[float] = field(default_factory=list)
    tcp_max: List[float] = field(default_factory=list)
    elbow_min: List[float] = field(default_factory=list)
    elbow_max: List[float] = field(default_factory=list)
    samples: int = 0
    marks: List[Dict] = field(default_factory=list)
    note: str = ""

    # Spherical sector about the base. This is the primary check for the TCP:
    # it fits an arm's real workspace far more tightly than the boxes, which
    # are retained mainly because the pendant's safety planes are planes.
    #
    # Deliberately NOT applied to the elbow. The elbow tracks close to the
    # base axis, where bearing and elevation are ill-conditioned: a few
    # centimetres of real movement swings elevation by tens of degrees, so a
    # dome fitted to it rejects poses that were plainly taught. The elbow is
    # bounded by its box instead, which is well behaved over its smaller
    # range of motion.
    dome: Optional[Dome] = None

    # Joint ranges are SHRUNK by this much: the operator guided the arm to
    # where it was safe, not past it, so the taught extreme needs headroom for
    # the overshoot a blend produces.
    joint_margin_rad: float = 0.05

    # Cartesian bounds are EXPANDED by this much, which is the opposite
    # treatment and deliberate. The TCP and elbow boxes are the bounding box
    # of a curve, so they already over-approximate where the arm actually
    # went; shrinking them again rejects poses that were genuinely taught.
    # Their job is to catch joint combinations that sit inside the joint box
    # but fling the arm somewhere never demonstrated, and a small tolerance
    # keeps that check from firing on its own discretisation.
    cartesian_tolerance_m: float = 0.01

    # Joints (1-6) exempt from the per-joint range check, bounded by the
    # Cartesian extents alone. Use when a joint was deliberately held still
    # during teaching but must still be free to move -- typically the wrists,
    # whose rotation the TCP and elbow boxes already constrain.
    free_joints: List[int] = field(default_factory=list)

    # ------------------------------------------------------------- building

    @classmethod
    def from_samples(cls, joint_samples: Sequence[Sequence[float]],
                     note: str = "") -> "Envelope":
        if not joint_samples:
            raise ValueError("no samples recorded")
        qs = np.asarray(joint_samples, dtype=float)
        tcps = np.asarray([tcp_xyz(q) for q in joint_samples], dtype=float)
        elbows = np.asarray([joint_origins(q)[ELBOW_INDEX] for q in joint_samples],
                            dtype=float)
        return cls(
            joint_min=qs.min(axis=0).tolist(),
            joint_max=qs.max(axis=0).tolist(),
            tcp_min=tcps.min(axis=0).tolist(),
            tcp_max=tcps.max(axis=0).tolist(),
            elbow_min=elbows.min(axis=0).tolist(),
            elbow_max=elbows.max(axis=0).tolist(),
            dome=Dome.from_points(tcps.tolist()),
            samples=len(joint_samples),
            note=note,
        )

    # ------------------------------------------------------------ checking

    def contains(self, joints: Sequence[float]) -> Optional[Violation]:
        """None if this pose is safely inside the taught region."""
        for i, q in enumerate(joints):
            if (i + 1) in self.free_joints:
                continue
            lo_t, hi_t = self.joint_min[i], self.joint_max[i]
            # Never let the margin invert a narrow range. A joint that was
            # taught as fixed keeps a zero-width window, so any motion on it
            # is refused -- which is the intended answer.
            margin = min(self.joint_margin_rad, (hi_t - lo_t) / 4.0)
            if not (lo_t + margin <= q <= hi_t - margin):
                return Violation("joint",
                                 f"J{i + 1} at {math.degrees(q):.1f} deg, taught range "
                                 f"{math.degrees(lo_t):.1f} to {math.degrees(hi_t):.1f}",
                                 list(joints))

        tol = self.cartesian_tolerance_m
        tcp = tcp_xyz(joints)
        elbow = list(joint_origins(joints)[ELBOW_INDEX])

        # The dome is the tighter and more meaningful test, so it runs first
        # and its message is the one worth reading.
        if self.dome is not None:
            why = self.dome.outside(tcp, tol_m=tol)
            if why is not None:
                return Violation("tcp", why, list(joints))

        for label, point, lo_b, hi_b in (("tcp", tcp, self.tcp_min, self.tcp_max),
                                         ("elbow", elbow, self.elbow_min, self.elbow_max)):
            for axis, name in enumerate("xyz"):
                if not (lo_b[axis] - tol <= point[axis] <= hi_b[axis] + tol):
                    return Violation(label,
                                     f"{name}={point[axis]:.3f} m, taught range "
                                     f"{lo_b[axis]:.3f} to {hi_b[axis]:.3f}",
                                     list(joints))
        return None

    def validate_path(self, waypoints: Sequence[Sequence[float]],
                      closed: bool = True,
                      samples_per_leg: int = 8) -> Optional[Violation]:
        """Check waypoints and the interpolated poses between them."""
        poses = [list(wp[:6]) for wp in waypoints]
        if not poses:
            return None
        legs = list(zip(poses, poses[1:] + ([poses[0]] if closed and len(poses) > 1 else [])))
        for a, b in legs:
            av, bv = np.asarray(a), np.asarray(b)
            for k in range(samples_per_leg + 1):
                q = list(av + (bv - av) * (k / samples_per_leg))
                v = self.contains(q)
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
        # asdict() flattens the nested domes to plain dicts; rebuild them or
        # the guard silently degrades to box-only checking.
        data.pop("elbow_dome", None)   # dropped: ill-conditioned near the base
        if isinstance(data.get("dome"), dict):
            data["dome"] = Dome(**data["dome"])
        return cls(**data)

    @classmethod
    def load_if_present(cls, path: str = DEFAULT_PATH) -> Optional["Envelope"]:
        try:
            return cls.load(path)
        except (OSError, TypeError, ValueError):
            return None

    # ------------------------------------------------------------ reporting

    def narrow_joints(self, threshold_rad: float = 0.10) -> List[int]:
        """Joints whose taught span is so small that the guard will treat them
        as fixed. Marking corners with the wrist held in one orientation is the
        usual cause, and it silently forbids every choreography that rotates
        it -- so this is worth surfacing rather than discovering later."""
        return [i + 1 for i in range(6)
                if (self.joint_max[i] - self.joint_min[i]) < threshold_rad]

    def report(self) -> str:
        lines = [f"=== taught envelope ({self.samples} samples) ==="]
        if self.note:
            lines.append(f"note: {self.note}")
        lines.append("\nJoint limits -- enter these on the pendant under")
        lines.append("Installation > Safety > Joint Limits (Position tab):")
        lines.append(f"  {'joint':>8} {'min deg':>9} {'max deg':>9} {'span':>8}")
        for i in range(6):
            lo, hi = math.degrees(self.joint_min[i]), math.degrees(self.joint_max[i])
            lines.append(f"  {'J' + str(i + 1):>8} {lo:>9.1f} {hi:>9.1f} {hi - lo:>8.1f}")

        if self.dome is not None:
            lines.append("\nReachable dome about the base (the primary check):")
            lines.extend(self.dome.describe())
        lines.append("\nCartesian extent (metres), for siting safety planes:")
        for label, lo_b, hi_b in (("tcp", self.tcp_min, self.tcp_max),
                                  ("elbow", self.elbow_min, self.elbow_max)):
            for axis, name in enumerate("xyz"):
                lines.append(f"  {label:>6} {name}: {lo_b[axis]:>7.3f} to {hi_b[axis]:>7.3f}")
        lines.append(f"\n  floor: the lowest the TCP reached was "
                     f"{self.tcp_min[2]:.3f} m, the elbow {self.elbow_min[2]:.3f} m")

        if self.marks:
            lines.append("\nMarked points:")
            for m in self.marks:
                deg = [round(math.degrees(q), 1) for q in m["joints"]]
                lines.append(f"  {m['name']:<20} {deg}")

        narrow = self.narrow_joints()
        if narrow:
            names = ", ".join(f"J{j}" for j in narrow)
            lines.append(f"\n!! {names} barely moved during teaching, so the guard will")
            lines.append("!! treat them as FIXED and refuse any path that rotates them.")
            lines.append("!! If a demo needs those joints, teach again while moving them,")
            lines.append("!! or re-run with --free-joints to bound them by Cartesian")
            lines.append("!! extent alone.")

        lines.append("\nA safety plane placed at a taught extreme leaves no room for "
                     "\nblend overshoot. Site planes a little OUTSIDE these numbers, "
                     "\nand keep this envelope as the tighter software check.")
        return "\n".join(lines)
