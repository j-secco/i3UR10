# UR10 CB3 Reference: Interfaces, Motion Semantics, and Why Our Motion Stalls

Research compiled 2026-07-31 for the i3UR10 project.
Robot: UR10 CB3, PolyScope/URSoftware **3.13.1.10297** (May 2020), IP **192.168.10.24**.
Control PC: Elo i3 touchscreen (`elo3`), SSH alias `ur10-wifi`, 192.168.10.26.

Every claim below is either (a) quoted from an official UR document, (b) measured
directly on this robot, or (c) explicitly flagged UNVERIFIED. Measurements beat
documentation where they disagree, and in one case they did.

---

## 1. Getting a Linux terminal on the robot controller

The CB3 control box is an x86 PC running a Debian-based Linux. Port 22 is
**open** on 192.168.10.24 (measured). PolyScope runs on top of that OS.

### Enabling and connecting

SSH is **not enabled by default**; it is a toggle in PolyScope under
**Settings → Security → Secure Shell**. Once enabled:

```bash
ssh root@192.168.10.24          # factory password: easybot
```

Our Mac's OpenSSH (8.8+) may refuse the handshake with the controller's
2013-vintage sshd, which offers SHA-1 signature algorithms that modern clients
disable. If that happens, scope the workaround to this host only:

```
Host ur10-controller
    HostName 192.168.10.24
    User root
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedKeyTypes +ssh-rsa
    KexAlgorithms +diffie-hellman-group1-sha1
```

UNVERIFIED: the exact algorithms this controller's sshd offers. Start with only
`HostKeyAlgorithms +ssh-rsa` and add the others only if the error persists.

### What is on the filesystem

| Path | Contents |
|---|---|
| `/programs/` | `.urp` program files; `scp` target for scripts |
| `/programs/usbdisk` | USB mount point on CB3 |
| `/root/.urcontrol/` | `urcontrol.conf`, calibration, `.installation` files, **safety config** |
| log files | `log_history.txt`, flight reports (read these via UR Log Viewer) |

`scp` is officially supported and is the sanctioned way to move files:

```bash
scp myscript.script root@192.168.10.24:/programs/
```

### Cautions

- **Do not hand-edit the safety configuration.** It is CRC-protected and UR
  supplies `update_urcontrol_crc.py` for a reason. Editing it out of band
  desyncs the robot's actual safety state from what PolyScope displays. Change
  safety limits at the pendant, not over SSH.
- **Do not run `apt`/`dpkg`.** The OS is a frozen, EOL Debian that PolyScope was
  validated against; UR's only supported update path is a `.urup` file via USB.
- **Do not change the root password** unless you have a tested rollback. There is
  no recovery path; UR Support's only remedy is a full re-flash. The admin
  password has no reset at all.
- Treat shell access as read-mostly: inspection, log retrieval, file transfer.

---

## 2. The controller's TCP interfaces

| Interface | Port | Rate (CB3) | Accepts URScript | Notes |
|---|---|---|---|---|
| Primary | 30001 | 10 Hz | yes | State **plus** key messages, runtime exceptions, popups. This is the channel PolyScope itself uses. |
| Secondary | 30002 | 10 Hz | yes | State + version message only. Preferred for external script upload: leaves the pendant's own primary connection clean. |
| Realtime | 30003 | 125 Hz | yes | Big fixed binary struct. **Deprecated since 3.5** in favour of RTDE. |
| RTDE | 30004 | 1–125 Hz | **no** | Negotiated binary recipes. Cannot command motion. |
| Dashboard | 29999 | n/a | no | ASCII commands: power, brake release, unlock protective stop, load/play/stop, safetymode. |

Read-only variants exist on 30011/30012 (primary/secondary) for clients that
must never be able to inject script.

### Realtime packet layout — measured on this robot

Documentation sources disagreed (guesses of 1108 and 1140 bytes). The actual
value on 3.13.1, measured over 30 consecutive packets:

**1116 bytes = 4-byte `int32` length + 139 × `float64`, no padding.**

Verified field offsets (index into the float64 array after the length prefix):

| Field | Index |
|---|---|
| Time | 0 |
| q target | 1–6 |
| q actual | 31–36 |
| qd actual | 37–42 |
| TCP pose actual | 55–60 |
| TCP speed actual | 61–66 |
| Robot mode | 94 |
| Safety mode | 101 |

Cross-checked three ways: robot mode read `7.0` while the Dashboard reported
`RUNNING`; safety mode read `1.0` while the Dashboard reported `NORMAL`; and the
TCP pose at index 55 matched forward kinematics computed from `q actual` in the
same packet to within 4 mm. `motion_lab/telemetry.py` encodes these offsets.

### Program execution semantics — the important part

**Every complete send to 30001/30002/30003 becomes a new program on the
controller, and a new program replaces the one currently running.**

