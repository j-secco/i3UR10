"""
Find a home pose from which every demo is geometrically valid.

Demos apply fixed joint offsets to the saved home, so home is not a cosmetic
setting: it decides whether a choreography folds the elbow into the shoulder.
Six of the eleven demos are currently refused by the production guard because
the saved home's elbow (J3 = +145.5 deg) leaves no room for the offsets they
add, which is the failure pose_guard was written to catch.

Self-collision is independent of J1 -- rotating the whole arm about the base
axis cannot change the distance between two of its own links -- so the search
is over J2 and J3, the two joints that set the fold. Cart clearance does
depend on J1, so it is checked but not optimised.

Offsets are taken once and reapplied, which is exact for ten of the demos and
approximate for PlungeDemo (it clamps, so it drifts by up to 8 deg). The
winner is therefore re-verified by actually building all eleven, which is the
only result worth acting on.

    venv/bin/python motion_lab/find_home.py

Author: jsecco (R)
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import yaml  # noqa: E402

import demos  # noqa: E402
from control.pose_guard import collision_report, validate_path  # noqa: E402
from envelope import Envelope  # noqa: E402
from obstacles import ObstacleSet  # noqa: E402

SAMPLES_SWEEP = 4          # per leg while searching
SAMPLES_VERIFY = 8         # per leg when confirming, matching the guard

# Accept a home only if it clears both guards by this much. Landing exactly on
# zero would mean the next small edit to any demo puts it back in the refused
# pile, and the guards already carry their own margins under this number.
MARGIN_WANTED = 0.010      # metres


def offsets(cfg, home):
    """Each demo's waypoints expressed as offsets from home."""
    out = {}
    for cls in demos.demo_classes():
        rows = demos.capture(cls, home, cfg["demo"])
        if rows:
            out[cls.__name__] = [
                [r[j] - home[j] for j in range(6)] + list(r[6:]) for r in rows]
    return out


def poses(rows, n):
    P = [list(r[:6]) for r in rows]
    for a, b in zip(P, P[1:] + [P[0]]):
        av, bv = np.asarray(a), np.asarray(b)
        for k in range(n + 1):
            yield list(av + (bv - av) * k / n)


def build(home, offs):
    for rows in offs.values():
        yield [[home[j] + r[j] for j in range(6)] + list(r[6:]) for r in rows]


def self_score(home, offs, n=SAMPLES_SWEEP, early=True):
    """Worst self clearance over every demo.

    With early=True this stops at the first negative value, which makes the
    sweep tractable but means a negative result is "the first failure found",
    NOT the worst one -- do not print it as though it were. Ranking is
    unaffected: only candidates that clear zero are ever compared, and those
    never exit early, so their score is the true worst.
    """
    worst = math.inf
    for built in build(home, offs):
        for q in poses(built, n):
            c = collision_report(q)[0]
            if c < worst:
                worst = c
                if early and worst < 0.0:
                    return worst
    return worst


def cart_score(home, offs, obs, n=SAMPLES_SWEEP):
    """Worst clearance to a measured solid. An order of magnitude dearer than
    the self check -- every link sampled at 20 mm against every polygon -- so
    it is only ever run on a home that has already passed self-collision."""
    worst = math.inf
    for built in build(home, offs):
        for q in poses(built, n):
            w = obs.worst(q)
            if w and w[0] < worst:
                worst = w[0]
                if worst < 0.0:
                    return worst
    return worst


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "robot_config.yaml")))
    home = list(cfg["demo"]["saved_home_joints"])
    env = Envelope.load(os.path.join(HERE, "workspace_envelope.json"))
    obs = ObstacleSet.from_json(env.obstacles)

    print("taking each demo's offsets from home…")
    offs = offsets(cfg, home)
    print(f"  {len(offs)} demos captured\n")

    bs = self_score(home, offs, early=False)
    print(f"current home  J2 {math.degrees(home[1]):+.1f}  J3 {math.degrees(home[2]):+.1f}"
          f"   self {bs*1000:+.0f} mm"
          + (f"   cart {cart_score(home, offs, obs)*1000:+.0f} mm" if bs >= 0 else
             "   (refused, so cart not evaluated)"))
    print("  (both include their safety margins: 30 mm self, 50 mm cart)\n")

    # Search outward from the pose the arm holds today, not over the whole
    # grid. Home is not a free parameter: it is where the arm rests between
    # runs and the point every choreography is staged around, so the useful
    # answer is the SMALLEST change that makes the catalogue legal. Optimising
    # clearance instead walks off to a wildly different posture that happens
    # to have lots of room and stages every demo somewhere new.
    j2_now, j3_now = math.degrees(home[1]), math.degrees(home[2])
    cands = []
    for d2 in np.arange(-30.0, 30.5, 1.5):
        for d3 in np.arange(-60.0, 20.5, 1.5):
            cands.append((math.hypot(d2, d3), d2, d3))
    cands.sort()

    print(f"searching outward from J2 {j2_now:+.1f} J3 {j3_now:+.1f} "
          f"({len(cands)} candidates)…")
    best = None
    tested = 0
    for dist, d2, d3 in cands:
        h = list(home)
        h[1], h[2] = math.radians(j2_now + d2), math.radians(j3_now + d3)
        tested += 1
        s = self_score(h, offs)
        if s < MARGIN_WANTED:
            continue
        c = cart_score(h, offs, obs)
        if c < MARGIN_WANTED:
            continue
        best = (dist, j2_now + d2, j3_now + d3, s, c)
        print(f"  found after {tested} candidates", flush=True)
        break

    if best is None:
        print(f"\nno home within 30 deg of the current one clears every demo.")
        print("the stubborn demos need their amplitudes reduced as well; see")
        print("the per-demo amplitude headroom for how much that costs.")
        return
    _, j2d, j3d, s, c = best
    print(f"\nsmallest change that works:")
    print(f"  J2 {j2_now:+.1f} -> {j2d:+.1f}   ({j2d - j2_now:+.1f} deg)")
    print(f"  J3 {j3_now:+.1f} -> {j3d:+.1f}   ({j3d - j3_now:+.1f} deg)")
    print(f"  clearance then: self {s*1000:+.0f} mm, cart {c*1000:+.0f} mm\n")
    # Authoritative check: actually build all eleven from the winner.
    print("\nverifying by building every demo from that home…")
    h = list(home)
    h[1], h[2] = math.radians(j2d), math.radians(j3d)
    ok = True
    for cls in demos.demo_classes():
        rows = demos.capture(cls, h, cfg["demo"])
        if not rows:
            print(f"  {cls.__name__:<16} no program")
            continue
        v = validate_path(rows, closed=True)
        cart = min((obs.worst(q) or [9])[0] for q in poses(rows, SAMPLES_VERIFY))
        state = "REFUSED" if v is not None else "runs"
        if v is not None or cart < 0:
            ok = False
        print(f"  {cls.__name__:<16} {state:>8}   cart {cart*1000:+.0f} mm")
    print("\n" + ("all eleven demos validate from this home."
                  if ok else "some demos still fail; amplitudes need reducing too."))
    print("\nNothing has been changed. config/robot_config.yaml still holds the "
          "old home.")


if __name__ == "__main__":
    main()
