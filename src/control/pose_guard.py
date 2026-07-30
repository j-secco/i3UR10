"""
Self-collision guard for UR10 demo choreographies.

Pure geometry, no robot I/O. Forward kinematics plus a calibrated capsule
model of the arm links, used to answer two questions:

  1. validate_path(): is a joint-space path (as executed by blended movej
     legs) free of self-collision, including the poses BETWEEN waypoints?
  2. max_safe_scale(): how far can a choreography's amplitude grow from the
     current saved home before the arm self-collides?

History: every protective stop in logs/safety_events.log clusters at an
elbow fold of ~166 deg. Demos apply fixed joint deltas relative to the
user-savable home pose, so re-saving home with a more folded elbow silently
pushed choreography targets into self-collision (PlungeDemo deep pose
reached a 177 deg fold from the 2026-07 home). This module is the systemic
fix: geometry is validated against the ACTUAL home before anything is sent
to the robot.

The FK and capsule model come from reach_map.py, whose predictions were
verified against a real protective stop: model said first contact at
J3=163.2 deg, the robot tripped at J3=165.8 deg.

Author: jsecco (R)
"""

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

# --- UR10 (CB-series) standard Denavit-Hartenberg parameters (meters / rad) ---
_A     = [0.0,      -0.612,   -0.5723,  0.0,       0.0,       0.0]
_D     = [0.1273,    0.0,      0.0,     0.163941,  0.1157,    0.0922]
_ALPHA = [math.pi/2, 0.0,      0.0,     math.pi/2, -math.pi/2, 0.0]

# --- capsule link radii (m), calibrated in reach_map.py against a known
# --- bow self-collision and known-good poses. ---
R_BASE_SHOULDER = 0.090
R_UPPER_ARM     = 0.075
R_FOREARM       = 0.060
R_WRIST         = 0.050
SAFETY_MARGIN   = 0.030   # extra clearance required beyond capsule surfaces


# ----------------------------- kinematics -----------------------------------

def _dh(a: float, d: float, alpha: float, theta: float) -> np.ndarray:
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st*ca,  st*sa, a*ct],
        [st,  ct*ca, -ct*sa, a*st],
        [0.0,  sa,     ca,    d  ],
        [0.0,  0.0,    0.0,   1.0],
    ])


def joint_origins(joints: Sequence[float]) -> List[np.ndarray]:
    """XYZ of each frame origin P0..P6 in the base frame."""
    T = np.eye(4)
    pts = [T[0:3, 3].copy()]
    for i in range(6):
        T = T @ _dh(_A[i], _D[i], _ALPHA[i], joints[i])
        pts.append(T[0:3, 3].copy())
    return pts


def tcp_xyz(joints: Sequence[float]) -> List[float]:
    return joint_origins(joints)[-1].tolist()


# ------------------------- self-collision model -----------------------------

