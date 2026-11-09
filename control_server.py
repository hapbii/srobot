"""Protocol V2 control. State belongs to asyncio; serial readers use a bounded inbox."""
import asyncio
import json
import logging
import math
import queue
import socket
import time
from robot_config import (AXES, HOME_POSE, GEAR_RATIO, JOINT_LIMITS, MAX_SPEED,
                          MIN_SPEED, SPEED_LIMIT, ENCODER_TTL, HOME_TIMEOUT,
                          PROTOCOL_VERSION, deg_to_steps, steps_to_deg)
from serial_transport import ArduinoSerialManager
from terminal_dashboard import TerminalDashboard

log = logging.getLogger('WS_SERVER')
JOINT_HOME_DEG = HOME_POSE

def initial_motor_steps():
    return dict.fromkeys(AXES, 0)

class ScaraWSServer:
    def __init__(self, motor_mgr=None, enc_mgr=None, arduino_ports=None, transport=None):
        self.motor_mgr, self.enc_mgr = motor_mgr, enc_mgr
        self._clients = set()
        self._owner = None
        self._loop = self._shutdown_event = None
        self._stopping = False
        self._inbox = queue.Queue(maxsize=256)
        self._overflow = False
        self._dash = TerminalDashboard(self._get_local_ip())
        self._last_steps = initial_motor_steps()
        self._last_joint = dict(HOME_POSE)
        self._actual = dict.fromkeys(AXES)
        self._last_enc = {a: self._invalid_encoder() for a in AXES}
        self._enc_prev = dict.fromkeys(AXES)
        self._enc_count = dict.fromkeys(AXES, 0)
        self._enc_zero = dict.fromkeys(AXES)
        self._home_offset = dict.fromkeys(AXES)
        self._homing = dict.fromkeys(AXES, False)
        self._home_deadline = 0
        self._home_pending = set()
        self._current_speed = dict(MAX_SPEED)
        self._command_id = 0
        self._pending = None
        self._dirty = True
        self._last_heartbeat = self._lease_time = 0
        self._last_status = 0
        self._arduino = transport or ArduinoSerialManager(arduino_ports, self._dash, self._enqueue_line)

    @staticmethod
    def _invalid_encoder():
        return {'raw': None, 'deg': None, 'ok': False, 'ts': 0, 'magnet': None}

    @staticmethod
    def _get_local_ip():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('8.8.8.8', 80))
                return sock.getsockname()[0]
        except OSError:
            return '127.0.0.1'

    def _enqueue_line(self, axis, line):
        try:
            self._inbox.put_nowait((axis, line))
        except queue.Full:
            self._overflow = True

    async def _send(self, ws, data):
        try:
            await asyncio.wait_for(ws.send(json.dumps(data, allow_nan=False)), 0.25)
        except (OSError, TimeoutError, RuntimeError):
            if ws is self._owner:
                self._stop_motion('client send timeout')
            self._clients.discard(ws)
            try:
                await asyncio.wait_for(ws.close(), 0.25)
            except Exception:
                pass

    async def _broadcast(self, data):
        if self._clients:
            await asyncio.gather(*(self._send(ws, data) for ws in tuple(self._clients)))

    def _stop_motion(self, reason='stop'):
        self._arduino.stop_all()
        self._homing = dict.fromkeys(AXES, False)
        self._home_pending.clear()
        self._pending = None
        self._last_steps = dict.fromkeys(AXES)  # allow same-target resume
        self._owner = None
        self._dash.set_controlling(False)
        self._dirty = True
        log.info('STOP: %s', reason)

    async def _handler(self, ws):
        if self._stopping:
            await ws.close(code=1001, reason='Server stopping')
            return
        if len(self._clients) >= 8:
            await ws.close(code=1013, reason='Too many clients')
            return
        self._clients.add(ws)
        self._dash.set_ws(len(self._clients))
        try:
            await self._send(ws, {'type': 'hello', 'server': 'scara-ws', 'protocol': PROTOCOL_VERSION,
                                  'home_pose': HOME_POSE, 'gear_ratio': GEAR_RATIO,
                                  'hardware_enabled': getattr(self, '_hardware_enabled', True)})
            await self._send(ws, self._status_payload())
            async for message in ws:
                await self._on_message(ws, message)
        except ConnectionError:
            pass
        finally:
            self._clients.discard(ws)
            if ws is self._owner:
                self._stop_motion('controller disconnected')
                await self._broadcast({'type': 'stopped', 'reason': 'controller disconnected'})
            self._dash.set_ws(len(self._clients))

    @staticmethod
    def _number(value, low, high):
        if isinstance(value, bool):
            raise ValueError('boolean is not a number')
        value = float(value)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'value must be finite and between {low} and {high}')
        return value

    def _parse_speed(self, value):
        return round(self._number(value, MIN_SPEED, SPEED_LIMIT))

    def _claim(self, ws):
        if self._owner is not None and self._owner is not ws:
            raise ValueError('another client controls the robot')
        self._owner = ws
        self._lease_time = time.monotonic()

    async def _on_message(self, ws, message):
        request_id = kind = None
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                raise ValueError('JSON object required')
            kind, request_id = data.get('type'), data.get('request_id')
            if self._stopping and kind not in ('stop', 'ping', 'status_req'):
                raise ValueError('server is shutting down')
            if not getattr(self, '_hardware_enabled', True) and kind in ('joint', 'home_start', 'go_home'):
                raise ValueError('hardware commands are disabled in demo mode')
            if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 80):
                request_id = None
                raise ValueError('bad request id')
            if kind == 'stop':
                self._stop_motion()
                await self._broadcast({'type': 'stopped'})
            elif kind == 'joint':
                if any(self._homing.values()) or self._pending:
                    raise ValueError('homing or physical move completion in progress')
                targets = {a: self._number(data.get(a, self._last_joint[a]), *JOINT_LIMITS[a]) for a in AXES}
                speed = self._parse_speed(data.get('speed', 1200))
                if not all(self._arduino.is_connected(a) for a in AXES):
                    raise ValueError('all three V2 axes must be connected')
                self._claim(ws)
                await self._joint(targets, speed, request_id if data.get('wait') else None)
                await self._send(ws, {'type': 'joint_ack', 'request_id': request_id,
                                      'target': targets, 'steps': self._last_steps,
                                      'arduino': {a: self._arduino.is_connected(a) for a in AXES}})
            elif kind == 'home_start':
                speed = self._parse_speed(data.get('speed', 700))
                if not all(self._arduino.is_connected(a) for a in AXES):
                    raise ValueError('all three V2 axes must be connected')
                self._claim(ws)
                self._arduino.stop_all()
                self._pending = None
                self._home_pending = set(AXES)
                self._home_offset = dict.fromkeys(AXES)
                self._home_deadline = time.monotonic() + HOME_TIMEOUT
                for a in AXES:
                    self._homing[a] = True
                    if not self._arduino.send_home_search(a, -1, speed):
                        raise ValueError(f'{a} serial write failed')
                    self._current_speed[a] = speed
                await self._broadcast({'type': 'home_started', 'pose': HOME_POSE})
            elif kind == 'go_home':
                if any(self._homing.values()) or self._pending:
                    raise ValueError('motion already in progress')
                if any(self._home_offset[a] is None for a in AXES):
                    raise ValueError('set home first')
                if not all(self._arduino.is_connected(a) for a in AXES):
                    raise ValueError('axis disconnected')
                speed = self._parse_speed(data.get('speed', 700))
                self._claim(ws)
                await self._joint(dict(HOME_POSE), speed, request_id or 'go-home')
                await self._broadcast({'type': 'going_home', 'pose': HOME_POSE})
            elif kind == 'ping':
                if ws is self._owner:
                    self._lease_time = time.monotonic()
                await self._send(ws, {'type': 'pong'})
            elif kind == 'status_req':
                await self._send(ws, self._status_payload())
            elif kind == 'enc_req':
                axis = data.get('axis')
                if axis not in AXES:
                    raise ValueError('unknown axis')
                await self._send(ws, {'type': 'enc', 'axis': axis, **self._encoder(axis)})
            elif kind == 'home_status':
                await self._send(ws, {'type': 'home_status', 'offsets': self._home_offset, 'pose': HOME_POSE})
            else:
                raise ValueError('unknown message type')
        except (ValueError, TypeError, OverflowError) as exc:
            if ws is self._owner and kind in ('home_start', 'go_home'):
                self._stop_motion(str(exc))
            await self._send(ws, {'type': 'error', 'message': str(exc), 'request_id': request_id})

    async def _joint(self, targets, speed, request_id=None):
        self._command_id = self._command_id % 2000000000 + 1
        cid = self._command_id
        steps = {a: deg_to_steps(a, targets[a]) for a in AXES}
        for axis in AXES:
            if speed != self._current_speed[axis]:
                if not self._arduino.send_speed(axis, speed):
                    self._stop_motion('speed write failed')
                    raise ValueError('serial write failed')
                self._current_speed[axis] = speed
            if request_id or steps[axis] != self._last_steps[axis]:
                if not self._arduino.send_goto(axis, steps[axis], cid):
                    self._stop_motion('target write failed')
                    raise ValueError('serial write failed')
                self._last_steps[axis] = steps[axis]
            self._dash.update_joint(axis, targets[axis], steps[axis])
        self._last_joint = dict(targets)
        self._dash.set_controlling(True)
        if request_id:
            distance = max(abs(steps[a] - (self._actual[a] or {}).get('current', steps[a])) for a in AXES)
            self._pending = {'id': cid, 'request_id': request_id, 'steps': steps,
                             'deadline': time.monotonic() + max(15, distance / speed * 3 + 5)}
        self._dirty = True

    def _encoder(self, axis):
        enc = self._last_enc[axis]
        return dict(enc) if time.monotonic() - enc['ts'] <= ENCODER_TTL else self._invalid_encoder()

    def _status_payload(self):
        return {'type': 'status', 'home_pose': HOME_POSE, 'homing': any(self._homing.values()),
                'axes': {a: {'connected': self._arduino.is_connected(a),
                             'target': self._last_joint[a], 'steps': self._last_steps[a],
                             'actual': self._actual[a], 'encoder': self._encoder(a)} for a in AXES}}

    async def _process_line(self, axis, line):
        if axis not in AXES:
            return
        parts = line.split(',')
        kind = parts[0]
        try:
            if kind in ('ENC', 'HOME_DONE'):
                raw, sensor = int(parts[1]), int(parts[2])
                valid = 0 <= raw < 4096
                if kind == 'HOME_DONE' and (not self._homing[axis] or not valid or sensor != 0):
                    if self._homing[axis]:
                        self._stop_motion('invalid HOME_DONE')
                        await self._broadcast({'type': 'error', 'message': 'invalid home encoder/sensor'})
                    return
                if valid:
                    prev = self._enc_prev[axis]
                    if prev is None:
                        self._enc_count[axis] = self._enc_zero[axis] = raw
                    else:
                        self._enc_count[axis] += (raw - prev + 2048) % 4096 - 2048
                    self._enc_prev[axis] = raw
                    if kind == 'HOME_DONE':
                        self._enc_zero[axis] = self._enc_count[axis]
                    deg = HOME_POSE[axis] + (self._enc_count[axis] - self._enc_zero[axis]) * 360 / 4096 / GEAR_RATIO[axis]
                    self._last_enc[axis] = {'raw': raw, 'deg': round(deg, 3), 'ok': True,
                                            'ts': time.monotonic(),
                                            'magnet': int(parts[3]) if len(parts) > 3 else None}
                else:
                    self._last_enc[axis] = self._invalid_encoder()
                self._dash.update_encoder(axis, raw if valid else 0, self._last_enc[axis]['deg'] or 0, valid)
                await self._broadcast({'type': 'enc', 'axis': axis, **self._encoder(axis)})
                if kind == 'HOME_DONE':
                    self._homing[axis] = False
                    self._home_pending.discard(axis)
                    self._home_offset[axis] = raw
                    self._last_steps[axis] = 0
                    self._last_joint[axis] = HOME_POSE[axis]
                    await self._broadcast({'type': 'home_saved', 'axis': axis, 'raw': raw,
                                           'deg': HOME_POSE[axis], 'done': True})
                    if not self._home_pending:
                        self._owner = None
                        self._dash.set_controlling(False)
                        await self._broadcast({'type': 'home_all_set', 'pose': HOME_POSE})
            elif kind == 'STATE':
                current, target, cid, moving = map(int, parts[1:5])
                self._actual[axis] = {'current': current, 'target': target, 'id': cid,
                                      'moving': bool(moving), 'deg': steps_to_deg(axis, current),
                                      'ts': time.monotonic()}
            elif kind in ('HOME_FAILED', 'WATCHDOG', 'DISCONNECTED', 'ERROR') or 'READY' in line:
                self._last_enc[axis] = self._invalid_encoder()
                self._actual[axis] = None
                self._home_offset[axis] = None
                self._enc_prev[axis] = None
                self._stop_motion(line)
                await self._broadcast({'type': 'error', 'message': f'{axis}: {line}'})
            self._dirty = True
        except (ValueError, IndexError):
            log.warning('Malformed serial line %s: %s', axis, line[:160])

    async def _tick(self):
        now = time.monotonic()
        if self._overflow:
            self._overflow = False
            self._stop_motion('serial feedback overflow')
            await self._broadcast({'type': 'stopped', 'reason': 'serial feedback overflow'})
        for _ in range(256):
            try:
                axis, line = self._inbox.get_nowait()
            except queue.Empty:
                break
            await self._process_line(axis, line)
        if self._owner and now - self._lease_time > 2:
            self._stop_motion('browser heartbeat expired')
            await self._broadcast({'type': 'stopped', 'reason': 'heartbeat expired'})
        if any(self._homing.values()) and now > self._home_deadline:
            self._stop_motion('home timeout')
            await self._broadcast({'type': 'error', 'message': 'home timeout'})
        if self._pending:
            pending = self._pending
            arrived = all(self._actual[a] and self._actual[a]['id'] == pending['id']
                          and not self._actual[a]['moving']
                          and self._actual[a]['current'] == pending['steps'][a]
                          and now - self._actual[a]['ts'] < 1 for a in AXES)
            if arrived:
                self._pending = None
                await self._broadcast({'type': 'move_done', 'request_id': pending['request_id']})
            elif now > pending['deadline']:
                self._stop_motion('move timeout')
                await self._broadcast({'type': 'error', 'message': 'physical move timeout',
                                       'request_id': pending['request_id']})
        if self._owner and now - self._last_heartbeat >= 0.3:
            self._arduino.heartbeat()
            self._last_heartbeat = now
        if self._dirty or now - self._last_status >= 0.25:
            self._dirty = False
            self._last_status = now
            await self._broadcast(self._status_payload())

    async def _tick_loop(self):
        while not self._shutdown_event.is_set():
            await self._tick()
            await asyncio.sleep(0.05)

ScaraBLEServer = ScaraWSServer
