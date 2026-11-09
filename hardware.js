'use strict';
// One transport and one 50 Hz publisher own all hardware commands.
let SIMULATE_MODE = true;
let controller = {running:false, start(){this.running=true;}, stop(){this.running=false;}, dispose(){this.stop();}};
const byId = id => document.getElementById(id);
const modeBadge=byId('modeBadge'),btnConnect=byId('btnConnect'),btnStart=byId('btnStart'),btnMode=byId('btnMode');
let pendingMove=null, finalPose=null, lastSent='', sequence=0, homing=false;
let protocolReady=false, lastStatus=null, lastHeartbeat=0;
let applicationConfig=null, applicationStopping=false, applicationStopped=false;
let stopConfirmationTimer=null;
let hostedConfigStarted=false;

function websocketUrl(endpoint){
  if(/^wss?:\/\//i.test(endpoint))return new URL(endpoint).href;
  const base=new URL(`${location.protocol==='https:'?'https':'http'}://${endpoint}`);
  base.protocol=base.protocol==='https:'?'wss:':'ws:';
  if(!base.port)base.port='8080';
  base.pathname='/ws';return base.href;
}
function showApplicationStatus(message,failed=false){
  const panel=byId('applicationStopOverlay');panel.hidden=false;
  byId('applicationStopMessage').textContent=message;
  panel.dataset.failed=String(failed);
}
function finishApplicationStop(){
  if(applicationStopped)return;
  applicationStopped=true;applicationStopping=true;
  clearTimeout(stopConfirmationTimer);
  stopAll('프로그램 종료 완료',false);ScaraBLE.disconnect(false);
  clearInterval(hwStreamTimer);window.dispatchEvent(new Event('ScaraApplicationStopped'));
  window.ScaraScene?.dispose();
  byId('btnShutdownApp').disabled=true;
  showApplicationStatus('웹·제어 프로그램이 종료되었습니다. 이 화면을 닫아도 됩니다. 라즈베리파이 전원은 운영체제를 종료한 뒤 꺼 주세요.');
}

function log(message,color='#8899aa') {
  const el=byId('hwLog'),line=document.createElement('div');
  line.style.color=color;line.textContent=`[${new Date().toLocaleTimeString()}] ${message}`;
  el.appendChild(line);while(el.children.length>50)el.firstChild.remove();el.scrollTop=el.scrollHeight;
}
function getManualSpeed(){
  const speed=Math.round(Math.max(120,Math.min(3000,Number(byId('hwSpeed').value)||1200)));
  byId('hwLabelSpeed').textContent=speed+' st/s';return speed;
}
function calcLiveSpeed(){return getManualSpeed();}
function updateControlUI(){
  btnStart.textContent=controller.running?'⏸ 정지':'▶ 제어 시작';
  btnStart.classList.toggle('running',controller.running);
  modeBadge.textContent=SIMULATE_MODE?'SIM MODE':'HW MODE';
  modeBadge.className='hw-badge '+(SIMULATE_MODE?'sim':'real');
}
function notifyEditor(cmd,extra={}){
  const win=window.__scaraBlockWin;
  if(win&&!win.closed)win.postMessage({src:'scaraMain',cmd,...extra},location.origin==='null'?'*':location.origin);
}
function cancelPending(reason){
  finalPose=null;
  if(pendingMove){clearTimeout(pendingMove.timer);const p=pendingMove;pendingMove=null;p.reject(new Error(reason));}
}
function stopAll(reason='정지',send=true){
  controller.stop();homing=false;lastSent='';cancelPending(reason);
  window.ScaraScene?.stop();
  if(send)ScaraBLE.sendStop();
  notifyEditor('motionStopped',{reason});updateControlUI();
}
function completeSceneMove(pose){
  if(SIMULATE_MODE)return Promise.resolve();
  if(!ScaraBLE.connected||!protocolReady)return Promise.reject(new Error('V2 서버 연결이 필요합니다'));
  if(pendingMove)return Promise.reject(new Error('이전 이동 응답 대기 중'));
  const request_id='move-'+Date.now()+'-'+(++sequence);
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{stopAll('실물 도착 응답 시간 초과');},180000);
    pendingMove={request_id,resolve,reject,timer};
    finalPose={...ScaraCore.validatePose(pose),request_id};
  });
}
const ScaraBLE = {
  ws:null,connected:false,liveSpeed:1200,_generation:0,_shouldReconnect:false,
  _reconnectTimer:null,_connectTimer:null,_url:'',_finishConnect:null,
  connect(ip,isReconnect=false){
    if(applicationStopping||applicationStopped)return Promise.resolve(false);
    this.disconnect(false);this._shouldReconnect=true;
    const generation=++this._generation;
    let url;
    try{url=websocketUrl(ip);}catch{log('서버 주소를 확인하세요');return Promise.resolve(false);}
    this._url=url;
    return new Promise(resolve=>{
      let settled=false;
      const finish=ok=>{if(!settled){settled=true;resolve(ok);}};
      this._finishConnect=finish;
      let ws;
      try{ws=this.ws=new WebSocket(url);}catch{finish(false);return;}
      ws.onopen=()=>{if(generation!==this._generation)return;this.connected=true;};
      ws.onmessage=event=>{
        if(generation!==this._generation)return;
        try{
          const data=JSON.parse(event.data);
          if(data.type==='hello'){
            if(data.protocol!==2){log('서버와 펌웨어 V2 업데이트가 필요합니다','#ff6666');this.disconnect();finish(false);return;}
            protocolReady=true;clearTimeout(this._connectTimer);this._connectTimer=null;
            SIMULATE_MODE=data.hardware_enabled===false;controller.stop();lastSent='';
            byId('bleDot').className='connected';byId('bleStatusText').textContent='연결됨 ✓';
            byId('bleDeviceName').textContent=url;btnConnect.textContent='✓ 연결됨 (해제)';
            updateControlUI();finish(true);log(isReconnect?'서버 재연결 완료 — 제어 시작을 눌러 재개':'서버 연결 완료');
          }else if(data.type==='server_stopping'){
            applicationStopping=true;this._shouldReconnect=false;
            stopAll('서버 프로그램 종료 중',false);showApplicationStatus('모터 정지 및 USB 통신을 정리하고 있습니다…');
          }else if(data.type==='server_stopped'){
            finishApplicationStop();
          }else if(data.type==='server_shutdown_failed'){
            applicationStopping=true;this._shouldReconnect=false;stopAll('서버 종료 확인 실패',false);
            showApplicationStatus('종료를 확인하지 못했습니다. 전원을 끄기 전에 SSH에서 서비스 상태를 확인하세요.',true);
          }else if(data.type==='status'){
            lastStatus=data;
            if(data.homing)homing=true;
            updateFeedback();
          }else if(data.type==='enc'){
            if(lastStatus?.axes?.[data.axis])lastStatus.axes[data.axis].encoder=data;
            updateFeedback();
          }else if(data.type==='move_done'){
            if(pendingMove?.request_id===data.request_id){
              const p=pendingMove;pendingMove=null;clearTimeout(p.timer);lastSent='';p.resolve();
            }
          }else if(data.type==='home_started'){
            homing=true;log('원점 센서 탐색 중');
          }else if(data.type==='home_saved'){
            byId('homeSavedStatus').style.display='block';
            byId('homeSaved'+data.axis.toUpperCase()).textContent=`${data.axis.toUpperCase()}: ${data.deg}° (raw ${data.raw})`;
          }else if(data.type==='home_all_set'){
            homing=false;controller.stop();window.ScaraScene?.setPose(data.pose||ScaraCore.HOME);lastSent='';
            updateControlUI();log('원점 설정 완료 (0°, 180°, 0°)');
          }else if(data.type==='stopped'){
            stopAll(data.reason||'서버 정지',false);
          }else if(data.type==='error'){
            log(data.message,'#ff6666');stopAll(data.message);
          }
        }catch(error){log(error.message,'#ff6666');}
      };
      ws.onclose=()=>{
        if(generation!==this._generation)return;
        clearTimeout(this._connectTimer);this._connectTimer=null;
        this.connected=false;protocolReady=false;this.ws=null;finish(false);
        stopAll('연결 끊김',false);SIMULATE_MODE=true;updateControlUI();
        byId('bleDot').className='';byId('bleStatusText').textContent='WebSocket 미연결';btnConnect.textContent='🟢 WS 연결';
        if(applicationStopping&&!applicationStopped)showApplicationStatus('서버 연결이 닫혔지만 종료 완료 응답을 받지 못했습니다. SSH에서 서비스 상태를 확인하세요.',true);
        if(this._shouldReconnect&&!applicationStopping)this._reconnectTimer=setTimeout(()=>this.connect(ip,true),3000);
      };
      ws.onerror=()=>finish(false);
      this._connectTimer=setTimeout(()=>{finish(false);ws.close();},5000);
    });
  },
  disconnect(sendStop=true){
    if(sendStop)stopAll('연결 해제');
    this._shouldReconnect=false;++this._generation;
    clearTimeout(this._reconnectTimer);clearTimeout(this._connectTimer);
    this._reconnectTimer=this._connectTimer=null;
    this._finishConnect?.(false);this._finishConnect=null;
    const ws=this.ws;this.ws=null;
    if(ws){ws.onopen=ws.onmessage=ws.onclose=ws.onerror=null;ws.close();}
    this.connected=false;protocolReady=false;
  },
  _send(data){
    if(!this.connected||this.ws?.readyState!==WebSocket.OPEN)return false;
    if(this.ws.bufferedAmount>32768){stopAll('송신 지연',false);this.ws.close();return false;}
    this.ws.send(JSON.stringify(data));return true;
  },
  sendJoint(j1,j2,j3,speed,extra={}){return this._send({type:'joint',j1,j2,j3,speed,...extra});},
  sendStop(){this._send({type:'stop'});},
  setHome(speed){this._send({type:'home_start',speed});},
  requestStatus(){this._send({type:'status_req'});},
  isSupported(){return true;}
};
const ScaraSerial=ScaraBLE;
function updateFeedback(){
  for(const a of ScaraCore.AXES){
    const axis=lastStatus?.axes?.[a],enc=axis?.encoder;
    const pose=window.__scaraJointState||ScaraCore.HOME;
    const angle=SIMULATE_MODE?pose[a]:(enc?.ok?enc.deg:null);
    const name=a.toUpperCase(),range=a==='j3'?180:360;
    byId('val'+name).textContent=angle==null?'—':angle.toFixed(1)+'°';
    byId('bar'+name).style.width=angle==null?'0%':Math.max(0,Math.min(100,(angle+range)/(range*2)*100))+'%';
    byId('raw'+name).textContent=SIMULATE_MODE?'SIM':enc?.ok?enc.raw:'—';
    byId('pwm'+name).textContent=SIMULATE_MODE?'SIM':axis?.actual?.moving?'이동 중':'대기';
    const mag=SIMULATE_MODE?3:enc?.magnet;
    byId('mag'+name).className=mag===3?'mag-ok':mag>0?'mag-weak':'mag-none';
  }
}
const hwStreamTimer=setInterval(()=>{
  if(applicationStopped)return;
  updateFeedback();
  if(SIMULATE_MODE||!ScaraBLE.connected||!protocolReady)return;
  const now=performance.now();
  if(now-lastHeartbeat>=500){ScaraBLE._send({type:'ping'});lastHeartbeat=now;}
  if(!controller.running||homing)return;
  if(finalPose){
    const p=finalPose;finalPose=null;
    ScaraBLE.sendJoint(p.j1,p.j2,p.j3,getManualSpeed(),{request_id:p.request_id,wait:true});return;
  }
  if(pendingMove)return;
  const pose=window.__scaraJointState;
  if(!pose)return;
  const p=ScaraCore.AXES.map(a=>Math.round(pose[a]*1000)/1000),key=p.join(',');
  if(key!==lastSent && ScaraBLE.sendJoint(...p,getManualSpeed()))lastSent=key;
},20);

