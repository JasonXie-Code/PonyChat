/* Explicit occurrence mechanics + site-styled choice requests. No admission/audio writes. */
(function(root){
  'use strict';
  const PROFILE='complete-original-ensemble-occurrence-reading-reference/v1';
  const SCHEMA='mechanical-complete-ensemble-occurrence-layout/v1';
  const need=(v,m)=>{if(!v)throw Error(m);};
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const gcd=(a,b)=>{a=a<0n?-a:a;while(b){const t=b;b=a%b;a=t;}return a||1n;};
  function fraction(n,d=1n){need(d!==0n,'Zero fraction denominator');if(d<0n){n=-n;d=-d;}const g=gcd(n,d);return {n:n/g,d:d/g};}
  function parse(value){
    need(typeof value==='string'||finite(value),'Explicit rational coordinate required');
    const text=String(value),ratio=/^([+-]?\d+)\/(\d+)$/.exec(text);
    if(ratio)return fraction(BigInt(ratio[1]),BigInt(ratio[2]));
    const m=/^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text);
    need(m,'Invalid rational/decimal');const exponent=Number(m[4]||0)-(m[3]||'').length;
    need(Number.isInteger(exponent)&&Math.abs(exponent)<=1000,'Coordinate exponent exceeds bound');
    const n=BigInt((m[1]==='-'?'-':'')+m[2]+(m[3]||''));
    return exponent<0?fraction(n,10n**BigInt(-exponent)):fraction(n*10n**BigInt(exponent));
  }
  const add=(a,b)=>fraction(a.n*b.d+b.n*a.d,a.d*b.d);
  const sub=(a,b)=>fraction(a.n*b.d-b.n*a.d,a.d*b.d);
  const mul=(a,b)=>fraction(a.n*b.n,a.d*b.d);
  const div=(a,b)=>fraction(a.n*b.d,a.d*b.n);
  const compare=(a,b)=>a.n*b.d<b.n*a.d?-1:a.n*b.d>b.n*a.d?1:0;
  const numeric=a=>Number(a.n)/Number(a.d);
  const text=a=>a.d===1n?String(a.n):`${a.n}/${a.d}`;
  function coordinate(row,name){
    const f=row[name+'Fraction'];if(f===undefined)return parse(row[name]);
    const exact=parse(f),shown=row[name];
    need((finite(shown)&&shown===numeric(exact))||(typeof shown==='string'&&compare(parse(shown),exact)===0),'Fraction/display mismatch');
    return exact;
  }
  const eq=(a,b)=>compare(a,b)===0;
  const clone=v=>JSON.parse(JSON.stringify(v));
  function freeze(v){if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;}
  function validate(data){
    need(data?.schema===SCHEMA&&data.profile===PROFILE&&data.referenceOnly===true,'Explicit occurrence layout required');
    need(data.requiresIndependentNormalAuthority===true&&data.normalAdmissionValidated===false&&data.clockApproved===false
      &&data.RootModelApproved===false&&data.normalUIApproved===false&&data.formalAccepted===false&&data.seekRequestsOnly===true
      &&data.actualAudioClockAssignedByThisModule===false,
      'Mechanical helper cannot grant normal authority');
    need(['approved','sourceApproved','physicalPerformanceGold','isolatedSingerPitchAttackReleaseGold'].every(k=>data[k]===undefined||data[k]===false),
      'Mechanical helper cannot grant approval or performance Gold');
    const physical=data.physicalSource,instances=data.instances,visits=data.visits,curves=data.curves;
    need(Array.isArray(physical)&&physical.length===data.physicalEntityCount&&Array.isArray(instances)&&instances.length>0,'Complete physical/instance inventories required');
    const by=new Map(physical.map(e=>[e.sourcePhysicalId,e]));need(by.size===physical.length,'Duplicate physical source');
    const counts={pitch:0,rest:0,unpitched:0};
    for(const e of physical){need(Object.hasOwn(counts,e.sourceKind),'Unknown physical source kind');counts[e.sourceKind]++;
      need(['time','endTime','eventIndex'].every(k=>e[k]===null)&&e.seekAllowed===false,'Physical row acquired occurrence time/seek');
      need(compare(coordinate(e,'sourceQuarter'),coordinate(e,'sourceQuarterEnd'))<0&&e.nativePoint
        &&finite(e.nativePoint.x)&&finite(e.nativePoint.y)&&e.nativeInkBounds&&['x','y','width','height'].every(k=>finite(e.nativeInkBounds[k]))
        &&e.nativeInkBounds.width>0&&e.nativeInkBounds.height>0,'Physical native geometry invalid');}
    need(Object.keys(counts).every(k=>counts[k]===data.physicalCounts[k]),'Physical partition differs');
    need(Array.isArray(visits)&&Array.isArray(curves)&&visits.length===curves.length&&visits.length>0,'Complete visit curves required');
    need(new Set(visits.map(v=>v.visitId)).size===visits.length,'Duplicate visit');
    const occurrences=new Set(),eventIndices=[];
    for(const e of instances){const p=by.get(e.sourcePhysicalId);need(p&&p.sourceKind!=='rest'&&p.sourceKind===e.sourceKind
      &&p.sourcePart===e.sourcePart&&p.pitch===e.pitch&&!occurrences.has(e.occurrenceId),'Invalid/repeated occurrence or timed rest');
      occurrences.add(e.occurrenceId);need(finite(e.sourceReadingTime)&&finite(e.sourceReadingEndTime)&&e.sourceReadingEndTime>e.sourceReadingTime,'Occurrence interval invalid');
      need(e.physicalPerformanceGold===false&&e.noteAttackGold===false,'Occurrence acquired physical performance Gold');
      need(eq(coordinate(p,'sourceQuarter'),coordinate(e,'sourceQuarter'))&&eq(coordinate(p,'sourceQuarterEnd'),coordinate(e,'sourceQuarterEnd')),'Occurrence changed printed coordinate');
      if(e.sourceKind==='unpitched')need(['pitch','midi','time','endTime','eventIndex'].every(k=>e[k]===null)&&e.seekAllowed===false,'X gained pitch/event/seek');
      else {need(e.time===e.sourceReadingTime&&e.endTime===e.sourceReadingEndTime&&Number.isInteger(e.eventIndex),'Pitched reading tuple differs');eventIndices.push(e.eventIndex);}
    }
    need(eventIndices.every((n,i)=>n===i),'Missing/duplicated pitched event index');
    for(let i=0;i<visits.length;i++){
      const v=visits[i],c=curves[i],a=coordinate(v,'sourceStart'),b=coordinate(v,'sourceEnd'),p=coordinate(v,'performanceStart'),z=coordinate(v,'performanceEnd');
      need(c.visitId===v.visitId&&compare(a,b)<0&&eq(sub(z,p),sub(b,a)),'Visit identity/length differs');
      if(i){const prior=visits[i-1];need(eq(p,coordinate(prior,'performanceEnd')),'Performance visit gap/overlap');
        const jumping=!eq(a,coordinate(prior,'sourceEnd'));need(jumping?['DS','DC','ToCoda','repeat','reviewed-jump'].includes(v.incomingEdge):v.incomingEdge==='continue','Undeclared navigation edge');
        if(jumping)need(Array.isArray(v.navigationEvidenceSha256s)&&v.navigationEvidenceSha256s.length
          &&v.navigationEvidenceSha256s.every(s=>/^[a-f0-9]{64}$/.test(s)),'Navigation evidence locator missing');
        need(c.nodes[0].time>=curves[i-1].nodes.at(-1).time,'Overlapping visit clocks');}
      else need(v.incomingEdge==='start'&&eq(p,parse(0)),'Visit origin invalid');
      const events=instances.filter(e=>e.visitId===v.visitId),expected=new Set([text(p),text(z)]);
      const members=physical.filter(e=>compare(a,coordinate(e,'sourceQuarter'))<=0&&compare(coordinate(e,'sourceQuarter'),b)<0);
      need(!physical.some(e=>compare(coordinate(e,'sourceQuarter'),a)<0&&compare(a,coordinate(e,'sourceQuarterEnd'))<0)
        &&members.every(e=>compare(coordinate(e,'sourceQuarterEnd'),b)<=0),'Visit bisects physical source');
      const nonrests=members.filter(e=>e.sourceKind!=='rest');
      need(events.length===nonrests.length&&nonrests.every(e=>events.some(i=>i.sourcePhysicalId===e.sourcePhysicalId)),
        'Visit omitted or duplicated an actual nonrest occurrence');
      for(const e of events){expected.add(text(coordinate(e,'performanceQuarter')));expected.add(text(coordinate(e,'performanceQuarterEnd')));
        need(eq(coordinate(e,'performanceQuarter'),add(p,sub(coordinate(e,'sourceQuarter'),a)))
          &&eq(coordinate(e,'performanceQuarterEnd'),add(p,sub(coordinate(e,'sourceQuarterEnd'),a))),'Occurrence projection differs');}
      need(c.nodes.length===expected.size,'Missing occurrence clock boundary');const seen=new Set(),times=new Map();
      for(let j=0;j<c.nodes.length;j++){const n=c.nodes[j],pq=coordinate(n,'performanceQuarter'),key=text(pq);
        need(expected.has(key)&&!seen.has(key)&&finite(n.time)&&n.time>=0&&n.time<=data.nativeDuration
          &&finite(n.uncertaintySeconds)&&n.uncertaintySeconds>=0,'Invalid/unbound clock node');seen.add(key);times.set(key,n.time);
        if(j)need(n.time>c.nodes[j-1].time&&compare(pq,coordinate(c.nodes[j-1],'performanceQuarter'))>0,'Collapsed/backward clock');}
      need(eq(coordinate(c.nodes[0],'performanceQuarter'),p)&&eq(coordinate(c.nodes.at(-1),'performanceQuarter'),z),'Incomplete visit curve');
      for(const e of events)need(times.get(text(coordinate(e,'performanceQuarter')))===e.sourceReadingTime
        &&times.get(text(coordinate(e,'performanceQuarterEnd')))===e.sourceReadingEndTime,'Occurrence clock identity differs');
    }
    need(instances.every(e=>visits.some(v=>v.visitId===e.visitId)),'Occurrence points to missing visit');
    need(finite(data.nativeDuration)&&data.nativeDuration>0&&data.musicActiveUntilTime===curves.at(-1).nodes.at(-1).time,'Terminal/native duration differs');
    need(Array.isArray(data.sourceKeyPlan)&&data.sourceKeyPlan.length&&eq(coordinate(data.sourceKeyPlan[0],'sourceQuarter'),parse(0)),
      'Source tonic origin required');
    for(let i=0;i<data.sourceKeyPlan.length;i++){const z=data.sourceKeyPlan[i];need(/^[A-G](?:#{1,2}|b{1,2})?$/.test(z.tonic)
      &&(!i||compare(coordinate(data.sourceKeyPlan[i-1],'sourceQuarter'),coordinate(z,'sourceQuarter'))<0),'Printed tonic plan invalid');}
    const covered=new Set();
    for(const s of data.sourceSystems){need(s.actualSourceParts.length&&new Set(s.physicalIds).size===s.physicalIds.length,'Original system inventory invalid');
      const members=physical.filter(p=>s.firstMeasure<=p.measure&&p.measure<=s.lastMeasure),ids=new Set(members.map(p=>p.sourcePhysicalId));
      need(ids.size===s.physicalIds.length&&s.physicalIds.every(id=>ids.has(id)&&!covered.has(id)),'Source system coverage differs');s.physicalIds.forEach(id=>covered.add(id));
      const parts=data.sourceParts.map(p=>p.id).filter(p=>members.some(e=>e.sourcePart===p));
      need(JSON.stringify(parts)===JSON.stringify(s.actualSourceParts),'Original printed part hidden');
      need(parts.every(p=>s.staffLines[p]?.length===5&&Math.min(...s.staffLines[p])>=s.wholeSourcePartsBounds.top
        &&Math.max(...s.staffLines[p])<=s.wholeSourcePartsBounds.bottom),'Long line truncates an original staff');}
    need(covered.size===physical.length,'Source system omitted physical entity');
    const bars=new Set();for(const m of data.measureBounds){const owner=data.sourceSystems.filter(s=>s.sourceSystemId===m.sourceSystemId
      &&s.firstMeasure<=m.measure&&m.measure<=s.lastMeasure&&s.actualSourceParts.includes(m.part));
      const key=m.part+':'+m.measure;need(owner.length===1&&!bars.has(key)&&finite(m.x0)&&finite(m.x1)&&m.x0<m.x1
        &&compare(coordinate(m,'sourceQuarterStart'),coordinate(m,'sourceQuarterEnd'))<0,'Printed bar interval invalid');bars.add(key);}
    const expectedBars=new Set(physical.map(p=>p.sourcePart+':'+p.measure));
    need(bars.size===expectedBars.size&&[...expectedBars].every(k=>bars.has(k)),'Printed bar coverage incomplete');return true;
  }
  function createReader(input){
    const data=freeze(clone(input));validate(data);const by=new Map(data.physicalSource.map(p=>[p.sourcePhysicalId,p]));
    function instancesForSource(id){return data.instances.filter(e=>e.sourcePhysicalId===id).map(clone).sort((a,b)=>a.sourceReadingTime-b.sourceReadingTime);}
    function position(nativeTime){
      need(finite(nativeTime)&&nativeTime>=0,'Invalid actual native time');if(nativeTime>=data.nativeDuration)return null;
      const near=[...new Set(data.curves.flatMap(c=>c.nodes.filter(n=>Math.abs(n.time-nativeTime)<=3e-6).map(n=>n.time)))];
      need(near.length<=1,'Ambiguous numerical reading-node equivalence');const time=near.length?near[0]:nativeTime;
      if(time>=data.musicActiveUntilTime)return null;
      const index=data.curves.findIndex(c=>c.nodes[0].time<=time&&time<c.nodes.at(-1).time);if(index<0)return null;
      const v=data.visits[index],nodes=data.curves[index].nodes;let i=1;while(nodes[i].time<=time)i++;
      const a=nodes[i-1],b=nodes[i],ratio=div(sub(parse(time),parse(a.time)),sub(parse(b.time),parse(a.time)));
      const pq=add(coordinate(a,'performanceQuarter'),mul(ratio,sub(coordinate(b,'performanceQuarter'),coordinate(a,'performanceQuarter'))));
      const sq=add(coordinate(v,'sourceStart'),sub(pq,coordinate(v,'performanceStart')));
      const active=data.instances.filter(e=>e.visitId===v.visitId&&e.sourceReadingTime<=time&&time<e.sourceReadingEndTime);if(!active.length)return null;
      const zones=data.sourceKeyPlan.filter(z=>compare(coordinate(z,'sourceQuarter'),sq)<=0);need(zones.length,'No printed tonic');
      return {visitId:v.visitId,performanceQuarter:numeric(pq),performanceQuarterFraction:text(pq),sourceQuarter:numeric(sq),sourceQuarterFraction:text(sq),
        actualNativeTime:nativeTime,readingCoordinateTime:time,localTonic:zones.at(-1).tonic,
        activeOccurrenceIds:active.map(e=>e.occurrenceId),activePhysicalIds:active.map(e=>e.sourcePhysicalId),
        activeSourceParts:[...new Set(active.map(e=>e.sourcePart))].sort(),activeUnpitchedOccurrenceIds:active.filter(e=>e.sourceKind==='unpitched').map(e=>e.occurrenceId),
        commonReadingLineCount:1,mechanicalOnly:true,normalAdmissionValidated:false};
    }
    function lineGeometry(pos){
      if(!pos)return null;const q=coordinate(pos,'sourceQuarter');
      const systems=data.sourceSystems.filter(s=>compare(coordinate(s,'sourceQuarterStart'),q)<=0&&compare(q,coordinate(s,'sourceQuarterEnd'))<0);
      need(systems.length===1,'Printed system coordinate ambiguous');const s=systems[0];
      const intervals=data.measureBounds.filter(m=>m.sourceSystemId===s.sourceSystemId&&compare(coordinate(m,'sourceQuarterStart'),q)<=0&&compare(q,coordinate(m,'sourceQuarterEnd'))<0);
      need(intervals.length,'Actual printed measure interval missing');const m=intervals[0];
      const columns=new Map();for(const id of s.physicalIds){const p=by.get(id);if(p.sourceKind==='rest'||p.measure!==m.measure)continue;
        const key=p.sourceQuarterFraction;if(!columns.has(key))columns.set(key,[]);columns.get(key).push(p.nativePoint.x);}
      const anchors=[{q:coordinate(m,'sourceQuarterStart'),x:m.x0},...Array.from(columns,([q,xs])=>({q:parse(q),x:xs.reduce((a,b)=>a+b,0)/xs.length})),
        {q:coordinate(m,'sourceQuarterEnd'),x:m.x1}].sort((a,b)=>compare(a.q,b.q));
      const unique=[];for(const a of anchors){if(unique.length&&eq(unique.at(-1).q,a.q))unique[unique.length-1]=a;else unique.push(a);}
      let i=1;while(i<unique.length&&compare(unique[i].q,q)<=0)i++;const a=unique[Math.max(0,i-1)],b=unique[Math.min(i,unique.length-1)];
      const ratio=eq(a.q,b.q)?0:numeric(div(sub(q,a.q),sub(b.q,a.q)));const x=a.x+(b.x-a.x)*ratio;
      return {sourceSystemId:s.sourceSystemId,printedMeasure:m.measure,sourceQuarter:pos.sourceQuarter,
        xNative:x,topNative:s.wholeSourcePartsBounds.top,bottomNative:s.wholeSourcePartsBounds.bottom,
        allSourceParts:[...s.actualSourceParts],lineCount:1,normalUIApproved:false};
    }
    function seekRequest(physicalId,occurrenceId){
      const p=by.get(physicalId),e=data.instances.find(e=>e.occurrenceId===occurrenceId&&e.sourcePhysicalId===physicalId);
      need(p?.sourceKind==='pitch'&&e?.sourceKind==='pitch','Explicit pitched occurrence required; rest/X cannot seek');
      return {kind:'explicit-occurrence-seek-request/v1',profile:PROFILE,sourcePhysicalId:physicalId,occurrenceId:e.occurrenceId,visitId:e.visitId,
        eventIndex:e.eventIndex,time:e.time,requiresIndependentNormalAuthority:true,normalAdmissionValidated:false};
    }
    return Object.freeze({profile:PROFILE,position,lineGeometry,instancesForSource,seekRequest,physicalIds:()=>[...by.keys()]});
  }
  function openOccurrenceMenu(document,trigger,reader,physicalId,onExplicitRequest){
    const choices=reader.instancesForSource(physicalId).filter(e=>e.sourceKind==='pitch');need(choices.length,'No pitched occurrence choices');
    const menu=document.createElement('div');menu.className='ensemble-occurrence-menu';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','选择演唱次数');
    const close=()=>{menu.remove();trigger.focus?.();};
    choices.forEach((e,index)=>{const button=document.createElement('button');button.type='button';button.dataset.occurrenceId=e.occurrenceId;
      button.textContent=`第 ${index+1} 次 · ${e.time.toFixed(2)} 秒`;button.setAttribute('aria-label',`第${index+1}次演唱`);
      button.addEventListener('click',event=>{if(event.isTrusted!==true)return;const request=reader.seekRequest(physicalId,e.occurrenceId);close();onExplicitRequest(request);});menu.appendChild(button);});
    menu.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
    document.body.appendChild(menu);const rect=trigger.getBoundingClientRect(),view=document.defaultView;
    const width=menu.getBoundingClientRect().width||180,height=menu.getBoundingClientRect().height||160;
    menu.style.left=Math.max(12,Math.min(rect.left,view.innerWidth-width-12))+'px';
    menu.style.top=Math.max(12,Math.min(rect.bottom+8,view.innerHeight-height-12))+'px';
    menu.querySelector('button')?.focus();return {element:menu,close};
  }
  const bindings=new WeakMap();
  function bindPhysicalTargets(container,reader,onExplicitRequest){
    bindings.get(container)?.dispose();
    const seen=new Set(),ids=new Set(reader.physicalIds()),listeners=[];let menu=null;
    for(const node of container.querySelectorAll('[data-source-id],.jp-note[data-id]')){
      const id=node.dataset.sourceId||node.dataset.id;if(!ids.has(id))continue;
      for(const field of ['data-time','data-event-index','data-occurrence-id','tabindex'])node.removeAttribute(field);
      const candidates=reader.instancesForSource(id).filter(e=>e.sourceKind==='pitch');
      if(node.dataset.sourceFragment==='continuation'||seen.has(id)||!candidates.length){node.setAttribute('role','img');continue;}
      seen.add(id);node.setAttribute('role','button');node.setAttribute('tabindex','0');
      const activate=event=>{if(event.isTrusted!==true)return;event.preventDefault();menu?.close();
        if(candidates.length===1)onExplicitRequest(reader.seekRequest(id,candidates[0].occurrenceId));
        else menu=openOccurrenceMenu(node.ownerDocument,node,reader,id,onExplicitRequest);};
      const keydown=event=>{if(event.key==='Enter')activate(event);};
      node.addEventListener('keydown',keydown);node.addEventListener('dblclick',activate);
      listeners.push(()=>{node.removeEventListener('keydown',keydown);node.removeEventListener('dblclick',activate);});
    }
    const result={nativePhysicalTargets:seen.size,close:()=>menu?.close(),dispose:()=>{
      menu?.close();listeners.forEach(remove=>remove());if(bindings.get(container)===result)bindings.delete(container);}};
    bindings.set(container,result);return result;
  }
  const api={PROFILE,SCHEMA,validate,createReader,openOccurrenceMenu,bindPhysicalTargets};root.EnsembleOccurrenceReading=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
