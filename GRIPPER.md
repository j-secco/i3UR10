# Gripper: DYNAMIXEL XL330-M288-T on the UR10 CB3

Companion to `UR10_REFERENCE.md`. Everything here is sourced from the ROBOTIS
e-Manual and the UR10/CB3 User Manual, with the electrical limits that actually
constrain the design called out first.

## The two constraints that decide the whole design

**1. The servo is 5 V. The tool connector is 12/24 V.**
XL330-M288-T operates on 3.7–6.0 V, recommended 5.0 V. Its only overvoltage
protection is a software voltage-monitor register (Max Voltage Limit, default
7.0 V) — there is no hardware clamp or fuse. Feeding it 12 V or 24 V destroys
it. **A 5 V regulator between the tool connector and the servo is mandatory.**

**2. The CB3 tool connector has no serial bus.**
RS-485 at the tool flange is an **e-Series** feature and is **not present on
CB3**. The eight pins are fully accounted for: 2 analog in, 2 digital in,
2 digital out, power, ground. There is no UART, so the Dynamixel's TTL data
line cannot terminate at the wrist. It has to terminate either at a
microcontroller mounted on the tool, or at the control PC via a cable.

## Tool connector pinout (8-pin M8, Lumberg RSMEDG8)

| Pin | Colour | Signal | Notes |
|---|---|---|---|
| 1 | White | Analog in 2 | non-differential |
| 2 | Brown | Analog in 3 | non-differential |
| 3 | Yellow | Digital in 0 | 47 kΩ weak pull-down (floats low) |
| 4 | Green | Digital in 1 | same |
| 5 | **Grey** | **Tool power 0 / 12 / 24 V** | selectable; **600 mA max**, short-circuit protected |
| 6 | Blue | Digital out 0 | **open-drain, sink only**, 1 A |
| 7 | Pink | Digital out 1 | same |
| 8 | **Red** | **0 V** | common return |

Pin numbers come from the UR5 Service Manual and colours from the UR10/CB3
User Manual; no single official table prints both, so verify continuity with a
meter before trusting the pairing on your cable.

Two consequences worth internalising:

- The tool digital outputs **sink only, they cannot source**. Anything reading
  them needs a pull-up to its own logic rail, and the logic is inverted:
  asserting the UR output pulls the line low.
- Tool voltage is currently set to **0 V** on this robot (confirmed from the
  pendant I/O screenshot). It must be set to 24 V before anything at the tool
  powers up — `set_tool_voltage(24)` in URScript, or the I/O tab in PolyScope.

## Power budget: the tool connector can run this servo, at 24 V

| | |
|---|---|
| Tool connector at 24 V | 24 V × 0.6 A = **14.4 W available** |
| Buck converter to 5 V, ~85% efficient | ≈ 12 W at 5 V ≈ **2.4 A** |
| XL330 stall current at 5 V | 1.47 A = 7.35 W, drawing ≈ **360 mA at 24 V** |

So a 24 V→5 V buck rated for at least 2 A leaves roughly 40% headroom against
the connector's limit even with the servo fully stalled. **Do not do this at
12 V**: 12 V × 0.6 A yields only ~1.2 A at 5 V, below the servo's stall
current, so a hard grip would brown it out.

Watch inrush — the buck's input capacitance can trip the connector's
short-circuit protection at power-on. Prefer a converter with soft-start, and
keep input capacitance modest.

## Recommended architecture: serial to the control PC

```
Elo PC ── USB ── U2D2 ──┐
                        │ DATA + GND  (2 wires up the arm)
                        ▼
UR tool connector ── 24 V → buck → 5 V ── XL330 (VDD)
       pin 5 / pin 8                        │
                                     GND common ┘
```

- The **U2D2 does not supply power** — it is signal only. Power comes from the
  local buck at the tool, so only DATA and GND run the length of the arm.
- Ground must be common between the U2D2 and the servo. Tie them at the servo
  end; the robot's 0 V and the PC's USB ground are usually already bonded
  through mains earth, so join at one point only.
- TTL at 57 600 baud over ~1.5 m of unshielded wire is unproblematic. Do not
  raise the baud rate to 1 Mbps+ over that run without shielding.

