
'use strict';
const state={blocks:[],vars:{},waypoints:[],running:false,execIdx:0,loopStack:[]};
let dragSrcType=null,dragSrcIdx=null,dragOverIdx=null,dragOverSide=null,blockIdCounter=1;
const BLOCK_DEF={
  EndLoop:{label:'EndLoop',icon:'↩',cls:'pb-loop',color:'#ff6b6b',params:[]},
  MoveL:{label:'MoveL',icon:'🎯',cls:'pb-move',color:'#4dabf7',params:['x','z','speed']},
  MoveJ:{label:'MoveJ',icon:'🔗',cls:'pb-movej',color:'#8877ff',params:['j1','j2','speed']},
  MoveHome:{label:'Home',icon:'🏠',cls:'pb-home',color:'#3ccfff',params:['speed']},
  Gripper:{label:'Gripper',icon:'✊',cls:'pb-grip',color:'#44ffaa',params:['action']},
  Wait:{label:'Wait',icon:'⏱',cls:'pb-wait',color:'#ffd43b',params:['sec']},
  Loop:{label:'Loop',icon:'🔁',cls:'pb-loop',color:'#ff6b6b',params:['count']},
  If:{label:'If',icon:'❓',cls:'pb-if',color:'#ffa94d',params:['var','op','val']},
  SetVar:{label:'SetVar',icon:'📝',cls:'pb-set',color:'#bb55ff',params:['var','val']},
  Stop:{label:'Stop',icon:'🛑',cls:'pb-stop',color:'#ff5555',params:[]},
};
function defaultParams(t){
  const d={EndLoop:{},MoveL:{x:'0',z:'0',speed:'4'},MoveJ:{j1:'0',j2:'180',speed:'4'},MoveHome:{speed:'4'},Gripper:{action:'open'},Wait:{sec:'1'},Loop:{count:'3'},If:{'var':'i',op:'>',val:'0'},SetVar:{'var':'i',val:'0'},Stop:{}};
  return{...d[t]};
}
const dropZone=document.getElementById('drop-zone');
const emptyHint=document.getElementById('empty-hint');
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function buildParamsHTML(blk){
  const p=blk.params,t=blk.type;
  const pg=(label,key,type='number',extra='')=>'<span class="param-group"><label>'+label+'</label><input type="'+type+'" value="'+esc(p[key]??'')+'" data-key="'+key+'" '+extra+'></span>';
  const sel=(label,key,opts)=>'<span class="param-group"><label>'+label+'</label><select data-key="'+key+'">'+opts.map(o=>'<option value="'+o[0]+'" '+(p[key]===o[0]?'selected':'')+'>'+o[1]+'</option>').join('')+'</select></span>';
  if(t==='MoveL')    return pg('X','x')+pg('Z','z')+pg('SPD','speed');
  if(t==='MoveJ')    return pg('J1°','j1')+pg('J2°','j2')+pg('SPD','speed');
  if(t==='MoveHome') return pg('SPD','speed');
  if(t==='Gripper')  return sel('ACTION','action',[['open','열기'],['close','닫기']]);
  if(t==='Wait')     return pg('초','sec');
  if(t==='Loop')     return pg('횟수','count','number','min="1"');
  if(t==='If')       return pg('변수','var','text')+sel('OP','op',[['>','>'],['<','<'],['==','=='],['!=','!=']])+pg('값','val');
  if(t==='SetVar')   return pg('변수','var','text')+pg('값','val');
  return '';
}
function renderBlocks(){
  [...dropZone.querySelectorAll('.prog-block')].forEach(el=>el.remove());
  emptyHint.style.display=state.blocks.length===0?'':'none';
  state.blocks.forEach((blk,i)=>{
    const def=BLOCK_DEF[blk.type];
    const el=document.createElement('div');
    el.className='prog-block'; el.dataset.idx=i;
    if(state.running&&i===state.execIdx) el.classList.add('exec-active');
    if(state.running&&i<state.execIdx)   el.classList.add('exec-done');
    const inner=document.createElement('div');
    inner.className='prog-block-inner '+def.cls;
    inner.style.borderLeftColor=def.color;
    inner.style.background=def.color+'18';
    inner.innerHTML='<span class="block-num">'+String(i+1).padStart(2,'0')+'</span><span class="block-icon">'+def.icon+'</span><span class="block-label">'+def.label+'</span><span class="block-params">'+buildParamsHTML(blk)+'</span>';
    const del=document.createElement('div');
    del.className='block-del'; del.textContent='✕';
    del.addEventListener('click',e=>{e.stopPropagation();removeBlock(i);});
    el.appendChild(inner); el.appendChild(del);
    el.draggable=true;
    el.addEventListener('dragstart',e=>{dragSrcIdx=i;dragSrcType=null;el.classList.add('dragging');e.dataTransfer.effectAllowed='move';});
    el.addEventListener('dragend',()=>{el.classList.remove('dragging');clearDragOver();});
    el.addEventListener('dragover',e=>{
      e.preventDefault();
      const rect=el.getBoundingClientRect();
      const side=e.clientY<rect.top+rect.height/2?'top':'bot';
      if(dragOverIdx!==i||dragOverSide!==side){clearDragOver();dragOverIdx=i;dragOverSide=side;el.classList.add(side==='top'?'drag-over-top':'drag-over-bot');}
    });
    el.addEventListener('dragleave',()=>clearDragOver());
    el.addEventListener('drop',e=>{
      e.preventDefault();const side=dragOverSide;clearDragOver();
      const insertAt=side==='top'?i:i+1;
      if(dragSrcType)insertBlock(dragSrcType,insertAt);
      else if(dragSrcIdx!==null&&dragSrcIdx!==i)reorderBlock(dragSrcIdx,insertAt);
    });
    inner.addEventListener('change',e=>{if(e.target.dataset.key)blk.params[e.target.dataset.key]=e.target.value;});
    inner.addEventListener('input', e=>{if(e.target.dataset.key)blk.params[e.target.dataset.key]=e.target.value;});
    dropZone.appendChild(el);
  });
  const pf=document.getElementById('prog-fill');
  pf.style.width=(state.running&&state.blocks.length>0)?(state.execIdx/state.blocks.length*100)+'%':'0%';
}
function addBlock(type,idx){const blk={id:blockIdCounter++,type,params:defaultParams(type)};if(idx===undefined)state.blocks.push(blk);else state.blocks.splice(idx,0,blk);renderBlocks();clog('블록 추가: '+type,'info');}
function insertBlock(t,i){addBlock(t,i);}
function removeBlock(idx){const t=state.blocks[idx]?.type??'';state.blocks.splice(idx,1);renderBlocks();clog('블록 삭제: '+t,'warn');}
function reorderBlock(from,to){const[blk]=state.blocks.splice(from,1);state.blocks.splice(to>from?to-1:to,0,blk);renderBlocks();}
const ghost=document.getElementById('drag-ghost');
document.querySelectorAll('.palette-block').forEach(pb=>{
  pb.addEventListener('dragstart',e=>{
    dragSrcType=pb.dataset.type;dragSrcIdx=null;
    const def=BLOCK_DEF[dragSrcType];
    ghost.className='palette-block '+def.cls;ghost.style.borderLeftColor=def.color;ghost.textContent=def.icon+' '+def.label;ghost.style.display='block';
    e.dataTransfer.effectAllowed='copy';
  });
  pb.addEventListener('dragend',()=>{dragSrcType=null;ghost.style.display='none';clearDragOver();});
});
document.addEventListener('dragover',e=>{if(dragSrcType){ghost.style.left=e.clientX+'px';ghost.style.top=e.clientY+'px';}});
const programArea=document.getElementById('program-area');
programArea.addEventListener('dragover',e=>{e.preventDefault();if(dragSrcType)document.getElementById('drop-placeholder').style.display='block';});
programArea.addEventListener('dragleave',e=>{if(!programArea.contains(e.relatedTarget))document.getElementById('drop-placeholder').style.display='none';});
programArea.addEventListener('drop',e=>{e.preventDefault();document.getElementById('drop-placeholder').style.display='none';ghost.style.display='none';if(dragSrcType)addBlock(dragSrcType);dragSrcType=null;});
function clearDragOver(){if(dragOverIdx!==null){const el=dropZone.querySelector('[data-idx="'+dragOverIdx+'"]');if(el)el.classList.remove('drag-over-top','drag-over-bot');}dragOverIdx=dragOverSide=null;}
function refreshWaypointPanel(){
  const list=document.getElementById('wp-list-r');
  const wps=state.waypoints;
  document.getElementById('wp-count').textContent='('+wps.length+')';
  if(wps.length===0){list.innerHTML='<div class="wp-empty">웨이포인트 없음 — 메인창에서 우클릭으로 저장</div>';return;}
  list.innerHTML='';
  wps.forEach((wp,i)=>{
    const chip=document.createElement('div');chip.className='wp-chip';
    chip.innerHTML='<div class="wp-chip-dot" style="background:'+wp.color+'"></div><span class="wp-chip-name">WP-'+String(i+1).padStart(2,'0')+'</span><span class="wp-chip-coord">X'+wp.wx.toFixed(1)+' Z'+wp.wz.toFixed(1)+'</span><span class="wp-chip-add" title="MoveL 추가">L＋</span><span class="wp-chip-addj" style="margin-left:3px;font-size:11px;color:#445;padding:0 2px;transition:color .12s;cursor:pointer;" title="MoveJ 추가">J＋</span>';
    chip.querySelector('.wp-chip-add').addEventListener('click',()=>{state.blocks.push({id:blockIdCounter++,type:'MoveL',params:{x:wp.wx.toFixed(3),z:wp.wz.toFixed(3),speed:'4',_j3:String(wp.j3??0)}});renderBlocks();clog('WP-'+(i+1)+' → MoveL 추가','ok');});
    chip.querySelector('.wp-chip-addj').addEventListener('click',()=>{const j1Deg=wp.j1!=null?(wp.j1*180/Math.PI).toFixed(1):'0';const j2Deg=wp.j2!=null?(wp.j2*180/Math.PI).toFixed(1):'180';state.blocks.push({id:blockIdCounter++,type:'MoveJ',params:{j1:j1Deg,j2:j2Deg,speed:'4',_j3:String(wp.j3??0)}});renderBlocks();clog('WP-'+(i+1)+' → MoveJ 추가','ok');});
    chip.querySelector('.wp-chip-addj').addEventListener('mouseover',e=>{e.target.style.color='#8877ff';});
    chip.querySelector('.wp-chip-addj').addEventListener('mouseout',e=>{e.target.style.color='#445';});
    list.appendChild(chip);
  });
}
function renderVars(){
  const list=document.getElementById('var-list');list.innerHTML='';
  Object.entries(state.vars).forEach(([name,val])=>{
    const row=document.createElement('div');row.className='var-item';
    row.innerHTML='<span class="var-item-name">'+esc(name)+'</span><span class="var-item-val">'+esc(val)+'</span><span class="var-item-del" data-name="'+esc(name)+'">✕</span>';
    row.querySelector('.var-item-del').addEventListener('click',()=>{delete state.vars[name];renderVars();});
    list.appendChild(row);
  });
}
document.getElementById('varAddBtn').addEventListener('click',()=>{
  const n=document.getElementById('varNameIn').value.trim();
  const v=document.getElementById('varValIn').value.trim()||'0';
  if(!/^[A-Za-z_][A-Za-z0-9_]{0,31}$/.test(n)||['__proto__','constructor','prototype'].includes(n))return;state.vars[n]=isNaN(+v)?v:+v;
  document.getElementById('varNameIn').value='';document.getElementById('varValIn').value='';
  renderVars();clog('변수 설정: '+n+' = '+state.vars[n],'info');
});
const logEl=document.getElementById('log-out');
function clog(msg,level){
  level=level||'info';
  const line=document.createElement('div');line.className='log-line log-'+level;
  line.textContent='['+new Date().toLocaleTimeString()+'] '+msg;
  logEl.appendChild(line);
  while(logEl.children.length>120)logEl.removeChild(logEl.firstChild);
  logEl.scrollTop=logEl.scrollHeight;
}
let execTimer=null;
function setStatus(msg,mode){mode=mode||'idle';document.getElementById('status-msg').textContent=msg;document.getElementById('status-dot').className='status-dot '+mode;}
function moveDelay(spd){return Math.max(200,Math.round(2200/Math.max(1,spd)));}
function postToMain(msg){try{if(window.opener&&!window.opener.closed)window.opener.postMessage(Object.assign({src:'scaraBlockEditor'},msg),location.origin==='null'?'*':location.origin);}catch(e){}}
let epoch=0, stepToken=null;
function finishProgram(isErr){
  state.running=false;state.waitingMove=false;state._resumeExec=null;clearTimeout(execTimer);epoch++;stepToken=null;
  document.getElementById('runBtn').classList.remove('running');
  document.getElementById('runBtn').textContent='▶ 실행';
  document.getElementById('prog-fill').style.width='0%';
  document.getElementById('status-step').textContent='';
  setStatus(isErr?'실행 중단':'실행 완료',isErr?'err':'idle');renderBlocks();
}
function stopProgram(){if(!state.running)return;postToMain({cmd:'Stop'});finishProgram(true);clog('프로그램 정지','warn');}
function runProgram(){
  if(state.running||!state.blocks.length)return;
  let runner;
  try{runner=new ScaraCore.ProgramRunner(state.blocks,state.vars);}catch(error){clog(error.message,'err');return;}
  const runEpoch=++epoch;state.running=true;state.waitingMove=false;
  document.getElementById('runBtn').classList.add('running');document.getElementById('runBtn').textContent='⏸ 실행 중';
  function exec(){
    if(!state.running||runEpoch!==epoch)return;
    try{
      const b=runner.step();renderVars();
      if(!b){finishProgram(false);postToMain({cmd:'programFinished'});return;}
      state.execIdx=b.index;renderBlocks();const p=b.params;
      setStatus(b.type+' 실행 중','run');clog(b.type,'info');
      if(b.type==='Stop'){postToMain({cmd:'Stop'});finishProgram(false);return;}
      if(b.type==='Wait'){
        const delay=ScaraCore.finite(p.sec,.1,3600)*1000;execTimer=setTimeout(exec,delay);return;
      }
      if(!['MoveL','MoveJ','MoveHome','Gripper'].includes(b.type))throw new Error('지원하지 않는 블록');
      const speed=ScaraCore.finite(p.speed??4,1,10);
      const message={cmd:b.type,speed,_j3:p._j3,token:'block-'+Date.now()+'-'+runEpoch+'-'+b.index+'-'+Math.random().toString(36).slice(2)};
      if(b.type==='MoveJ'){message.j1=ScaraCore.finite(p.j1,-360,360);message.j2=ScaraCore.finite(p.j2,-360,360);}
      if(b.type==='MoveL'){message.x=ScaraCore.finite(p.x);message.z=ScaraCore.finite(p.z);}
      if(b.type==='Gripper')message.action=p.action;
      stepToken=message.token;state.waitingMove=true;postToMain(message);
      execTimer=setTimeout(()=>{if(state.running&&runEpoch===epoch){postToMain({cmd:'Stop'});clog('이동 응답 시간 초과','err');finishProgram(true);}},190000);
    }catch(error){postToMain({cmd:'Stop'});clog(error.message,'err');finishProgram(true);}
  }
  state._resumeExec=exec;exec();
}
document.getElementById('runBtn').addEventListener('click',runProgram);
document.getElementById('stopBtn').addEventListener('click',stopProgram);
document.getElementById('exportBtn').addEventListener('click',()=>{
  const data={version:2,vars:state.vars,blocks:state.blocks.map(b=>({type:b.type,params:b.params}))};
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='scara_program.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);
  clog('내보내기 완료','ok');
});
window.addEventListener('message',function(e){
  if(e.source!==window.opener||e.origin!==location.origin||!e.data||e.data.src!=='scaraMain')return;
  if(e.data.cmd==='motionStopped'){if(state.running){clog(e.data.reason||'정지','warn');finishProgram(true);}return;}
  if(e.data.cmd==='moveComplete'){
    if(e.data.token===stepToken&&state.waitingMove&&state.running&&state._resumeExec){
      clearTimeout(execTimer);
      state.waitingMove=false;
      const currentEpoch=epoch;execTimer=setTimeout(()=>{if(currentEpoch===epoch)state._resumeExec();},80);
    }
    return;
  }
  if(e.data.cmd==='syncWaypoints'||e.data.cmd==='waypointAdded'){
    state.waypoints=e.data.waypoints||[];refreshWaypointPanel();
    if(e.data.cmd==='waypointAdded')clog('웨이포인트 동기화: '+state.waypoints.length+'개','info');
  }
});
(function drawGrid(){
  const cv=document.getElementById('canvas-bg');const ctx=cv.getContext('2d');
  function resize(){cv.width=cv.offsetWidth;cv.height=cv.offsetHeight;ctx.clearRect(0,0,cv.width,cv.height);ctx.strokeStyle='rgba(40,70,120,0.15)';ctx.lineWidth=1;for(let x=0;x<cv.width;x+=32){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,cv.height);ctx.stroke();}for(let y=0;y<cv.height;y+=32){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(cv.width,y);ctx.stroke();}}
  resize();window.addEventListener('resize',resize);
})();
renderBlocks();renderVars();
clog('SCARA Block Editor 준비 완료','ok');
clog('메인 창에서 웨이포인트를 저장하면 자동 동기화됩니다','info');
postToMain({cmd:'requestWaypoints'});
/* ── 조작 가이드 모달 ── */
(function(){
  const overlay=document.getElementById('help-overlay');
  const closeBtn=document.getElementById('help-modal-close');
  const hintBtn=document.getElementById('help-hint-btn');
  function openHelp(){overlay.classList.remove('hidden');}
  function closeHelp(){overlay.classList.add('hidden');}
  closeBtn.addEventListener('click',closeHelp);
  hintBtn.addEventListener('click',openHelp);
  overlay.addEventListener('click',e=>{if(e.target===overlay)closeHelp();});
  document.addEventListener('keydown',e=>{
    if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
    if(e.key.toLowerCase()==='i'){e.preventDefault();overlay.classList.contains('hidden')?openHelp():closeHelp();}
    if(e.key==='Escape')closeHelp();
  });
})();

window.addEventListener('pagehide',()=>{if(state.running)postToMain({cmd:'Stop'});clearTimeout(execTimer);},{once:true});
