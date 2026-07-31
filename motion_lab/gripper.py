"""
DYNAMIXEL XL330-M288-T gripper driver.

Talks to the servo over a TTL half-duplex bus via a USB adapter (U2D2 or
equivalent) on the control PC. Independent of the robot: the arm and the
gripper are separate actuators that the app coordinates.

Why current-based position control (Operating Mode 5)
-----------------------------------------------------
Grip force on this servo is a CURRENT limit, not a position. In mode 5 the
servo drives toward Goal Position but never exceeds Goal Current, so closing
on an object simply stalls gently at the commanded force instead of crushing
it or faulting. Closing "to a position" would either miss the object or jam.

Thermal reality (matters for a demo that grips and holds)
---------------------------------------------------------
Stall torque is 0.52 N.m at 5 V but ROBOTIS' estimated *continuous* rating is
about 0.10 N.m -- roughly 20% of stall. Holding near stall heats the servo,
and at Temperature Limit (default 70 C) the Shutdown register forces Torque
Enable off, which DROPS WHATEVER IS HELD. So: hold at a modest current, and
poll temperature during sustained grips. `check_health()` exists for that.

Electrical, non-negotiable
--------------------------
Operating range is 3.7-6.0 V, recommended 5.0 V. The UR tool connector
supplies 12 V or 24 V. Feeding either to this servo destroys it -- there is
only a software voltage-monitor register, not hardware protection. A 5 V
regulator between the two is mandatory.

Control table values are for XL330-M288-T, Protocol 2.0.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

# --- Control table (XL330-M288-T, Protocol 2.0) ---
ADDR_OPERATING_MODE = 11     # EEPROM, 1 byte  (write with torque disabled)
ADDR_TEMP_LIMIT = 31         # EEPROM, 1 byte, degrees C
ADDR_CURRENT_LIMIT = 38      # EEPROM, 2 bytes, ~1 mA/unit, max 1750
ADDR_TORQUE_ENABLE = 64      # RAM, 1 byte
ADDR_HARDWARE_ERROR = 70     # RAM, 1 byte, bitmask
ADDR_GOAL_CURRENT = 102      # RAM, 2 bytes, ~1 mA/unit
ADDR_GOAL_POSITION = 116     # RAM, 4 bytes, pulses
ADDR_MOVING = 122            # RAM, 1 byte
ADDR_PRESENT_CURRENT = 126   # RAM, 2 bytes
ADDR_PRESENT_POSITION = 132  # RAM, 4 bytes
ADDR_PRESENT_VOLTAGE = 144   # RAM, 2 bytes, 0.1 V/unit
ADDR_PRESENT_TEMP = 146      # RAM, 1 byte, degrees C

MODE_CURRENT_BASED_POSITION = 5

POSITION_MIN = 0             # 0..4095 spans 360 degrees
POSITION_MAX = 4095
PULSES_PER_DEGREE = 4096 / 360.0

STALL_CURRENT_MA = 1470      # at 5 V, per ROBOTIS
DEFAULT_GRIP_CURRENT_MA = 150   # well under stall: enough to hold, cool enough to hold *for a while*
MAX_ALLOWED_CURRENT_MA = 800    # driver-level cap; nothing here needs stall force

# Hardware Error Status bits
HW_ERROR_BITS = {
    0: "input voltage out of range",
    2: "overheating",
    3: "motor encoder error",
    4: "electrical shock / insufficient power",
    5: "overload",
}


@dataclass
class GripperState:
    position: int
    current_ma: int
    temperature_c: int
    voltage_v: float
    moving: bool
    hardware_error: int

    @property
    def error_text(self) -> str:
        if not self.hardware_error:
            return ""
        return ", ".join(txt for bit, txt in HW_ERROR_BITS.items()
                         if self.hardware_error & (1 << bit))


class GripperError(RuntimeError):
    pass


class Gripper:
    """XL330-M288-T in current-based position control.

    `open_position` and `closed_position` are in pulses (0-4095) and must be
    calibrated for the physical linkage -- see calibrate() below. Closing
    force is set by `grip_current_ma`, not by how far the servo is told to go.
    """

    def __init__(self,
                 port: str = "/dev/ttyUSB0",
                 baudrate: int = 57600,
                 dxl_id: int = 1,
                 open_position: int = 2048,
                 closed_position: int = 1024,
                 grip_current_ma: int = DEFAULT_GRIP_CURRENT_MA,
                 temperature_limit_c: int = 60):
        if not (0 < grip_current_ma <= MAX_ALLOWED_CURRENT_MA):
            raise ValueError(
                f"grip_current_ma must be in (0, {MAX_ALLOWED_CURRENT_MA}]; "
                f"stall is {STALL_CURRENT_MA} mA and sustained high current overheats")
        for name, p in (("open_position", open_position),
                        ("closed_position", closed_position)):
            if not (POSITION_MIN <= p <= POSITION_MAX):
                raise ValueError(f"{name} must be within {POSITION_MIN}..{POSITION_MAX}")

        self.port_name = port
        self.baudrate = baudrate
        self.id = dxl_id
        self.open_position = open_position
        self.closed_position = closed_position
        self.grip_current_ma = grip_current_ma
        self.temperature_limit_c = temperature_limit_c

        self._port = None
        self._packet = None
        self._log = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------ plumbing

    def _check(self, result: int, error: int, what: str) -> None:
        if result != 0:
            raise GripperError(f"{what}: comm failed ({self._packet.getTxRxResult(result)})")
        if error != 0:
            raise GripperError(f"{what}: servo error ({self._packet.getRxPacketError(error)})")

    def _write(self, addr: int, value: int, size: int, what: str) -> None:
        fn = {1: self._packet.write1ByteTxRx,
              2: self._packet.write2ByteTxRx,
              4: self._packet.write4ByteTxRx}[size]
        self._check(*fn(self._port, self.id, addr, value), what)

    def _read(self, addr: int, size: int, what: str) -> int:
        fn = {1: self._packet.read1ByteTxRx,
              2: self._packet.read2ByteTxRx,
              4: self._packet.read4ByteTxRx}[size]
        value, result, error = fn(self._port, self.id, addr)
        self._check(result, error, what)
        return value

    # ------------------------------------------------------------ lifecycle

    @staticmethod
    def _port_hint() -> str:
        import glob
        found = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        if not found:
            return ("No USB serial adapter is present. Plug in the U2D2 and check "
                    "`dmesg | tail`.")
        return (f"Adapters present: {', '.join(found)}. If permission is denied, add this "
                f"user to the 'dialout' group (sudo usermod -aG dialout $USER, then log out).")

    def connect(self) -> None:
        try:
            from dynamixel_sdk import PacketHandler, PortHandler
        except ImportError as exc:
            raise GripperError(
                "dynamixel-sdk not installed: venv/bin/pip install dynamixel-sdk") from exc

        self._port = PortHandler(self.port_name)
        self._packet = PacketHandler(2.0)

        # openPort() returns False on some failures but propagates pyserial's
        # SerialException on others (missing device node, permission denied),
        # so both paths have to be turned into one clear message.
        try:
            opened = self._port.openPort()
        except Exception as exc:
            self._port = None
            raise GripperError(f"cannot open {self.port_name}: {exc}. {self._port_hint()}") from exc
        if not opened:
            self._port = None
            raise GripperError(f"cannot open {self.port_name}. {self._port_hint()}")

        try:
            ok = self._port.setBaudRate(self.baudrate)
        except Exception as exc:
            self.disconnect()
            raise GripperError(f"cannot set baud {self.baudrate}: {exc}") from exc
        if not ok:
            self.disconnect()
            raise GripperError(f"cannot set baud {self.baudrate} on {self.port_name}")

        # Fail loudly on a supply that would damage or brown out the servo,
        # before enabling torque.
        volts = self._read(ADDR_PRESENT_VOLTAGE, 2, "read voltage") / 10.0
        if not (3.7 <= volts <= 6.0):
            self.disconnect()
            raise GripperError(
                f"servo reports {volts:.1f} V, outside its 3.7-6.0 V range. "
                f"Check the 5 V regulator before continuing.")
        self._log.info("XL330 connected on %s at %.1f V", self.port_name, volts)

        # Operating mode lives in EEPROM and only accepts writes with torque off.
        self._write(ADDR_TORQUE_ENABLE, 0, 1, "disable torque")
        self._write(ADDR_OPERATING_MODE, MODE_CURRENT_BASED_POSITION, 1, "set mode 5")
        self._write(ADDR_TEMP_LIMIT, self.temperature_limit_c, 1, "set temp limit")
        self._write(ADDR_CURRENT_LIMIT, MAX_ALLOWED_CURRENT_MA, 2, "set current limit")
        self._write(ADDR_TORQUE_ENABLE, 1, 1, "enable torque")

    def disconnect(self) -> None:
        if self._port is None:
            return
        try:
            self._write(ADDR_TORQUE_ENABLE, 0, 1, "disable torque")
        except Exception:
            pass
        try:
            self._port.closePort()
        finally:
            self._port = None
            self._packet = None

    def __enter__(self) -> "Gripper":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    # ------------------------------------------------------------ commands

    def state(self) -> GripperState:
        return GripperState(
            position=self._read(ADDR_PRESENT_POSITION, 4, "read position"),
            current_ma=self._to_signed(self._read(ADDR_PRESENT_CURRENT, 2, "read current")),
            temperature_c=self._read(ADDR_PRESENT_TEMP, 1, "read temperature"),
            voltage_v=self._read(ADDR_PRESENT_VOLTAGE, 2, "read voltage") / 10.0,
            moving=bool(self._read(ADDR_MOVING, 1, "read moving")),
            hardware_error=self._read(ADDR_HARDWARE_ERROR, 1, "read hw error"),
        )

    @staticmethod
    def _to_signed(raw: int) -> int:
        return raw - 65536 if raw > 32767 else raw

    def check_health(self) -> None:
        """Raise if the servo is faulted or approaching thermal shutdown.

        Worth calling during any sustained grip: at Temperature Limit the
        servo cuts torque and drops the object without warning.
        """
        s = self.state()
        if s.hardware_error:
            raise GripperError(f"servo hardware error: {s.error_text}")
        if s.temperature_c >= self.temperature_limit_c - 5:
            raise GripperError(
                f"servo at {s.temperature_c} C, near its {self.temperature_limit_c} C "
                f"limit; it will cut torque and release the load")

    def _goto(self, position: int, current_ma: int) -> None:
        self._write(ADDR_GOAL_CURRENT, current_ma, 2, "set goal current")
        self._write(ADDR_GOAL_POSITION, position, 4, "set goal position")

    def open(self, wait: bool = True, timeout: float = 2.0) -> None:
        self._goto(self.open_position, self.grip_current_ma)
        if wait:
            self._settle(timeout)

    def close(self, wait: bool = True, timeout: float = 2.0) -> bool:
        """Close onto an object. Returns True if something was gripped.

        In current-based position mode the servo stalls at `grip_current_ma`
        when it meets resistance, so "did we grab something?" is answered by
        where it stopped, not by whether it reached the goal.
        """
        self._goto(self.closed_position, self.grip_current_ma)
        if not wait:
            return False
        self._settle(timeout)
        final = self.state().position
        span = abs(self.open_position - self.closed_position)
        stopped_short = abs(final - self.closed_position) > span * 0.05
        return stopped_short

    def _settle(self, timeout: float) -> None:
        """Wait until motion stops, then confirm the servo is not faulted."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.state()
            if s.hardware_error:
                raise GripperError(f"servo hardware error: {s.error_text}")
            if not s.moving:
                return
            time.sleep(0.02)
        self._log.warning("gripper did not settle within %.1fs", timeout)

    def release(self) -> None:
        """Cut torque. The fingers go limp -- use when parking the robot."""
        self._write(ADDR_TORQUE_ENABLE, 0, 1, "disable torque")

    # ------------------------------------------------------------ calibration

    def calibrate(self) -> Tuple[int, int]:
        """Report the current position so open/closed can be set by hand.

        With torque off you can move the fingers manually; read the position
        at each end and put those numbers in the constructor.
        """
        self.release()
        s = self.state()
        print(f"torque off. position now {s.position} "
              f"({s.position / PULSES_PER_DEGREE:.1f} deg), {s.temperature_c} C")
        return s.position, s.temperature_c
