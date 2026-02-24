"""
Centrifuge Control System - Serial Bridge
Handles all communication between the Python UI and the Arduino.

Usage:
    controller = SerialController(port="COM3", baud=115200)  # Windows
    controller = SerialController(port="/dev/ttyUSB0", baud=115200)  # Linux
    controller = SerialController(port="/dev/tty.usbmodem14101", baud=115200)  # macOS

    controller.connect()
    controller.start(rpm=1000, duration_sec=30)
    status = controller.get_status()
    controller.stop()
    controller.disconnect()
"""

import serial
import serial.tools.list_ports
import threading
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("SerialController")


# ==================== DATA TYPES ====================
class SystemState(Enum):
    IDLE = "IDLE"
    RAMPING_UP = "RAMPING_UP"
    RUNNING = "RUNNING"
    RAMPING_DOWN = "RAMPING_DOWN"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class ArduinoStatus:
    """Represents the latest status received from the Arduino."""
    state: SystemState = SystemState.DISCONNECTED
    current_rpm: int = 0
    target_rpm: int = 0
    pwm: int = 0
    lid_closed: bool = False
    level: bool = False
    running: bool = False
    remaining_ms: int = 0
    error_reason: str = ""
    last_updated: float = field(default_factory=time.time)

    @property
    def remaining_sec(self) -> int:
        return self.remaining_ms // 1000

    @property
    def is_connected(self) -> bool:
        return self.state != SystemState.DISCONNECTED


