#!/usr/bin/env python3
"""SCARA V2: python scara_main.py [--j1 PORT --j2 PORT --j3 PORT]."""
import argparse
import logging
import signal
import threading
from control_server import ScaraWSServer

def main():
    logging.basicConfig(level=logging.INFO,format='[%(asctime)s] %(levelname)s %(message)s')
    parser=argparse.ArgumentParser(description='SCARA V2 WebSocket controller')
    for axis in ('j1','j2','j3'):
        parser.add_argument('--'+axis,help='Matching V2 Arduino port; unspecified axes are detected')
    args=parser.parse_args()
    ports={a:getattr(args,a) for a in ('j1','j2','j3') if getattr(args,a)}
    server=ScaraWSServer(arduino_ports=ports)
    signal.signal(signal.SIGINT,lambda *_:server.stop())
    signal.signal(signal.SIGTERM,lambda *_:server.stop())
    def quit_reader():
        try:
            while input().strip().lower()!='q':
                pass
            server.stop()
        except (EOFError,OSError):
            pass
    threading.Thread(target=quit_reader,daemon=True,name='quit-reader').start()
    logging.info('WebSocket: ws://%s:8765 ? q + Enter to stop',server._dash._local_ip)
    try:
        server.run()
    finally:
        server.stop()

if __name__=='__main__':
    main()
