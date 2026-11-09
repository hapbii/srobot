const test=require('node:test'),assert=require('node:assert/strict');
const core=require('../scara_core.js');
test('exact FK/IK includes wrist angle across both branches',()=>{
  for(const flip of [false,true])for(const a of [-100,-20,40,130])for(const b of [30,90,150])for(const c of [-120,0,80]){
    const p={j1:a,j2:flip?-b:b,j3:c},tip=core.tip(p);
    const ik=core.solveTip(tip.x,tip.z,-c*core.RAD,flip);
    const result=core.tip({j1:-ik.theta1/core.RAD,j2:-ik.theta2/core.RAD,j3:c});
    assert.ok(Math.hypot(result.x-tip.x,result.z-tip.z)<1e-6);
  }
});
test('MoveL samples keep the tip on the Cartesian line',()=>{
  const from={x:1,z:1},to={x:2,z:1.5};
  for(let i=0;i<=100;i++){
    const t=i/100,x=from.x+(to.x-from.x)*t,z=from.z+(to.z-from.z)*t;
    const ik=core.solveTip(x,z,.4),actual=core.tip({j1:-ik.theta1/core.RAD,j2:-ik.theta2/core.RAD,j3:-.4/core.RAD});
    assert.ok(Math.hypot(actual.x-x,actual.z-z)<1e-6);
  }
});
const block=(type,params={})=>({type,params});
function execute(blocks){const runner=new core.ProgramRunner(blocks),out=[];for(let i=0;i<100;i++){const b=runner.step();if(!b)return out;out.push(b.type);}throw Error('infinite loop');}
test('legacy Loop repeats remainder exactly N times',()=>{
  assert.deepEqual(execute([block('Loop',{count:3}),block('MoveJ')]),['MoveJ','MoveJ','MoveJ']);
});
test('nested explicit loops and following statements',()=>{
  const out=execute([block('Loop',{count:2}),block('Loop',{count:3}),block('Wait'),block('EndLoop'),block('EndLoop'),block('MoveJ')]);
  assert.equal(out.filter(x=>x==='Wait').length,6);assert.equal(out.at(-1),'MoveJ');
});
test('If skips a complete loop and invalid loop structures fail',()=>{
  assert.deepEqual(execute([block('If',{var:'x',op:'>',val:0}),block('Loop',{count:3}),block('Wait'),block('EndLoop'),block('MoveJ')]),['MoveJ']);
  assert.throws(()=>new core.ProgramRunner([block('EndLoop')]));
});
test('SetVar cannot mutate object prototypes',()=>{
  const runner=new core.ProgramRunner([block('SetVar',{var:'__proto__',val:1})]);
  assert.throws(()=>runner.step());assert.equal({}.polluted,undefined);
});
test('a false If at the end of a loop cannot bypass the loop boundary',()=>{
  for(const ending of [[],[block('EndLoop')]]){
    const result=execute([block('Loop',{count:3}),block('Wait'),block('If',{var:'x',op:'>',val:0}),...ending]);
    assert.equal(result.length,3);
  }
});
test('input rejects nonfinite or out of bounds values',()=>{
  for(const n of [NaN,Infinity,-Infinity,''])assert.throws(()=>core.finite(n));
  assert.throws(()=>core.validatePose({j1:0,j2:180,j3:181}));
});
test('disposing ghosts preserves borrowed geometry',()=>{
  let geometries=0,materials=0;
  const shared={dispose(){geometries++;}},mat={dispose(){materials++;}};
  const root={traverse(fn){fn({geometry:shared,material:mat});fn({geometry:shared,material:mat});},clear(){}};
  for(let i=0;i<100;i++)core.disposeObject(root,{geometry:false});
  assert.equal(geometries,0);assert.equal(materials,100);
  core.disposeObject(root);assert.equal(geometries,1);assert.equal(materials,101);
});
