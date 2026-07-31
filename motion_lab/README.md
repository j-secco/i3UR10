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
| `teach.py` | Hand-guide the arm to record a safe workspace. **Read-only by default** — you hold the pendant Freedrive button, this only watches telemetry. |
| `envelope.py` | What the arm is allowed to do: reachability minus the measured solids minus self-collision. Joint ranges are recorded but **not** enforced — inside the free space the arm moves freely. |
| `obstacles.py` | The measured cell: each obstacle a polygon footprint extruded vertically. Capsule-aware, so the arm's 75 mm thickness is tested rather than its centreline. |
| `pointer.py` | Click a point in a 3D view of the cell and send the tool there. Solves IK, runs every guard, then reports the model's target against the position the **robot** says it reached. |
| `../src/control/ur_kinematics.py` | Closed-form UR10 inverse kinematics, all 8 branches. Shares its forward model with `pose_guard`, so FK and IK cannot drift apart. |
| `gripper.py` | XL330-M288-T driver (current-based position control). Independent of the arm. |
| `experiments/` | One file per question. Each states what it measures and whether it moves the robot. |

## Teaching the safe workspace

`pose_guard` checks the arm against itself and knows nothing about your table.
Teaching fixes that:

```bash
venv/bin/python motion_lab/teach.py          # hold pendant Freedrive, guide the arm
venv/bin/python motion_lab/teach.py --freedrive 120   # software freedrive instead
```

Once `workspace_envelope.json` exists, every experiment is checked against it
automatically — `Lab.check_waypoints()` refuses any path that leaves the
region, including the interpolated poses between waypoints.

**This is not a safety function.** It is Python on the control PC: it can
crash, lag, or be skipped, and nothing certifies it. The real fence is the
PolyScope safety configuration, enforced by the robot's separate safety
processor. `teach.py` prints its results formatted for that screen, so the
workflow is: teach → read the numbers → enter them under Installation →
Safety → Joint Limits and safety planes → and keep the envelope as the
tighter software check in front of it.

**It cannot represent a hole.** Anything the arm must avoid has to be measured
as a solid (`obstacles.py`) or fenced with a pendant safety plane. Tracing the
edges of a region does not exclude what is inside it.

## Pointing the arm at a place

Everything else here specifies poses in JOINT space, which is safe and easy to
validate but cannot be checked against the cell: if the arm ends up somewhere
odd you cannot tell whether the model is wrong or the request was.

```bash
venv/bin/python motion_lab/pointer.py            # plan only, nothing moves
venv/bin/python motion_lab/pointer.py --confirm  # motion enabled

# from another machine
ssh -L 8765:localhost:8765 ur10-wifi
open http://localhost:8765
```

Click a point on the working plane; the amber arm is the solved pose, and
nothing moves until you press Go. After each move it reports the point you
asked for against the position the **robot** reports reaching. That last number
is the only measured one, and it is what tells you whether the model is right.

Expect a few mm of disagreement: the kinematics use nominal DH parameters,
while the controller applies this robot's factory calibration, which we do not
have. Measured against the robot's own TCP report, the forward model agrees to
about 5 mm.

### The mistake this replaced

`exp05_probe_cart.py` tried to answer "will the arm hit the cart?" by searching
J2/J3 for poses whose closest approach to the cart was 150 mm. It found them,
and every clearance it printed was true -- but the closest part of the arm was
always the forearm, about 22 cm behind the tool, so the tool itself was never
constrained at all. Replayed afterwards, its eight positions put the tool
anywhere from 0.39 m to 0.88 m from the base. **Optimising a proxy for the
thing you care about is not the same as constraining it.** Cartesian intent
needs a Cartesian solve, which is what `pointer.py` does.

## Experiments

| # | Moves robot | Question |
|---|---|---|
| `exp01_audit_blends.py` | no | Which demos contain waypoints the controller will silently skip? |
| `exp02_blend_ab.py` | **yes** | Does repairing the blend geometry actually remove mid-motion stalls? Speeds are held identical so blending is the only variable. |
| `exp03_speed_ramp.py` | **yes** | Where is the real speed ceiling? Compares commanded against achieved joint speed at rising multipliers and stops when they stop tracking. |
| `exp04_joint_ceilings.py` | **yes** | Do the wrists reach their higher 3.14 rad/s ceiling, or is the base's 2.09 rad/s limiting every demo? |

### Joint limits worth knowing before reading exp03

The UR10's own maxima are **120 deg/s (2.09 rad/s) on the base and shoulder**
and **180 deg/s (3.14 rad/s) on elbow and wrists**. A choreography that sweeps
J1 therefore hits a hardware wall at 2.09 rad/s no matter what the safety
configuration allows. When a ramp stops tracking, check which joint is
leading the motion before assuming the safety limiter is responsible.

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

# the checks, none of which touch the robot
for t in kinematics obstacles volume zone; do venv/bin/python motion_lab/test_$t.py; done
```

## Promoting a change to production

A change moves from `motion_lab/` into `src/` only when:

1. the offline blend audit reports zero overlapping or degenerate legs,
2. a recorded run shows zero mid-motion stalls,
3. peak joint speed matches what was commanded (no silent scaling),
4. the run completes without leaving safety `NORMAL`.
