# motion_lab

A sandbox for getting UR10 motion smooth and fast **before** changing the
production app. Nothing in `src/` imports anything from here, and nothing here
is loaded by the touchscreen UI. Experiments are run by hand.

Background and the documented rules these tools enforce: `../UR10_REFERENCE.md`.

## Why it exists

Judging motion by ear does not scale. The lab records what the arm actually did
at 125 Hz and reports it numerically, so "is it smooth now?" has an answer that
does not depend on who is listening.

## The tools

| File | Purpose |
|---|---|
| `telemetry.py` | Records the realtime stream (port 30003). Field offsets verified against this controller. Detects **mid-motion stalls** — intervals where every joint is below 0.02 rad/s while motion is still ongoing. That is what a program boundary or a skipped blend looks like in the data. |
| `blend.py` | Enforces the URScript overlap rule `r[i] + r[i+1] <= tcp_leg_length`. Blend radii are in **metres of TCP path**, even for `movej`. Violations mean the controller **skips the waypoint entirely**, not that it blends less. `suggest_radii()` computes the largest legal radii for a path. |
| `lab.py` | Sends a URScript program, records the run, reports it. Also builds the three program shapes (persistent loop, one-shot, per-waypoint) so experiments can *measure* the cost of program boundaries instead of assuming it. |
| `experiments/` | One file per question. Each states what it measures and whether it moves the robot. |

## Safety model

Motion only happens when **all** of these hold:

- the caller passes `confirm=True` (CLI: `--confirm`)
- the robot reports safety `NORMAL` and mode `RUNNING` before the run
- the arm is not already moving
- every waypoint **and the interpolated path between waypoints** clears
  `pose_guard` self-collision checking
- speeds and accelerations are within the lab ceilings (3.2 rad/s, 6.0 rad/s²)
  — a typo guard, not a policy limit
- a watchdog stops the program after `max_seconds` regardless of what happens

`stopj` is always sent on exit, including on Ctrl-C and on any exception.

**Do not run a motion experiment with nobody at the robot.** Analysis
experiments (like `exp01`) command no motion and are safe to run any time.

## Running

```bash
cd ~/Documents/i3UR10

# offline analysis, no motion
venv/bin/python motion_lab/experiments/exp01_audit_blends.py

# motion experiments require --confirm and a person watching
venv/bin/python motion_lab/experiments/exp02_....py --confirm
```

## Promoting a change to production

A change moves from `motion_lab/` into `src/` only when:

1. the offline blend audit reports zero overlapping or degenerate legs,
2. a recorded run shows zero mid-motion stalls,
3. peak joint speed matches what was commanded (no silent scaling),
4. the run completes without leaving safety `NORMAL`.
