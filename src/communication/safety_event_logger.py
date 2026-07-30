"""
Safety event logger for the UR10 i3UR10 app.

Records protective-stop and emergency-stop events -- with the joint
configuration, TCP pose, robot mode, and any controller message text seen just
before the stop -- to logs/safety_events.log.

Fed by WebSocketReceiver. Every public method is defensive: a logging failure
must never disrupt robot communication, so each one swallows its own
exceptions. Nothing here ever raises into the caller.

Author: jsecco (R)
"""

import logging
import math
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

# UR robot mode codes -> names (primary interface "Robot Mode Data").
ROBOT_MODE_NAMES = {
    -1: "NO_CONTROLLER", 0: "DISCONNECTED", 1: "CONFIRM_SAFETY", 2: "BOOTING",
    3: "POWER_OFF", 4: "POWER_ON", 5: "IDLE", 6: "BACKDRIVE", 7: "RUNNING",
    8: "UPDATING_FIRMWARE",
}


class SafetyEventLogger:
    """
    Appends protective-stop / emergency-stop events to a plain-text log.

    Usage (from WebSocketReceiver):
      - note_robot_message(text)  whenever a controller text message arrives
      - on_state(protective, emergency, robot_mode, joints, tcp)  every state update

    on_state() writes a detailed block only on a *transition into* a stop, and
    a one-line note when a stop clears -- so the log stays meaningful, not noisy.
    """

    def __init__(self, log_path: str = "logs/safety_events.log",
                 recent_message_capacity: int = 12):
        self.log_path = Path(log_path)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._lock = threading.Lock()
        # Ring buffer of the most recent controller text messages.
        self._recent_messages: deque = deque(maxlen=recent_message_capacity)
        self._prev_protective = False
        self._prev_emergency = False
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.debug("safety log dir create failed: %s", exc)

    # --------------------------------------------------------------------- #

    def note_robot_message(self, text: str, source: Optional[str] = None) -> None:
        """Buffer a human-readable controller message (decoded from a type-20
        packet). Kept until the next stop event, then written with it."""
        try:
            text = (text or "").strip()
            if not text:
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            prefix = ("(%s) " % source) if source else ""
            self._recent_messages.append("[%s] %s%s" % (stamp, prefix, text))
        except Exception as exc:
            self.logger.debug("note_robot_message failed: %s", exc)

    def on_state(self, protective: bool, emergency: bool,
                 robot_mode: Optional[int] = None,
                 joints: Optional[Sequence[float]] = None,
                 tcp: Optional[Sequence[float]] = None) -> None:
        """Call on every robot-state update. Writes a block on a transition
        into a stop state, and a short line when a stop clears."""
        try:
            protective = bool(protective)
            emergency = bool(emergency)
            if emergency and not self._prev_emergency:
                self._write_event("EMERGENCY STOP", robot_mode, joints, tcp)
            elif protective and not self._prev_protective:
                self._write_event("PROTECTIVE STOP", robot_mode, joints, tcp)
            elif self._prev_emergency and not emergency:
                self._write_line("emergency stop CLEARED")
            elif self._prev_protective and not protective:
                self._write_line("protective stop CLEARED")
            self._prev_protective = protective
            self._prev_emergency = emergency
        except Exception as exc:
            self.logger.debug("on_state failed: %s", exc)

    # --------------------------------------------------------------------- #

    def _write_event(self, title: str, robot_mode: Optional[int],
                     joints: Optional[Sequence[float]],
                     tcp: Optional[Sequence[float]]) -> None:
        lines: List[str] = ["=" * 68]
        lines.append("%s  %s" % (title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        lines.append("  robot_mode : %s" % ROBOT_MODE_NAMES.get(robot_mode, str(robot_mode)))
        if joints and len(joints) == 6:
            lines.append("  joints rad : [%s]" % ", ".join("%.4f" % q for q in joints))
            lines.append("  joints deg : [%s]" % ", ".join("%.1f" % math.degrees(q) for q in joints))
        else:
            lines.append("  joints     : (not available)")
        if tcp and len(tcp) >= 3:
            lines.append("  tcp xyz m  : [%.4f, %.4f, %.4f]" % (tcp[0], tcp[1], tcp[2]))
        if self._recent_messages:
            lines.append("  controller messages leading up to the stop:")
            for msg in list(self._recent_messages):
                lines.append("    %s" % msg)
        else:
            lines.append("  controller messages: (none captured)")
        lines.append("=" * 68)
        self._append("\n".join(lines) + "\n")

    def _write_line(self, text: str) -> None:
        self._append("---- %s  %s\n"
                      % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))

    def _append(self, text: str) -> None:
        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(text)
            except Exception as exc:
                self.logger.debug("safety log append failed: %s", exc)


# ------------------------------- self-test ------------------------------- #

if __name__ == "__main__":
    import os
    import tempfile

    path = os.path.join(tempfile.gettempdir(), "safety_events_selftest.log")
    if os.path.exists(path):
        os.remove(path)

    sl = SafetyEventLogger(path)
    sl.on_state(protective=False, emergency=False)                  # no-op (no transition)
    sl.note_robot_message("PROGRAM jsecco_demo_loop started")
    sl.note_robot_message("Protective Stop: Position deviates from path",
                          source="controller")
    sl.on_state(protective=True, emergency=False, robot_mode=7,
                joints=[-0.8528, -0.7817, 3.2823, -3.8002, -0.9644, 0.2586],
                tcp=[-0.3387, 0.1047, 0.0904])                      # -> writes a block
    sl.on_state(protective=True, emergency=False)                   # no-op (still stopped)
    sl.on_state(protective=False, emergency=False)                  # -> writes "CLEARED"

    print("--- %s ---" % path)
    print(open(path).read())
    assert "PROTECTIVE STOP" in open(path).read()
    assert "Position deviates from path" in open(path).read()
    assert "protective stop CLEARED" in open(path).read()
    print("SELF-TEST PASSED")
    os.remove(path)
