"""
Blend-radius validation for URScript movej/movel paths.

The rule, verbatim from The URScript Programming Language v3.13 (movej, p.25):

    "If a blend radius is set, the robot arm trajectory will be modified to
     avoid the robot stopping at the point. However, if the blend region of
     this move overlaps with the blend radius of previous or following
     waypoints, this move will be SKIPPED, and an 'Overlapping Blends'
     warning message will be generated."

Two consequences the codebase did not account for:

1. r is in METRES OF TCP PATH, even for movej (the manual spells it out:
   "r = 0 -> the blend radius is zero meters"). It is a Cartesian sphere
   around the waypoint; joint-space travel is irrelevant to whether two
   blends overlap.

2. The failure mode is a SKIPPED WAYPOINT, not a gentle clamp. The arm does
   not slow down and pass through the point, it never goes there. That is a
   path-safety issue as much as a smoothness one.

So the constraint on every leg is:

    r[i] + r[i+1] <= tcp_distance(wp[i], wp[i+1])

with a margin, since the blends must not merely touch. A zero-length leg
(two geometrically identical consecutive waypoints) violates it for any
r > 0 and is always a bug.
"""

import math
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from control.pose_guard import tcp_xyz  # noqa: E402

# Blends that exactly touch are a coin flip on the controller's rounding.
# Require this much clear air between them (metres of TCP path).
BLEND_MARGIN_M = 0.005


@dataclass
class LegReport:
    index: int
    tcp_distance: float
    r_out: float          # blend radius of the waypoint the leg leaves
    r_in: float           # blend radius of the waypoint the leg arrives at
    joint_delta: float    # largest single-joint change on this leg (rad)

    @property
    def demand(self) -> float:
        return self.r_out + self.r_in

    @property
    def slack(self) -> float:
        return self.tcp_distance - self.demand

    @property
    def overlapping(self) -> bool:
        return self.slack < BLEND_MARGIN_M

    @property
    def degenerate(self) -> bool:
        """Zero-length leg: consecutive waypoints are the same pose."""
        return self.tcp_distance < 1e-6

    def describe(self) -> str:
        flag = ("DEGENERATE (zero-length leg)" if self.degenerate
                else "OVERLAP -> waypoint skipped" if self.overlapping
                else "ok")
        return (f"leg {self.index}: tcp {self.tcp_distance:.4f} m  "
                f"r_out {self.r_out:.3f} + r_in {self.r_in:.3f} = {self.demand:.3f}  "
                f"slack {self.slack:+.4f}  joint delta {self.joint_delta:.2f} rad  [{flag}]")


def analyse(waypoints: Sequence[Sequence[float]], closed: bool = True) -> List[LegReport]:
    """Per-leg blend feasibility for a [j1..j6, v, a, r] waypoint list."""
    n = len(waypoints)
    poses = [wp[:6] for wp in waypoints]
    radii = [wp[8] for wp in waypoints]
    pts = [tcp_xyz(p) for p in poses]

    legs = []
    count = n if closed else n - 1
    for i in range(count):
        j = (i + 1) % n
        legs.append(LegReport(
            index=i,
            tcp_distance=math.dist(pts[i], pts[j]),
            r_out=radii[i],
            r_in=radii[j],
            joint_delta=max(abs(a - b) for a, b in zip(poses[i], poses[j])),
        ))
    return legs


def problems(waypoints: Sequence[Sequence[float]], closed: bool = True) -> List[LegReport]:
    return [l for l in analyse(waypoints, closed) if l.overlapping or l.degenerate]


def suggest_radii(waypoints: Sequence[Sequence[float]], closed: bool = True,
                  fraction: float = 0.35) -> List[float]:
    """Largest per-waypoint radii that satisfy the overlap rule everywhere.

    Each waypoint's radius is capped at `fraction` of the shorter of its two
    adjoining legs, which guarantees r[i] + r[i+1] <= 0.7 * leg for every leg
    while keeping the blends as large (and therefore the motion as round) as
    the geometry allows. Degenerate legs force their waypoints to r = 0.
    """
    n = len(waypoints)
    poses = [wp[:6] for wp in waypoints]
    pts = [tcp_xyz(p) for p in poses]

    count = n if closed else n - 1
    leg_len = [math.dist(pts[i], pts[(i + 1) % n]) for i in range(count)]

    out = []
    for i in range(n):
        before = leg_len[(i - 1) % count] if (closed or i > 0) else math.inf
        after = leg_len[i] if (closed or i < count) else math.inf
        shortest = min(before, after)
        out.append(0.0 if shortest < 1e-6 else round(min(0.15, shortest * fraction), 4))
    return out


def dedupe(waypoints: Sequence[Sequence[float]],
           tol_m: float = 1e-6) -> List[List[float]]:
    """Drop waypoints that are geometrically identical to their predecessor.

    A zero-length leg cannot host a blend at any radius, and the arm has
    nowhere to travel, so the waypoint is pure cost: it forces the controller
    to resolve a blend against a degenerate segment. Several demos contain
    these (SprintDemo's 'Sprint Ctr' and 'Lower' are the same pose).
    """
    out: List[List[float]] = []
    for wp in waypoints:
        if out and math.dist(tcp_xyz(out[-1][:6]), tcp_xyz(wp[:6])) < tol_m:
            continue
        out.append(list(wp))
    # The path loops, so also collapse a final waypoint equal to the first.
    while len(out) > 2 and math.dist(tcp_xyz(out[-1][:6]), tcp_xyz(out[0][:6])) < tol_m:
        out.pop()
    return out


def repair(waypoints: Sequence[Sequence[float]], closed: bool = True,
           fraction: float = 0.35, only_reduce: bool = True) -> List[List[float]]:
    """Return a path with degenerate legs removed and legal blend radii.

    Speeds and accelerations are untouched: this changes only the geometry of
    the corners, never how fast the arm is asked to move.

    only_reduce (default) keeps any radius that was already legal, so the
    repair fixes violations without reshaping the parts of the choreography
    that were fine. Measured on Sprint, letting radii GROW to the geometric
    maximum rounded the long sweeps so much that peak TCP speed fell from
    0.67 to 0.55 m/s -- legal, but a visibly tamer motion. The author's
    radius is a choreographic choice; only the illegal ones need touching.
    """
    fixed = dedupe(waypoints)
    largest = suggest_radii(fixed, closed=closed, fraction=fraction)
    for wp, cap in zip(fixed, largest):
        wp[8] = min(wp[8], cap) if only_reduce else cap
    return fixed


def report(waypoints: Sequence[Sequence[float]], closed: bool = True,
           title: str = "") -> str:
    legs = analyse(waypoints, closed)
    bad = [l for l in legs if l.overlapping or l.degenerate]
    lines = [f"=== blend analysis{': ' + title if title else ''} ==="]
    lines += [l.describe() for l in legs]
    if bad:
        lines.append(f"--> {len(bad)} of {len(legs)} legs violate the overlap rule; "
                     f"the controller will SKIP those waypoints")
        lines.append(f"--> suggested radii: {suggest_radii(waypoints, closed)}")
    else:
        lines.append("--> all legs satisfy r[i] + r[i+1] <= tcp_leg_length")
    return "\n".join(lines)
