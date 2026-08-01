"""
Shrink a demo until it fits, instead of refusing to run it.

THE PROBLEM
-----------
Demos apply fixed joint offsets to the saved home, so whether a choreography
is safe depends on a pose it does not control. With the elbow at home folded
to +145.5 deg, offsets that add up to +21 deg reach the ~166 deg fold where
the forearm meets the base, and pose_guard correctly refuses the program.
Six of the eleven demos were in that state: pressing them on the touchscreen
sent nothing at all.

Refusing is safe but useless. A demo at reduced amplitude is the same
choreography performed smaller, which is worth far more than a button that
does nothing.

WHY THIS IS COMPUTED, NOT TABULATED
-----------------------------------
A table of per-demo scales would be wrong the moment anyone re-saves home or
edits a waypoint, and wrong silently. Fitting against the guard at send time
means the number is always current: straighten the home elbow and the demos
go back to full size on their own, with nothing to remember to update.

BLEND RADII SCALE TOO
---------------------
Blend radius is in metres of TCP path, and the overlap rule is
r[i] + r[i+1] <= leg_length. Halving a demo halves its legs, so radii left
alone would suddenly overlap and the controller would start SKIPPING
waypoints -- a shrunken demo would also be the wrong shape. Scaling radii by
the same factor holds the ratio, and with it the character of the motion.

Author: jsecco (R)
"""

import math
from typing import List, Optional, Sequence, Tuple

from control import pose_guard

# Below this a demo is no longer a smaller version of itself, it is a twitch.
# Refusing outright is more honest than performing something unrecognisable.
MIN_SCALE = 0.25

# Resolution of the search. Finer than this is false precision: the capsule
# model is an approximation of the arm, not a measurement of it.
SCALE_TOL = 0.01


def scale_waypoints(waypoints: Sequence[Sequence[float]],
                    home: Sequence[float], s: float) -> List[List[float]]:
    """The same choreography performed at `s` times the size, about home.

    Speeds and accelerations are left alone: they are limits, not geometry.
    Blend radii scale with the legs they have to fit inside.
    """
    out = []
    for wp in waypoints:
        row = [home[j] + s * (wp[j] - home[j]) for j in range(6)]
        row.extend(wp[6:8])                       # v, a unchanged
        if len(wp) > 8:
            row.append(wp[8] * s)                 # r is a length; it scales
        out.append(row)
    return out


def fit(waypoints: Sequence[Sequence[float]],
        home: Optional[Sequence[float]],
        closed: bool = True,
        min_scale: float = MIN_SCALE
        ) -> Tuple[Optional[List[List[float]]], float]:
    """Largest amplitude of this program that clears the self-collision guard.

    Returns (waypoints, scale). scale is 1.0 and the waypoints are returned
    unchanged when the program is already safe, which is the common case and
    must stay free of surprises. Returns (None, 0.0) when no amplitude above
    `min_scale` is safe, and the caller should refuse as before.
    """
    if pose_guard.validate_path(waypoints, closed=closed) is None:
        return [list(w) for w in waypoints], 1.0
    if not home or len(home) != 6:
        return None, 0.0                          # nothing to shrink towards

    s = pose_guard.max_safe_scale(
        lambda x: scale_waypoints(waypoints, home, x),
        hi=1.0, tol=SCALE_TOL, closed=closed)
    if s < min_scale:
        return None, 0.0

    fitted = scale_waypoints(waypoints, home, s)
    # max_safe_scale binary-searches, so confirm rather than trust the bound.
    if pose_guard.validate_path(fitted, closed=closed) is not None:
        return None, 0.0
    return fitted, s


def describe(scale: float) -> str:
    return (f"reduced to {scale * 100:.0f}% amplitude to clear the "
            f"self-collision guard")
