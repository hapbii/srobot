'use strict';
(() => {
  let blockWin=null;
  const origin=location.origin==='null'?'*':location.origin;
  function sync(){
    if(blockWin&&!blockWin.closed)blockWin.postMessage({src:'scaraMain',cmd:'syncWaypoints',waypoints:window.__scaraWaypoints||[]},origin);
  }
  byId('blockCodingBtn').addEventListener('click',()=>{
    if(blockWin&&!blockWin.closed){blockWin.focus();sync();return;}
    blockWin=window.open(new URL('block_editor.html',location.href).href,'scaraBlockEditor',
      'width=1100,height=720,resizable=yes,scrollbars=yes');
    if(!blockWin){alert('블록 편집기를 열려면 팝업을 허용하세요.');return;}
    window.__scaraBlockWin=blockWin;
  });
  function onMessage(event){
    if(!blockWin||event.source!==blockWin||event.origin!==location.origin||event.data?.src!=='scaraBlockEditor')return;
    const d=event.data;
    if(d.cmd==='requestWaypoints'){sync();return;}
    if(['Stop','programFinished'].includes(d.cmd)){stopAll('블록 프로그램 정지');delete window.__scaraBlockMoveToken;return;}
    if(!['MoveL','MoveJ','MoveHome','Gripper'].includes(d.cmd))return;
    try{
      if(homing)throw new Error('원점 탐색 중입니다');
      if(!window.ScaraScene)throw new Error('3D 화면 로딩 중입니다');
      if(typeof d.token!=='string'||d.token.length>80)throw new Error('명령 식별자 오류');
      const speed=ScaraCore.finite(d.speed??4,1,10);
      if(d._j3!=null&&d._j3!=='')ScaraCore.finite(d._j3,-Math.PI,Math.PI);
      const cmd={speed,_j3:d._j3};
      if(d.cmd==='MoveJ'){
        cmd.j1=ScaraCore.finite(d.j1,-360,360)*Math.PI/180;
        cmd.j2=ScaraCore.finite(d.j2,-360,360)*Math.PI/180;
      }else if(d.cmd==='MoveL'){
        cmd.x=ScaraCore.finite(d.x);cmd.z=ScaraCore.finite(d.z);
      }else if(d.cmd==='Gripper'){
        if(!['open','close'].includes(d.action))throw new Error('그리퍼 명령 오류');
        cmd.action=d.action;
      }
      window.__scaraBlockMoveToken=d.token;
      controller.start();updateControlUI();window['__scara'+d.cmd+'Cmd']=cmd;
    }catch(error){stopAll(error.message);log(error.message,'#ff6666');}
  }
  window.addEventListener('message',onMessage);
  const observer=new MutationObserver(sync);
  observer.observe(byId('wpList'),{childList:true});
  // Closing the editor while a program runs cancels the main motion too.
  const closeCheck=setInterval(()=>{
    if(blockWin?.closed){if(window.__scaraBlockMoveToken)stopAll('블록 편집기 종료');blockWin=null;delete window.__scaraBlockWin;delete window.__scaraBlockMoveToken;}
  },500);
  window.addEventListener('pagehide',()=>{
    observer.disconnect();clearInterval(closeCheck);window.removeEventListener('message',onMessage);
    if(blockWin&&!blockWin.closed)blockWin.close();blockWin=null;
  },{once:true});
})();
