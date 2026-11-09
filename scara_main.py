#!/usr/bin/env python3
"""Serve the dashboard and robot controller from one Raspberry Pi process."""
import argparse
import asyncio
import logging
import signal
from aiohttp import web
from control_server import ScaraWSServer
from web_app import create_app, RUNTIME

async def serve(args):
    ports={a:getattr(args,a) for a in ('j1','j2','j3') if getattr(args,a)}
    app=create_app(ScaraWSServer(arduino_ports=ports),demo=args.demo)
    runtime=app[RUNTIME]
    runner=web.AppRunner(app,shutdown_timeout=5)
    loop=asyncio.get_running_loop()
    previous={}
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:
            loop.add_signal_handler(sig,runtime.request_stop,'OS signal')
        except NotImplementedError:
            previous[sig]=signal.signal(sig,lambda *_:loop.call_soon_threadsafe(runtime.request_stop,'OS signal'))
    try:
        await runner.setup()
        site=web.TCPSite(runner,args.host,args.port)
        await site.start()
        logging.info('Dashboard: http://%s:%s (same-port /ws)',args.host,args.port)
        await runtime.stop_event.wait()
    finally:
        await runner.cleanup()
        for sig,handler in previous.items():
            signal.signal(sig,handler)
    return 0 if runtime.closed else 1

def main():
    parser=argparse.ArgumentParser(description='SCARA web dashboard + robot controller')
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--demo',action='store_true',help='Serve simulator without opening USB ports')
    for axis in ('j1','j2','j3'):
        parser.add_argument('--'+axis,help='Matching V2 Arduino port; unspecified axes are detected')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('port must be 1..65535')
    logging.basicConfig(level=logging.INFO,format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
    try:
        return asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0

if __name__=='__main__':
    raise SystemExit(main())
