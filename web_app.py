"""Single-port HTTP + WebSocket application with an orderly process shutdown."""
import asyncio
import hmac
import logging
from pathlib import Path
import secrets
from aiohttp import web, WSMsgType
from control_server import ScaraWSServer

log = logging.getLogger('WEB')
ROOT = Path(__file__).resolve().parent
ASSETS = frozenset(('index.html', 'hardware.js', 'scara_core.js', 'block_bridge.js',
                    'block_editor.html', 'block_editor.js', 'vendor/three.min.js'))
RUNTIME = web.AppKey('runtime', object)


class WebSocketAdapter:
    def __init__(self, socket):
        self.socket = socket

    async def send(self, message):
        await self.socket.send_str(message)

    async def close(self, code=1000, reason=''):
        await self.socket.close(code=code, message=reason.encode('utf-8'))

    async def __aiter__(self):
        async for message in self.socket:
            if message.type == WSMsgType.TEXT:
                yield message.data
            elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
                break
            else:
                await self.close(code=1003, reason='Text JSON required')
                break


class ApplicationRuntime:
    def __init__(self, robot, *, demo=False, discover=True):
        self.robot = robot
        self.demo = demo
        self.discover = discover and not demo
        self.token = secrets.token_urlsafe(32)
        self.state = 'starting'
        self.reason = None
        self.stop_event = asyncio.Event()
        self.shutdown_task = self.discovery_task = self.ticker = None
        self.closed = False
        self.fault = None

    async def start(self):
        self.robot._loop = asyncio.get_running_loop()
        self.robot._shutdown_event = asyncio.Event()
        self.robot._hardware_enabled = not self.demo
        self.ticker = asyncio.create_task(self.robot._tick_loop(), name='robot-feedback')
        self.ticker.add_done_callback(self._task_finished)
        # Serve the page immediately, even while USB boards are still booting.
        if self.discover:
            self.discovery_task = asyncio.create_task(self._discover(), name='usb-discovery')
            self.discovery_task.add_done_callback(self._task_finished)
        self.state = 'running'

    def _task_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self.state == 'running':
            self.fault = error
            log.error('Background task failed: %s', error)
            self.request_stop('background task failed')

    async def _discover(self):
        await asyncio.to_thread(self.robot._arduino.connect_all)
        start_retry = getattr(self.robot._arduino, 'start_reconnect', None)
        if start_retry and not self.robot._stopping:
            start_retry()

    def request_stop(self, reason='web button'):
        if self.shutdown_task is None:
            self.state = 'stopping'
            self.reason = reason
            self.robot._stopping = True
            self.shutdown_task = asyncio.create_task(self._shutdown(), name='orderly-shutdown')
        return self.shutdown_task

    async def _shutdown(self):
        # Give the POST response a chance to leave before terminating HTTP.
        await asyncio.sleep(0.1)
        failed = self.fault is not None
        try:
            self.robot._stop_motion('application shutdown')
            await self.robot._broadcast({'type': 'server_stopping'})
            self.robot._shutdown_event.set()
            if self.ticker:
                results = await asyncio.gather(self.ticker, return_exceptions=True)
                failed = failed or any(isinstance(r, BaseException) for r in results)
            try:
                await asyncio.to_thread(self.robot._arduino.close)
            except Exception:
                failed = True
                log.exception('USB cleanup failed')
            if self.discovery_task:
                results = await asyncio.gather(self.discovery_task, return_exceptions=True)
                failed = failed or any(isinstance(r, BaseException) for r in results)
            self.robot._dash.stop() if self.robot._dash._running else None
            self.state = 'shutdown_failed' if failed else 'stopped'
            await self.robot._broadcast({'type': 'server_shutdown_failed' if failed else 'server_stopped',
                                        'reason': self.reason})
        except Exception:
            failed = True
            self.state = 'shutdown_failed'
            log.exception('Could not confirm complete application shutdown')
            await self.robot._broadcast({'type': 'server_shutdown_failed'})
        finally:
            await asyncio.gather(*(ws.close(code=1001, reason='Server stopped')
                                   for ws in tuple(self.robot._clients)), return_exceptions=True)
            self.robot._clients.clear()
            self.closed = not failed
            self.stop_event.set()

    async def cleanup(self):
        await self.request_stop('service stop')
        # No live reader/discovery/ticker is left behind after the site closes.
        for task in (self.ticker, self.discovery_task):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def same_origin(request):
    return request.headers.get('Origin') == f'{request.scheme}://{request.host}'


async def static_file(request):
    name = request.match_info.get('asset') or 'index.html'
    if name not in ASSETS:
        raise web.HTTPNotFound()
    response = web.FileResponse(ROOT / name)
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


async def config(request):
    runtime = request.app[RUNTIME]
    response = web.json_response({'protocol': 2, 'websocket_path': '/ws',
                                  'shutdown_token': runtime.token, 'demo': runtime.demo,
                                  'state': runtime.state})
    response.headers['Cache-Control'] = 'no-store'
    return response


async def health(request):
    runtime = request.app[RUNTIME]
    response = web.json_response({'state': runtime.state, 'demo': runtime.demo,
                                  'axes': {a: value['connected'] for a, value in
                                           runtime.robot._status_payload()['axes'].items()}})
    response.headers['Cache-Control'] = 'no-store'
    return response


async def shutdown(request):
    runtime = request.app[RUNTIME]
    supplied = request.headers.get('X-SRobot-Token', '')
    if not same_origin(request) or not hmac.compare_digest(supplied, runtime.token):
        raise web.HTTPForbidden(text='Same-origin shutdown token required')
    if request.content_type != 'application/json':
        raise web.HTTPUnsupportedMediaType()
    runtime.request_stop()
    return web.json_response({'state': 'stopping'}, status=202,
                             headers={'Cache-Control': 'no-store'})


async def websocket(request):
    runtime = request.app[RUNTIME]
    if runtime.state != 'running':
        raise web.HTTPServiceUnavailable(text='Server is stopping')
    # Browsers must connect from the served application, not a foreign website.
    if request.headers.get('Origin') and not same_origin(request):
        raise web.HTTPForbidden(text='Foreign WebSocket origin')
    socket = web.WebSocketResponse(heartbeat=10, max_msg_size=16384,
                                   timeout=1, compress=False)
    await socket.prepare(request)
    await runtime.robot._handler(WebSocketAdapter(socket))
    return socket


def create_app(robot=None, *, demo=False, discover=True):
    app = web.Application(client_max_size=1024)
    runtime = ApplicationRuntime(robot or ScaraWSServer(), demo=demo, discover=discover)
    app[RUNTIME] = runtime

    async def lifecycle(app):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.cleanup()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/api/config', config)
    app.router.add_get('/api/health', health)
    app.router.add_post('/api/shutdown', shutdown)
    app.router.add_get('/ws', websocket)
    app.router.add_get('/', static_file)
    app.router.add_get('/{asset:.*}', static_file)
    return app