This has a consequence that drives our entire motion architecture: a `movej`
sent on its own is a complete program whose motion queue ends at that single
target. There is no following waypoint to blend into, so the arm **must**
decelerate to zero. Sending one position per socket write can therefore never
produce continuous motion, no matter what blend radius is specified.

Wrapping matters: `def name(): … end` defines a primary program that
pauses/replaces the main program; `sec name(): … end` defines a secondary thread
that runs in parallel but **cannot** control motion. A bare single line is
accepted as an implicit one-line program.

Syntax errors come back as a **RuntimeExceptionMessage** (robot message type 20,
sub-type 10) with script line and column — **on the primary interface only**.
The `PROGRAM_XXX_STARTED` / `PROGRAM_XXX_STOPPED` entries our safety log records
are **Key Messages** (sub-type 7), also primary-only.

UNVERIFIED: maximum program size over a socket. UR publishes no limit; a forum
report puts practical trouble around ~500 waypoints. Architecturally, stream via
registers rather than sending enormous programs.

---

## 3. RTDE (port 30004)

Binary protocol, 3-byte header (`uint16` size, `uint8` type). Lifecycle:
connect → negotiate protocol version (request v2, fall back to v1) → declare
input/output **recipes** by variable name → `START` → data packages flow.
Because the recipe fixes field order and types up front, the controller's
real-time thread does a memcpy rather than parsing text. That is the whole
design goal: telemetry without disturbing real-time behaviour.

**Frequency on CB3 is 125 Hz maximum, and the output rate is
`floor(125 / requested)`.** Ask for 100 Hz and you get 125. Use divisors of 125.

### The hard limit that shapes everything

**There is no motion command in the RTDE input set.** Inputs are: digital and
analog outputs, the speed slider (`speed_slider_mask` + `speed_slider_fraction`),
and general-purpose registers. On CB3 you have **registers 0–23 only** — the
24–47 range is 5.3.0+ and does not exist here.

Therefore: **to move the robot from an external PC, a URScript program must be
running on the controller.** Registers are only a side-channel into that program.

### How ur_rtde actually works

`RTDEControlInterface` is not an RTDE-only client. On construction it opens the
RTDE session *and* uploads a ~1300-line URScript control script that loops
forever at 125 Hz, reading a command ID from input register 0 and dispatching
`movej` / `speedj` / `servoj` with arguments from the float registers.
Continuous-motion commands run in dedicated URScript threads so the dispatcher
stays responsive.

This exists precisely to avoid the per-command program restart described in §2.
One program start, ever; sub-8 ms command latency; real blending, because
consecutive moves live in the same program.

**What kills the control script:** a protective stop, an E-stop, any other
program sent to the controller, a pendant Stop, or a Dashboard `play`. After
that, every call fails with *"RTDE control script is not running!"* Recovery is
`reuploadScript()` — and on CB3 the protective stop must be **unlocked first**,
or the reupload will not run.

**Watchdog:** `setWatchdog()` installs `rtde_set_watchdog(..., "stop")`. Use it
whenever streaming `servoj`/`speedj`, because those commands never time out on
their own (§4).

Relevant to us: `ur_rtde` 1.6.3 is now installed in the venv. Our config has
`use_rtde_for_motion: true`, which until 2026-07-30 silently fell back to the
WebSocket path because the library was missing.

---

## 4. URScript motion semantics (v3.13 manual)

### `movej(q, a=1.4, v=1.05, t=0, r=0)`

- `a`, `v` apply to the **leading axis** (the joint with the largest excursion).
  All joints are time-scaled to arrive together, so `v=1.05` does not mean every
  joint moves at 1.05 rad/s.
- `t` **overrides** `a` and `v` entirely. The manual states it twice.
- **`r` is a blend radius in METRES**, even for a joint-space move. The manual is
  explicit: *"r = 0 → the blend radius is zero meters."* It defines a Cartesian
  sphere around the target TCP position; when the TCP enters that sphere the
  controller begins transitioning to the next trajectory.

That unit is the single most important fact in this document, and §6 shows how
badly our code got it wrong.

### Blending: how it works and how it fails

A blend has an entry point and an exit point on the sphere of radius `r` around
the waypoint. The look-ahead is **exactly one trajectory segment**, resolved at
the moment the TCP crosses into the blend sphere.

**The failure mode, verbatim from the manual (movej, p.25):**

> *"if the blend region of this move overlaps with the blend radius of previous
> or following waypoints, **this move will be skipped**, and an 'Overlapping
> Blends' warning message will be generated."*

Read that carefully: the waypoint is **skipped entirely**. The arm does not slow
down and pass through it — it never goes there. This is a path-safety hazard as
much as a smoothness problem.

The real constraint on every leg is therefore:

