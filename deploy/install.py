#!/usr/bin/env python3
"""Install on the Pi when SSH is available. Never executed by local tests."""
import argparse
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
TARGET = Path('/opt/srobot')
EXCLUDED = {'.git', '.venv', '__pycache__', 'backups', 'build', 'dist', 'artifacts'}


def render_service(user, group, port):
    if not all(re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', name) for name in (user, group)):
        raise ValueError('Invalid Linux user/group name')
    if not 1024 <= port <= 65535:
        raise ValueError('Service port must be 1024..65535')
    text = (SOURCE / 'deploy/srobot.service.in').read_text(encoding='utf-8')
    for key, value in {'USER': user, 'GROUP': group, 'PORT': str(port)}.items():
        text = text.replace('@' + key + '@', value)
    return text


def backup_existing(target):
    if not target.exists():
        return None
    directory = target.parent / 'backups'
    directory.mkdir(exist_ok=True)
    korea_time = timezone(timedelta(hours=9), 'Asia/Seoul')
    name = 'D' + datetime.now(korea_time).strftime('%m%d%H%M') + '.zip'
    destination = directory / name
    # Refuse to overwrite a same-minute backup.
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(target.rglob('*')):
            if path.is_file() and not EXCLUDED.intersection(path.relative_to(target).parts):
                archive.write(path, Path(target.name) / path.relative_to(target))
    return destination


def command(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description='Install srobot on Raspberry Pi OS')
    parser.add_argument('--user', required=True, help='Existing non-root desktop/login user')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--start', action='store_true', help='Start service immediately as well as at boot')
    parser.add_argument('--desktop', action='store_true', help='Open Chromium after desktop login')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run with sudo on the Raspberry Pi, not on the development PC')
    import pwd
    import grp
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0:
        parser.error('Use a non-root service user')
    group = grp.getgrgid(account.pw_gid).gr_name
    service = render_service(args.user, group, args.port)
    # A backup collision must not stop a currently healthy service.
    archived = backup_existing(TARGET)
    if archived:
        print('Backup:', archived)
    # A running deployment is stopped before any files are replaced.
    if Path('/etc/systemd/system/srobot.service').exists():
        command('systemctl', 'stop', 'srobot.service')
    if SOURCE != TARGET:
        shutil.copytree(SOURCE, TARGET, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*EXCLUDED, '*.pyc', '*.zip', '*.bak*', '.env*'))
    command(sys.executable, '-m', 'venv', str(TARGET / '.venv'))
    command(str(TARGET / '.venv/bin/python'), '-m', 'pip', 'install', '-r', str(TARGET / 'requirements.txt'))
    Path('/etc/systemd/system/srobot.service').write_text(service, encoding='utf-8')
    command('systemctl', 'daemon-reload')
    command('systemctl', 'enable', 'srobot.service')
    if args.desktop:
        home = Path(account.pw_dir)
        autostart = home / '.config/autostart'
        autostart.mkdir(parents=True, exist_ok=True)
        for path in (home / '.config', autostart):
            os.chown(path, account.pw_uid, account.pw_gid)
        entry = autostart / 'srobot.desktop'
        entry.write_text('[Desktop Entry]\nType=Application\nName=SCARA Robot\n'
                         f'Exec=/opt/srobot/.venv/bin/python /opt/srobot/deploy/open_dashboard.py --port {args.port}\n'
                         'Terminal=false\nX-GNOME-Autostart-enabled=true\n', encoding='utf-8')
        os.chown(entry, account.pw_uid, account.pw_gid)
    if args.start:
        command('systemctl', 'start', 'srobot.service')
    print(f'Installed. Dashboard: http://<PI-IP>:{args.port}')
    print('Normal web shutdown leaves the service inactive until restart or the next boot.')


if __name__ == '__main__':
    main()
