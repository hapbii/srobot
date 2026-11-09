"""Bounded serial transport. Robot state is owned by the asyncio thread."""
import logging
import threading
import time
import serial
import serial.tools.list_ports
from robot_config import AXES, MAX_SPEED, ACCEL

log = logging.getLogger('SERIAL')

class ArduinoSerialManager:
    BAUD = 115200

    def __init__(self, ports=None, dashboard=None, on_line=None):
        self._ports = ports or {}
        self._dashboard = dashboard
        self._on_line = on_line or (lambda axis, line: None)
        self._serials, self._threads = {}, {}
        self._lock = threading.Lock()
        self._closing = threading.Event()

    @staticmethod
    def _identify(ser, seconds=3):
        end = time.monotonic() + seconds
        next_query = 0
        while time.monotonic() < end:
            if time.monotonic() >= next_query:
                ser.write(b'ID\n')
                next_query = time.monotonic() + 0.5
            line = ser.readline(128).decode('ascii', errors='ignore').strip()
            for axis in AXES:
                if line == f'{axis.upper()} READY V2':
                    return axis
        return None

    def connect_all(self):
        # Explicit ports override discovery only for their own axes.
        candidates = sorted({p.device for p in serial.tools.list_ports.comports()
                             if any(x in p.device for x in ('ttyUSB', 'ttyACM', 'COM'))}
                            | set(self._ports.values()))
        if len(set(self._ports.values())) != len(self._ports):
            raise ValueError('Each axis requires a different serial port')
        for port in candidates:
            if self._closing.is_set():
                break
            ser = None
            try:
                ser = serial.Serial(port, self.BAUD, timeout=0.1, write_timeout=0.5)
                # Opening a Nano normally resets it. Never guess an unidentified axis.
                axis = self._identify(ser)
                if self._closing.is_set():
                    raise InterruptedError('Shutdown during port identification')
                explicit = next((a for a, p in self._ports.items() if p == port), None)
                if axis is None or (explicit and explicit != axis):
                    raise ValueError('Missing/mismatched READY V2; upload the matching firmware')
                if axis in self._serials or (axis in self._ports and not explicit):
                    raise ValueError('Duplicate axis or explicitly assigned elsewhere')
                self._serials[axis] = ser
                if self._dashboard:
                    self._dashboard.set_arduino(axis, True, port)
                self._write(axis, 'STOP')
                self._write(axis, f'SPEED,{MAX_SPEED[axis]}')
                self._write(axis, f'ACCEL,{ACCEL[axis]}')
                thread = threading.Thread(target=self._read, args=(axis, ser), daemon=True,
                                          name=f'scara-serial-{axis}')
                self._threads[axis] = thread
                thread.start()
                ser = None  # owned by manager now
            except Exception as exc:
                log.warning('%s: %s', port, exc)
            finally:
                if ser is not None:
                    ser.close()

    def _read(self, axis, ser):
        buf = bytearray()
        discard = False
        try:
            while not self._closing.is_set() and ser.is_open:
                chunk = ser.read(128)
                for value in chunk:
                    if value == 10:
                        if buf and not discard:
                            self._on_line(axis, buf.decode('ascii', errors='ignore').strip())
                        buf.clear()
                        discard = False
                    elif value != 13 and not discard:
                        if len(buf) >= 160:
                            buf.clear()
                            discard = True
                        else:
                            buf.append(value)
        except (OSError, serial.SerialException):
            pass
        finally:
            ser.close()
            if self._dashboard:
                self._dashboard.set_arduino(axis, False)
            self._on_line(axis, 'DISCONNECTED')

    def _write(self, axis, command):
        ser = self._serials.get(axis)
        if ser is None or not ser.is_open:
            return False
        try:
            with self._lock:
                payload = (command + '\n').encode('ascii')
                if ser.write(payload) != len(payload):
                    raise OSError('Short serial write')
            return True
        except (OSError, serial.SerialException):
            ser.close()
            self._on_line(axis, 'DISCONNECTED')
            return False

    def is_connected(self, axis):
        ser = self._serials.get(axis)
        return bool(ser and ser.is_open)

    def send_goto(self, axis, steps, command_id):
        return self._write(axis, f'GOTO,{int(steps)},{command_id}')

    def send_speed(self, axis, speed):
        return self._write(axis, f'SPEED,{speed}')

    def send_home_search(self, axis, direction, speed):
        return self._write(axis, f'HOME_SEARCH,{direction},{speed}')

    def stop_all(self):
        for axis in AXES:
            self._write(axis, 'STOP')

    def heartbeat(self):
        for axis in AXES:
            self._write(axis, 'PING')

    def close(self):
        if self._closing.is_set():
            return
        self.stop_all()
        self._closing.set()
        for ser in self._serials.values():
            ser.close()
        for thread in self._threads.values():
            if thread is not threading.current_thread():
                thread.join(timeout=1)
        self._threads.clear()
        self._serials.clear()
