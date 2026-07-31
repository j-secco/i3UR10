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

from envelope import DEFAULT_PATH, Envelope  # noqa: E402
from telemetry import Recorder, read_once  # noqa: E402

PRIMARY_PORT = 30001
DASHBOARD_PORT = 29999
MAX_FREEDRIVE_SECONDS = 300


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


def live_line(samples):
    q = samples[-1].q
    return ("  J " + " ".join(f"{math.degrees(v):7.1f}" for v in q) +
            f"   tcp z {samples[-1].tcp[2]:.3f} m   {len(samples)} samples")


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
    args = ap.parse_args()

    if args.freedrive is not None and not (0 < args.freedrive <= MAX_FREEDRIVE_SECONDS):
        raise SystemExit(f"--freedrive must be in (0, {MAX_FREEDRIVE_SECONDS}] seconds")

    safety = dashboard(args.host, "safetymode")
    mode = dashboard(args.host, "robotmode")
    print(f"robot: {safety} / {mode}")
    if "NORMAL" not in safety:
        raise SystemExit("recover the robot before teaching")
    if "RUNNING" not in mode:
        raise SystemExit("power on and release brakes before teaching")
    if read_once(args.host) is None:
        raise SystemExit("no telemetry; is another client holding port 30003?")

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
            if args.duration is not None:
                deadline = time.time() + args.duration
                while time.time() < deadline:
                    time.sleep(0.2)
            else:
                print("\nEnter a name + Enter to mark the current pose, "
                      "or just 'q' + Enter to finish.\n")
                while True:
                    try:
                        line = input().strip()
                    except EOFError:
                        break
                    if line.lower() in ("q", "quit", "done"):
                        break
                    if rec.trace.samples:
                        s = rec.trace.samples[-1]
                        marks.append({"name": line or f"mark{len(marks) + 1}",
                                      "joints": list(s.q), "tcp": list(s.tcp)})
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
    samples = [list(s.q) for s in rec.trace.samples]
    if len(samples) < 50:
        raise SystemExit(f"only {len(samples)} samples; move the arm through the "
                         f"region for longer")

    env = Envelope.from_samples(samples, note=args.note)
    env.marks = marks

    if args.append:
        old = Envelope.load_if_present(args.out)
        if old:
            env.joint_min = [min(a, b) for a, b in zip(env.joint_min, old.joint_min)]
            env.joint_max = [max(a, b) for a, b in zip(env.joint_max, old.joint_max)]
            env.tcp_min = [min(a, b) for a, b in zip(env.tcp_min, old.tcp_min)]
            env.tcp_max = [max(a, b) for a, b in zip(env.tcp_max, old.tcp_max)]
            env.elbow_min = [min(a, b) for a, b in zip(env.elbow_min, old.elbow_min)]
            env.elbow_max = [max(a, b) for a, b in zip(env.elbow_max, old.elbow_max)]
            env.marks = old.marks + env.marks
            env.samples += old.samples
            print(f"widened the existing envelope from {args.out}")

    print("\n" + env.report())
    print(f"\nsaved to {env.save(args.out)}")
    print("The lab now refuses any experiment whose path leaves this region.")


if __name__ == "__main__":
    main()