```
r[i] + r[i+1] <= tcp_distance(waypoint[i], waypoint[i+1])
```

The commonly quoted "r must be less than half the segment" is just this rule
applied to two equal radii.

**What breaks blending:**

| Between two moves | Blending survives? |
|---|---|
| Separate programs / socket sends | **No, always broken** |
| `sleep(x)` | **No** — consumes physical time, nothing queued at the blend point |
| `sync()` | Very likely no (UNVERIFIED; same mechanism as `sleep`) |
| `if`/conditional choosing the next waypoint | **Yes** — evaluated early, on entering the blend sphere |
| Pure computation, `textmsg`, `get_actual_*` | **Yes** — costs no physical time |
| Waiting on I/O or an operator | **No** — and may trigger a protective stop |

Rule to code against: blending survives anything that costs zero physical time
and resolves before the TCP reaches the blend entry point.

UNVERIFIED, worth bench-testing in the lab: (a) whether setting `t` together with
`r` voids `t`; (b) whether MoveJ↔MoveL blends work — the manual says yes, a
forum report says no; (c) whether `sleep()` is speed-slider-dependent on 3.13 as
it was on CB2.

### `speedj(qd, a, t)` / `speedl(...)` / `stopj(a)`

`t` is **how long the call blocks the calling thread**, not a duration after
which the robot decelerates. When the call returns, **the arm keeps moving at
the last commanded velocity, indefinitely.** There is no implicit stop.

That is why chaining `speedj` every ~100 ms yields smooth jogging: each command
replaces the velocity setpoint without the arm ever coming to rest. Set `t`
comfortably longer than the send interval (our jog uses `t=0.2` with a 100 ms
loop, a 2× margin) so a stalled sender holds velocity rather than doing
something discontinuous. Only `stopj(a)` decelerates to zero.

**Safety consequence:** a jog loop must be paired with a watchdog or a guaranteed
`stopj` in the error path. A crashed control PC otherwise leaves the arm moving.

### `servoj(q, t=0.008, lookahead_time=0.1, gain=300)`

Streaming position control; `t=0.008` is one 125 Hz frame on CB3 (e-Series
examples use 0.002 — do not copy them). No blend radius and none needed;
smoothness comes from `lookahead_time` and from your setpoints being smooth.
It faithfully reproduces jerk in the setpoint stream. Requires a genuine 125 Hz
feed, and speed scaling below 100% stretches each call, silently halving your
effective loop rate.

### Program end, deceleration, and the brakes

UNVERIFIED: the 3.13 manual specifies **no** deceleration profile for program
termination. Do not rely on an implicit stop; end any script that leaves the arm
moving with an explicit `stopj(a)`.

On brakes, the documentation is clearer than our code comments assumed:

- Brakes are commanded to stop the arm only on a **Stop Category 0** (safety
  limit violation / safety-system fault). Categories 1 and 2 decelerate with
  drive power on.
- Brakes engage on **arm power-off**.
- **There is no documented idle-timeout brake engagement on CB3.** Robot mode
  stays `RUNNING (7)` between programs and holding is done by motor torque.
- Brake *release* is documented to click, but that is the initialization event.

**So the "click" between separately-sent motions is almost certainly not the
brakes.** The most plausible explanation is the program lifecycle itself: each
send is a full load/start/stop cycle, and what is heard is the servo transition
from trajectory-following to position-hold plus the mechanical settle of an
abrupt deceleration. Our `SMOOTH_MOTION.md` attributes it to brake engagement;
that attribution is probably wrong, though **the fix it prescribes is right for
the right reason** — eliminating program boundaries eliminates the stop.

This is settleable with our own instrument: log `robot_mode`, `joint_mode` and
`actual_current` at 125 Hz across a boundary. If `joint_mode` stays `253
(RUNNING)` through the click, the brakes never engaged. That is experiment 03.

### Speed scaling

The pendant slider does **not** rewrite `v` and `a` — it **dilates the time axis**
of trajectory execution, preserving the path exactly. Consequences: a blocking
`movej(t=…)` takes `t/s` seconds; a `speedj` loop at 50% both halves the achieved
velocity and stretches each blocking call; and `servoj(t=0.008)` at 50% blocks
16 ms, silently dropping a 125 Hz feed to 62 Hz.

Read `target_speed_fraction` for the slider position. Do **not** infer it from
`speed_scaling`, which is also reduced by program pause, E-stop, safeguard stop,
and proximity to safety limits. `speed_scaling == 0` means paused or E-stopped.

Measured on this robot: `target_speed_fraction` **1.00**, `speed_scaling`
**1.00** — nothing on the controller side is throttling us.

---

## 5. How our code currently drives the robot