def _seg_seg_distance(p1: np.ndarray, q1: np.ndarray,
                      p2: np.ndarray, q2: np.ndarray) -> float:
    """Minimum distance between segments p1q1 and p2q2 (clamped parametric)."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    EPS = 1e-9
    if a <= EPS and e <= EPS:
        return float(np.linalg.norm(p1 - p2))
    if a <= EPS:
        s, t = 0.0, np.clip(f / e, 0.0, 1.0)
    else:
        c = d1 @ r
        if e <= EPS:
            t, s = 0.0, np.clip(-c / a, 0.0, 1.0)
        else:
            b = d1 @ d2
            denom = a * e - b * b
            s = np.clip((b * f - c * e) / denom, 0.0, 1.0) if denom > EPS else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, np.clip(-c / a, 0.0, 1.0)
            elif t > 1.0:
                t, s = 1.0, np.clip((b - c) / a, 0.0, 1.0)
    c1, c2 = p1 + d1 * s, p2 + d2 * t
    return float(np.linalg.norm(c1 - c2))


# Each link is (origin_index_a, origin_index_b, radius).
_LINKS = {
    "base_shoulder": (0, 1, R_BASE_SHOULDER),
    "upper_arm":     (1, 2, R_UPPER_ARM),
    "forearm":       (2, 3, R_FOREARM),
    "wrist":         (3, 6, R_WRIST),
}
# Non-adjacent capsule pairs to test.
_PAIRS = [("upper_arm", "wrist"), ("base_shoulder", "forearm"), ("base_shoulder", "wrist")]


def collision_report(joints: Sequence[float]) -> Tuple[float, List[Tuple[str, str, float, float]]]:
    """Return (min_clearance, detail). Each detail row is
    (link_a, link_b, capsule_axis_distance, clearance). clearance < 0 means
    the capsules overlap once the safety margin is included."""
    P = joint_origins(joints)
    worst = math.inf
    detail = []
    for na, nb in _PAIRS:
        ia, ib, ra = _LINKS[na]
        ja, jb, rb = _LINKS[nb]
        d = _seg_seg_distance(P[ia], P[ib], P[ja], P[jb])
        clearance = d - (ra + rb) - SAFETY_MARGIN
        detail.append((na, nb, d, clearance))
        worst = min(worst, clearance)
    return worst, detail


def is_safe(joints: Sequence[float]) -> bool:
    return collision_report(joints)[0] >= 0.0


def fold_angles(joints: Sequence[float]) -> dict:
    """Bend angle (deg) at elbow/wrist joints: 0 = straight, 180 = doubled back."""
    P = joint_origins(joints)
    segs = [P[i+1] - P[i] for i in range(6)]

    def _angle(v1: np.ndarray, v2: np.ndarray) -> float:
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-9 or n2 < 1e-9:
            return 0.0
        c = float(np.clip((v1 @ v2) / (n1 * n2), -1.0, 1.0))
        return math.degrees(math.acos(c))

    return {name: _angle(segs[a], segs[b])
            for name, a, b in [("elbow", 1, 2), ("wrist1", 2, 3),
                               ("wrist2", 3, 4), ("wrist3", 4, 5)]}


# ------------------------------ path validation ------------------------------

@dataclass
class PathViolation:
    """First unsafe point found along a path."""
    leg:       int                  # index of the leg's START waypoint
    t:         float                # fraction along the leg (0..1)
    joints:    List[float]          # the offending pose
    clearance: float                # metres; negative = collision + margin
    pair:      Tuple[str, str]      # limiting capsule pair

    def describe(self) -> str:
        deg = [round(math.degrees(q), 1) for q in self.joints]
        return (f"leg {self.leg} t={self.t:.2f}: clearance {self.clearance:+.3f} m "
                f"({self.pair[0]}/{self.pair[1]}) at joints {deg} deg")


def validate_path(waypoints: Sequence[Sequence[float]],
                  closed: bool = True,
                  samples_per_leg: int = 8) -> Optional[PathViolation]:
    """
    Check a joint-space path for self-collision.

    waypoints: joint poses only (first 6 values of each row are used, so
    9-element [j1..j6, v, a, r] rows can be passed directly).
    closed: also check the wrap-around leg from the last waypoint back to
    the first (demo programs loop forever).

    movej interpolates in joint space, so each leg is sampled linearly.
    Blending (r>0) rounds corners BETWEEN legs and never leaves the union
    of the two legs' neighbourhoods, so sampling the straight legs bounds
    the executed path.

    Returns None if safe, else the first PathViolation.
    """
    poses = [list(wp[:6]) for wp in waypoints]
    if not poses:
        return None
    legs = list(zip(poses, poses[1:] + ([poses[0]] if closed and len(poses) > 1 else [])))
    for leg_idx, (a, b) in enumerate(legs):
        av, bv = np.asarray(a), np.asarray(b)
        for k in range(samples_per_leg + 1):
            t = k / samples_per_leg
            q = list(av + (bv - av) * t)
            worst, detail = collision_report(q)
            if worst < 0.0:
                lim = min(detail, key=lambda d: d[3])
                return PathViolation(leg=leg_idx, t=t, joints=q,
                                     clearance=worst, pair=(lim[0], lim[1]))
    return None


def max_safe_scale(build_path: Callable[[float], Sequence[Sequence[float]]],
                   hi: float = 1.0,
                   tol: float = 0.02,
                   closed: bool = True) -> float:
    """
    Largest amplitude scale s in [0, hi] for which build_path(s) validates.

    build_path(s) must return the choreography's waypoint poses with all
    amplitude deltas multiplied by s. Assumes safety is monotonic in s
    (larger amplitude = closer to collision), which holds for the demo
    choreographies where s=0 collapses to the (safe) home pose.
    """
    if validate_path(build_path(hi), closed=closed) is None:
        return hi
    lo = 0.0
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if validate_path(build_path(mid), closed=closed) is None:
            lo = mid
        else:
            hi = mid
    return lo