# ==================== SERIAL CONTROLLER ====================
class SerialController:
    """
    Manages serial communication with the Arduino centrifuge controller.

    Runs a background reader thread that continuously parses incoming data
    and updates a shared status object. The UI reads from this object
    without blocking.

    Callback hooks:
        on_status_update(status: ArduinoStatus)  - called on every status packet
        on_state_change(old, new: SystemState)   - called when state changes
        on_error(reason: str)                    - called on ERROR state or comms failure
        on_complete()                            - called when a run finishes (IDLE after RUNNING)
    """

    WATCHDOG_INTERVAL = 2.0   # seconds between PINGs
    RECONNECT_DELAY   = 3.0   # seconds before attempting reconnect
    READLINE_TIMEOUT  = 1.0   # serial readline timeout

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = 115200,
        auto_detect: bool = True,
        on_status_update: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ):
        self.port = port
        self.baud = baud
        self.auto_detect = auto_detect

        # Callbacks
        self.on_status_update = on_status_update
        self.on_state_change = on_state_change
        self.on_error = on_error
        self.on_complete = on_complete

        # Internal state
        self._serial: Optional[serial.Serial] = None
        self._status = ArduinoStatus()
        self._status_lock = threading.Lock()
        self._write_lock = threading.Lock()

        self._reader_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._previous_state = SystemState.DISCONNECTED

    # ==================== CONNECTION ====================
    def connect(self) -> bool:
        """
        Open serial connection to the Arduino.
        If port is None and auto_detect is True, attempts to find the port automatically.
        Returns True if connection was successful.
        """
        if self.port is None and self.auto_detect:
            self.port = self._auto_detect_port()
            if self.port is None:
                log.error("Could not auto-detect Arduino port.")
                return False

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=self.READLINE_TIMEOUT
            )
            # Arduino resets on serial connect - wait for it to boot
            time.sleep(2.0)
            self._serial.reset_input_buffer()

            self._stop_event.clear()
            self._start_threads()

            log.info(f"Connected to Arduino on {self.port} at {self.baud} baud.")
            return True

        except serial.SerialException as e:
            log.error(f"Failed to connect to {self.port}: {e}")
            return False

    def disconnect(self):
        """Gracefully stop threads and close the serial port."""
        log.info("Disconnecting...")
        self._stop_event.set()

        for thread in (self._reader_thread, self._watchdog_thread):
            if thread and thread.is_alive():
                thread.join(timeout=3.0)

        if self._serial and self._serial.is_open:
            self._serial.close()

        with self._status_lock:
            self._status.state = SystemState.DISCONNECTED

        log.info("Disconnected.")

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @staticmethod
    def list_ports() -> list[str]:
        """Return a list of available serial ports (useful for port picker UI)."""
        return [p.device for p in serial.tools.list_ports.comports()]

    # ==================== COMMANDS ====================
    def start(self, rpm: int, duration_sec: int) -> bool:
        """
        Send START command to Arduino.
        Arduino expects: START:<RPM>:<DURATION_MS>
        Returns True if command was sent successfully.
        """
        if not self.is_connected():
            log.error("Cannot start: not connected.")
            return False

        duration_ms = duration_sec * 1000
        command = f"START:{rpm}:{duration_ms}\n"
        log.info(f"Sending: {command.strip()}")
        return self._send(command)

    def stop(self) -> bool:
        """Send STOP command (initiates ramp-down)."""
        log.info("Sending: STOP")
        return self._send("STOP\n")

    def emergency_stop(self) -> bool:
        """Send EMERGENCY_STOP command (immediate shutdown, enters ERROR state)."""
        log.warning("Sending: EMERGENCY_STOP")
        return self._send("EMERGENCY_STOP\n")

    def clear_error(self) -> bool:
        """
        Send CLEAR_ERROR command.
        Only works if the underlying safety condition has been resolved.
        """
        log.info("Sending: CLEAR_ERROR")
        return self._send("CLEAR_ERROR\n")

    def request_status(self) -> bool:
        """Ask the Arduino for an immediate status packet."""
        return self._send("STATUS\n")

    def ping(self) -> bool:
        """Send PING to reset the Arduino watchdog timer."""
        return self._send("PING\n")

    # ==================== STATUS ACCESS ====================
    def get_status(self) -> ArduinoStatus:
        """Return a snapshot of the latest Arduino status (thread-safe)."""
        with self._status_lock:
            # Return a shallow copy so the UI has a stable snapshot
            s = self._status
            return ArduinoStatus(
                state=s.state,
                current_rpm=s.current_rpm,
                target_rpm=s.target_rpm,
                pwm=s.pwm,
                lid_closed=s.lid_closed,
                level=s.level,
                running=s.running,
                remaining_ms=s.remaining_ms,
                error_reason=s.error_reason,
                last_updated=s.last_updated,
            )

    # ==================== PRIVATE: THREADS ====================
    def _start_threads(self):
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="arduino-reader",
            daemon=True
        )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="arduino-watchdog",
            daemon=True
        )
        self._reader_thread.start()
        self._watchdog_thread.start()

    def _reader_loop(self):
        """Background thread: continuously read and parse lines from Arduino."""
        log.debug("Reader thread started.")
        while not self._stop_event.is_set():
            try:
                raw = self._serial.readline()
                if not raw:
                    continue  # timeout, loop again

                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._parse_line(line)

            except serial.SerialException as e:
                log.error(f"Serial read error: {e}")
                self._handle_disconnect()
                break
            except Exception as e:
                log.warning(f"Unexpected error in reader: {e}")

        log.debug("Reader thread stopped.")

    def _watchdog_loop(self):
        """
        Background thread: send periodic PINGs to reset the Arduino watchdog.
        The Arduino disconnects (enters error state) if it doesn't hear from us
        within WATCHDOG_TIMEOUT (5s). We ping every 2s to be safe.
        """
        log.debug("Watchdog thread started.")
        while not self._stop_event.is_set():
            time.sleep(self.WATCHDOG_INTERVAL)
            if self.is_connected() and not self._stop_event.is_set():
                self.ping()
        log.debug("Watchdog thread stopped.")

    # ==================== PRIVATE: PARSING ====================
    def _parse_line(self, line: str):
        """Dispatch a line from the Arduino to the appropriate parser."""
        log.debug(f"Arduino → {line}")

        if line.startswith("{"):
            self._parse_status_json(line)

        elif line.startswith("ERROR:"):
            reason = line[6:]
            log.error(f"Arduino error: {reason}")
            with self._status_lock:
                self._status.state = SystemState.ERROR
                self._status.error_reason = reason
            self._fire_callback(self.on_error, reason)
            self._check_state_change()

        elif line.startswith("STATE:"):
            state_str = line[6:]
            try:
                new_state = SystemState(state_str)
                with self._status_lock:
                    self._status.state = new_state
                self._check_state_change()
            except ValueError:
                log.warning(f"Unknown state: {state_str}")

        elif line.startswith("STATUS:COMPLETE"):
            log.info("Run complete.")
            self._fire_callback(self.on_complete)

        elif line.startswith("WARNING:"):
            log.warning(f"Arduino warning: {line[8:]}")

        elif line == "PONG":
            log.debug("Watchdog PONG received.")

        elif line.startswith("ACK:"):
            log.info(f"Arduino ACK: {line[4:]}")

        elif line.startswith("Centrifuge Control") or line == "System Ready":
            log.info(f"Arduino boot message: {line}")

        else:
            log.debug(f"Unhandled Arduino line: {line}")

    def _parse_status_json(self, line: str):
        """Parse the JSON status packet sent by the Arduino every 200ms."""
        try:
            data = json.loads(line)

            with self._status_lock:
                try:
                    self._status.state = SystemState(data.get("state", "IDLE"))
                except ValueError:
                    self._status.state = SystemState.IDLE

                self._status.current_rpm  = int(data.get("currentRPM", 0))
                self._status.target_rpm   = int(data.get("targetRPM", 0))
                self._status.pwm          = int(data.get("pwm", 0))
                self._status.lid_closed   = bool(data.get("lidClosed", False))
                self._status.level        = bool(data.get("level", False))
                self._status.running      = bool(data.get("running", False))
                self._status.remaining_ms = int(data.get("remainingMs", 0))
                self._status.last_updated = time.time()

            self._fire_callback(self.on_status_update, self.get_status())
            self._check_state_change()

        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Failed to parse status JSON '{line}': {e}")

    def _check_state_change(self):
        """Fire on_state_change callback if state has changed since last check."""
        with self._status_lock:
            current = self._status.state

        if current != self._previous_state:
            log.info(f"State: {self._previous_state.value} → {current.value}")
            self._fire_callback(self.on_state_change, self._previous_state, current)
            self._previous_state = current

    # ==================== PRIVATE: HELPERS ====================
    def _send(self, command: str) -> bool:
        """Write a command string to the serial port (thread-safe)."""
        if not self.is_connected():
            log.warning(f"Cannot send '{command.strip()}': not connected.")
            return False
        try:
            with self._write_lock:
                self._serial.write(command.encode("utf-8"))
            return True
        except serial.SerialException as e:
            log.error(f"Write failed: {e}")
            self._handle_disconnect()
            return False

    def _handle_disconnect(self):
        """Called when the serial connection is unexpectedly lost."""
        log.error("Serial connection lost.")
        with self._status_lock:
            self._status.state = SystemState.DISCONNECTED
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
        self._fire_callback(self.on_error, "SERIAL_DISCONNECTED")

    def _fire_callback(self, cb: Optional[Callable], *args):
        """Safely invoke a callback, ignoring exceptions so threads don't die."""
        if cb is None:
            return
        try:
            cb(*args)
        except Exception as e:
            log.warning(f"Callback {cb.__name__} raised: {e}")

    @staticmethod
    def _auto_detect_port() -> Optional[str]:
        """
        Try to find the Arduino port automatically by checking USB descriptions.
        Works on Windows (COM*), Linux (/dev/ttyUSB*, /dev/ttyACM*), and macOS.
        """
        keywords = ["arduino", "usb serial", "ch340", "cp210", "ftdi", "usbmodem", "usbserial"]
        ports = serial.tools.list_ports.comports()

        for port in ports:
            description = (port.description or "").lower()
            manufacturer = (port.manufacturer or "").lower()
            hwid = (port.hwid or "").lower()

            if any(kw in description or kw in manufacturer or kw in hwid for kw in keywords):
                log.info(f"Auto-detected Arduino on {port.device} ({port.description})")
                return port.device

        # Fallback: return first available port
        if ports:
            log.warning(f"No Arduino-specific port found. Falling back to {ports[0].device}")
            return ports[0].device

        return None


