/* Explicit typed-unpitched source-reading layout seam. No admission decisions. */
(function(root){
  'use strict';
  const PROFILE='typed-unpitched-common-source-reading-reference/v1';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const need=(v,m)=>{if(!v)throw Error(m);};
  function validate(data){
    need(data.profile===PROFILE&&data.sourceReadingOnly===true,'Explicit typed-unpitched profile required');
    need(data.normalAdmissionValidated===false&&data.formalAccepted===false,'Layout cannot grant normal admission');
    need(Array.isArray(data.entities)&&data.entities.length===data.physicalEntityCount,'Complete physical source inventory required');
    const ids=new Set(data.entities.map(e=>e.sourcePhysicalId));need(ids.size===data.entities.length,'Duplicate physical entity');
    const counts={pitch:0,rest:0,unpitched:0};
    for(const e of data.entities){
      need(['pitch','rest','unpitched'].includes(e.sourceKind),'Actual physical kind required');counts[e.sourceKind]++;
      need(e.isRest===(e.sourceKind==='rest')&&e.isUnpitched===(e.sourceKind==='unpitched'),'Physical kind changed');
      need(finite(e.sourceQuarter)&&finite(e.durationBeats)&&e.durationBeats>0,'Physical source rhythm required');
      if(e.sourceKind==='unpitched'){
        need(['x','circle-x'].includes(e.noteheadShape)&&e.sourceNotehead?.[0]?.text===e.noteheadShape,'Literal X/circle-X shape differs');
        need(['pitch','sourcePitch','midi','time','endTime','eventIndex'].every(k=>e[k]===null),'Unpitched acquired pitched field');
        need(e.seekAllowed===false&&e.cursorPrimary===false,'Unpitched acquired seek/primary');
        need(e.sourceUnpitchedDisplay?.tag==='unpitched','Display-only staff position missing');
      }else if(e.sourceKind==='rest'){
        need(['pitch','sourcePitch','midi','time','endTime','eventIndex','sourceReadingTime','sourceReadingEndTime'].every(k=>e[k]===null),'Rest acquired recording/reference fields');
        need(e.seekAllowed===false&&e.cursorPrimary===false,'Rest acquired seek/primary');
      }else need(typeof e.pitch==='string'&&Number.isInteger(e.midi),'Only pitched entities carry pitch/MIDI');
      if(data.readingCoordinatesValidated===false)need(e.sourceReadingTime===null&&e.sourceReadingEndTime===null,'Unsigned source acquired coordinate');
      else if(!e.isRest)need(finite(e.sourceReadingTime)&&finite(e.sourceReadingEndTime)&&e.sourceReadingTime<e.sourceReadingEndTime,'Reviewed coordinate interval invalid');
    }
    need(JSON.stringify(counts)===JSON.stringify({pitch:data.physicalCounts.pitch,rest:data.physicalCounts.rest,unpitched:data.physicalCounts.unpitched}),'Physical partition differs');
    const nested=data.measures.flatMap(m=>m.tokens),nids=new Set(nested.map(t=>t.sourcePhysicalId));
    need(nested.length===data.entities.length&&nids.size===ids.size&&[...ids].every(id=>nids.has(id)),'Flat/nested physical inventory differs');
    const by=new Map(data.entities.map(e=>[e.sourcePhysicalId,e]));
    need(nested.every(t=>JSON.stringify(t)===JSON.stringify(by.get(t.sourcePhysicalId))),'Flat/nested semantic payload differs');
    return counts;
  }
  function layout(data,width=1000,scale=1){
    validate(data);need(finite(width)&&width>=180&&finite(scale)&&scale>0,'Actual layout dimensions required');
    const rows=[],positions=new Map(),partOrder=data.sourceParts.map(p=>p.id);let y=0;
    for(const m of data.measures){
      const tokens=m.tokens;if(!tokens.length)continue;
      const lanes=[];
      for(const part of partOrder)for(const voice of [...new Set(tokens.filter(e=>e.sourcePart===part).map(e=>e.voice))])lanes.push({part,voice});
      need(lanes.length>0,'Every actual physical voice requires a lane');
      const beats=m.beatsPerMeasure||Math.max(...tokens.map(e=>e.beat+e.durationBeats));
      const q0=tokens[0].sourceQuarter-tokens[0].beat;
      need(tokens.every(e=>Math.abs((e.sourceQuarter-e.beat)-q0)<1e-6),'Source measure starts differ across voices');
      const minWidth=Math.max(width,80+tokens.length*24*scale);const left=62*scale,right=minWidth-22*scale;
      const h=(65+lanes.length*95)*scale,row={index:rows.length,measure:m.measure,q0,q1:q0+beats,left,right,width:minWidth,height:h,y,lanes};
      for(const e of tokens){
        const lane=lanes.findIndex(l=>l.part===e.sourcePart&&l.voice===e.voice),x=left+(e.beat+.18)/beats*(right-left);
        positions.set(e.sourcePhysicalId,{row:row.index,x,y:(88+lane*95)*scale,sourceQuarter:e.sourceQuarter,sourcePart:e.sourcePart});
      }
      rows.push(row);y+=h+14*scale;
    }
    return {rows,positions,height:y,data,scale};
  }
  function render(data,width=1000,scale=1,stock=root.TypedUnpitchedNumberedNotation){
    validate(data);need(stock?.profile===PROFILE,'Exact opt-in stock numbered renderer required');
    const rendered=stock.render(data,width,scale);return {...rendered,data,scale};
  }
  function readingPosition(data,nativeTime){
    validate(data);if(!data.readingCoordinatesValidated||!finite(nativeTime))return null;
    const nodes=data.commonClock;need(Array.isArray(nodes)&&nodes.length>1,'Reviewed common quarter clock required');
    // Native MP3 currentTime may truncate a requested double to microseconds.
    // Equate only an existing approved node, preserving the native clock itself.
    const near=nodes.filter(n=>Math.abs(n.time-nativeTime)<=3e-6);
    need(near.length<=1,'Ambiguous approved reading-node numerical equivalence');
    const readingTime=near.length?near[0].time:nativeTime;
    const active=data.entities.filter(e=>!e.isRest&&e.sourceReadingTime<=readingTime&&readingTime<e.sourceReadingEndTime);
    if(!active.length)return null;
    let i=1;while(i<nodes.length&&nodes[i].time<readingTime)i++;
    if(i===nodes.length)return null;
    const a=nodes[i-1],b=nodes[i];if(readingTime<a.time)return null;
    const q=a.sourceQuarter+(b.sourceQuarter-a.sourceQuarter)*(readingTime-a.time)/(b.time-a.time);
    return {sourceQuarter:q,activePhysicalIds:active.map(e=>e.sourcePhysicalId),activeIncludesUnpitched:active.some(e=>e.isUnpitched),seekablePhysicalIds:active.filter(e=>e.seekAllowed).map(e=>e.sourcePhysicalId)};
  }
  function cursorGeometry(rendered,position){
    if(!position)return null;const q=position.sourceQuarter,scale=rendered.scale;
    for(const row of rendered.geometry.rows)for(const fragment of row.fragments){
      const tokens=fragment.measure.tokens;if(!tokens.length)continue;
      const origin=tokens[0].sourceQuarter-tokens[0].beat,beat=q-origin;
      if(beat<fragment.start||beat>=fragment.end)continue;
      const ui=fragment.units.findIndex(u=>beat>=u.start&&beat<u.end),unit=fragment.units[ui];if(!unit)continue;
      const center=unit.x+unit.width/2,next=fragment.units[ui+1],nextCenter=next?next.x+next.width/2:fragment.x+fragment.width-8*scale;
      const x=center+(nextCenter-center)*(beat-unit.start)/(unit.end-unit.start);
      return {row:row.index,x,
        y1:row.y+30*scale,y2:row.y+row.height-10*scale,
        allSourceParts:[...new Set(row.fragments.flatMap(f=>f.measure.tokens.map(e=>e.sourcePart)))],
        allSourceVoices:[...new Set(row.fragments.flatMap(f=>f.measure.tokens.map(e=>`${e.sourcePart}:${e.voice}:${e.staff}`)))],lineCount:1};
    }
    return null;
  }
  function setCursor(container,rendered,nativeTime){
    return setCursorPosition(container,rendered,readingPosition(rendered.data,nativeTime));
  }
  // A complete-source controller already computes the approved common position.
  // Reuse it across displayed sections instead of revalidating every inactive one.
  function setCursorPosition(container,rendered,position){
    const svg=container.querySelector('.jp-svg');need(svg,'Actual opt-in rendered stock SVG required');
    let line=svg.querySelector('.typed-shared-reading-line');
    if(!line){line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('class','typed-shared-reading-line');line.setAttribute('stroke','#ad8aff');line.setAttribute('stroke-width','3');line.setAttribute('pointer-events','none');svg.appendChild(line);}
    line.setAttribute('hidden','');line.style.display='none';
    const geometry=cursorGeometry(rendered,position);if(!geometry)return null;
    for(const name of ['y1','y2'])line.setAttribute(name,geometry[name]);line.setAttribute('x1',geometry.x);line.setAttribute('x2',geometry.x);
    line.removeAttribute('hidden');line.style.display='';return position;
  }
  const api={PROFILE,validate,layout,render,readingPosition,cursorGeometry,setCursor,setCursorPosition};root.TypedUnpitchedSourceReadingLayout=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
