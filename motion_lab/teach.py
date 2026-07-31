"""
Teach the safe workspace by hand-guiding the arm.

Records where you take the robot and turns it into an envelope: per-joint
limits, TCP bounds, elbow bounds. Those numbers go onto the pendant's Safety
screen (where they become genuinely enforced) and into the lab's pre-flight
check (where they stop an experiment ever commanding a path outside).

DEFAULT MODE IS READ-ONLY. It sends the robot nothing. You hold the Freedrive
button on the teach pendant and move the arm; this just watches the 125 Hz
telemetry stream. Nothing here can make the arm limp, so nothing here can
leave it limp.

    venv/bin/python motion_lab/teach.py                 # interactive, read-only
    venv/bin/python motion_lab/teach.py --duration 90   # unattended window
    venv/bin/python motion_lab/teach.py --freedrive 120 # software freedrive

--freedrive commands a TIME-BOUNDED freedrive from the PC, for when nobody is
holding the pendant. It expires on its own inside the URScript program, so a
dropped network connection cannot leave the arm free. Prefer the pendant
button when you have it: a dead-man switch beats a timeout.

WHAT THIS CAPTURES, AND WHAT IT DOES NOT
----------------------------------------
The result is a bounding box per quantity. If you trace the edges of a region,
the whole box is treated as allowed -- including parts you never visited. That
is usually what you want and it is always at least as permissive as reality,
so walk the arm around anything inside the box that it must avoid, and place a
pendant safety plane there instead. This tool cannot represent a hole.
"""

import argparse
import json
import math
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)

import yaml  # noqa: E402

from envelope import (BASE_EXCLUSION_R, DEFAULT_PATH, FLOOR_SECTORS,  # noqa: E402
                      Envelope, Zone, arm_points)
from obstacles import ObstacleSet, Prism  # noqa: E402
from telemetry import Recorder, read_once  # noqa: E402

PRIMARY_PORT = 30001
DASHBOARD_PORT = 29999
MAX_FREEDRIVE_SECONDS = 300

# Every prompt accepts the same words for "I am finished". Two modes with two
# different keys is a trap when the operator is standing at the robot with one
# hand on the Freedrive button.
DONE_WORDS = ("d", "q", "done", "quit", "finish", "end")

# UR10 joints travel +/-360 degrees. Hand-guiding the arm round the base
# several times in the same direction winds J1 up without anything physical
# stopping it, and once a joint is past its limit the robot sits in Recovery
# Mode -- which a power cycle does not clear, because the position persists.
# Warn well before that, and again at the end.
JOINT_LIMIT_DEG = 360.0
JOINT_WARN_DEG = 300.0

# A checklist for --guided. Between them these six poses pin every face of the
# box; skipping one leaves that face defined by wherever the arm happened to
# be, which is how a taught envelope ends up quietly wrong.
GUIDED_STEPS = [
    ("left", "swing the arm as far LEFT as it should ever go"),
    ("right", "now as far RIGHT as it should ever go"),
    ("forward", "reach as far FORWARD / away from the base as it should go"),
    ("near", "bring it back as CLOSE to the base as it should go"),
    ("high", "raise the tool as HIGH as it should ever go"),
    ("low", "lower the tool as LOW as it should go -- mind the table"),
]


def dashboard(host, cmd):
    with socket.create_connection((host, DASHBOARD_PORT), timeout=4) as s:
        s.recv(4096)
        s.sendall((cmd + "\n").encode())
        return s.recv(4096).decode().strip()


def send(host, program):
    with socket.create_connection((host, PRIMARY_PORT), timeout=4) as s:
        s.sendall((program.rstrip("\n") + "\n").encode())


def freedrive_program(seconds: float) -> str:
    """Bounded freedrive. Expires inside the controller, so losing the network
    cannot strand the arm in a hand-movable state."""
    return (
        "def lab_teach_freedrive():\n"
        "  freedrive_mode()\n"
        f"  sleep({seconds:.1f})\n"
        "  end_freedrive_mode()\n"
        "end\n"
        "lab_teach_freedrive()"
    )


