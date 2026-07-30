"""
UR10 Forward Kinematics

Minimal forward kinematics for the Universal Robots UR10 using modified
Denavit-Hartenberg parameters. Used to convert joint angles to TCP pose
[x, y, z, rx, ry, rz] in meters and rotation vector (axis-angle, radians)
for movel commands.

Parameters from Universal Robots UR10 specification (modified DH).
Author: jsecco (R)
"""

import math
from typing import List

import numpy as np

# UR10 modified DH parameters (meters, radians). theta_i = joint angle q[i].
# T_i = Rx(alpha_i) * Tx(a_i) * Rz(theta_i) * Tz(d_i)
_DH_A = [0.0, -0.6127, -0.57155, 0.0, 0.0, 0.0]
_DH_D = [0.1273, 0.0, 0.0, 0.163941, 0.1157, 0.0922]
_DH_ALPHA = [math.pi / 2, 0.0, 0.0, math.pi / 2, -math.pi / 2, 0.0]


def _dh_transform(a: float, d: float, alpha: float, theta: float) -> np.ndarray:
    """Single link 4x4 transformation (modified DH)."""
    ct = math.cos(theta)
    st = math.sin(theta)
    ca = math.cos(alpha)
    sa = math.sin(alpha)
    return np.array([
        [ct, -st, 0, a],
        [st * ca, ct * ca, -sa, -d * sa],
        [st * sa, ct * sa, ca, d * ca],
        [0, 0, 0, 1],
    ])


def _rotation_matrix_to_axis_angle(R: np.ndarray) -> List[float]:
    """Convert 3x3 rotation matrix to rotation vector (axis * angle in radians)."""
    angle = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0)))
    if angle < 1e-9:
        return [0.0, 0.0, 0.0]
    sin_a = math.sin(angle)
    if abs(sin_a) < 1e-9:
        return [0.0, 0.0, 0.0]
    rx = (R[2, 1] - R[1, 2]) / (2 * sin_a)
    ry = (R[0, 2] - R[2, 0]) / (2 * sin_a)
    rz = (R[1, 0] - R[0, 1]) / (2 * sin_a)
    scale = angle / sin_a
    return [rx * scale, ry * scale, rz * scale]


def joint_to_pose(joints: List[float]) -> List[float]:
    """
    Compute TCP pose from joint angles.

    Args:
        joints: [j1, j2, j3, j4, j5, j6] in radians.

    Returns:
        [x, y, z, rx, ry, rz]: position in meters, orientation as rotation
        vector (axis-angle) in radians, suitable for movel().
    """
    if len(joints) != 6:
        raise ValueError("joints must have 6 elements")
    T = np.eye(4)
    for i in range(6):
        T = T @ _dh_transform(_DH_A[i], _DH_D[i], _DH_ALPHA[i], joints[i])
    x, y, z = T[0:3, 3].tolist()
    R = T[0:3, 0:3]
    rx, ry, rz = _rotation_matrix_to_axis_angle(R)
    return [x, y, z, rx, ry, rz]


def joints_to_poses(joint_waypoints: List[List[float]]) -> List[List[float]]:
    """Convert a list of joint waypoints to Cartesian poses (for movel)."""
    return [joint_to_pose(j) for j in joint_waypoints]
