"""
Measured keep-out solids: the cart, its post, and whatever stands on it.

WHY THIS BEATS A TAUGHT FLOOR
-----------------------------
A taught floor is evidence -- "the lowest the arm happened to reach here" --
so it is sparse, it under-approximates free space, and it never describes the
obstacle. A measured solid is the obstacle: a handful of numbers, exact,
re-checkable with a tape, and correct for poses nobody ever demonstrated.

Each solid is a vertical PRISM: a polygon footprint in the robot's base frame
extruded down to the floor. That covers a cart, a post, a monitor or a
keyboard tray without assuming any of them line up with the robot's axes,
which they generally do not.

Measurements come from the robot itself. Hand-guiding the flange to a corner
and reading its position puts the number straight into the base frame, with
none of the transform arithmetic that makes tape measurements go wrong.

THE ARM HAS THICKNESS
---------------------
Links are capsules, not lines -- the upper arm is 75 mm in radius. A point
test on the link centreline would let the surface of the arm pass through a
solid while the centreline cleared it, so every test is capsule-aware: the
link's own radius plus a clearance margin.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from control.pose_guard import _LINKS, joint_origins

# Sampling along a link when testing it against a solid. At 20 mm a link
# cannot straddle a solid without some sample landing within its own radius
# of it, so nothing can tunnel through.
LINK_SAMPLE_M = 0.02

DEFAULT_MARGIN_M = 0.05

# Index of the first link whose position depends on the joint angles.
FIRST_MOVING_LINK = 1


def point_in_polygon(x: float, y: float, poly: Sequence[Sequence[float]]) -> bool:
    """Ray casting. Polygon is a list of (x, y), implicitly closed."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def _seg_point_distance(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def distance_to_polygon(x: float, y: float, poly: Sequence[Sequence[float]]) -> float:
    """Horizontal distance to the footprint, 0 inside it."""
    if point_in_polygon(x, y, poly):
        return 0.0
    n = len(poly)
    return min(_seg_point_distance(x, y, poly[i][0], poly[i][1],
                                   poly[(i + 1) % n][0], poly[(i + 1) % n][1])
               for i in range(n))


@dataclass
class Prism:
    """A measured solid: polygon footprint extruded between two heights."""
    name: str = ""
    polygon: List[List[float]] = field(default_factory=list)
    z_top: float = 0.0
    z_bottom: float = -3.0          # to the floor unless stated
    margin: float = DEFAULT_MARGIN_M

    def clearance(self, p: Sequence[float], radius: float = 0.0) -> float:
        """How much room is left between a sphere at `p` and this solid.

        Negative means overlap. Only the horizontal gap is returned when the
        point is within the solid's height band; above the top the vertical
        gap is what matters, and the smaller of the two governs.
        """
        x, y, z = p
        need = radius + self.margin
        horiz = distance_to_polygon(x, y, self.polygon) - need
        if self.z_bottom - need <= z <= self.z_top + need:
            return horiz
        vert = (self.z_bottom - need - z) if z < self.z_bottom else (z - self.z_top - need)
        if horiz >= 0.0:
            return math.hypot(max(0.0, horiz), max(0.0, vert)) if vert > 0 else horiz
        return vert

    def hits(self, p: Sequence[float], radius: float = 0.0) -> bool:
        return self.clearance(p, radius) < 0.0


def link_radii() -> List[float]:
    """Radius of each consecutive link in the kinematic chain."""
    by_index = {}
    for _, (a, b, r) in _LINKS.items():
        for i in range(a, b):
            by_index[i] = max(by_index.get(i, 0.0), r)
    return [by_index.get(i, 0.05) for i in range(6)]


@dataclass
class ObstacleSet:
    solids: List[Prism] = field(default_factory=list)

    def worst(self, joints: Sequence[float]) -> Optional[tuple]:
        """Closest approach of the arm to any solid.

        Returns (clearance, solid_name, point) or None with no solids. Every
        link is sampled and carries its own radius, so the arm's surface is
        what is tested, not its centreline.
        """
        if not self.solids:
            return None
        chain = joint_origins(joints)
        radii = link_radii()
        best = None
        # Link 0 runs from the base origin up to the shoulder, along the axis
        # J1 turns about, so it occupies the same space at every pose. On this
        # cell the robot is bolted to the cart, which means that column is
        # permanently "intersecting" it. Structure that cannot move cannot
        # newly collide, so it is not tested; the first link that can is 1.
        for i, (a, b) in enumerate(zip(chain, chain[1:])):
            if i < FIRST_MOVING_LINK:
                continue
            length = math.dist(a, b)
            n = max(2, int(length / LINK_SAMPLE_M) + 1)
            r = radii[i]
            for k in range(n + 1):
                t = k / n
                p = [a[j] + (b[j] - a[j]) * t for j in range(3)]
                for solid in self.solids:
                    c = solid.clearance(p, r)
                    if best is None or c < best[0]:
                        best = (c, solid.name, p)
        return best

    def blocked(self, joints: Sequence[float]) -> Optional[str]:
        w = self.worst(joints)
        if w is None or w[0] >= 0.0:
            return None
        c, name, p = w
        return (f"arm intersects '{name}' by {-c * 1000:.0f} mm at "
                f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})")

    def to_json(self) -> List[Dict]:
        return [{"name": s.name, "polygon": s.polygon, "z_top": s.z_top,
                 "z_bottom": s.z_bottom, "margin": s.margin} for s in self.solids]

    @classmethod
    def from_json(cls, data) -> "ObstacleSet":
        return cls(solids=[Prism(**d) for d in (data or [])])

    def describe(self) -> List[str]:
        if not self.solids:
            return ["  none measured"]
        lines = []
        for s in self.solids:
            xs = [p[0] for p in s.polygon]
            ys = [p[1] for p in s.polygon]
            lines.append(f"      {s.name:<14} {len(s.polygon)}-sided footprint  "
                         f"x {min(xs):+.3f}..{max(xs):+.3f}  y {min(ys):+.3f}..{max(ys):+.3f}  "
                         f"top {s.z_top:+.3f} m  margin {s.margin * 1000:.0f} mm")
        return lines