def checkpoint(marks, out_path):
    """Write marks to a sidecar after every one.

    Teaching costs physical effort at the robot. If anything later in the run
    fails, the poses that were actually walked to should survive it, so they
    hit the disk immediately rather than only at the end.
    """
    if not marks:
        return
    try:
        with open(out_path + ".marks.json", "w") as fh:
            json.dump(marks, fh, indent=2)
    except OSError as exc:
        print(f"  (could not checkpoint marks: {exc})")


def current_pose(rec, timeout: float = 3.0):
    """Latest telemetry sample, waiting briefly for the stream to warm up.

    The recorder needs a moment to connect and the first mark can land inside
    that window, so wait rather than telling the operator to try again while
    they are standing at the robot holding the arm.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if rec.trace.samples:
            return rec.trace.samples[-1]
        time.sleep(0.05)
    return None


def wound_joints(sample, threshold=JOINT_WARN_DEG):
    """Joints approaching their +/-360 degree travel limit."""
    return [(i + 1, math.degrees(v)) for i, v in enumerate(sample.q)
            if abs(math.degrees(v)) > threshold]


def live_line(samples):
    s = samples[-1]
    warn = ""
    for j, d in wound_joints(s):
        warn += f"   !! J{j} {d:+.0f} deg, limit {JOINT_LIMIT_DEG:.0f}"
    return ("  J " + " ".join(f"{math.degrees(v):7.1f}" for v in s.q) +
            f"   tcp z {s.tcp[2]:.3f} m   {len(samples)} samples" + warn)


def check_winding(sample, when):
    """Refuse to start, or complain at the end, if a joint is wound up.

    Sweeping the arm around the base repeatedly is the natural way to teach a
    workspace and the natural way to wind J1 past its travel limit. The cost
    of missing it is Recovery Mode and hand-unwinding nearly two turns, so it
    is worth saying loudly.
    """
    bad = wound_joints(sample)
    if not bad:
        return False
    print(f"\n!! {when}:")
    for j, d in bad:
        turns = (abs(d) - JOINT_LIMIT_DEG) / 360.0
        past = f", {turns:.2f} turns PAST its limit" if abs(d) > JOINT_LIMIT_DEG else ""
        print(f"!!   J{j} is at {d:+.0f} deg (limit +/-{JOINT_LIMIT_DEG:.0f}){past}")
    print("!! Unwind it before continuing -- past the limit the robot enters Recovery")
    print("!! Mode, which a restart does not clear, and it has to be jogged back by")
    print("!! hand from the pendant. Sweep back the way you came rather than round again.")
    return True




def measure_obstacle(args):
    """Measure a solid by walking the flange around its top edge.

    Each press records where the flange centre is, so the footprint and the
    top height arrive already in the robot's base frame -- no tape, no
    transform arithmetic. The recorded point is the CENTRE of the flange, not
    its surface, which is why a clearance margin is kept around the result.
    """
    env = Envelope.load_if_present(args.out)
    if env is None:
        raise SystemExit(f"no envelope at {args.out}; teach the workspace first")

    rec = Recorder(args.host)
    corners = []
    with rec:
        print(f"\n=== measuring '{args.obstacle}' ===")
        print("Put the FLANGE CENTRE on each corner of the solid's TOP edge and press")
        print("Enter. Go round in order -- the points become a footprint polygon, and")
        print("their height becomes the top surface.")
        print("  Enter    record a corner        u  undo the last one")
        print("  d or q   done, and save         Ctrl-C  same\n")
        while True:
            try:
                line = input(f"  [{len(corners)} corners] ").strip().lower()
            except EOFError:
                line = "d"
            if line in DONE_WORDS:
                break
            if line == "u":
                if corners:
                    print(f"    removed {corners.pop()}")
                continue
            smp = current_pose(rec)
            if smp is None:
                print("    no telemetry")
                continue
            pt = [round(smp.tcp[0], 4), round(smp.tcp[1], 4), round(smp.tcp[2], 4)]
            corners.append(pt)
            print(f"    corner {len(corners)}: x {pt[0]:+.3f}  y {pt[1]:+.3f}  z {pt[2]:+.3f}")

    if len(corners) < 3:
        raise SystemExit(f"{len(corners)} corners; a footprint needs at least 3")

    polygon = [[c[0], c[1]] for c in corners]
    z_top = max(c[2] for c in corners)
    spread = z_top - min(c[2] for c in corners)
    solid = Prism(name=args.obstacle, polygon=polygon, z_top=round(z_top, 4),
                  margin=args.margin)

    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
    print(f"\n  footprint {len(polygon)} corners, "
          f"{max(xs) - min(xs):.3f} x {max(ys) - min(ys):.3f} m")
    print(f"  top surface {z_top:+.3f} m, corners varied by {spread * 1000:.0f} mm")
    if spread > 0.03:
        print("  (they should all be on the same top surface -- check the outliers)")
    print(f"  clearance kept: {args.margin * 1000:.0f} mm around it, plus each link's "
          f"own radius")

    env.obstacles = [o for o in env.obstacles if o.get("name") != solid.name]
    env.obstacles.append({"name": solid.name, "polygon": solid.polygon,
                          "z_top": solid.z_top, "z_bottom": solid.z_bottom,
                          "margin": solid.margin})
    env.save(args.out)
    print("\n" + "\n".join(ObstacleSet.from_json(env.obstacles).describe()))
    print(f"\nsaved to {args.out}")


def teach_zone(args):
    """Teach one region's real limit and merge it into the saved envelope.

    The arm is swept ALONG the obstacle at the lowest height it may safely
    reach, and the floor is recorded per bearing sector as it goes. Clearance
    is rarely uniform -- tighter at one end, roomier at the other -- so a
    single number for the whole sweep would be wrong wherever the real limit
    is tighter than the average.
    """
    env = Envelope.load_if_present(args.out)
    if env is None or env.dome is None:
        raise SystemExit(f"no envelope at {args.out} to add a zone to; teach one first")

    rec = Recorder(args.host)
    with rec:
        print(f"\n=== teaching zone '{args.zone}' ===")
        print("Position the arm at the lowest pose that clears the obstacle at ONE END")
        print("of this region, then press Enter to start recording.")
        try:
            input("  ready... ")
        except EOFError:
            raise SystemExit("aborted")
        if current_pose(rec) is None:
            raise SystemExit("no telemetry")
        start = len(rec.trace.samples)

        print("\nNow sweep ALONG the obstacle to the other end, keeping the arm as low")
        print("as it may safely go. Raise it where it has to come up -- that is the")
        print("point. Press Enter when you reach the far end.")
        try:
            input("  recording... ")
        except EOFError:
            pass
        swept = rec.trace.samples[start:]

    if len(swept) < 40:
        raise SystemExit(f"only {len(swept)} samples; sweep more slowly")

    # Lowest the whole arm reached, per bearing sector.
    step = 360 // FLOOR_SECTORS
    lows, counts = {}, {}
    for smp in swept:
        pts = [p for p in arm_points(smp.q) if math.hypot(p[0], p[1]) > BASE_EXCLUSION_R]
        if not pts:
            continue
        # One cell per arm point: a zone limit belongs to where that part of
        # the arm actually was, in bearing AND distance out.
        for pt in pts:
            key = Zone._key(pt[0], pt[1])
            lows[key] = min(lows.get(key, math.inf), pt[2])
            counts[key] = counts.get(key, 0) + 1

    # A sector crossed in a fraction of a second was passed through, not
    # demonstrated. Requiring a dwell keeps a flick of the wrist from
    # declaring a limit.
    MIN_SAMPLES = 25
    kept = {k: round(v + args.clearance, 4) for k, v in lows.items()
            if counts[k] >= MIN_SAMPLES}
    thin = [k for k in lows if counts[k] < MIN_SAMPLES]
    if not kept:
        raise SystemExit("no sector was held long enough; sweep more slowly")
    bearings = {k.split(",")[0] for k in kept}
    if len(bearings) >= FLOOR_SECTORS - 2:
        print(f"\n!! this sweep touches {len(bearings)} of {FLOOR_SECTORS} bearings -- nearly")
        print("!! the whole circle. A zone is meant to be a region; if you swept")
        print("!! everywhere, general teaching is the right tool. Saving anyway.")

    reach = max(math.sqrt(sum(v * v for v in p))
                for smp in swept for p in arm_points(smp.q))
    zone = Zone(name=args.zone, floors=kept,
                r_max=reach if args.limit_reach else math.inf)

    print(f"\n  {len(swept)} samples over {len(kept)} sectors "
          f"(+{args.clearance:.3f} m clearance applied)")
    for k in sorted(kept, key=lambda kk: (int(kk.split(",")[0]), int(kk.split(",")[1]))):
        base = env.dome.cells.get(k, float("nan"))
        d = kept[k] - base
        arrow = ("raises" if d > 0.005 else "lowers" if d < -0.005 else "matches") + \
                f" the inferred bin by {abs(d):.3f} m" if abs(d) > 0.005 else "matches the bin"
        sec, ring = (int(v) for v in k.split(","))
        print(f"    {sec * step:>3}-{(sec + 1) * step:<3} deg  "
              f"{ring * 0.2:.1f}-{(ring + 1) * 0.2:.1f} m out  "
              f"{kept[k]:+.3f} m   grid {base:+.3f} m   {arrow}")
    if thin:
        print(f"  skipped {len(thin)} cells passed through too quickly")
    print(f"  furthest the arm reached: {reach:.3f} m"
          + ("  (enforced)" if args.limit_reach else "  (recorded only)"))

    env.dome.zones = [z for z in env.dome.zones if z.name != zone.name] + [zone]
    env.save(args.out)
    print("\n" + "\n".join(env.dome.describe()))
    print(f"\nsaved to {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.10.24")
    ap.add_argument("--out", default=DEFAULT_PATH)
    ap.add_argument("--duration", type=float, default=None,
                    help="record for N seconds without prompting, then save")
    ap.add_argument("--freedrive", type=float, default=None,
                    help="command a time-bounded software freedrive for N seconds "
                         "instead of using the pendant button")
    ap.add_argument("--note", default="")
    ap.add_argument("--append", action="store_true",
                    help="widen an existing envelope instead of replacing it")
    ap.add_argument("--guided", action="store_true",
                    help="walk a checklist of extremes, marking each one")
    ap.add_argument("--from-marks", action="store_true",
                    help="build the envelope from marked poses only, ignoring "
                         "the motion between them (implied by --guided)")
    ap.add_argument("--obstacle", default=None, metavar="NAME",
                    help="measure a solid by touching round its top edge: the "
                         "footprint and height go straight into the base frame")
    ap.add_argument("--margin", type=float, default=0.05,
                    help="clearance kept around a measured solid (default 0.05 m)")
    ap.add_argument("--zone", default=None, metavar="NAME",
                    help="teach one bearing sector's limit into an existing "
                         "envelope: hold the arm at the lowest safe pose, then "
                         "sweep the arc that limit applies to")
    ap.add_argument("--clearance", type=float, default=0.02,
                    help="raise a taught zone floor by this much (default 0.02 m)")
    ap.add_argument("--limit-reach", action="store_true",
                    help="also cap reach in the zone at the radius swept")
    ap.add_argument("--free-joints", default="",
                    help="comma-separated joints exempt from the range check, "
                         "e.g. 4,5,6 when the wrists were held still")
    args = ap.parse_args()

    from_marks = args.from_marks or args.guided
    free_joints = [int(j) for j in args.free_joints.split(",") if j.strip()]

    if args.freedrive is not None and not (0 < args.freedrive <= MAX_FREEDRIVE_SECONDS):
        raise SystemExit(f"--freedrive must be in (0, {MAX_FREEDRIVE_SECONDS}] seconds")

    safety = dashboard(args.host, "safetymode")
    mode = dashboard(args.host, "robotmode")
    print(f"robot: {safety} / {mode}")
    if "NORMAL" not in safety:
        raise SystemExit("recover the robot before teaching")
    if "RUNNING" not in mode:
        raise SystemExit("power on and release brakes before teaching")
    first = read_once(args.host)
    if first is None:
        raise SystemExit("no telemetry; is another client holding port 30003?")
    if check_winding(first, "before starting, a joint is already wound up"):
        raise SystemExit("unwind it first, or teaching will push it further")

    if args.obstacle:
        print("\nRead-only: hold the pendant Freedrive button to move the arm.")
        measure_obstacle(args)
        return

    if args.zone:
        print("\nRead-only: hold the pendant Freedrive button to move the arm.")
        teach_zone(args)
        return

    if args.freedrive is not None:
        print(f"\n!! commanding software freedrive for {args.freedrive:.0f}s.")
        print("!! SUPPORT THE ARM: it goes limp and will sag under its own weight")
        print("!! and under any tool. It re-holds automatically when the time expires.")
        input("press Enter when you are ready and holding the arm... ")
        send(args.host, freedrive_program(args.freedrive))
        time.sleep(0.3)
    else:
        print("\nRead-only mode: nothing is sent to the robot.")
        print("Hold the Freedrive button on the pendant and guide the arm to the")
        print("edges of the region you want it to work in. Walk the perimeter and")
        print("both the highest and lowest poses you are happy with.")

    rec = Recorder(args.host)
    marks = []
    stop = threading.Event()

    def show():
        while not stop.wait(1.0):
            if rec.trace.samples:
                print(live_line(rec.trace.samples), end="\r", flush=True)

    with rec:
        printer = threading.Thread(target=show, daemon=True)
        printer.start()
        try:
            if args.guided:
                print("\nGuided teaching. Move the arm to each pose, then press Enter.")
                print("  Enter    record this pose       s  skip it")
                print("  d or q   finish and save        Ctrl-C  same\n")
                done_early = False
                for name, prompt in GUIDED_STEPS:
                    while True:
                        try:
                            answer = input(f"  [{name}] {prompt} ... ").strip().lower()
                        except EOFError:
                            answer = "q"
                        if answer in DONE_WORDS:
                            done_early = True
                            break
                        if answer == "s":
                            print(f"    skipped {name}")
                            break
                        s = current_pose(rec)
                        if s is None:
                            print("    no telemetry; check the connection")
                            continue
                        marks.append({"name": name, "joints": list(s.q),
                                      "tcp": list(s.tcp)})
                        checkpoint(marks, args.out)
                        print(f"    recorded {name}: tcp "
                              f"({s.tcp[0]:.3f}, {s.tcp[1]:.3f}, {s.tcp[2]:.3f}) m"
                              f"   [{len(marks)} marked]")
                        break
                    if done_early:
                        print(f"  finishing early with {len(marks)} marks")
                        break
                if not done_early:
                    print("\nChecklist done. Name an extra pose + Enter to mark it, "
                          "or 'q' / 'd' to finish.")
                    while True:
                        try:
                            line = input().strip()
                        except EOFError:
                            break
                        if line.lower() in DONE_WORDS:
                            break
                        s = current_pose(rec)
                        if s is not None:
                            marks.append({"name": line or f"extra{len(marks) + 1}",
                                          "joints": list(s.q), "tcp": list(s.tcp)})
                            checkpoint(marks, args.out)
                            print(f"  marked '{marks[-1]['name']}'   "
                                  f"[{len(marks)} total]")
            elif args.duration is not None:
                deadline = time.time() + args.duration
                while time.time() < deadline:
                    time.sleep(0.2)
            else:
                print("\nEnter a name + Enter to mark the current pose, "
                      "or 'q' / 'd' + Enter to finish.\n")
                while True:
                    try:
                        line = input().strip()
                    except EOFError:
                        break
                    if line.lower() in DONE_WORDS:
                        break
                    s = current_pose(rec)
                    if s is not None:
                        marks.append({"name": line or f"mark{len(marks) + 1}",
                                      "joints": list(s.q), "tcp": list(s.tcp)})
                        checkpoint(marks, args.out)
                        print(f"  marked '{marks[-1]['name']}' at "
                              f"{[round(math.degrees(v), 1) for v in s.q]}")
        except KeyboardInterrupt:
            print("\ninterrupted")
        finally:
            stop.set()

    if args.freedrive is not None:
        try:
            send(args.host, "end_freedrive_mode()")
            print("\nfreedrive ended")
        except OSError:
            print("\ncould not send end_freedrive_mode; it expires on its own")

    if rec.error:
        print(f"telemetry warning: {rec.error}")
    if rec.trace.samples:
        check_winding(rec.trace.samples[-1], "finished, but a joint is wound up")

    swept = [list(s.q) for s in rec.trace.samples]
    if from_marks:
        if len(marks) < 2:
            raise SystemExit(f"only {len(marks)} marks; at least 2 are needed to "
                             f"bound a region")
        source = [m["joints"] for m in marks]
        print(f"\nbuilding the envelope from {len(marks)} marked poses "
              f"(motion between them ignored)")
    else:
        if len(swept) < 50:
            raise SystemExit(f"only {len(swept)} samples; move the arm through the "
                             f"region for longer")
        source = swept
        print(f"\nbuilding the envelope from {len(swept)} swept samples")

    env = Envelope.from_samples(source, note=args.note)
    env.marks = marks
    env.free_joints = free_joints

    # Show what the other choice would have given, so the difference between
    # "where I deliberately stopped" and "everywhere I happened to pass
    # through" is visible rather than assumed.
    if from_marks and len(swept) >= 50:
        alt = Envelope.from_samples(swept)
        print("  for comparison, the full swept motion would have given:")
        for i in range(6):
            m_span = math.degrees(env.joint_max[i] - env.joint_min[i])
            s_span = math.degrees(alt.joint_max[i] - alt.joint_min[i])
            if s_span - m_span > 1.0:
                print(f"    J{i + 1}: {m_span:.1f} deg from marks vs "
                      f"{s_span:.1f} deg swept")

    if args.append:
        old = Envelope.load_if_present(args.out)
        if old and old.dome and env.dome:
            # Widening a volume: reach further out, higher, and lower in each
            # bearing sector than either session alone.
            env.joint_min = [min(a, b) for a, b in zip(env.joint_min, old.joint_min)]
            env.joint_max = [max(a, b) for a, b in zip(env.joint_max, old.joint_max)]
            env.dome.r_max = max(env.dome.r_max, old.dome.r_max)
            env.dome.z_ceiling = max(env.dome.z_ceiling, old.dome.z_ceiling)
            env.dome.sector_floors = [min(a, b) for a, b in
                                      zip(env.dome.sector_floors, old.dome.sector_floors)]
            env.marks = old.marks + env.marks
            env.samples += old.samples
            print(f"widened the existing envelope from {args.out}")
        elif old:
            print(f"ignoring {args.out}: it predates the volume model, rebuild instead")

    if env.narrow_joints():
        names = ", ".join(f"J{j}" for j in env.narrow_joints())
        print(f"\nnote: {names} barely moved while teaching. That no longer restricts")
        print("the robot -- joint ranges are reportage now -- but if you copy them onto")
        print("the pendant's Joint Limits screen, widen those first.")
    print("\n" + env.report())
    print(f"\nsaved to {env.save(args.out)}")
    print("The lab now refuses any experiment whose path leaves this region.")


if __name__ == "__main__":
    main()
