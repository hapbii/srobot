import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_server import ScaraWSServer
from web_app import create_app, RUNTIME
from test_control import Transport


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = Transport()
        self.closed = False
        def close():
            self.transport.commands.append(('close',))
            self.closed = True
        self.transport.close = close
        self.robot = ScaraWSServer(transport=self.transport)
        self.app = create_app(self.robot, discover=False)
        self.runtime = self.app[RUNTIME]
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        self.url = 'http://127.0.0.1:' + str(self.site._server.sockets[0].getsockname()[1])
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def test_serves_only_frontend_assets(self):
        for asset in ('/', '/hardware.js', '/vendor/three.min.js', '/block_editor.html'):
            async with self.client.get(self.url + asset) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(await response.read())
        for asset in ('/.git/config', '/scara_main.py', '/requirements.txt', '/deploy/install.py', '/backups/foo.zip'):
            async with self.client.get(self.url + asset) as response:
                self.assertEqual(response.status, 404)

    async def test_config_and_same_port_websocket(self):
        async with self.client.get(self.url + '/api/config') as response:
            config = await response.json()
        self.assertEqual(config['websocket_path'], '/ws')
        async with self.client.ws_connect(self.url + '/ws', origin=self.url) as ws:
            self.assertEqual((await ws.receive_json())['type'], 'hello')
            self.assertEqual((await ws.receive_json())['type'], 'status')
            await ws.send_json({'type': 'ping'})
            while (await ws.receive_json())['type'] != 'pong':
                pass

    async def test_shutdown_rejects_foreign_origin_missing_token_and_get(self):
        for headers in ({}, {'Origin': self.url},
                        {'Origin': 'http://foreign.invalid', 'X-SRobot-Token': self.runtime.token}):
            async with self.client.post(self.url + '/api/shutdown', json={}, headers=headers) as response:
                self.assertEqual(response.status, 403)
        async with self.client.get(self.url + '/api/shutdown') as response:
            self.assertIn(response.status, (404, 405))
        self.assertEqual(self.runtime.state, 'running')
        self.assertFalse(self.closed)

    async def test_web_shutdown_orders_stop_close_and_final_confirmation(self):
        async with self.client.ws_connect(self.url + '/ws', origin=self.url) as ws:
            await ws.receive_json()
            await ws.receive_json()
            headers = {'Origin': self.url, 'X-SRobot-Token': self.runtime.token}
            async with self.client.post(self.url + '/api/shutdown', json={}, headers=headers) as response:
                self.assertEqual(response.status, 202)
            # Motion is rejected as soon as shutdown is accepted.
            await ws.send_json({'type': 'joint', 'j1': 90})
            messages = []
            while True:
                message = await asyncio.wait_for(ws.receive(), 3)
                if message.type.name == 'TEXT':
                    data = json.loads(message.data)
                    messages.append(data['type'])
                    if data['type'] == 'server_stopped':
                        self.assertTrue(self.closed)
                else:
                    break
            self.assertIn('server_stopping', messages)
            self.assertIn('server_stopped', messages)
            self.assertLess(self.transport.commands.index(('stop',)), self.transport.commands.index(('close',)))
            self.assertFalse(any(c[0] == 'goto' for c in self.transport.commands))
        await self.runtime.stop_event.wait()
        self.assertEqual(self.runtime.state, 'stopped')
        self.assertTrue(self.runtime.closed)

    async def test_repeated_shutdown_closes_transport_once(self):
        first = self.runtime.request_stop()
        self.assertIs(first, self.runtime.request_stop())
        await first
        self.assertEqual(self.transport.commands.count(('close',)), 1)

    async def test_foreign_websocket_origin_is_rejected(self):
        async with self.client.get(self.url + '/ws', headers={'Origin': 'http://foreign.invalid'}) as response:
            self.assertEqual(response.status, 403)

    async def test_demo_does_not_open_hardware(self):
        await self.runner.cleanup()
        transport = Transport()
        transport.connect_all = lambda: self.fail('Demo must not open USB')
        demo_app = create_app(ScaraWSServer(transport=transport), demo=True)
        demo_runner = web.AppRunner(demo_app)
        await demo_runner.setup()
        try:
            self.assertFalse(demo_app[RUNTIME].robot._hardware_enabled)
        finally:
            await demo_runner.cleanup()

    async def test_failed_feedback_task_closes_hardware_and_reports_failure(self):
        async def broken_tick():
            raise RuntimeError('feedback failed')
        await self.runner.cleanup()
        robot = ScaraWSServer(transport=self.transport)
        robot._tick_loop = broken_tick
        app = create_app(robot, discover=False)
        runner = web.AppRunner(app)
        await runner.setup()
        runtime = app[RUNTIME]
        try:
            await asyncio.wait_for(runtime.stop_event.wait(), 3)
            self.assertTrue(self.closed)
            self.assertFalse(runtime.closed)
            self.assertEqual(runtime.state, 'shutdown_failed')
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
