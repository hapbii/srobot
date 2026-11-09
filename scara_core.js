/* Pure geometry, program execution, and ownership helpers (browser + Node). */
(function (root) {
  'use strict';
  const AXES = ['j1', 'j2', 'j3'];
  const HOME = Object.freeze({j1: 0, j2: 180, j3: 0});
  const RAD = Math.PI / 180;
  function finite(value, min = -Infinity, max = Infinity) {
    const n = Number(value);
    if (value === '' || !Number.isFinite(n) || n < min || n > max) throw new Error('유효한 범위의 숫자를 입력하세요');
    return n;
  }
  function validatePose(p) {
    return {j1: finite(p.j1, -360, 360), j2: finite(p.j2, -360, 360), j3: finite(p.j3, -180, 180)};
  }
  function tip(p, l1=2, l2=2.105, grip=.35) {
    const a=-p.j1*RAD, b=-p.j2*RAD, c=-p.j3*RAD;
    return {x:l1*Math.cos(a)+l2*Math.cos(a+b)+grip*Math.cos(a+b+c),
            z:l1*Math.sin(a)+l2*Math.sin(a+b)+grip*Math.sin(a+b+c)};
  }
  function solveTip(x, z, j3=0, flip=false, l1=2, l2=2.105, grip=.35) {
    finite(x); finite(z); finite(j3, -Math.PI, Math.PI);
    // Fold the wrist extension into an effective second link; exact for fixed J3.
    const bx=l2+grip*Math.cos(j3), bz=grip*Math.sin(j3);
    const length=Math.hypot(bx,bz), offset=Math.atan2(bz,bx), d=Math.hypot(x,z);
    const min=Math.abs(l1-length)+1e-8, max=l1+length-1e-8;
    const radius=Math.max(min,Math.min(max,d));
    const heading=d>1e-10?Math.atan2(z,x):0;
    const cx=radius*Math.cos(heading), cz=radius*Math.sin(heading);
    const q2=(flip?1:-1)*Math.acos(Math.max(-1,Math.min(1,(radius*radius-l1*l1-length*length)/(2*l1*length))));
    const q1=heading-Math.atan2(length*Math.sin(q2),l1+length*Math.cos(q2));
    return {theta1:q1,theta2:q2-offset,clampedX:cx,clampedZ:cz,status:Math.abs(radius-d)>1e-6?'unreachable':'ok'};
  }
  function nearest(angle, reference) {
    return angle + Math.round((reference-angle)/(Math.PI*2))*Math.PI*2;
  }
  function disposeObject(root, {geometry=true, materials=true, textures=false}={}) {
    const gs=new Set(), ms=new Set(), ts=new Set();
    root.traverse(obj=>{
      if(geometry && obj.geometry)gs.add(obj.geometry);
      if(materials)(Array.isArray(obj.material)?obj.material:[obj.material]).filter(Boolean).forEach(m=>ms.add(m));
    });
    for(const m of ms) {
      if(textures)for(const v of Object.values(m))if(v?.isTexture)ts.add(v);
      m.dispose();
    }
    gs.forEach(g=>g.dispose());ts.forEach(t=>t.dispose());
    root.clear();
  }
  class ProgramRunner {
    constructor(blocks, vars={}) {
      this.blocks=blocks.map(b=>({type:b.type,params:{...b.params}}));
      this.vars=vars;this.index=0;this.stack=[];this.ends=new Map();
      const starts=[];
      this.blocks.forEach((b,i)=>{
        if(b.type==='Loop')starts.push(i);
        if(b.type==='EndLoop'){
          if(!starts.length)throw new Error('EndLoop 앞에 Loop가 필요합니다');
          this.ends.set(starts.pop(),i);
        }
      });
      // Existing programs used a Loop with no terminator: repeat the remainder.
      if(starts.length>1)throw new Error('중첩 Loop에는 EndLoop가 필요합니다');
      if(starts.length)this.ends.set(starts[0],this.blocks.length);
    }
    step() {
      for(let guard=0;guard<10000;guard++) {
        const top=this.stack[this.stack.length-1];
        if(top && this.index===top.end) {
          if(--top.remaining>0)this.index=top.start+1;
          else {this.stack.pop();if(top.end<this.blocks.length)this.index++;}
          continue;
        }
        if(this.index>=this.blocks.length)return null;
        const i=this.index++,b=this.blocks[i],p=b.params;
        if(b.type==='Loop') {
          const count=Number(p.count);
          if(!Number.isInteger(count)||count<1||count>10000)throw new Error('반복 횟수: 1~10000 정수');
          this.stack.push({start:i,end:this.ends.get(i),remaining:count});continue;
        }
        if(b.type==='EndLoop')throw new Error('잘못된 반복 범위');
        if(b.type==='If') {
          const lhs=this.vars[p.var]??0,rhs=Number.isFinite(Number(p.val))?Number(p.val):p.val;
          const ok=p.op==='>'?lhs>rhs:p.op==='<'?lhs<rhs:p.op==='=='?lhs==rhs:lhs!=rhs;
          if(!ok){
            const skipped=this.index;
            // A condition skips executable blocks, never a structural loop end.
            if(!(top && skipped===top.end))
              this.index=this.blocks[skipped]?.type==='Loop'?this.ends.get(skipped)+1:skipped+1;
          }
          continue;
        }
        if(b.type==='SetVar') {
          if(!/^[A-Za-z_][A-Za-z0-9_]{0,31}$/.test(p.var)||['__proto__','constructor','prototype'].includes(p.var))throw new Error('변수 이름 오류');
          this.vars[p.var]=Number.isFinite(Number(p.val))?Number(p.val):String(p.val);continue;
        }
        return {index:i,type:b.type,params:p};
      }
      throw new Error('실행 단계 제한을 초과했습니다');
    }
  }
  const api={AXES,HOME,RAD,finite,validatePose,tip,solveTip,nearest,disposeObject,ProgramRunner};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.ScaraCore=api;
})(typeof globalThis!=='undefined'?globalThis:window);
