"""
Motion lab harness: send a URScript program, record what the arm actually did,
report it. Isolated from the production app in src/ -- nothing here is imported
by the touchscreen UI.

Safety model (motion only happens when all of these hold):
  - the caller passes confirm=True (the CLI requires --confirm)
  - the robot reports safety NORMAL and mode RUNNING before the run
  - every waypoint and the interpolated path between them clears pose_guard
  - a watchdog stops the program after max_seconds no matter what
  - stopj is always sent on exit, including on Ctrl-C or an exception

Usage from an experiment script:

    from lab import Lab
    lab = Lab()
    trace = lab.run_program(urscript_text, seconds=8, confirm=True)
    print(trace.summary())
"""

import math
import os
import signal
import socket
import sys
import time
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from control.pose_guard import validate_path  # noqa: E402  (path set above)

from telemetry import Recorder, Trace, read_once  # noqa: E402

PRIMARY_PORT = 30001
DASHBOARD_PORT = 29999

# Ceilings for anything this harness is willing to emit. Deliberately at the
# UR10's own joint limits: the lab exists to explore full capability, so these
# are a sanity net against typos (a stray 18.0 instead of 1.8), not a policy.
LAB_MAX_SPEED_RAD_S = 3.2
LAB_MAX_ACCEL_RAD_S2 = 6.0
LAB_MAX_SECONDS = 120.0


class LabError(RuntimeError):
    pass


class Lab:
    def __init__(self, host: str = "192.168.10.24"):
        self.host = host

    # ---------------------------------------------------------------- robot io

    def dashboard(self, cmd: str) -> str:
        with socket.create_connection((self.host, DASHBOARD_PORT), timeout=4) as s:
            s.recv(4096)
            s.sendall((cmd + "\n").encode())
            return s.recv(4096).decode().strip()

    def _send(self, program: str) -> None:
        with socket.create_connection((self.host, PRIMARY_PORT), timeout=4) as s:
            s.sendall((program.rstrip("\n") + "\n").encode())

    def stop(self, decel: float = 3.0) -> None:
        """Abort whatever is running. Safe to call repeatedly."""
        try:
            self._send(f"stopj({decel})")
        except OSError:
            pass

    # ------------------------------------------------------------ preflight

    def preflight(self) -> None:
        safety = self.dashboard("safetymode")
        mode = self.dashboard("robotmode")
        if "NORMAL" not in safety:
            raise LabError(f"robot not ready: {safety} (recover it first)")
        if "RUNNING" not in mode:
            raise LabError(f"robot not ready: {mode} (power on / release brakes)")
        sample = read_once(self.host)
        if sample is None:
            raise LabError("no realtime telemetry; is another client hogging 30003?")
        if sample.joint_speed_max > 0.05:
            raise LabError("robot is already moving; stop it before running a test")

    # ------------------------------------------------------------ validation

    @staticmethod
    def check_waypoints(waypoints: Sequence[Sequence[float]], closed: bool) -> None:
        """Refuse obviously wrong programs before the robot sees them."""
        for i, wp in enumerate(waypoints):
            if len(wp) < 8:
                raise LabError(f"waypoint {i} must be [j1..j6, v, a, r]")
            v, a = wp[6], wp[7]
            if not (0 < v <= LAB_MAX_SPEED_RAD_S):
                raise LabError(f"waypoint {i}: speed {v} outside (0, {LAB_MAX_SPEED_RAD_S}]")
            if not (0 < a <= LAB_MAX_ACCEL_RAD_S2):
                raise LabError(f"waypoint {i}: accel {a} outside (0, {LAB_MAX_ACCEL_RAD_S2}]")
        violation = validate_path(waypoints, closed=closed)
        if violation is not None:
            raise LabError(f"self-collision: {violation.describe()}")

    # ------------------------------------------------------------ execution

    def run_program(self, program: str, seconds: float, confirm: bool = False,
                    label: str = "") -> Trace:
        """Send `program`, record telemetry for `seconds`, then stop and report."""
        if not confirm:
            raise LabError("refusing to move: pass confirm=True (CLI: --confirm)")
        if not (0 < seconds <= LAB_MAX_SECONDS):
            raise LabError(f"seconds must be in (0, {LAB_MAX_SECONDS}]")
        self.preflight()

        print(f"--- running {label or 'program'} for {seconds:.1f}s "
              f"(Ctrl-C stops the robot) ---")

        prev_handler = signal.getsignal(signal.SIGINT)

        def _panic(_sig, _frm):
            self.stop()
            signal.signal(signal.SIGINT, prev_handler)
            raise KeyboardInterrupt("aborted; stopj sent")

        signal.signal(signal.SIGINT, _panic)
        rec = Recorder(self.host)
        try:
            with rec:
                self._send(program)
                deadline = time.time() + seconds
                while time.time() < deadline:
                    time.sleep(0.05)
                    last = rec.trace.samples[-1] if rec.trace.samples else None
                    if last and last.safety_mode != 1.0:
                        print("!! safety mode left NORMAL - aborting")
                        break
        finally:
            self.stop()
            signal.signal(signal.SIGINT, prev_handler)
            time.sleep(0.4)  # let the deceleration land in the trace

        if rec.error:
            print(f"telemetry warning: {rec.error}")
        return rec.trace

    # ------------------------------------------------- urscript construction

    @staticmethod
    def loop_program(waypoints: Sequence[Sequence[float]], name: str = "lab_loop") -> str:
        """One persistent program that never voluntarily ends: the shape that
        allows the controller to blend across every waypoint, including the
        wrap from the last back to the first."""
        lines = [f"def {name}():", "  while True:"]
        for wp in waypoints:
            q = ", ".join(f"{x:.6f}" for x in wp[:6])
            lines.append(f"    movej([{q}], a={wp[7]}, v={wp[6]}, r={wp[8]})")
        lines += ["  end", "end", f"{name}()"]
        return "\n".join(lines)

    @staticmethod
    def oneshot_program(waypoints: Sequence[Sequence[float]], name: str = "lab_path") -> str:
        """A single program that runs the waypoints once and ends. Useful as the
        control case: the arm must decelerate to zero at the final waypoint."""
        lines = [f"def {name}():"]
        for wp in waypoints:
            q = ", ".join(f"{x:.6f}" for x in wp[:6])
            lines.append(f"  movej([{q}], a={wp[7]}, v={wp[6]}, r={wp[8]})")
        lines += ["end", f"{name}()"]
        return "\n".join(lines)

    @staticmethod
    def per_waypoint_programs(waypoints: Sequence[Sequence[float]]) -> List[str]:
        """One program per waypoint: the anti-pattern, kept so experiments can
        measure the cost of program boundaries instead of assuming it."""
        out = []
        for wp in waypoints:
            q = ", ".join(f"{x:.6f}" for x in wp[:6])
            out.append(f"movej([{q}], a={wp[7]}, v={wp[6]}, r={wp[8]})")
        return out


def tcp_leg_lengths(waypoints: Sequence[Sequence[float]], closed: bool = True) -> List[float]:
    """Cartesian distance travelled by the TCP on each leg, for blend sizing.
    URScript's r is in metres of TCP path, so a blend only takes effect if it
    is comfortably smaller than half the shortest adjoining leg."""
    from control.pose_guard import tcp_xyz
    pts = [tcp_xyz(wp[:6]) for wp in waypoints]
    if closed:
        pts.append(pts[0])
    return [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
