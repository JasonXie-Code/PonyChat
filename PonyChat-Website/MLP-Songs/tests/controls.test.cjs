const test=require('node:test');
const assert=require('node:assert/strict');
const {keyboardAction,popupPlacement}=require('../web/controls.js');
const {tooltipPlacement}=require('../web/controls.js');
test('glass listbox keyboard navigation wraps, selects explicitly and cancels safely',()=>{
  assert.deepEqual(keyboardAction('ArrowDown',3,4),{type:'move',index:0});
  assert.deepEqual(keyboardAction('ArrowUp',0,4),{type:'move',index:3});
  assert.deepEqual(keyboardAction('Home',2,4),{type:'move',index:0});
  assert.deepEqual(keyboardAction('End',1,4),{type:'move',index:3});
  assert.deepEqual(keyboardAction('Enter',2,4),{type:'choose',index:2});
  assert.deepEqual(keyboardAction(' ',1,4),{type:'choose',index:1});
  assert.deepEqual(keyboardAction('Escape',2,4),{type:'close',restoreFocus:true});
  assert.deepEqual(keyboardAction('Tab',2,4),{type:'close',restoreFocus:true});
  assert.equal(keyboardAction('a',2,4),null);
});
for(const [w,h,r]of [[375,812,{left:250,top:28,bottom:62,width:74}],[328,200,{left:220,top:24,bottom:58,width:74}],[1280,900,{left:1170,top:790,bottom:824,width:74}]]){
  test(`glass listbox stays inside ${w}x${h} including bottom/right edges`,()=>{
    const p=popupPlacement(r,180,w,h);
    assert(p.left>=8 && p.top>=8);assert(p.left+p.width<=w-8);assert(p.top+p.height<=h-8);
    assert(p.height>0);if(h===900)assert(p.top<r.top);
  });
}
test('bottom player tooltip clears the entire button row, including its larger play button',()=>{
  const button={left:220,right:260,top:662,bottom:702,width:40,height:40};
  const row={left:120,right:320,top:650,bottom:708};
  const p=tooltipPlacement(button,80,32,1280,720,row);
  assert(p.top+32<=row.top-8);
  assert(p.left>=8 && p.left+80<=1272);
});
test('top controls place their tooltip below; tight vertical space uses a clear side',()=>{
  const top={left:240,right:280,top:8,bottom:48,width:40,height:40};
  const p=tooltipPlacement(top,100,32,320,240);
  assert(p.top>=top.bottom+8 && p.left+100<=312);
  const tall={left:40,right:80,top:10,bottom:70,width:40,height:60};
  const side=tooltipPlacement(tall,80,24,200,80);
  assert(side.left>=tall.right+8 && side.top>=8 && side.top+24<=72);
});
test('a tooltip with no unobstructed space is hidden instead of covering its button',()=>{
  const rect={left:8,right:168,top:8,bottom:72,width:160,height:64};
  assert.equal(tooltipPlacement(rect,40,20,176,80),null);
});
