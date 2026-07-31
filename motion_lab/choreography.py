"""
Why a choreography is as fast as it is.

THE QUESTION THIS ANSWERS
------------------------
"The robot still isn't going fast" is usually blamed on a speed limit, and on
this cell that has almost always been wrong. A joint that must start and stop
inside a leg of length d, accelerating at a, never exceeds

    v_peak = sqrt(a * d)

regardless of the speed you command. Commanding 2.5 rad/s across a 0.18 rad
leg at 4.5 rad/s^2 gets you 0.90 rad/s and not one bit more. That is why
raising `a` unlocked the Sprint demo when raising `v` had done nothing.

So each leg is one of three things, and the fix differs completely:

  SPEED-LIMITED     v_cmd < sqrt(a*d).  The leg is long enough to reach the
                    commanded speed. Raising v does something. This is the
                    only case where a speed limit is the binding constraint.
  ACCEL-LIMITED     sqrt(a*d) < v_cmd, but a modest rise in a would close the
                    gap. Raise acceleration.
  GEOMETRY-LIMITED  the leg is so short that no plausible acceleration helps.
                    The choreography itself has to change: longer legs, fewer
                    waypoints, or blends that chain legs together.

BLENDS CHAIN LEGS
-----------------
A blend radius above zero means the arm does not stop at that waypoint, so a
run of consecutive legs driving the same joint the same way behaves like one
long leg and the joint keeps accelerating across all of them. That is why
shrinking blend radii to satisfy the overlap rule made Sprint TAMER (peak TCP
0.67 -> 0.55 m/s) and why `blend.repair()` only ever reduces where it must.
Runs are therefore computed across blended legs, not per leg.

THESE ARE ESTIMATES
-------------------
Triangular velocity profiles, ignoring the wrist's contribution to TCP speed
and the rounding a blend puts on a reversal. They are for deciding WHERE to
look and WHAT to change. What a demo actually did is a question for
telemetry.py, and every number here should be confirmed against a recording
before it is believed.

Author: jsecco (R)
"""

import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

from control import pose_guard  # noqa: E402

# UR10 per-joint maxima. The base and shoulder are held to 120 deg/s; elbow
# and wrists to 180 deg/s. A choreography led by the base hits a hardware wall
# at 2.09 rad/s no matter what the safety configuration allows, so a demo that
# wants to look fast is better off being led by the elbow or a wrist.
JOINT_CEILING = [2.09, 2.09, 3.14, 3.14, 3.14, 3.14]
JOINT_NAME = ["J1 base", "J2 shoulder", "J3 elbow",
              "J4 wrist1", "J5 wrist2", "J6 wrist3"]

# Below this, no acceleration we would dare command rescues the leg.
GEOMETRY_LIMIT_RAD = 0.12


@dataclass
class Leg:
    index: int
    dq: List[float]            # per-joint signed travel
    v_cmd: float
    a_cmd: float
    r: float                   # blend radius arriving at the far waypoint
    tcp_len: float

    @property
    def lead(self) -> int:
        return max(range(6), key=lambda j: abs(self.dq[j]))

    @property
    def d_lead(self) -> float:
        return abs(self.dq[self.lead])


@dataclass
class Run:
    """Consecutive legs a joint crosses without stopping."""
    joint: int
    legs: List[int]
    distance: float
    v_cmd: float
    a_cmd: float

    @property
    def v_geo(self) -> float:
        """Peak speed the geometry allows: triangular profile over the run."""
        return math.sqrt(self.a_cmd * self.distance)

    @property
    def v_peak(self) -> float:
        return min(self.v_cmd, self.v_geo, JOINT_CEILING[self.joint])

    @property
    def limited_by(self) -> str:
        if self.v_geo >= min(self.v_cmd, JOINT_CEILING[self.joint]):
            return "ceiling" if self.v_cmd >= JOINT_CEILING[self.joint] else "speed"
        if self.distance < GEOMETRY_LIMIT_RAD:
            return "geometry"
        return "accel"

    def accel_for(self, v_target: float) -> float:
        """Acceleration needed to reach v_target over this run."""
        return v_target * v_target / self.distance if self.distance > 0 else float("inf")


def legs_of(waypoints: Sequence[Sequence[float]], closed: bool = True) -> List[Leg]:
    """Legs of a program. Each waypoint carries the v/a/r of the move that
    ARRIVES at it, which is how URScript movej reads, so leg i->i+1 takes its
    parameters from waypoint i+1."""
    n = len(waypoints)
    out: List[Leg] = []
    last = n if closed else n - 1
    for i in range(last):
        a, b = waypoints[i], waypoints[(i + 1) % n]
        dq = [b[j] - a[j] for j in range(6)]
        tcp = math.dist(pose_guard.tcp_xyz(a[:6]), pose_guard.tcp_xyz(b[:6]))
        out.append(Leg(index=i, dq=dq, v_cmd=float(b[6]), a_cmd=float(b[7]),
                       r=float(b[8]) if len(b) > 8 else 0.0, tcp_len=tcp))
    return out