| Call site | Program shape | Trigger |
|---|---|---|
| `move_joint()` → `movej` | one-shot, ends immediately | Move-Home, Test-Move, step jog |
| `speed_joint()` → `speedj` | one-shot, `t=0.2`, resent every 100 ms | continuous jog |
| `move_joint_path()` / `move_joint_program()` | one program, multi-waypoint, **ends** | `DemoRunner`, legacy demos |
| `move_joint_program_loop()` | one persistent `while True` program | all 11 choreographed demos |

The choreographed demos already use the correct architecture. The logs confirm
the historical problem and its fix: one May block shows `jsecco_demo_path`
starting *and fully stopping* every ~3 seconds — five complete program lifecycles
in a row — immediately before switching to `jsecco_demo_loop`.

**Two per-position paths remain live:**

1. Step jog and Move-Home send one `movej` with `r=0` per action. Intentional
   and correct — a single deliberate move should stop.
2. `DemoRunner` falls back to a per-waypoint `move_joint()` loop when the
   controller lacks `move_joint_path`. **`RTDEController` lacks that method**, so
   now that `ur_rtde` is installed and `use_rtde_for_motion: true`, this fallback
   can reintroduce exactly the anti-pattern. This needs fixing before the RTDE
   path is used for demos.

---

## 6. The actual cause of the stalling: overlapping blends

Applying the documented rule `r[i] + r[i+1] <= tcp_leg_length` to the programs
our demos really emit (measured via `motion_lab/experiments/exp01_audit_blends.py`,
which captures each demo's waypoints through a fake controller and computes TCP
leg lengths from forward kinematics):

| Demo | Legs violating the rule |
|---|---|
| WaveDemo | **17 of 22** |
| SortingDemo | **20 of 37** |
| StackingDemo | **17 of 34** |
| PendulumDemo | **12 of 20** |
| TechnicalDemo | **11 of 23** |
| BowDemo | **9 of 12** |
| JuggleDemo | **8 of 13** |
| IndustrialDemo | **7 of 14** |
| SprintDemo | **3 of 8** |
| ReachDemo | **2 of 8** |
| PlungeDemo | **1 of 9** |

**Every demo is affected.** The controller is skipping waypoints throughout the
choreographies and emitting 'Overlapping Blends' warnings we never surfaced.

Two distinct defects produce this:

1. **Radii authored in the wrong unit.** The blend values (0.05–0.12) were chosen
   as though they were joint-space quantities. In metres of TCP path they are
   enormous: WaveDemo leg 11 travels **9 mm** of TCP while demanding 172 mm of
   combined blend — 19× more than exists.
2. **Degenerate zero-length legs.** Several demos contain consecutive waypoints
   that are geometrically identical (SprintDemo's "Sprint Ctr" and "Lower" both
   resolve to the same pose; WaveDemo has four such legs). Any `r > 0` violates
   the rule there, and the leg does nothing anyway.

This is a much better explanation of the symptom than program boundaries: the
demos already run as one looping program, yet motion still looks wrong, because
the controller is discarding waypoints and improvising the path between whatever
survives.

Note the interaction with speed: raising the speed caps (2026-07-30) did not
change the geometry, so faster execution of a path with skipped waypoints looks
*more* erratic, not less.

---

## 7. What to do, in order

Work happens in `motion_lab/` against the real robot and is only promoted into
`src/` once measured. See `motion_lab/README.md`.

1. **Re-derive every demo's blend radii from TCP geometry.** `blend.suggest_radii()`
   already computes the largest radii that satisfy the rule. Apply, re-audit,
   confirm zero violations offline.
2. **Delete degenerate waypoints** (zero-length legs) from the choreographies.
3. **Measure before/after on the real arm** with `motion_lab/lab.py`, which
   records joint velocity at 125 Hz and reports mid-motion stalls automatically.
   The acceptance criterion is objective: zero stalls, and peak joint speed at
   the commanded value.
4. **Settle the click question** (experiment 03) by logging `joint_mode` across a
   program boundary — this tells us whether `SMOOTH_MOTION.md`'s brake theory or
   the program-lifecycle theory is right.
5. **Fix the `DemoRunner` RTDE fallback** before enabling RTDE motion for demos.
6. **Bench-test the three UNVERIFIED items** in §4.
7. Only then promote changes into `src/` and re-run the full audit.

## Sources

Official: URScript Programming Language v3.13 (scriptManual.pdf); UR10/CB3 User
Manual; RTDE Guide; Overview of Client Interfaces; Primary/Secondary and Realtime
Client Interface specifications; Dashboard Server CB-Series; UR support articles
on SSH, magic files, password reset, speed slider, and servoj trajectories.
Library: ur_rtde (`rtde_control.script`, `rtde_control_interface.cpp`).
Measured on this robot: realtime packet size and field offsets, speed scaling and
slider fraction, blend audit of all 11 demos, port 22 reachability.
