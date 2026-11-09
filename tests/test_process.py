"""A real main process must release its HTTP/WS port and exit zero on web stop."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class ProcessTests(unittest.TestCase):
    def test_demo_process_serves_then_exits_cleanly_on_shutdown(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([sys.executable, '-B', str(ROOT/'scara_main.py'),
                                        '--demo', '--host', '127.0.0.1', '--port', str(port)],
                                       stdout=output, stderr=output,
                                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            try:
                config = None
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urllib.request.urlopen(base+'/api/config', timeout=.5) as response:
                            config = json.load(response)
                        break
                    except OSError:
                        time.sleep(.05)
                self.assertIsNotNone(config)
                self.assertTrue(config['demo'])
                request = urllib.request.Request(base+'/api/shutdown', data=b'{}', method='POST',
                    headers={'Origin': base, 'Content-Type': 'application/json',
                             'X-SRobot-Token': config['shutdown_token']})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 202)
                code = process.wait(timeout=10)
                output.seek(0)
                self.assertEqual(code, 0, output.read().decode('utf-8', errors='replace'))
                with socket.socket() as sock:
                    sock.settimeout(.5)
                    self.assertNotEqual(sock.connect_ex(('127.0.0.1', port)), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