def runs_of(legs: Sequence[Leg], closed: bool = True) -> List[Run]:
    """Group legs into stretches a joint crosses without coming to rest.

    A run continues while the joint keeps moving the same way AND the waypoint
    between the legs is blended. A zero blend forces a stop; a sign change
    means the joint must reverse, and reverse it must decelerate to do.
    """
    out: List[Run] = []
    n = len(legs)
    if n == 0:
        return out
    for j in range(6):
        i = 0
        seen = set()
        while i < n:
            if i in seen:
                break
            if abs(legs[i].dq[j]) < 1e-9:
                i += 1
                continue
            sign = math.copysign(1.0, legs[i].dq[j])
            idx, dist = [], 0.0
            v = legs[i].v_cmd
            a = legs[i].a_cmd
            k = i
            steps = 0
            while steps < n:
                if not closed and k >= n:
                    break
                leg = legs[k % n]
                if abs(leg.dq[j]) < 1e-9:
                    break
                if math.copysign(1.0, leg.dq[j]) != sign:
                    break
                idx.append(k % n)
                seen.add(k % n)
                dist += abs(leg.dq[j])
                v, a = min(v, leg.v_cmd), min(a, leg.a_cmd)
                if leg.r <= 1e-9:            # a stop ends the run
                    k += 1
                    steps += 1
                    break
                k += 1
                steps += 1
            if idx:
                out.append(Run(joint=j, legs=idx, distance=dist, v_cmd=v, a_cmd=a))
            i = max(k, i + 1)
    return out


@dataclass
class DemoReport:
    name: str
    waypoints: int
    legs: List[Leg]
    runs: List[Run]
    lead_joint: int
    v_cmd: float
    a_cmd: float
    v_possible: float
    limited_by: str
    accel_to_ceiling: float
    clearance_m: Optional[float] = None
    clearance_solid: str = ""
    self_collision: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def ceiling(self) -> float:
        return JOINT_CEILING[self.lead_joint]

    @property
    def fraction(self) -> float:
        return self.v_possible / self.ceiling if self.ceiling else 0.0


def analyse(name: str, waypoints: Sequence[Sequence[float]],
            closed: bool = True, obstacles=None) -> DemoReport:
    legs = legs_of(waypoints, closed)
    runs = runs_of(legs, closed)

    # The demo's character is set by the joint that travels furthest overall,
    # not by whichever joint happens to lead one leg.
    travel = [sum(abs(l.dq[j]) for l in legs) for j in range(6)]
    lead = max(range(6), key=lambda j: travel[j])

    lead_runs = [r for r in runs if r.joint == lead] or runs
    best = max(lead_runs, key=lambda r: r.v_peak) if lead_runs else None
    v_possible = best.v_peak if best else 0.0
    limited = best.limited_by if best else "unknown"
    accel_needed = best.accel_for(JOINT_CEILING[lead]) if best else float("inf")

    rep = DemoReport(
        name=name, waypoints=len(waypoints), legs=legs, runs=runs,
        lead_joint=lead,
        v_cmd=max((l.v_cmd for l in legs), default=0.0),
        a_cmd=max((l.a_cmd for l in legs), default=0.0),
        v_possible=v_possible, limited_by=limited,
        accel_to_ceiling=accel_needed,
    )

    v = pose_guard.validate_path([list(w[:6]) for w in waypoints], closed=closed)
    if v is not None:
        rep.self_collision = v.describe() if hasattr(v, "describe") else str(v)

    if obstacles is not None and obstacles.solids:
        worst = None
        for w in waypoints:
            got = obstacles.worst(list(w[:6]))
            if got and (worst is None or got[0] < worst[0]):
                worst = got
        if worst:
            rep.clearance_m, rep.clearance_solid = worst[0], worst[1]

    short = [l for l in legs if l.d_lead < GEOMETRY_LIMIT_RAD]
    if short:
        rep.notes.append(f"{len(short)} of {len(legs)} legs are shorter than "
                         f"{GEOMETRY_LIMIT_RAD} rad on their leading joint")
    dead = [l for l in legs if l.d_lead < 1e-3]
    if dead:
        rep.notes.append(f"{len(dead)} legs move essentially nothing and only "
                         f"cost time")
    unblended = [l for l in legs if l.r <= 1e-9]
    if unblended:
        rep.notes.append(f"{len(unblended)} legs end in a full stop (r=0)")
    return rep


def describe(rep: DemoReport) -> str:
    L = []
    L.append(f"=== {rep.name} ===")
    L.append(f"  {rep.waypoints} waypoints, {len(rep.legs)} legs, "
             f"led by {JOINT_NAME[rep.lead_joint]} (ceiling "
             f"{rep.ceiling:.2f} rad/s)")
    L.append(f"  commanded      v {rep.v_cmd:.2f} rad/s   a {rep.a_cmd:.2f} rad/s^2")
    L.append(f"  achievable     {rep.v_possible:.2f} rad/s  "
             f"= {rep.fraction * 100:.0f}% of the joint's ceiling   "
             f"[{rep.limited_by}-limited]")
    if rep.limited_by == "accel":
        L.append(f"  to reach the ceiling on its longest run it would need "
                 f"a = {rep.accel_to_ceiling:.1f} rad/s^2")
    elif rep.limited_by == "geometry":
        L.append(f"  no acceleration fixes this: the longest run is only "
                 f"{max((r.distance for r in rep.runs if r.joint == rep.lead_joint), default=0):.2f} rad")
    if rep.clearance_m is not None:
        L.append(f"  clearance      {rep.clearance_m * 1000:.0f} mm to the "
                 f"{rep.clearance_solid}")
    if rep.self_collision:
        L.append(f"  SELF-COLLISION {rep.self_collision}")
    for n in rep.notes:
        L.append(f"  note           {n}")
    return "\n".join(L)
