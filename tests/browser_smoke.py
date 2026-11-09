"""Real Chromium/WebGL and WebSocket checks; no serial ports or motors are used."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time
from playwright.sync_api import sync_playwright
from aiohttp import web
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_server import ScaraWSServer
from web_app import create_app, RUNTIME

ROOT=Path(__file__).resolve().parents[1]
class FakeTransport:
    def __init__(self):self.server=None;self.commands=[];self.ids={};self.positions={};self.timers=[]
    def is_connected(self,a):return True
    def connect_all(self):pass
    def send_speed(self,a,s):return True
    def send_home_search(self,a,d,s):return True
    def send_goto(self,a,target,cid):
        self.commands.append((a,target,cid));self.ids[a]=cid
        self.server._enqueue_line(a,f'STATE,{self.positions.get(a,0)},{target},{cid},1')
        def done():
            if self.ids.get(a)!=cid:return
            self.positions[a]=target
            self.server._enqueue_line(a,f'STATE,{target},{target},{cid},0')
        timer=threading.Timer(.35,done);timer.daemon=True;timer.start();self.timers.append(timer)
        self.timers=[t for t in self.timers if t.is_alive()]
        return True
    def stop_all(self):self.ids.clear()
    def heartbeat(self):pass
    def close(self):
        for timer in self.timers:timer.cancel()

def run():
    ready=threading.Event();stop=threading.Event();info={}
    hw=FakeTransport();server=ScaraWSServer(transport=hw);hw.server=server
    async def serve():
        app=create_app(server,discover=False)
        info['runtime']=app[RUNTIME]
        runner=web.AppRunner(app)
        await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0)
        await site.start()
        info['port']=site._server.sockets[0].getsockname()[1];ready.set()
        try:
            while not stop.is_set() and not app[RUNTIME].stop_event.is_set():
                await asyncio.sleep(.02)
        finally:
            await runner.cleanup()
    thread=threading.Thread(target=lambda:asyncio.run(serve()),daemon=True);thread.start();assert ready.wait(5)
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,
                                      args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1000})
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{info['port']}/index.html")
            page.wait_for_function('!!window.ScaraScene',timeout=30000)
            assert page.evaluate('ScaraScene.readPose().j2')==180
            page.locator('#helpModalClose').click()
            page.evaluate("document.getElementById('j1').value=35;document.getElementById('j1').dispatchEvent(new Event('input'))")
            assert abs(page.evaluate('window.__scaraJointState.j1')-35)<1e-6
            # Repeated ghost add/remove must leave GPU geometry/texture counts stable.
            page.evaluate('ScaraScene.addWaypoint()');page.wait_for_timeout(200)
            page.evaluate('ScaraScene.removeWaypoint(0)');page.wait_for_timeout(200)
            before=page.evaluate('ScaraScene.memory()')
            for _ in range(15):
                page.evaluate('ScaraScene.addWaypoint()');page.wait_for_timeout(40)
                page.evaluate('ScaraScene.removeWaypoint(0)');page.wait_for_timeout(40)
            after=page.evaluate('ScaraScene.memory()')
            assert before['geometries']==after['geometries'],(before,after)
            assert before['textures']==after['textures'],(before,after)
            print('GPU ownership plateau:',before,after)
            # Popup engine: 3 iterations complete and report completion.
            with page.expect_popup() as popup:
                page.locator('#blockCodingBtn').click()
            editor=popup.value;editor.on('pageerror',lambda error:errors.append(str(error)))
            editor.wait_for_function("typeof runProgram==='function'")
            editor.evaluate("state.blocks=[{type:'Loop',params:{count:3}},{type:'Wait',params:{sec:.1}}];runProgram()")
            editor.wait_for_function('!state.running')
            assert editor.locator('#log-out').inner_text().count('Wait')==3
            # Hardware connection uses a real localhost WebSocket with fake motors.
            page.wait_for_function('protocolReady && !SIMULATE_MODE')
            page.locator('#btnStart').click()
            page.wait_for_function('controller.running')
            page.evaluate("ScaraScene.setPose({j1:20,j2:180,j3:0})")
            page.wait_for_timeout(200)
            assert any(a=='j1' and target==1778 for a,target,_ in hw.commands)
            # Final command must wait for all physical position reports (350ms fake lag).
            page.evaluate("window.testDone=false;window.testStart=performance.now();completeSceneMove(ScaraScene.readPose()).then(()=>{window.testDone=true;window.testElapsed=performance.now()-window.testStart})")
            page.wait_for_function('window.testDone')
            assert page.evaluate('window.testElapsed')>=300
            print('Physical completion delay (ms):',page.evaluate('window.testElapsed'))
            # Popup stop cancels an in-flight main animation as well as motors.
            editor.evaluate("state.blocks=[{type:'MoveJ',params:{j1:30,j2:180,speed:10}}];runProgram()")
            page.wait_for_function('window.__scaraWpPlaying')
            editor.evaluate('stopProgram()')
            page.wait_for_function('!window.__scaraWpPlaying && !controller.running')
            page.wait_for_timeout(200);assert not server._pending
            # Endpoint accuracy and hardware completion through the full block path.
            editor.evaluate("state.blocks=[{type:'MoveJ',params:{j1:25,j2:170,speed:10}}];runProgram()")
            editor.wait_for_function('!state.running',timeout=10000)
            pose=page.evaluate('ScaraScene.readPose()')
            assert abs(pose['j1']-25)<1e-6 and abs(pose['j2']-170)<1e-6,pose
            assert any(a=='j2' and target==-889 for a,target,_ in hw.commands)
            # Exercise the Cartesian animation itself, not just the pure solver.
            page.evaluate("const ik=ScaraCore.solveTip(1,1,0);ScaraScene.setPose({j1:-ik.theta1/ScaraCore.RAD,j2:-ik.theta2/ScaraCore.RAD,j3:0})")
            editor.evaluate("state.blocks=[{type:'MoveL',params:{x:1.5,z:1,speed:10}}];runProgram()")
            editor.wait_for_function('!state.running',timeout=10000)
            actual=page.evaluate('ScaraCore.tip(ScaraScene.readPose())')
            assert abs(actual['x']-1.5)<1e-6 and abs(actual['z']-1)<1e-6,actual
            # Manual input during an animation preserves the newly requested value.
            editor.evaluate("state.blocks=[{type:'MoveJ',params:{j1:0,j2:180,speed:1}}];runProgram()")
            page.wait_for_function('window.__scaraWpPlaying')
            page.evaluate("const slider=document.getElementById('hwSliderJ1');slider.value=17;slider.dispatchEvent(new Event('input'))")
            page.wait_for_function('!window.__scaraWpPlaying && !controller.running')
            assert abs(page.evaluate('ScaraScene.readPose().j1')-17)<1e-6
            assert not errors,errors
            if os.environ.get('SCARA_TEST_ARTIFACTS'):
                artifacts=Path(os.environ['SCARA_TEST_ARTIFACTS'])
                artifacts.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(artifacts/'smoke.png'))
            page.once('dialog',lambda dialog:dialog.accept())
            page.locator('#btnShutdownApp').click()
            page.wait_for_function('applicationStopped',timeout=15000)
            assert page.locator('#applicationStopOverlay').is_visible()
            assert page.evaluate('!window.ScaraScene && !ScaraBLE._shouldReconnect')
            assert info['runtime'].closed
            if os.environ.get('SCARA_TEST_ARTIFACTS'):
                page.screenshot(path=str(Path(os.environ['SCARA_TEST_ARTIFACTS'])/'shutdown.png'))
            assert not errors,errors
            print('Hosted app / automatic connection / orderly shutdown checks passed; JS errors:',errors)
            browser.close()
    finally:
        stop.set();thread.join(10);hw.close();assert not thread.is_alive()

if __name__=='__main__':run()