btnConnect.addEventListener('click',async()=>{
  if(ScaraBLE.connected){ScaraBLE.disconnect();SIMULATE_MODE=true;updateControlUI();btnConnect.textContent='🟢 WS 연결';byId('bleStatusText').textContent='WebSocket 미연결';return;}
  const ip=byId('wsIpInput').value.trim();if(!ip){log('라즈베리파이 IP를 입력하세요');return;}
  btnConnect.disabled=true;
  try{if(!await ScaraBLE.connect(ip))log('연결 실패 — IP/서버를 확인하세요','#ff6666');}
  finally{btnConnect.disabled=false;}
});
btnStart.addEventListener('click',()=>{
  if(applicationStopping)return;
  if(controller.running||homing){stopAll();return;}
  if(!SIMULATE_MODE&&!protocolReady){log('V2 서버 연결이 필요합니다');return;}
  controller.start();lastSent='';updateControlUI();
});
btnMode.addEventListener('click',()=>{
  if(SIMULATE_MODE&&!protocolReady){log('먼저 서버에 연결하세요');return;}
  stopAll('모드 전환');SIMULATE_MODE=!SIMULATE_MODE;updateControlUI();
});
function _hwDirectSend(){
  const pose={j1:Number(byId('hwSliderJ1').value),j2:Number(byId('hwSliderJ2').value),j3:Number(byId('sliderJ3').value)};
  if(window.__scaraWpPlaying)stopAll('수동 조작');
  window.ScaraScene?.setPose(pose);
}
['hwSliderJ1','hwSliderJ2','sliderJ3'].forEach(id=>byId(id).addEventListener('input',_hwDirectSend));
byId('hwSpeed').addEventListener('input',getManualSpeed);
byId('btnSetHome').addEventListener('click',()=>{
  if(!protocolReady){log('먼저 V2 서버에 연결하세요');return;}
  stopAll('원점 탐색 시작');homing=true;ScaraBLE.setHome(getManualSpeed());
});
byId('btnGoHome').addEventListener('click',()=>{
  if(!protocolReady){log('먼저 V2 서버에 연결하세요');return;}
  stopAll('원점 복귀');controller.start();
  const request_id='home-'+(++sequence);
  pendingMove={request_id,timer:setTimeout(()=>stopAll('원점 복귀 시간 초과'),180000),
    resolve:()=>{window.ScaraScene?.setPose(ScaraCore.HOME);controller.stop();updateControlUI();},reject:()=>{}};
  ScaraBLE._send({type:'go_home',speed:getManualSpeed(),request_id});updateControlUI();
});
byId('btnShutdownApp').addEventListener('click',async()=>{
  if(!applicationConfig||applicationStopping)return;
  if(!confirm('모터를 정지하고 라즈베리파이의 웹·제어 프로그램을 모두 종료할까요? 다시 사용하려면 서비스를 시작해야 합니다.'))return;
  applicationStopping=true;ScaraBLE._shouldReconnect=false;
  stopAll('프로그램 종료 요청');byId('btnShutdownApp').disabled=true;
  showApplicationStatus('프로그램 종료를 요청하고 있습니다…');
  try{
    const response=await fetch('/api/shutdown',{method:'POST',headers:{'Content-Type':'application/json','X-SRobot-Token':applicationConfig.shutdown_token},body:'{}',signal:AbortSignal.timeout(5000)});
    if(!response.ok)throw new Error('종료 요청 거절 ('+response.status+')');
    // HTTP 202 only means accepted. Completion requires the final WS event.
    if(!applicationStopped)stopConfirmationTimer=setTimeout(()=>{if(!applicationStopped)showApplicationStatus('종료 완료를 확인하지 못했습니다. SSH에서 서비스를 확인하세요.',true);},15000);
  }catch(error){
    if(applicationStopped)return;
    showApplicationStatus(error.message+'. SSH에서 서비스 상태를 확인하세요.',true);
  }
});
async function connectHostedApplication(){
  if(hostedConfigStarted)return;
  hostedConfigStarted=true;
  if(!/^https?:$/.test(location.protocol))return;
  try{
    const response=await fetch('/api/config',{cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok)return; // Separate static-file hosting still supports manual connection.
    const config=await response.json();
    if(config.protocol!==2||config.websocket_path!=='/ws'||typeof config.shutdown_token!=='string')return;
    applicationConfig=config;byId('btnShutdownApp').disabled=false;
    if(config.state!=='running'){applicationStopping=true;showApplicationStatus('서버 프로그램이 종료 중입니다.');return;}
    const url=new URL(config.websocket_path,location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:';
    byId('wsIpInput').value=location.host;
    byId('wsIpRow').style.display='none';
    await ScaraBLE.connect(url.href);
  }catch(error){log('서버 자동 연결: '+error.message);}
}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAll('화면 비활성화');});
window.addEventListener('pagehide',()=>{stopAll('페이지 종료');clearInterval(hwStreamTimer);ScaraBLE.disconnect(false);},{once:true});
getManualSpeed();updateControlUI();log('준비 완료. 서버 연결 후 제어 시작을 누르세요.');
if(window.ScaraScene)connectHostedApplication();
else window.addEventListener('ScaraSceneReady',connectHostedApplication,{once:true});
// Keep server controls available even if WebGL initialization fails.
if(document.readyState==='complete')connectHostedApplication();
else window.addEventListener('load',connectHostedApplication,{once:true});
