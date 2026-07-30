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

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "src"))

# Single source of truth for FK + capsule model (shared with the runtime
# guard in WebSocketController.move_joint_program_loop).
from control.pose_guard import collision_report, fold_angles, is_safe, tcp_xyz

_FALLBACK_HOME = [-0.8527525107013147, -1.6017263571368616, 2.5422890186309814,
                  -3.8001683394061487, -1.5843680540667933, 0.2585873603820801]


def _load_home():
    """Current saved home from config/robot_config.yaml. Demos run relative to
    THIS pose, so sweeps must too; a hardcoded home silently invalidates every
    result once the operator re-saves Home from the jog page."""
    try:
        import yaml
        with open(os.path.join(_ROOT, "config", "robot_config.yaml")) as fh:
            cfg = yaml.safe_load(fh)
        h = cfg["demo"]["saved_home_joints"]
        if isinstance(h, list) and len(h) == 6:
            return [float(x) for x in h]
    except Exception as exc:
        print(f"WARNING: could not load saved home ({exc}); using fallback")
    return list(_FALLBACK_HOME)


HOME = _load_home()


# ------------------------------ geometry diagnostics -------------------------

def _pose(j2=0.0, j3=0.0, j5=0.0):
    return [HOME[0], HOME[1]+j2, HOME[2]+j3, HOME[3], HOME[4]+j5, HOME[5]]


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
    # Starts BELOW 1.0: with a re-saved home the nominal amplitudes themselves
    # can already collide, and max_safe must not default to a value never
    # actually validated.
    max_safe = 0.0
    first_bad = None
    s = 0.30
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


def report_plunge():
    """PlungeDemo adapts its own depth via pose_guard; report what it picks."""
    from control.plunge_demo import MIN_DEPTH_SCALE, PlungeDemo
    demo = PlungeDemo(None, HOME)
    s = demo._safe_depth_scale()
    print("=== PlungeDemo ===")
    verdict = "OK" if s >= MIN_DEPTH_SCALE else f"REFUSES to run (min {MIN_DEPTH_SCALE})"
    print("  max safe depth scale from current home: %.2fx -> %s\n" % (s, verdict))


if __name__ == "__main__":
    print("home (deg):", [round(math.degrees(q), 1) for q in HOME], "\n")
    run_validation()
    for mod_path, consts, cls_name in _DEMOS:
        try:
            sweep_demo(mod_path, consts, cls_name)
        except Exception as exc:
            print("=== %s: sweep error: %s ===\n" % (cls_name, exc))
    try:
        report_plunge()
    except Exception as exc:
        print("=== PlungeDemo: report error: %s ===\n" % exc)
