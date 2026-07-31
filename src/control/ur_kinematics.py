"""
Closed-form inverse kinematics for the UR10 (CB series).

WHY THIS EXISTS
---------------
Everything in motion_lab up to now specified poses in JOINT space: take home,
add an offset to J2 and J3, rotate J1. That is safe and easy to validate, but
it cannot answer the only question an operator actually asks, which is "put
the tool THERE".

exp05 showed what happens when you dodge that question. It searched J2/J3 for
poses whose closest approach to the cart was 150 mm, and it found them -- but
the closest part of the arm was always the forearm, 22 cm behind the tool, so
the tool itself was never constrained at all. Replaying the search afterwards,
the tool landed anywhere from 0.39 m to 0.88 m from the base at heights from
0.14 m to 0.44 m. The clearances it reported were true; the positions were
arbitrary. Cartesian intent needs a Cartesian solve.

APPROACH
--------
Analytic, not iterative. The UR wrist is spherical, so the arm admits a closed
form with up to 8 branches: shoulder left/right, elbow up/down, wrist
flipped/not. All 8 are returned and the CALLER chooses, which matters here --
one branch may be perfectly clear of the cart while another drives the elbow
straight through it, and an iterative solver seeded from the current pose
would simply never see the good one.

Derivation follows Hawkins, "Analytic Inverse Kinematics for the Universal
Robots UR-5/UR-10" (2013), using the same nominal DH parameters as the
forward kinematics in pose_guard, so FK and IK cannot drift apart.

ACCURACY
--------
Nominal DH, not this robot's factory calibration: the controller stores small
per-joint deltas that PolyScope applies and we do not have. Measured against
the robot's own reported TCP, our FK agrees to about 5 mm, and that is the
accuracy to expect from a position commanded through here. Fine for pointing
the arm at a spot in the cell; not a substitute for a taught waypoint if you
ever need to hit something repeatably.

Author: jsecco (R)
"""

import math
from typing import List, Optional, Sequence

import numpy as np

from control.pose_guard import _A, _ALPHA, _D, _dh

# Named for readability; these are the same numbers pose_guard uses for FK.
_d1, _d4, _d5, _d6 = _D[0], _D[3], _D[4], _D[5]
_a2, _a3 = _A[1], _A[2]

ZERO_THRESH = 1e-8


def fk_matrix(joints: Sequence[float]) -> np.ndarray:
    """Full 4x4 base-to-tool transform."""
    T = np.eye(4)
    for i in range(6):
        T = T @ _dh(_A[i], _D[i], _ALPHA[i], joints[i])
    return T


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _wrap(a: float) -> float:
    """To (-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))


def ik(T: np.ndarray) -> List[List[float]]:
    """Every joint solution that reaches pose T. Up to 8; fewer near
    singularities or when the pose is out of reach."""
    nx, ny = T[0, 0], T[1, 0]
    ox, oy = T[0, 1], T[1, 1]
    px, py, pz = T[0, 3], T[1, 3], T[2, 3]
    zx, zy, zz = T[0, 2], T[1, 2], T[2, 2]

    sols: List[List[float]] = []

    # --- theta1: the shoulder must swing so the wrist centre lies on a
    # --- cylinder of radius d4 about the base axis. Two ways round. ---
    p05 = np.array([px, py, pz]) - _d6 * np.array([zx, zy, zz])
    R = math.hypot(p05[0], p05[1])
    if R < abs(_d4):
        return []                      # wrist centre inside the cylinder
    phi1 = math.atan2(p05[1], p05[0])
    phi2 = math.acos(_clamp(_d4 / R))
    for t1 in (_wrap(phi1 + phi2 + math.pi / 2), _wrap(phi1 - phi2 + math.pi / 2)):
        s1, c1 = math.sin(t1), math.cos(t1)

        # --- theta5: wrist flip. ---
        c5 = _clamp((px * s1 - py * c1 - _d4) / _d6)
        for t5 in (math.acos(c5), -math.acos(c5)):
            s5 = math.sin(t5)
            if abs(s5) < ZERO_THRESH:
                # Wrist singular: J4 and J6 are the same axis, no unique split.
                continue
            # Projections of the tool's x and y axes onto frame 1. Note this
            # pairs the two AXES (columns of R06), not the two components of
            # one axis: the transposed grouping is a common typo, reproduces
            # theta6 to within 180 deg, and then quietly corrupts T14 and
            # every joint solved from it.
            t6 = math.atan2((-ox * s1 + oy * c1) / s5, (nx * s1 - ny * c1) / s5)

            # --- reduce to a planar 2-link problem for the arm. ---
            T01 = _dh(_A[0], _D[0], _ALPHA[0], t1)
            T45 = _dh(_A[4], _D[4], _ALPHA[4], t5)
            T56 = _dh(_A[5], _D[5], _ALPHA[5], t6)
            T14 = np.linalg.inv(T01) @ T @ np.linalg.inv(T56) @ np.linalg.inv(T45)
            p13 = (T14 @ np.array([0.0, -_d4, 0.0, 1.0]))[:3]
            L = math.hypot(p13[0], p13[1])
            if L > abs(_a2) + abs(_a3) or L < abs(abs(_a2) - abs(_a3)):
                continue               # out of reach for this branch
            c3 = _clamp((L * L - _a2 * _a2 - _a3 * _a3) / (2 * _a2 * _a3))

            # --- theta3: elbow up or down. ---
            for t3 in (math.acos(c3), -math.acos(c3)):
                t2 = -math.atan2(p13[1], -p13[0]) + math.asin(
                    _clamp(_a3 * math.sin(t3) / L))
                T12 = _dh(_A[1], _D[1], _ALPHA[1], t2)
                T23 = _dh(_A[2], _D[2], _ALPHA[2], t3)
                T34 = np.linalg.inv(T12 @ T23) @ T14
                t4 = math.atan2(T34[1, 0], T34[0, 0])
                sols.append([_wrap(t1), _wrap(t2), _wrap(t3),
                             _wrap(t4), _wrap(t5), _wrap(t6)])
    return sols


def nearest_turn(target: float, reference: float) -> float:
    """`target` shifted by whole turns to sit as close to `reference` as
    possible. IK returns angles in (-pi, pi]; the robot's joints are wound
    wherever they happen to be, and J4 in particular often sits past -180 deg.
    Commanding the wrapped value would unwind the joint the long way round."""
    return target + 2 * math.pi * round((reference - target) / (2 * math.pi))


def unwind_to(sol: Sequence[float], reference: Sequence[float]) -> List[float]:
    """A solution expressed in the turn closest to where the joints are now."""
    return [nearest_turn(s, r) for s, r in zip(sol, reference)]


def joint_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Total joint travel between two configurations (rad)."""
    return sum(abs(x - y) for x, y in zip(a, b))