# ==================== UI INTEGRATION HELPER ====================
class CentrifugeController:
    """
    Thin wrapper that integrates SerialController with the tkinter UI.

    The UI creates one of these, passes in its root window and the UI
    state variables, and calls connect(). The controller then drives
    the UI's variables from the background thread via root.after().

    Example usage inside CentrifugeUI.__init__:

        self.controller = CentrifugeController(self.root, ui=self)
        self.controller.connect()

    Then replace the TODO stubs:

        # In start_centrifuge():
        self.controller.start(self.target_rpm.get(), self.target_duration_sec.get())

        # In stop_centrifuge():
        self.controller.stop()
    """

    def __init__(self, root, ui):
        self.root = root
        self.ui = ui

        self.serial = SerialController(
            auto_detect=True,
            on_status_update=self._on_status,
            on_state_change=self._on_state_change,
            on_error=self._on_error,
            on_complete=self._on_complete,
        )

    def connect(self, port: Optional[str] = None) -> bool:
        if port:
            self.serial.port = port
        return self.serial.connect()

    def disconnect(self):
        self.serial.disconnect()

    def start(self, rpm: int, duration_sec: int) -> bool:
        return self.serial.start(rpm, duration_sec)

    def stop(self) -> bool:
        return self.serial.stop()

    def emergency_stop(self) -> bool:
        return self.serial.emergency_stop()

    def clear_error(self) -> bool:
        return self.serial.clear_error()

    # ---- Callbacks (called from background thread) ----
    # We use root.after(0, ...) to safely schedule UI updates on the main thread.

    def _on_status(self, status: ArduinoStatus):
        """Update UI variables from latest Arduino status packet."""
        def update():
            self.ui.current_rpm.set(status.current_rpm)
            self.ui.remaining_time_sec.set(status.remaining_sec)

            mins = status.remaining_sec // 60
            secs = status.remaining_sec % 60
            self.ui.time_label.config(text=f"{mins:02d}:{secs:02d}")

            # Update safety indicator colors
            lid_color = '#27ae60' if status.lid_closed else '#e74c3c'
            lvl_color = '#27ae60' if status.level else '#e74c3c'
            # (Wire these to your actual label widgets if you expose them)

        self.root.after(0, update)

    def _on_state_change(self, old_state: SystemState, new_state: SystemState):
        """Sync UI state label and button states with Arduino state machine."""
        state_colors = {
            SystemState.IDLE:         '#27ae60',
            SystemState.RAMPING_UP:   '#f39c12',
            SystemState.RUNNING:      '#27ae60',
            SystemState.RAMPING_DOWN: '#e67e22',
            SystemState.ERROR:        '#e74c3c',
            SystemState.DISCONNECTED: '#95a5a6',
        }

        def update():
            self.ui.state.set(new_state.value)
            color = state_colors.get(new_state, '#555')
            self.ui.state_label.config(fg=color)

            is_active = new_state in (SystemState.RAMPING_UP, SystemState.RUNNING, SystemState.RAMPING_DOWN)
            self.ui.start_btn.config(state='disabled' if is_active else 'normal')
            self.ui.stop_btn.config(state='normal' if is_active else 'disabled')
            self.ui.is_running = is_active

        self.root.after(0, update)

    def _on_error(self, reason: str):
        """Show error dialog on the main thread."""
        def show():
            from tkinter import messagebox
            messagebox.showerror("Arduino Error", f"Error: {reason}\n\nResolve the issue then click Clear Error.")

        self.root.after(0, show)

    def _on_complete(self):
        """Show completion dialog."""
        def show():
            from tkinter import messagebox
            messagebox.showinfo("Complete", "Centrifugation complete. Safe to remove samples.")

        self.root.after(0, show)


# ==================== STANDALONE TEST ====================
if __name__ == "__main__":
    """
    Run this file directly to test the serial connection without the UI.
    It will connect, request a status, and print output for 10 seconds.
    """
    import sys

    print("Available ports:", SerialController.list_ports())

    ctrl = SerialController(
        on_status_update=lambda s: print(
            f"  RPM: {s.current_rpm}/{s.target_rpm}  "
            f"State: {s.state.value}  "
            f"Remaining: {s.remaining_sec}s  "
            f"Lid: {'✓' if s.lid_closed else '✗'}  "
            f"Level: {'✓' if s.level else '✗'}"
        ),
        on_state_change=lambda old, new: print(f"\n>>> State changed: {old.value} → {new.value}"),
        on_error=lambda r: print(f"\n!!! ERROR: {r}"),
        on_complete=lambda: print("\n>>> Run complete!"),
    )

    if not ctrl.connect():
        print("Could not connect. Check your port and try again.")
        sys.exit(1)

    print("Connected. Requesting status for 10 seconds...")
    ctrl.request_status()

    try:
        time.sleep(10)
    except KeyboardInterrupt:
        pass

    ctrl.disconnect()
    print("Done.")