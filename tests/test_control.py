import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_server import ScaraWSServer
from robot_config import AXES, HOME_POSE, deg_to_steps

class Transport:
    def __init__(self): self.commands=[];self.failed=False
    def is_connected(self,a): return True
    def send_goto(self,a,v,c): self.commands.append(('goto',a,v,c));return not self.failed
    def send_speed(self,a,v): self.commands.append(('speed',a,v));return not self.failed
    def send_home_search(self,a,d,s): self.commands.append(('home',a,d,s));return not self.failed
    def stop_all(self): self.commands.append(('stop',))
    def heartbeat(self): self.commands.append(('heartbeat',))
    def close(self): pass

class Socket:
    def __init__(self):self.messages=[]
    async def send(self,m):self.messages.append(json.loads(m))
    async def close(self):pass

class ControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hw=Transport();self.s=ScaraWSServer(transport=self.hw);self.ws=Socket()
        self.s._clients.add(self.ws)
    async def message(self,**data):await self.s._on_message(self.ws,json.dumps(data))
    def test_home_coordinate_contract(self):
        for a in AXES:self.assertEqual(deg_to_steps(a,HOME_POSE[a]),0)
        self.assertEqual(deg_to_steps('j2',181),89)
    async def test_stop_same_target_resumes(self):
        await self.message(type='joint',j1=90)
        await self.message(type='stop');self.hw.commands.clear()
        await self.message(type='joint',j1=90)
        self.assertTrue(any(c[:3]==('goto','j1',8000) for c in self.hw.commands))
    async def test_bad_inputs_do_not_crash_or_move(self):
        for message in ['[]','null','1','{','{"type":"joint","j1":"Infinity"}',
                        '{"type":"joint","speed":"Infinity"}',
                        '{"type":"joint","j3":181}',
                        '{"type":"joint","request_id":NaN}']:
            await self.s._on_message(self.ws,message)
            self.assertEqual(self.ws.messages[-1]['type'],'error')
        self.assertFalse(any(c[0]=='goto' for c in self.hw.commands))
    async def test_encoder_failure_and_expiry(self):
        await self.s._process_line('j1','ENC,100,1,3')
        self.assertTrue(self.s._encoder('j1')['ok'])
        await self.s._process_line('j1','ENC,-1,1,0')
        self.assertFalse(self.s._encoder('j1')['ok'])
        await self.s._process_line('j1','ENC,110,1,3')
        self.s._last_enc['j1']['ts']-=2
        self.assertFalse(self.s._encoder('j1')['ok'])
    async def test_home_done_matches_pose_and_rejects_bad_raw(self):
        await self.message(type='home_start')
        for a in AXES:await self.s._process_line(a,'HOME_DONE,100,0,3')
        self.assertEqual(self.s._last_joint,HOME_POSE)
        self.assertTrue(any(m['type']=='home_all_set' for m in self.ws.messages))
        await self.message(type='home_start')
        await self.s._process_line('j1','HOME_DONE,-1,0,0')
        self.assertIsNone(self.s._home_offset['j1'])
        self.assertFalse(any(self.s._homing.values()))
    async def test_physical_barrier_needs_all_axes_and_matching_id(self):
        await self.message(type='joint',j1=10,j2=180,j3=0,wait=True,request_id='test-move')
        pending=self.s._pending
        for a in AXES:
            step=pending['steps'][a]
            await self.s._process_line(a,f'STATE,{step},{step},{pending["id"]-1},0')
        await self.s._tick();self.assertIsNotNone(self.s._pending)
        for a in AXES[:2]:
            step=pending['steps'][a]
            await self.s._process_line(a,f'STATE,{step},{step},{pending["id"]},0')
        await self.s._tick();self.assertIsNotNone(self.s._pending)
        await self.s._process_line('j3',f'STATE,0,0,{pending["id"]},0')
        await self.s._tick();self.assertIsNone(self.s._pending)
        self.assertEqual(sum(m['type']=='move_done' for m in self.ws.messages),1)
    async def test_write_failure_stops_all_axes_and_invalidates_dedup(self):
        self.hw.failed=True
        await self.message(type='joint',j1=30)
        self.assertEqual(self.ws.messages[-1]['type'],'error')
        self.assertIsNone(self.s._owner)
        self.assertTrue(all(v is None for v in self.s._last_steps.values()))
    async def test_owner_exclusion_and_expired_lease(self):
        await self.message(type='joint',j1=10)
        second=Socket();await self.s._on_message(second,'{"type":"joint","j1":20}')
        self.assertEqual(second.messages[-1]['type'],'error')
        self.s._lease_time-=3
        await self.s._tick();self.assertIsNone(self.s._owner)
        self.assertIn(('stop',),self.hw.commands)
    async def test_home_rejects_joint_and_times_out(self):
        await self.message(type='home_start')
        await self.message(type='joint',j1=30)
        self.assertEqual(self.ws.messages[-1]['type'],'error')
        self.s._home_deadline=time.monotonic()-1
        await self.s._tick();self.assertFalse(any(self.s._homing.values()))
    async def test_feedback_queue_is_bounded(self):
        for i in range(10000):self.s._enqueue_line('j1','ENC,100,1,3')
        self.assertEqual(self.s._inbox.qsize(),256)
        self.assertTrue(self.s._overflow)
        await self.s._tick();self.assertEqual(self.s._inbox.qsize(),0)
    async def test_controller_disconnect_stops_without_resetting_pose(self):
        ws=self.ws
        async def iterator():
            yield '{"type":"joint","j1":45}'
        ws.__class__.__aiter__=lambda _:iterator()
        await self.s._handler(ws)
        self.assertEqual(self.s._last_joint['j1'],45)
        self.assertIsNone(self.s._owner)
        self.assertIn(('stop',),self.hw.commands)

if __name__=='__main__':unittest.main()