def tool_down_pose(x: float, y: float, z: float,
                   yaw: Optional[float] = None) -> np.ndarray:
    """Target pose with the tool pointing straight down at (x, y, z)."""
    if yaw is None:
        yaw = math.atan2(y, x)
    c, s = math.cos(yaw), math.sin(yaw)
    # z axis down, x axis along the outward radial direction.
    return np.array([
        [c,  s,  0.0, x],
        [s, -c,  0.0, y],
        [0.0, 0.0, -1.0, z],
        [0.0, 0.0, 0.0, 1.0],
    ])


def pose_with_orientation(x: float, y: float, z: float,
                          R: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T


def solve_position(x: float, y: float, z: float,
                   reference: Sequence[float],
                   orientations: Optional[List[np.ndarray]] = None
                   ) -> List[List[float]]:
    """Joint solutions putting the TOOL at (x, y, z), nearest first.

    A clicked point fixes 3 of the 6 degrees of freedom, so the tool's
    orientation is ours to choose. Rather than pick one and call the point
    unreachable when it fails, several orientations are tried and every
    solution pooled: keeping the current orientation (the least surprising
    move), pointing the tool down, and pointing it down while yawed to face
    the target. Results are ordered by how little the arm has to move, so the
    caller can walk the list and take the first that clears every guard.
    """
    if orientations is None:
        orientations = default_orientations(x, y, reference)
    out: List[List[float]] = []
    for R in orientations:
        for sol in ik(pose_with_orientation(x, y, z, R)):
            out.append(unwind_to(sol, reference))
    out.sort(key=lambda s: joint_distance(s, reference))
    return out


def default_orientations(x: float, y: float,
                         reference: Sequence[float]) -> List[np.ndarray]:
    """A spread of tool orientations to try for a position-only target."""
    Rs = [fk_matrix(reference)[:3, :3]]           # what the tool is doing now
    yaw = math.atan2(y, x)
    for extra in (0.0, math.pi / 2, -math.pi / 2, math.pi):
        Rs.append(tool_down_pose(0, 0, 0, yaw + extra)[:3, :3])
    # Tilted 45 deg outward, which reaches low points near the base that a
    # straight-down tool cannot.
    for extra in (0.0, math.pi / 2, -math.pi / 2, math.pi):
        a = yaw + extra
        c, s = math.cos(a), math.sin(a)
        tilt = math.radians(45)
        ct, st = math.cos(tilt), math.sin(tilt)
        R = np.array([
            [c * ct, s, -c * st],
            [s * ct, -c, -s * st],
            [-st, 0.0, -ct],
        ])
        Rs.append(R)
    return Rs