**Why this one:** the app already lives on the Elo PC and already reads the
robot's realtime stream at 125 Hz. Driving the servo from the same Python
process makes the gripper just another actuator in the choreography — no
microcontroller, no firmware, no PWM timing problem, and grip force becomes a
register write rather than a mechanical guess.

### Synchronising the gripper with the arm

Two options, in increasing tightness:

1. **Timeline** — the demo runner already keeps a notify clock in step with the
   choreography; gripper calls slot into it. Simple, but drifts over long loops.
2. **Digital-output handshake** — the URScript program asserts a tool digital
   output at the grip moment (`set_tool_digital_out(0, True)`), and the Python
   side, already reading the realtime packet, sees the output bits change and
   commands the servo. Tight, and costs nothing extra because the telemetry
   loop exists.

## Alternative: microcontroller on the tool

If a cable along the arm is unacceptable, mount a small MCU (OpenRB-150, or a
XIAO plus a tri-state buffer for half-duplex) at the tool, powered from the
same buck. It speaks Dynamixel locally over a short, reliable bus, and takes
commands from the UR's two tool digital outputs — 2 bits, so 4 gripper states.

Trade-off: no cable, but only four discrete states, firmware to maintain, and
no servo feedback (position, current, temperature) reaching the app unless you
spend the two tool digital inputs on it. For a demo that wants proportional
grip and health monitoring, the serial route is better.

## Control model: force is a current limit, not a position

The driver (`motion_lab/gripper.py`) uses **Operating Mode 5, current-based
position control**. The servo drives toward Goal Position but never exceeds
Goal Current, so closing on an object stalls gently at the commanded force.
Closing "to a position" would either miss the object or crush it.

Key registers (XL330-M288-T, Protocol 2.0):

| Register | Addr | Size | Purpose |
|---|---|---|---|
| Operating Mode | 11 | 1 | 5 = current-based position (write with torque off) |
| Current Limit | 38 | 2 | EEPROM ceiling, ~1 mA/unit, max 1750 |
| Torque Enable | 64 | 1 | |
| Hardware Error Status | 70 | 1 | bitmask: voltage, overheat, overload… |
| Goal Current | 102 | 2 | **grip force** |
| Goal Position | 116 | 4 | 0–4095 over 360° |
| Present Position | 132 | 4 | |
| Present Temperature | 146 | 1 | °C |

**Thermal limit matters for a demo.** Stall torque is 0.52 N·m at 5 V, but
ROBOTIS' estimated *continuous* rating is about 0.10 N·m — roughly 20% of
stall. At Temperature Limit (default 70 °C) the Shutdown register forces
Torque Enable off, which **drops whatever is being held**. The driver
therefore defaults to 150 mA of grip current against a 1470 mA stall, caps any
request at 800 mA, and exposes `check_health()` for sustained grips.

## Before the gripper moves: pendant changes

1. **Tool voltage 0 V → 24 V** (I/O tab).
2. **Payload** — currently declared 2.00 kg with a bare flange. Set it to the
   real gripper mass plus workpiece.
3. **TCP offset** — currently 0,0,0. Set it to the new fingertip.
4. **Centre of gravity** — currently unset.

Items 2–4 are not paperwork. The robot estimates force and momentum from the
declared payload, and the momentum limit is the tightest safety constraint on
this installation. A wrong payload produces nuisance protective stops and
degrades the force estimate that the collaborative limits depend on.

## Software state on the control PC

- `dynamixel-sdk` 4.0.5 and `pyserial` 3.5 installed in the venv.
- No USB serial adapter present yet; `/dev/ttyUSB*` does not exist.
- **The `ur10` user is not in the `dialout` group.** Before the U2D2 can be
  opened: `sudo usermod -aG dialout ur10`, then log out and back in.
- `motion_lab/gripper.py` is written and unit-checked against bad inputs; it
  refuses to enable torque if the servo reports a supply outside 3.7–6.0 V.

## Calibration, once mounted

With torque off the fingers move by hand. `Gripper.calibrate()` prints the
present position; record it fully open and fully closed and pass those two
numbers as `open_position` and `closed_position`. Then set `grip_current_ma`
by experiment, starting low: enough to hold the object, no more.
