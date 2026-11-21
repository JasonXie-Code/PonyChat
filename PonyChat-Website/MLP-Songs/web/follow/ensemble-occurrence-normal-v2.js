/* V2 chord-aware genuine occurrence candidate controller. Never chooses an occurrence implicitly. */
(function(root){
  'use strict';
  const H=root.EnsembleOccurrenceReading,need=(v,m)=>{if(!v)throw Error(m);};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone=v=>JSON.parse(JSON.stringify(v));
  function displayToken(t){
    if(t.sourceKind==='rest')return '0';if(t.sourceKind==='unpitched')return '0';
    need(Number.isInteger(t.degree)&&t.degree>=1&&t.degree<=7&&Number.isInteger(t.octave),'Structured jianpu pitch required');
    const acc=({'♯':'#','♭':'b','𝄪':'##','𝄫':'bb','♮':''})[t.accidental]??t.accidental??'';
    need(['','b','bb','#','##'].includes(acc),'Unknown source accidental');
    return acc+t.degree+(t.octave>0?"'".repeat(t.octave):','.repeat(-t.octave));
  }
  async function digest(text){return Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256',typeof text==='string'?new TextEncoder().encode(text):text)))
    .map(b=>b.toString(16).padStart(2,'0')).join('');}
  const ordered=v=>Array.isArray(v)?v.map(ordered):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,ordered(v[k])])):v;
  const same=(a,b)=>JSON.stringify(ordered(a))===JSON.stringify(ordered(b));
  async function envelope(raw,name){need(raw&&/^[a-f0-9]{64}$/.test(raw.sha256)&&typeof raw.rawUtf8==='string'&&
    await digest(raw.rawUtf8)===raw.sha256,'Original '+name+' byte SHA differs');return JSON.parse(raw.rawUtf8);}
  async function verifySealed(authority,config,data){
    need(authority.normalAdmissionAllowed===true&&data?.sync?.accepted===true&&data?.song?.quality?.accepted===true,'Public normal admission missing');
    const context=await envelope(authority.normalContext,'normal context');
    need(authority.normalContext.sha256===config.contextSha256&&same(context,config.context)&&same(authority.context,config.context),'Public exact context differs');
    const actualSync=clone(data.sync);delete actualSync.accepted;
    need(same(actualSync,config.sync)&&same(data.jianpu,config.notation),'Public music payload differs from frozen display tuple');
    need(data.song.id===config.candidate.id&&data.song.audio===config.candidate.audio,'Public registered audio/song differs');
    const ui=await envelope(authority.normalUIDecision,'normal UI'),cert=await envelope(authority.certificate,'certificate');
    need(ui.schema==='root-complete-ensemble-occurrence-normal-ui-decision/v1'&&ui.reviewedBy==='/root'&&ui.approved===true&&
      ui.scope==='current-normal-native-complete-occurrence-source-reading-only'&&ui.qualifiedReadingProfile===H.PROFILE&&
      Object.entries(config.preparationIdentity).every(([k,v])=>ui[k]===v)&&same(ui.normalContext,config.context)&&
      same(ui.frontend,data.song.frontend),'Whole-occurrence native UI decision differs');
    need(cert.schemaVersion===1&&cert.status==='approved'&&cert.reviewedBy==='/root'&&typeof cert.signedAt==='string'&&cert.signedAt&&
      cert.followId===config.candidate.id&&cert.sourceSongId===config.candidate.sourceSongId&&cert.sourceScoreId===config.candidate.sourceScoreId&&
      ['machine','sourceScore','audioIndependent','visual'].every(k=>cert.gates?.[k]===true)&&Array.isArray(cert.reasons)&&cert.reasons.length===0,
      'Public certificate incomplete');
    need(Array.isArray(cert.bindings)&&cert.bindings.length,'Certificate original bindings missing');
    const covered=new Set();for(const b of cert.bindings){need(['follow','media'].includes(b.kind)&&typeof b.path==='string'&&
      !b.path.startsWith('/')&&!b.path.includes('\\')&&!b.path.split('/').includes('..')&&/^[a-f0-9]{64}$/.test(b.sha256),'Unsafe certificate original binding');covered.add(b.sha256);}
    for(const key of Object.keys(config.context).filter(k=>k.endsWith('Sha256')))need(covered.has(config.context[key]),'Certificate misses context original '+key);
    for(const raw of [authority.normalContext,authority.normalUIDecision])need(covered.has(raw.sha256),'Certificate misses original context/UI');
    const prefix='generated/'+config.candidate.id+'/',binding=(path,sha)=>cert.bindings.some(b=>b.kind==='follow'&&b.path===path&&b.sha256===sha);
    need(binding(prefix+'sync.json',config.preparationIdentity.syncSha256)&&binding(prefix+'notation.json',config.preparationIdentity.notationSha256),
      'Certificate misses exact S/N');
    const frontend=data.song.frontend;need(frontend?.version==='source-tempo-beats-v1'&&frontend.frame===prefix+'accepted-frontend/frame.html'&&
      same(Object.keys(frontend.assets||{}).sort(),['frame.html','source-tempo-beats-v1.css','source-tempo-beats-v1.js']),'Exact frontend metadata missing');
    for(const [name,sha]of Object.entries(frontend.assets)){need(binding(prefix+'accepted-frontend/'+name,sha),'Certificate frontend binding differs');
      const response=await root.fetch(new URL(name,root.location.href).href,{cache:'no-store'});need(response.ok&&await digest(await response.arrayBuffer())===sha,'Current frontend asset differs');}
    return true;
  }
  async function verifyAuthority(authority,config,data){
    need(authority?.profile===H.PROFILE&&authority.contextSha256===config.contextSha256,'Exact occurrence preparation authority missing');
    const sealed=authority.mode==='normal-sealed';
    if(!sealed)need(authority.mode==='root-qualified-occurrence-preparation'&&authority.normalAdmissionAllowed===false
      &&['127.0.0.1','localhost','[::1]'].includes(root.location.hostname)&&new URLSearchParams(root.location.search).get('review')==='1',
      'Unsigned occurrence context requires genuine loopback review');
    for(const [name,key]of [['sourceDecision','sourceDecisionSha256'],['routeDecision','routeDecisionSha256'],
      ['clockDecision','clockDecisionSha256'],['modelDecision','sourceModelDecisionSha256'],['rootV6Decision','rootV6DecisionSha256']]){
      const raw=authority[name];need(raw?.sha256===config.context[key]&&await digest(raw.rawUtf8)===raw.sha256,'Original '+name+' bytes differ');
      const body=JSON.parse(raw.rawUtf8);need(body.reviewedBy==='/root'&&body.approved===true,'Original Root decision pending');
      if(name!=='sourceDecision')need(body.qualifiedReadingProfile===H.PROFILE&&Object.entries(config.preparationIdentity).every(([k,v])=>body[k]===v),
        'Root occurrence tuple differs');
    }
    return sealed?verifySealed(authority,config,data):true;
  }
  function createController(document,config,send){
    const pane=document.querySelector('#score'),status=document.querySelector('#readingStatus'),reader=H.createReader(config.occurrenceLayout),
      tokens=new Map(config.notation.tokens.map(t=>[t.id,t])),model=config.sourceModel;
    let mode='staff',scale=1,manual=false,hidden=false,ready=false,lastWidth=null,sections=[],currentTime=0,selected=null,binding=null;
    function request(event){need(ready,'Source/route/clock/model/edition loading');
      const exact=reader.seekRequest(event.sourcePhysicalId,event.occurrenceId);need(exact.time===event.time,'Explicit occurrence changed');
      selected=exact;pane.dataset.selectedSourcePhysicalId=exact.sourcePhysicalId;pane.dataset.selectedOccurrenceId=exact.occurrenceId;
      manual=false;send({type:'music-seek',time:exact.time,sourcePhysicalId:exact.sourcePhysicalId,occurrenceId:exact.occurrenceId});}
    function draw(){
      if(!ready||hidden)return;binding?.dispose();sections=[];pane.replaceChildren();
      if(mode==='staff')for(const s of model.originalSystems){const card=document.createElement('section');card.className='original-system';card.dataset.systemId=s.sourceSystemId;
        const r=s.rect,w=r[2]-r[0],h=r[3]-r[1],image=config.originalImages[s.sha256];need(image?.startsWith('data:image/png;base64,'),'Bound original crop missing');
        const members=model.events.filter(e=>s.physicalIds.includes(e.id));
        card.innerHTML=`<h2>第 ${s.first}–${s.last} 小节</h2><svg viewBox="${r[0]} ${r[1]} ${w} ${h}" xmlns="http://www.w3.org/2000/svg"><image href="${image}" x="${r[0]}" y="${r[1]}" width="${w}" height="${h}"/>${members.map(e=>{
          const b=e.nativeInkBounds,label=`第${e.measure}小节，${e.part}，${e.pitch||'休止'}，${e.sourceLyric||''}`;
          return `<rect class="source-note" data-source-id="${esc(e.id)}" data-source-fragment="start" x="${b.x-3}" y="${b.y-5}" width="${b.width+6}" height="${b.height+10}" aria-label="${esc(label)}"/>`;}).join('')}</svg>`;
        card.querySelector('svg').style.minWidth=String(840*scale)+'px';
        pane.appendChild(card);sections.push({element:card,system:s});}
      else{
        const groups=[];for(const m of config.notation.measures){let group=groups.at(-1);if(!group||group.tonic!==m.localTonic){group={tonic:m.localTonic,measures:[]};groups.push(group);}group.measures.push(m);}
        for(const group of groups){const data={tonic:group.tonic,measures:clone(group.measures),tokens:[]};
          for(const m of data.measures)for(const t of m.tokens){t.token=displayToken(t);t.time=null;t.eventIndex=null;t.sourceOnlyUntimed=false;data.tokens.push(t);}
          data.tempo=model.soundQuarterTempo;
          const result=root.MusicNotation.render(data,Math.max(180,pane.clientWidth-20),scale),card=document.createElement('section');card.className='numbered-section';card.innerHTML=result.html;
          card.querySelector('.jp-head strong').textContent='1 = '+group.tonic.replace(/#/g,'♯').replace(/b/g,'♭');
          for(const node of card.querySelectorAll('.jp-note[data-id]')){const t=tokens.get(node.dataset.id);need(t,'Unexpected numbered physical ID');
            node.dataset.sourceId=t.id;node.dataset.sourceFragment=Number(node.dataset.start)>t.beat+1e-8?'continuation':'start';
            if(t.sourceKind==='unpitched')node.querySelector('.jp-digit').textContent=t.sourceNotehead.some(n=>n.text==='circle-x')?'⊗':'×';}
          pane.appendChild(card);sections.push({element:card,data,geometry:result.geometry});}
        for(const s of sections)for(const connection of config.notation.sourceConnections.filter(c=>c.kind==='slur')){
          const nodes=id=>[...s.element.querySelectorAll('.jp-note[data-id]')].filter(n=>n.dataset.id===id);
          const start=nodes(connection.source).at(-1),stop=nodes(connection.target)[0];if(!start&&!stop)continue;
          const pos=n=>{const b=n.querySelector('.jp-bg');return {x:Number(b.getAttribute('x'))+Number(b.getAttribute('width'))/2,
            y:Number(b.getAttribute('y'))-12*scale,row:n.dataset.row};};
          const a=start?pos(start):null,b=stop?pos(stop):null,svg=s.element.querySelector('svg');
          const arc=(x1,y1,x2,y2)=>{const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('class','jp-source-slur');
            path.setAttribute('d',`M ${x1} ${y1} C ${x1+(x2-x1)*.3} ${Math.min(y1,y2)-16*scale} ${x1+(x2-x1)*.7} ${Math.min(y1,y2)-16*scale} ${x2} ${y2}`);
            path.dataset.source=connection.source;path.dataset.target=connection.target;svg.appendChild(path);};
          if(a&&b&&a.row===b.row)arc(a.x,a.y,b.x,b.y);
          else{if(a)arc(a.x,a.y,s.geometry.width-12*scale,a.y);if(b)arc(12*scale,b.y,b.x,b.y);}}
      }
      binding=H.bindPhysicalTargets(pane,reader,request);pane.dataset.nativePhysicalTargets=String(binding.nativePhysicalTargets);
      pane.dataset.fragmentTotal=String(pane.querySelectorAll('[data-source-id],.jp-note[data-id]').length);
      pane.dataset.uniqueSourcePhysicalIds=String(new Set([...pane.querySelectorAll('[data-source-id],.jp-note[data-id]')].map(n=>n.dataset.sourceId||n.dataset.id)).size);
      pane.dataset.mode=mode;lastWidth=pane.clientWidth;paint(currentTime);
    }
    function safeScroll(anchor,line){if(manual||!line)return;const p=pane.getBoundingClientRect(),a=anchor.getBoundingClientRect(),l=line.getBoundingClientRect();
      const top=p.top+8,bottom=p.bottom-10,target=a.height<=bottom-top?a:l;
      if(target.top<top||target.bottom>bottom)pane.scrollTop+=target.top-top;
      if(mode==='staff'){const rect=anchor.getBoundingClientRect(),reading=pane.getBoundingClientRect(),actual=line.getBoundingClientRect(),
        left=Math.max(rect.left,reading.left)+12,right=Math.min(rect.right,reading.right)-12;
        if(actual.left<left)anchor.scrollLeft+=actual.left-left;else if(actual.right>right)anchor.scrollLeft+=actual.right-right;}}

    function paint(time){currentTime=time;pane.dataset.nativeTime=String(time);pane.dataset.manualReading=String(manual);pane.querySelectorAll('.occurrence-reading-line').forEach(n=>n.remove());
      const position=ready&&!hidden?reader.position(time):null;pane.dataset.sourceQuarter=position?String(position.sourceQuarter):'';
      pane.dataset.visitId=position?.visitId||'';pane.dataset.cursorLineCount='0';pane.dataset.sourceSystemId='';
      pane.dataset.cursorSourceParts='[]';pane.dataset.systemSourceParts='[]';pane.dataset.activeOccurrenceIds='[]';
      pane.dataset.activeUnpitchedOccurrenceIds='[]';pane.dataset.localTonic='';if(!position)return;
      let section,x,top,bottom,parts;
      if(mode==='staff'){const g=reader.lineGeometry(position);section=sections.find(s=>s.system.sourceSystemId===g.sourceSystemId);
        ({xNative:x,topNative:top,bottomNative:bottom,allSourceParts:parts}=g);pane.dataset.sourceSystemId=g.sourceSystemId;}
      else{outer:for(const s of sections)for(const row of s.geometry.rows)for(const f of row.fragments){const q0=f.measure.sourceQuarter,
          beat=position.sourceQuarter-q0;if(beat>=f.start&&beat<f.end){section=s;const u=f.units.find(u=>u.start<=beat&&beat<u.end)||f.units.at(-1);
            x=u.x+u.width*(beat-u.start)/(u.end-u.start);top=row.y+28*scale;bottom=row.y+row.height-6*scale;
            const g=reader.lineGeometry(position);parts=g.allSourceParts;pane.dataset.sourceSystemId=g.sourceSystemId;break outer;}}}
      if(!section)return;const svg=section.element.querySelector('svg'),line=document.createElementNS('http://www.w3.org/2000/svg','line');
      for(const [k,v]of Object.entries({x1:x,x2:x,y1:top,y2:bottom,class:'occurrence-reading-line'}))line.setAttribute(k,String(v));svg.appendChild(line);
      pane.dataset.cursorLineCount='1';pane.dataset.cursorSourceParts=JSON.stringify(parts);pane.dataset.systemSourceParts=JSON.stringify([...parts]);
      pane.dataset.activeOccurrenceIds=JSON.stringify(position.activeOccurrenceIds);pane.dataset.localTonic=position.localTonic;
      pane.dataset.activeUnpitchedOccurrenceIds=JSON.stringify(position.activeUnpitchedOccurrenceIds);
      safeScroll(section.element,line);status.textContent=`第 ${position.visitId} 段 · 1=${position.localTonic.replace(/#/g,'♯')}`;
    }
    function onMessage(event){if(event.source!==root.parent||event.origin!==root.location.origin||event.data?.type!=='music-time')return;
      hidden=event.data.visible===false;
      if(!hidden&&lastWidth!==pane.clientWidth)draw();paint(event.data.time);}
    for(const button of document.querySelectorAll('[data-mode]'))button.addEventListener('click',()=>{mode=button.dataset.mode;
      for(const b of document.querySelectorAll('[data-mode]'))b.setAttribute('aria-pressed',String(b===button));draw();});
    const sizeButton=document.querySelector('#sizeButton'),sizeMenu=document.querySelector('#sizeMenu');
    for(const [label,value]of [['小',.85],['标准',1],['大',1.25],['特大',1.5]]){const b=document.createElement('button');b.type='button';b.textContent=label;
      b.addEventListener('click',()=>{scale=value;sizeButton.textContent='字号：'+label;sizeMenu.hidden=true;sizeButton.setAttribute('aria-expanded','false');draw();});sizeMenu.appendChild(b);}
    sizeButton.addEventListener('click',()=>{sizeMenu.hidden=!sizeMenu.hidden;sizeButton.setAttribute('aria-expanded',String(!sizeMenu.hidden));
      const r=sizeButton.getBoundingClientRect(),m=sizeMenu.getBoundingClientRect();sizeMenu.style.left=Math.max(8,Math.min(r.left,root.innerWidth-m.width-8))+'px';sizeMenu.style.top=r.bottom+6+'px';});
    const markManual=()=>{manual=true;pane.dataset.manualReading='true';};
    pane.addEventListener('wheel',markManual,{passive:true});pane.addEventListener('touchmove',markManual,{passive:true});
    document.querySelector('#resumeFollow').addEventListener('click',()=>{manual=false;paint(currentTime);});
    root.addEventListener('message',onMessage);root.addEventListener('resize',()=>{if(lastWidth!==pane.clientWidth)draw();});
    return {activate(){ready=true;pane.dataset.clockApproved='true';pane.dataset.readingIntegration='enabled';pane.dataset.normalUIApproved='false';draw();},
      fail(){ready=false;pane.dataset.clockApproved='false';pane.dataset.readingIntegration='blocked';pane.replaceChildren();status.textContent='跟谱加载失败，请重试';},
      paint,draw,request,get selected(){return selected;}};
  }
  const api={displayToken,verifyAuthority,createController};root.EnsembleOccurrenceNormal=api;
  if(typeof module!=='undefined')module.exports=api;
  if(root.document&&root.OccurrenceBoundConfig){const config=root.OccurrenceBoundConfig,controller=createController(root.document,config,
      message=>root.parent.postMessage(message,root.location.origin));
    root.fetch(new URLSearchParams(root.location.search).get('review')==='1'?'/api/follow/'+encodeURIComponent(config.candidate.id)+'?view=source-tempo-beats-v1':'/api/follow/demo?song='+encodeURIComponent(config.candidate.id)+'&view=source-tempo-beats-v1',{cache:'no-store'})
      .then(response=>{need(response.ok,'Genuine occurrence API unavailable');return response.json();})
      .then(async data=>{await verifyAuthority(data.sourceReadingAuthority,config,data);controller.activate();})
      .catch(error=>{root.console.error(error);controller.fail();});}
})(typeof window==='undefined'?globalThis:window);
