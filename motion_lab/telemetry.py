"""
Realtime telemetry recorder for the UR10 CB3 (port 30003). Read-only.

Field offsets were verified empirically against this controller
(PolyScope 3.13.1, packet size 1116 B = 4 + 139 float64):
  - robot mode (idx 94) read 7.0 while the Dashboard reported RUNNING
  - safety mode (idx 101) read 1.0 while the Dashboard reported NORMAL
  - TCP pose (idx 55..60) matched forward kinematics of q_actual to 4 mm

This module never sends anything to the robot.
"""

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

REALTIME_PORT = 30003

# float64 indices within the packet body (after the int32 messageSize)
I_TIME = 0
I_Q_TARGET = slice(1, 7)
I_Q_ACTUAL = slice(31, 37)
I_QD_ACTUAL = slice(37, 43)
I_TCP_POSE = slice(55, 61)
I_TCP_SPEED = slice(61, 67)
I_ROBOT_MODE = 94
I_SAFETY_MODE = 101

ROBOT_MODE_RUNNING = 7.0
SAFETY_MODE_NORMAL = 1.0


@dataclass
class Sample:
    t: float                 # seconds since recording started
    q: List[float]           # actual joint angles (rad)
    qd: List[float]          # actual joint velocities (rad/s)
    tcp: List[float]         # actual TCP pose
    tcp_speed: List[float]   # actual TCP speed (linear xyz + angular)
    robot_mode: float
    safety_mode: float

    @property
    def joint_speed_max(self) -> float:
        """Fastest single joint right now (rad/s)."""
        return max(abs(v) for v in self.qd)

    @property
    def tcp_linear_speed(self) -> float:
        """Cartesian translation speed of the TCP (m/s)."""
        return sum(v * v for v in self.tcp_speed[:3]) ** 0.5


@dataclass
class Trace:
    samples: List[Sample] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def duration(self) -> float:
        return self.samples[-1].t - self.samples[0].t if len(self.samples) > 1 else 0.0

    def peak_joint_speed(self) -> float:
        return max((s.joint_speed_max for s in self.samples), default=0.0)

    def peak_tcp_speed(self) -> float:
        return max((s.tcp_linear_speed for s in self.samples), default=0.0)

    def faulted(self) -> bool:
        return any(s.safety_mode != SAFETY_MODE_NORMAL for s in self.samples)

    def stalls(self, threshold: float = 0.02, min_duration: float = 0.06):
        """Find intervals where the arm was effectively stopped mid-motion.

        A "stall" is what a brake-lock or a skipped blend looks like in the
        data: every joint at or below `threshold` rad/s for at least
        `min_duration` seconds, while motion is still ongoing (i.e. the arm
        moves again afterwards). Leading and trailing stillness is ignored so
        that idling before/after the run is not reported.

        Returns a list of (start_t, end_t, duration) tuples.
        """
        moving = [s.joint_speed_max > threshold for s in self.samples]
        if not any(moving):
            return []
        first, last = moving.index(True), len(moving) - 1 - moving[::-1].index(True)

        out = []
        i = first
        while i <= last:
            if moving[i]:
                i += 1
                continue
            j = i
            while j <= last and not moving[j]:
                j += 1
            dur = self.samples[min(j, last)].t - self.samples[i].t
            if dur >= min_duration:
                out.append((self.samples[i].t, self.samples[min(j, last)].t, dur))
            i = j
        return out

    def summary(self) -> str:
        lines = [
            f"samples            : {len(self)} over {self.duration:.2f} s "
            f"({len(self) / self.duration:.0f} Hz)" if self.duration else f"samples: {len(self)}",
            f"peak joint speed   : {self.peak_joint_speed():.3f} rad/s "
            f"({self.peak_joint_speed() * 57.29578:.1f} deg/s)",
            f"peak TCP speed     : {self.peak_tcp_speed():.3f} m/s",
            f"safety stayed NORMAL: {'no - FAULTED' if self.faulted() else 'yes'}",
        ]
        st = self.stalls()
        if st:
            total = sum(d for _, _, d in st)
            lines.append(f"mid-motion stalls  : {len(st)} totalling {total:.2f} s")
            for a, b, d in st[:10]:
                lines.append(f"    stall {d * 1000:6.0f} ms at t={a:.2f}s")
        else:
            lines.append("mid-motion stalls  : none (continuous motion)")
        return "\n".join(lines)


class Recorder:
    """Background recorder for the realtime stream."""

    def __init__(self, host: str, port: int = REALTIME_PORT):
        self.host = host
        self.port = port
        self.trace = Trace()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None

    def _run(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5)
        except OSError as exc:
            self.error = f"connect failed: {exc}"
            return
        t0 = time.time()
        try:
            while not self._stop.is_set():
                head = sock.recv(4)
                if len(head) < 4:
                    break
                n = struct.unpack("!i", head)[0]
                body = b""
                while len(body) < n - 4:
                    chunk = sock.recv(n - 4 - len(body))
                    if not chunk:
                        break
                    body += chunk
                count = len(body) // 8
                if count <= I_SAFETY_MODE:
                    continue
                v = struct.unpack("!%dd" % count, body[: count * 8])
                self.trace.samples.append(Sample(
                    t=time.time() - t0,
                    q=list(v[I_Q_ACTUAL]),
                    qd=list(v[I_QD_ACTUAL]),
                    tcp=list(v[I_TCP_POSE]),
                    tcp_speed=list(v[I_TCP_SPEED]),
                    robot_mode=v[I_ROBOT_MODE],
                    safety_mode=v[I_SAFETY_MODE],
                ))
        except OSError as exc:
            self.error = f"stream error: {exc}"
        finally:
            sock.close()

    def __enter__(self) -> "Recorder":
        self._thread = threading.Thread(target=self._run, daemon=True, name="rt-recorder")
        self._thread.start()
        time.sleep(0.3)  # let the stream establish before motion starts
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)


def read_once(host: str) -> Optional[Sample]:
    """Single read of current state. Used for pre-flight checks."""
    rec = Recorder(host)
    with rec:
        deadline = time.time() + 3.0
        while time.time() < deadline and not rec.trace.samples:
            time.sleep(0.05)
    return rec.trace.samples[-1] if rec.trace.samples else None
