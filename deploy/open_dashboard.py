#!/usr/bin/env python3
"""Optional desktop-session launcher. No root access or robot commands."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


def healthy(url):
    try:
        with urllib.request.urlopen(url + '/api/health', timeout=1) as response:
            return json.load(response).get('state') == 'running'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    for _ in range(120):
        if healthy(url):
            break
        time.sleep(1)
    else:
        raise SystemExit('srobot did not become ready within 120 seconds')
    chromium = shutil.which('chromium') or shutil.which('chromium-browser')
    if not chromium:
        raise SystemExit('Install Chromium to use desktop autostart')
    profile = Path.home() / '.cache/srobot-browser'
    # A dedicated profile keeps this child separate from other browser windows.
    child = subprocess.Popen([chromium, '--kiosk', '--no-first-run',
                              '--disable-session-crashed-bubble', f'--user-data-dir={profile}', url])
    failures = 0
    try:
        while child.poll() is None:
            time.sleep(1)
            failures = 0 if healthy(url) else failures + 1
            if failures >= 3:
                break
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
