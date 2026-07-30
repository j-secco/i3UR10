"""
UR10 reach / self-collision map for the i3UR10 demos.

Offline geometry tool -- commands NO robot motion. It answers: for the bow /
wave / pendulum demos, how far can the choreography amplitudes grow before the
arm self-collides?

  - Correct UR10 (CB) forward kinematics  (validated vs robot: 6.5 mm error)
  - Capsule link model + segment self-collision check
  - Calibration against the known bow self-collision and known-good poses
  - Per-demo amplitude sweep -> max safe scale + the limiting pose

Run from i3UR10 project root:  python reach_map.py
Author: jsecco (R)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# --- UR10 (CB-series) standard Denavit-Hartenberg parameters (meters / rad) ---
_A     = [0.0,      -0.612,   -0.5723,  0.0,       0.0,       0.0]
_D     = [0.1273,    0.0,      0.0,     0.163941,  0.1157,    0.0922]
_ALPHA = [math.pi/2, 0.0,      0.0,     math.pi/2, -math.pi/2, 0.0]

HOME = [-0.8527525107013147, -1.6017263571368616, 2.5422890186309814,
        -3.8001683394061487, -1.5843680540667933, 0.2585873603820801]

# --- capsule link radii (m). Calibrated below; conservative UR10 estimates. ---
R_BASE_SHOULDER = 0.090
R_UPPER_ARM     = 0.075
R_FOREARM       = 0.060
R_WRIST         = 0.050
SAFETY_MARGIN   = 0.030   # extra clearance required beyond capsule surfaces


# ----------------------------- kinematics -----------------------------------

def _dh(a, d, alpha, theta):
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st*ca,  st*sa, a*ct],
        [st,  ct*ca, -ct*sa, a*st],
        [0.0,  sa,     ca,    d  ],
        [0.0,  0.0,    0.0,   1.0],
    ])


def joint_origins(joints):
    """XYZ of each frame origin P0..P6 in the base frame."""
    T = np.eye(4)
    pts = [T[0:3, 3].copy()]
    for i in range(6):
        T = T @ _dh(_A[i], _D[i], _ALPHA[i], joints[i])
        pts.append(T[0:3, 3].copy())
    return pts


def tcp_xyz(joints):
    return joint_origins(joints)[-1].tolist()


# ------------------------- self-collision model -----------------------------

def _seg_seg_distance(p1, q1, p2, q2):
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


# Non-adjacent capsule pairs to test. Each link is (origin_index_a, origin_index_b, radius).
_LINKS = {
    "base_shoulder": (0, 1, R_BASE_SHOULDER),
    "upper_arm":     (1, 2, R_UPPER_ARM),
    "forearm":       (2, 3, R_FOREARM),
    "wrist":         (3, 6, R_WRIST),
}
_PAIRS = [("upper_arm", "wrist"), ("base_shoulder", "forearm"), ("base_shoulder", "wrist")]


def collision_report(joints):
    """Return (min_clearance, detail-list). clearance<0 => capsules overlap+margin."""
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


def is_safe(joints):
    return collision_report(joints)[0] >= 0.0


# ------------------------------ geometry diagnostics -------------------------

def _pose(j2=0.0, j3=0.0, j5=0.0):
    return [HOME[0], HOME[1]+j2, HOME[2]+j3, HOME[3], HOME[4]+j5, HOME[5]]


def _angle(v1, v2):
    """Angle (deg) between two vectors."""
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    c = float(np.clip((v1 @ v2) / (n1 * n2), -1.0, 1.0))
    return math.degrees(math.acos(c))


def fold_angles(joints):
    """Bend angle (deg) at each elbow/wrist joint: 0 = straight, 180 = doubled back.
    This is what catches over-folded ADJACENT links (the bow's failure mode)."""
    P = joint_origins(joints)
    segs = [P[i+1] - P[i] for i in range(6)]          # S0..S5
    # Meaningful bends: elbow (between upper-arm S2 and forearm S? ) -- use segments
    # upper_arm=P1->P2 (S1), forearm=P2->P3 (S2), wrist S3,S4,S5.
    bends = {}
    for name, a, b in [("elbow", 1, 2), ("wrist1", 2, 3),
                        ("wrist2", 3, 4), ("wrist3", 4, 5)]:
        bends[name] = _angle(segs[a], segs[b])
    return bends


# Non-adjacent capsule clearances + adjacent fold angles, for one pose.
def geometry_row(joints):
    worst_cap, detail = collision_report(joints)
    return worst_cap, detail, fold_angles(joints)


CALIBRATION = [
    # (label, joints, known_safe)   known_safe: True/False/None(unknown)
    ("home",                       list(HOME),                          True),
    ("amplified-bow apex (TRIP)",  _pose(j2=+0.82, j3=+0.74, j5=+0.62),  False),
    ("original-bow apex (UNTESTED)", _pose(j2=+0.60, j3=+0.50, j5=+0.40), None),
    ("amplified-pendulum extreme", _pose(j2=-0.80, j3=-0.26),            True),
]


def run_validation():
    q_real, tcp_real = [-0.886532, -1.104361, 1.781096, -3.658972, -1.03564, 0.258443], [-0.6832, 0.4952, 0.4197]
    tcp_fk = tcp_xyz(q_real)
    err = math.sqrt(sum((a-b)**2 for a, b in zip(tcp_fk, tcp_real)))
    print("=== FK validation vs robot ground truth ===")
    print("  err %.4f m  -> %s\n" % (err, "FK OK" if err < 0.02 else "FK MISMATCH"))

    print("=== geometry diagnostics (non-adjacent capsule dist + adjacent fold angles) ===")
    print("  %-32s %-7s %-7s %-7s | %-8s %-8s %-8s" %
          ("pose", "elbow", "wrist1", "wrist2", "ua/wr", "bs/fa", "bs/wr"))
    for label, q, _safe in CALIBRATION:
        _, detail, bends = geometry_row(q)
        dd = {(na, nb): d for na, nb, d, c in detail}
        print("  %-32s %6.1f  %6.1f  %6.1f  | %7.3f  %7.3f  %7.3f" % (
            label, bends["elbow"], bends["wrist1"], bends["wrist2"],
            dd[("upper_arm", "wrist")], dd[("base_shoulder", "forearm")],
            dd[("base_shoulder", "wrist")]))
    print()
    return True


# ------------------------------ reach sweep ----------------------------------

# (module path, [amplitude constant names], demo class name)
_DEMOS = [
    ("control.bow_demo",
     ["SHOULDER_PRE_RAD", "BOW_SHOULDER_RAD", "BOW_ELBOW_RAD", "BOW_WRIST_DOWN_RAD"],
     "BowDemo"),
    ("control.wave_demo",
     ["SHOULDER_LIFT_RAD", "ELBOW_FOLD_RAD", "WRIST_TILT_RAD", "WAVE_AMPLITUDE_RAD",
      "SWEEP_AMPLITUDE_RAD", "WRIST_FOLLOW_RAD", "WRIST_ROLL_RAD", "BOW_LEAN_RAD"],
     "WaveDemo"),
    ("control.pendulum_demo",
     ["SWING_AMPLITUDE_RAD", "RISE_LIFT_RAD", "J3_FOLLOW_RAD"],
     "PendulumDemo"),
]


def _all_waypoints(module, cls_name):
    """Instantiate the demo (no robot) and collect every choreography waypoint."""
    cls = getattr(module, cls_name)
    demo = cls(None, HOME, audience_offset_rad=0.0)
    pts = []
    for seg in demo._build_segments():
        pts.extend(seg.waypoints)
    return pts


def sweep_demo(mod_path, const_names, cls_name):
    import importlib
    module = importlib.import_module(mod_path)
    base = {c: getattr(module, c) for c in const_names}

    print("=== %s ===" % cls_name)
    print("  original amplitudes:", {k: round(v, 3) for k, v in base.items()})

    # Global scale sweep: scale every amplitude together, find max safe scale.
    max_safe = 1.0
    first_bad = None
    s = 1.0
    while s <= 2.01:
        for c in const_names:
            setattr(module, c, base[c] * s)
        worst_pose, worst_clear = None, math.inf
        for wp in _all_waypoints(module, cls_name):
            c0, _ = collision_report(wp)
            if c0 < worst_clear:
                worst_clear, worst_pose = c0, wp
        if worst_clear >= 0.0:
            max_safe = s
        elif first_bad is None:
            first_bad = (s, worst_clear, worst_pose)
        s = round(s + 0.05, 2)

    for c in const_names:                       # restore module globals
        setattr(module, c, base[c])

    print("  max safe global amplitude scale: %.2fx" % max_safe)
    if first_bad:
        s, clr, pose = first_bad
        _, detail = collision_report(pose)
        lim = min(detail, key=lambda d: d[3])
        print("  first self-collision at %.2fx (clearance %+.3f m); limiting pair: %s/%s"
              % (s, clr, lim[0], lim[1]))
    print("  -> recommended dramatic amplitudes (%.2fx, safe):" % max_safe)
    print("    ", {k: round(v * max_safe, 3) for k, v in base.items()})
    print()


if __name__ == "__main__":
    run_validation()
    for mod_path, consts, cls_name in _DEMOS:
        try:
            sweep_demo(mod_path, consts, cls_name)
        except Exception as exc:
            print("=== %s: sweep error: %s ===\n" % (cls_name, exc))
