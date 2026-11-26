    const el = id => document.getElementById(id);
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const pretty = value => esc(JSON.stringify(value, null, 2));
    const metric = (label,value) => `<div class="benchmark-metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
    const ms = value => typeof value==='number' ? `${value.toFixed(2)} ms` : 'Not measured';
    const timeDelta = value => typeof value!=='number' ? 'Not measured' : value>0 ? `${ms(value)} faster` : value<0 ? `${ms(-value)} slower` : 'Same time';
    function renderCapture(c) {
      const fields=[['Process lifecycle',c.process_lifecycle],['Process output',c.process_output],['Model inputs',c.model_inputs],
        ['Model outputs',c.model_outputs],['Tool calls',c.tool_calls],['Tool results',c.tool_results],
        ['Context',c.context],['Evidence',c.evidence],['Restorable checkpoints',c.restorable_checkpoints]];
      const rows=fields.map(([label,item])=>`<span class="capture-field"><strong>${esc(label)}</strong> ${esc(item.status)}</span>`).join('');
      const failures=c.capture_failures.map(item=>`${esc(item.stage)} (${esc(item.error_type)})`).join(', ');
      return `<div class="capture-summary"><strong>Captured in this run</strong><div class="capture-fields">${rows}</div>`+
        `<div class="muted">${esc(c.missing_data_note)} Runtime-backed checkpoints still require resume validation.</div>`+
        (failures?`<div class="fail">Capture failures: ${failures}</div>`:'')+'</div>';
    }
    function renderBenchmark(report, run) {
      let html='<h2>Measured recovery</h2>';
      if (Array.isArray(report)) {
        const result=report[0];
        if(!result) html+='<p>No saved branch comparison yet.</p>';
        else {
          html+=`<div class="benchmark-metrics">${metric('Incremental model saving',`$${result.net_model_saving_usd.toFixed(7)}`)}${metric('Tool calls avoided',result.tool_calls_avoided)}${metric('Recovery vs cold',timeDelta(result.wall_time_saved_ms))}${metric('Provider cache saving',`$${result.provider_cache_saving_usd.toFixed(7)}`)}</div>`;
          html+=`<p>${esc(result.verdict)}. ${esc(result.provider_cache_note || '')}</p>`;
        }
      } else if (report?.recovered) {
        const result=report.recovered[0];
        if(!result) html+='<p>Resume a corrected branch to compare recovery.</p>';
        else {
          html+=`<div class="benchmark-metrics">${metric('Steps skipped',result.skipped_steps)}${metric('Context objects shared',result.shared_context_objects)}${metric('Branch time',ms(result.elapsed_ms))}${metric('Recovery vs cold',timeDelta(result.wall_time_saved_ms_vs_latest_cold))}</div>`;
          html+='<p>Offline fixture: no model calls, so provider prompt-cache savings were not measured.</p>';
          if(!report.cold_baselines.length) html+='<button id="measure-cold" type="button">Measure cold comparison</button>';
        }
      } else html+='<p>No benchmark for this adapter.</p>';
      el('benchmark-summary').innerHTML=html;
      const button=el('measure-cold');
      if(button) button.onclick=async()=>{button.disabled=true;try{await api('/api/benchmark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:run.parent_run||run.id})});await showRun(run.id);notice('Cold comparison measured')}catch(error){notice(error.message);button.disabled=false}};
    }
    let selectedRun = null, selectedSnapshot = null, selectedEvent = null, selectedBranch = null, currentArtifacts = [], runIndex = [], branchIndex = [], playingBranch = null;
    let chatSession = null, chatReady = false;
    function chatNotice(value) { el('chat-notice').textContent=value; }
    function chatRuns() {
      const picker=el('chat-run'), before=picker.value;
      picker.innerHTML='<option value="">No run selected</option>'+runIndex.map((run,index)=>`<option value="${esc(run.id)}">${index+1}. ${esc(run.label)}</option>`).join('');
      picker.value=before || selectedRun || '';
    }
    function chatMessages(messages) {
      el('chat-messages').innerHTML=messages.map(item=>`<div class="chat-message ${item.role==='user'?'user':'assistant'}">${esc(item.content)}</div>`).join('');
      el('chat-messages').scrollTop=el('chat-messages').scrollHeight;
    }
    async function chatModel() {
      const data=await api('/api/chat/model');
      chatReady=!!data.model?.verified;
      el('chat-setup').hidden=chatReady;
      el('chat-workspace').hidden=!chatReady;
      if(chatReady) {
        chatNotice(`${data.model.provider} · ${data.model.model}`);
        const history=await api('/api/chat/sessions');
        const latest=history.sessions.at(-1);
        if(latest){chatSession=latest.id;chatMessages(latest.messages);chatRuns();el('chat-run').value=latest.run_id||''}
      } else chatNotice(data.model?'Last connection test failed. Update the model settings and try again.':'Connect a model to start chatting.');
    }
    const seenGraphEvents = new Set();
    let graphInitialized = false, refreshBusy = false;
    async function api(path, options) { const r = await fetch(path, options); const value = await r.json(); if (!r.ok) throw Error(value.error || `HTTP ${r.status}`); return value; }
    function notice(text) { el('notice').textContent = text; }
    async function load(live = false) {
      try {
        const data = await api('/api/runs');
        runIndex=data.runs; branchIndex=data.branches;
        chatRuns();
        el('runs').innerHTML = data.runs.length ? data.runs.map(r => `<div class="item ${r.id===selectedRun?'active':''}" data-run="${esc(r.id)}"><strong>${esc(r.label)}</strong><span class="pill ${r.status==='failed'?'fail':'ok'}">${esc(r.status)}</span><span class="pill ${r.outcome==='failed'?'fail':'ok'}">${esc(r.outcome || 'unreviewed')}</span><span class="muted">${esc(r.agent)} · ${esc(new Date(r.created*1000).toLocaleString())} · ${esc(r.id)}</span></div>`).join('') : '<div class="empty">No runs yet. Run <code>mangekyo demo</code> in a terminal.</div>';
        el('branches').innerHTML = data.branches.length ? data.branches.map(b => `<div class="item" data-branch="${esc(b.name)}"><strong>${esc(b.name)}</strong><span class="muted">${esc(b.result_run || 'Not resumed')}</span></div>`).join('') : '<div class="empty">No branches yet.</div>';
        document.querySelectorAll('[data-run]').forEach(n => n.onclick=()=>showRun(n.dataset.run));
        document.querySelectorAll('[data-branch]').forEach(n => n.onclick=()=>showBranch(n.dataset.branch, data.branches));
        if (!selectedRun && data.runs.length) await showRun(data.runs.find(r=>r.status==='failed' && !r.parent_run)?.id || data.runs[0].id);
        else if(selectedRun) {
          if(live) await showRun(selectedRun, true);
          else await renderGraph();
        }
      } catch(e) { notice(e.message); }
    }
    async function showRun(id, preserveInspector = false) {
      try {
        if(preserveInspector && selectedRun!==id)return;
        selectedRun=id;
        if(!preserveInspector){selectedSnapshot=null;selectedEvent=null;}
        const data=await api('/api/run/'+encodeURIComponent(id));
        if(selectedRun!==id)return;
        currentArtifacts=data.artifacts;
        el('live-indicator').textContent=data.run.status==='running'?'● Live · updating each second':'';
        renderBenchmark(data.benchmark,data.run);
        el('summary').innerHTML=`<strong>${esc(data.run.label)}</strong><br><span class="muted">${esc(data.run.agent)} · ${esc(new Date(data.run.created*1000).toLocaleString())} · ${esc(data.run.id)} · execution ${esc(data.run.status)} | outcome ${esc(data.run.outcome || 'unreviewed')} · adapter ${esc(data.run.adapter)}</span>`+renderCapture(data.capture);
        el('events').innerHTML=data.events.map(e=>`<div class="item ${e.kind==='error'?'fail':''}" data-event="${esc(e.id)}"><span class="pill">${e.seq}</span><strong>${esc(e.kind)}</strong><span class="muted">${esc(JSON.stringify(e.payload).slice(0,110))}</span></div>`).join('');
        document.querySelectorAll('[data-event]').forEach(n=>n.onclick=()=>showEvent(data.events.find(e=>e.id===n.dataset.event)));
        el('artifacts').innerHTML=data.artifacts.length ? data.artifacts.map(a=>`<div class="item" data-artifact="${esc(a.id)}"><strong>${esc(a.name)}</strong><span class="muted">${esc(a.mime)} · ${esc(a.id)}</span></div>`).join('') : '<div class="empty">No captured documents or screenshots for this run.</div>';
        document.querySelectorAll('[data-artifact]').forEach(n=>n.onclick=()=>showArtifact(n.dataset.artifact));
        if(!preserveInspector)el('inspector').innerHTML=`<div class="muted">Select a timeline event.</div><h2>Benchmark</h2><pre>${pretty(data.benchmark || {note:'No benchmark for this adapter'})}</pre>`;
        await loadListOnly();
        await renderGraph(preserveInspector);
      } catch(e) { notice(e.message); }
    }
    async function loadListOnly() { document.querySelectorAll('[data-run]').forEach(n=>n.classList.toggle('active',n.dataset.run===selectedRun)); }
    async function renderGraph(preserveScroll = false) {
      if(!selectedRun)return;
      const selected=runIndex.find(r=>r.id===selectedRun);
      if(!selected)return;
      const root=selected.parent_run ? runIndex.find(r=>r.id===selected.parent_run) || selected : selected;
      const related=branchIndex.filter(b=>b.source_run===root.id);
      const original=await api('/api/run/'+encodeURIComponent(root.id));
      const step=105, left=36, mainY=55, rowGap=68;
      const checkpointIndex=new Map();
      original.events.forEach((event,index)=>{if(event.snapshot_id)checkpointIndex.set(event.snapshot_id,index)});
      const branchData=await Promise.all(related.map(async branch=>({branch,run:branch.result_run?await api('/api/run/'+encodeURIComponent(branch.result_run)):null})));
      const maxCount=Math.max(original.events.length,...branchData.map(({branch,run})=>(checkpointIndex.get(branch.source_snapshot)??0)+1+(run?.events.length||1)));
      const width=Math.max(460,left*2+(maxCount-1)*step+110), height=150+branchData.length*rowGap;
      const paths=[], nodes=[];
      const eventColor=event=>{
        if(event.kind==='error'||event.kind==='capture_error'||(['verification','eval_result'].includes(event.kind)&&event.payload?.passed===false))return 'error';
        if(['verification','eval_result'].includes(event.kind)&&event.payload?.passed===true)return 'verified';
        if(['tool','tool_start','checkpoint','restore'].includes(event.kind))return 'action';
        return 'normal';
      };
      const node=(x,y,label,meta,classes,attrs)=>`<button type="button" class="graph-node ${classes}" style="left:${x-55}px;top:${y-10}px" ${attrs} title="${esc(label+' · '+meta)}"><span class="dot"></span><span>${esc(label)}</span><span>${esc(meta)}</span></button>`;
      const line=(x1,y1,x2,y2,classes='')=>paths.push(`<path class="${classes}" d="M${x1} ${y1} L${x2} ${y2}"/>`);
      original.events.forEach((event,index)=>{
        const x=left+index*step;
        if(index)line(x-step,mainY,x,mainY,related.length && index>(checkpointIndex.get(related[0].source_snapshot)??Infinity)?'abandoned':'');
        nodes.push(node(x,mainY,event.kind,event.snapshot_id?'checkpoint '+event.snapshot_id.slice(0,6):'#'+event.seq,`event-${eventColor(event)} ${event.id===selectedEvent?'active':''} ${graphInitialized&&!seenGraphEvents.has(event.id)?'fresh':''} ${original.run.status==='running'&&index===original.events.length-1?'live-tip':''}`,`data-graph-run="${esc(root.id)}" data-graph-event="${esc(event.id)}"`));
      });
      branchData.forEach(({branch,run},row)=>{
        const source=checkpointIndex.get(branch.source_snapshot)??0, forkX=left+source*step, y=mainY+(row+1)*rowGap;
        const endX=forkX+step;
        paths.push(`<path class="fork" d="M${forkX} ${mainY} C${forkX+step*.4} ${mainY},${forkX+step*.5} ${y},${endX} ${y}"/>`);
        if(run){run.events.forEach((event,index)=>{const x=endX+index*step;if(index)line(x-step,y,x,y,'fork');nodes.push(node(x,y,event.kind,branch.name,`event-${eventColor(event)} corrected ${event.id===selectedEvent?'active':''} ${graphInitialized&&!seenGraphEvents.has(event.id)?'fresh':''} ${run.run.status==='running'&&index===run.events.length-1?'live-tip':''}`,`data-graph-run="${esc(run.run.id)}" data-graph-event="${esc(event.id)}"`))});if(run.run.status==='completed'){const finalX=endX+(run.events.length-1)*step;paths.push(`<path class="feedback" d="M${finalX} ${y+17} C${finalX} ${y+34},${forkX} ${y+34},${forkX} ${mainY+17}"/>`)}}
        else nodes.push(node(endX,y,branch.name,'awaiting resume','corrected pending',`data-graph-branch="${esc(branch.name)}"`));
      });
      const graph=el('graph'), scroll=graph.parentElement;
      const oldScroll=scroll.scrollLeft, followEnd=oldScroll+scroll.clientWidth>=scroll.scrollWidth-40;
      graph.style.width=width+'px';graph.style.height=height+'px';
      graph.innerHTML=`<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><marker id="feedback-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="none" stroke="#39805a"/></marker></defs>${paths.join('')}</svg>${nodes.join('')}`;
      if(preserveScroll)scroll.scrollLeft=followEnd?scroll.scrollWidth-scroll.clientWidth:oldScroll;
      else if(related.length)scroll.scrollLeft=Math.max(0,left+(checkpointIndex.get(related[0].source_snapshot)??0)*step-190);
      original.events.forEach(event=>seenGraphEvents.add(event.id));
      branchData.forEach(({run})=>run?.events.forEach(event=>seenGraphEvents.add(event.id)));
      graphInitialized=true;
      graph.className='graph'+(playingBranch?' playing':'');
      graph.querySelectorAll('[data-graph-event]').forEach(button=>button.onclick=async()=>{const id=button.dataset.graphRun,eventId=button.dataset.graphEvent;const data=await api('/api/run/'+encodeURIComponent(id));if(selectedRun!==id)await showRun(id);await showEvent(data.events.find(e=>e.id===eventId));graph.querySelectorAll('.graph-node').forEach(n=>n.classList.toggle('active',n.dataset.graphEvent===eventId))});
      graph.querySelectorAll('[data-graph-branch]').forEach(button=>button.onclick=()=>showBranch(button.dataset.graphBranch,branchIndex));
    }
    async function showEvent(event) {
      selectedSnapshot=event.snapshot_id;selectedEvent=event.id;
      el('graph').querySelectorAll('.graph-node').forEach(n=>n.classList.toggle('active',n.dataset.graphEvent===event.id));
      let html=`<div class="muted">Event ${esc(event.id)} · ${esc(event.kind)}</div><pre>${pretty(event.payload)}</pre>`;
      if (selectedSnapshot) {
        const data=await api('/api/snapshot/'+encodeURIComponent(selectedSnapshot));
        html+=`<h2>Snapshot ${esc(selectedSnapshot)}</h2><div class="muted">${data.environment_restorable?'Simulation environment checkpoint available':'Context only; no environment restore'}</div><pre>${pretty(data.context)}</pre>`;
        const graph=data.snapshot.adapter==='langgraph';
        html+=`<div class="form"><label>New branch name</label><input id="branch-name" value="fix-${esc(selectedSnapshot.slice(0,5))}"><label>${graph?'Correction (key=value)':'Reference correction'}</label><input id="replacement" value="${graph?'selected_table=bookings':'safe'}"><button id="create-branch">Create branch</button></div>`;
      }
      el('inspector').innerHTML=html;
      if (selectedSnapshot) el('create-branch').onclick=createBranch;
      const linked=currentArtifacts.find(a=>a.event_id===event.id || a.id===event.payload?.artifact_id);
      if(linked) await showArtifact(linked.id);
    }
    async function showArtifact(id, page=0) {
      try {
        const data=await api('/api/artifact/'+encodeURIComponent(id));
        const a=data.artifact, count=data.page_count || 1;
        if(page<0 || page>=count) return;
        const rows=data.annotations.filter(n=>n.page===page);
        el('inspector').innerHTML=`<div class="muted">Captured evidence · ${esc(a.id)}</div><h2>${esc(a.name)}</h2><div class="muted">${esc(a.mime)} · source ${esc(a.source || 'agent supplied')} · <a href="/api/artifact/${encodeURIComponent(id)}/raw" target="_blank" rel="noopener">Open original</a></div><div class="evidence-tools"><button id="prev-page" ${page===0?'disabled':''}>Previous</button><span>Page ${page+1} of ${count}</span><button id="next-page" ${page+1>=count?'disabled':''}>Next</button></div><div class="evidence-view"><img id="evidence-image" src="/api/artifact/${encodeURIComponent(id)}/page/${page}" alt="Captured ${esc(a.name)} page ${page+1}"><canvas id="mark-layer"></canvas></div><div class="evidence-tools"><input id="annotation-note" placeholder="Describe what the agent saw or missed"><span class="muted">Draw a box on the image to save this note.</span></div><div id="annotations">${rows.map(n=>`<div class="annotation">${esc(n.note)}</div>`).join('')}</div><h2>Text captured by agent</h2><pre>${esc(data.parsed_text ?? 'No parsed text was supplied for this evidence.')}</pre>`;
        el('prev-page').onclick=()=>showArtifact(id,page-1);
        el('next-page').onclick=()=>showArtifact(id,page+1);
        const img=el('evidence-image'), canvas=el('mark-layer'), ctx=canvas.getContext('2d');
        let start=null, draft=null;
        function paint() {
          canvas.width=img.clientWidth; canvas.height=img.clientHeight;
          ctx.strokeStyle='#b44370'; ctx.lineWidth=2; ctx.fillStyle='rgba(180,67,112,.14)';
          for(const n of [...rows,...(draft?[draft]:[])]) {
            const x=n.x*canvas.width,y=n.y*canvas.height,w=n.width*canvas.width,h=n.height*canvas.height;
            ctx.fillRect(x,y,w,h); ctx.strokeRect(x,y,w,h);
          }
        }
        function point(e) { const r=canvas.getBoundingClientRect(); return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))}; }
        img.onload=paint; new ResizeObserver(paint).observe(img);
        canvas.onpointerdown=e=>{start=point(e);canvas.setPointerCapture(e.pointerId)};
        canvas.onpointermove=e=>{if(!start)return;const p=point(e);draft={x:Math.min(start.x,p.x),y:Math.min(start.y,p.y),width:Math.abs(p.x-start.x),height:Math.abs(p.y-start.y)};paint()};
        canvas.onpointerup=async e=>{if(!start)return;start=null;const box=draft;draft=null;paint();if(!box||box.width<.005||box.height<.005)return;const note=el('annotation-note').value.trim();if(!note){notice('Enter a note, then draw the box again.');return}try{await api('/api/annotation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({artifact:id,page,...box,note})});notice('Annotation saved');await showArtifact(id,page)}catch(error){notice(error.message)}};
      } catch(error) { notice(error.message); }
    }
    async function createBranch() {
      try {
        const value=el('replacement').value.trim();
        const body={snapshot:selectedSnapshot,name:el('branch-name').value,replacement:value};
        if(value.includes('=')){const split=value.indexOf('=');body.correction={[value.slice(0,split).trim()]:value.slice(split+1).trim()}}
        await api('/api/branch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        notice(`Created branch ${body.name}`); await load();await showBranch(body.name,branchIndex);
      } catch(e) { notice(e.message); }
    }
    async function showBranch(name, branches) {
      const branch=branches.find(b=>b.name===name); selectedBranch=name;
      const comparison=await api('/api/branch/'+encodeURIComponent(name));
      const available=!comparison.resume_unavailable_reason;
      el('inspector').innerHTML=`<div class="muted">Branch from snapshot ${esc(branch.source_snapshot)}</div><h2>Correction</h2><pre>${pretty(comparison.correction)}</pre><h2>Context comparison</h2><div class="muted">Changed: ${esc(comparison.changed.join(', ') || (comparison.after?'none':'Resume to compare'))}</div><pre>${pretty({original:comparison.before,corrected:comparison.after})}</pre>${available?'<button id="resume">Resume corrected branch</button>':`<div class="muted">Resume unavailable: ${esc(comparison.resume_unavailable_reason)}</div>`}${branch.result_run?'<button id="commit-branch">Commit passing correction</button>':''}`;
      if(available) el('resume').onclick=async()=>{ playingBranch=name;el('graph').classList.add('playing');el('resume').disabled=true;notice(`Executing branch ${name}…`);try {const [result]=await Promise.all([api('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({branch:name})}),new Promise(resolve=>setTimeout(resolve,900))]);playingBranch=null;notice(`Resumed as ${result.run_id}; skipped ${result.skipped_steps} steps`);await load();await showRun(result.run_id);el('graph').classList.add('success');setTimeout(()=>el('graph').classList.remove('success'),1300)}catch(e){playingBranch=null;el('graph').classList.remove('playing');notice(e.message);el('resume').disabled=false} };
      if(branch.result_run) el('commit-branch').onclick=async()=>{try{const result=await api('/api/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({branch:name})});notice(`Committed ${name} as ${result.commit_id}`)}catch(error){notice(error.message)}};
    }
    async function checkSelected(eventId) {
      if(!selectedRun){notice('Select a run first.');return}
      if(eventId===true&&!selectedEvent){notice('Select an event first.');return}
      try {
        const body={run_id:selectedRun,file:el('check-file').value};
        if(eventId===true)body.event_id=selectedEvent;
        const result=await api('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        notice(`Check ${result.outcome} at event ${result.source_event_seq}`);await showRun(selectedRun,true);
      } catch(error){notice(error.message)}
    }
    el('check-run').onclick=()=>checkSelected(false);
    el('check-event').onclick=()=>checkSelected(true);
    el('mark-event').onclick=async()=>{
      if(!selectedRun||!selectedEvent){notice('Select an event first.');return}
      try {const result=await api('/api/mark',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({run_id:selectedRun,event_id:selectedEvent,reason:el('mark-reason').value})});
        notice(`Marked event ${result.source_event_seq} as ${result.classification}`);await showRun(selectedRun,true)
      } catch(error){notice(error.message)}
    };
    el('view-toggle').onclick=()=>{const timeline=el('timeline'),list=timeline.classList.toggle('list-mode');timeline.classList.toggle('track-mode',!list);el('view-toggle').textContent=list?'Snapshot track':'List view';localStorage.setItem('mangekyo-timeline-view',list?'list':'track')};
    if(localStorage.getItem('mangekyo-timeline-view')==='list')el('view-toggle').click();
    el('chat-toggle').onclick=async()=>{
      el('chat-panel').hidden=false;
      try { await chatModel();chatRuns() } catch(error) { chatNotice(error.message) }
    };
    el('chat-close').onclick=()=>{el('chat-panel').hidden=true};
    el('chat-change-model').onclick=()=>{el('chat-workspace').hidden=true;el('chat-setup').hidden=false};
    el('chat-run').onchange=()=>{chatSession=null;chatMessages([]);chatNotice('Started a new conversation for the selected run.')};
    el('chat-provider').onchange=()=>{
      const provider=el('chat-provider').value;
      el('chat-key').value='';
      el('chat-key-env').value='';
      el('chat-endpoint').value='';
      el('chat-endpoint').placeholder=provider==='local'?'http://127.0.0.1:11434/v1':'https://provider.example/v1';
      el('chat-key-env').placeholder=provider==='openai'?'OPENAI_API_KEY':provider==='openrouter'?'OPENROUTER_API_KEY':'MODEL_API_KEY';
      el('chat-openrouter-signin').hidden=provider!=='openrouter';
    };
    el('chat-openrouter-signin').onclick=async()=>{
      const model=el('chat-model').value.trim();
      if(!model){chatNotice('Enter an OpenRouter model name first.');return}
      const bytes=crypto.getRandomValues(new Uint8Array(32));
      const verifier=Array.from(bytes,byte=>String.fromCharCode(byte)).join('');
      const verifierEncoded=btoa(verifier).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifierEncoded));
      const challenge=btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
      const state=crypto.randomUUID();
      sessionStorage.setItem('mangekyo-openrouter-oauth',JSON.stringify({verifier:verifierEncoded,state,model}));
      const url=new URL('https://openrouter.ai/auth');
      url.searchParams.set('callback_url',location.origin+'/');
      url.searchParams.set('code_challenge',challenge);
      url.searchParams.set('code_challenge_method','S256');
      url.searchParams.set('key_label','Mangekyo Agent');
      url.searchParams.set('state',state);
      location.href=url.href;
    };
    async function completeOpenRouterSignIn() {
      const params=new URLSearchParams(location.search),code=params.get('code');
      if(!code)return;
      history.replaceState(null,'',location.pathname);
      el('chat-panel').hidden=false;
      const pending=JSON.parse(sessionStorage.getItem('mangekyo-openrouter-oauth')||'null');
      sessionStorage.removeItem('mangekyo-openrouter-oauth');
      if(!pending||pending.state!==params.get('state')){chatNotice('OpenRouter sign-in state did not match. Try again.');return}
      chatNotice('Completing OpenRouter sign-in…');
      try {
        await api('/api/chat/oauth/exchange',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({code,verifier:pending.verifier,model:pending.model})});
        await chatModel();chatNotice('OpenRouter connected.');
      } catch(error){el('chat-setup').hidden=false;chatNotice(error.message)}
    }
    el('chat-connect').onclick=async()=>{
      const button=el('chat-connect');button.disabled=true;chatNotice('Testing model connection…');
      try {
        const body={provider:el('chat-provider').value,model:el('chat-model').value,
          base_url:el('chat-endpoint').value||undefined,api_key:el('chat-key').value||undefined,
          key_env:el('chat-key-env').value||undefined};
        await api('/api/chat/model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        el('chat-key').value='';await chatModel();chatNotice('Model connected. Select a run and ask a question.');
      } catch(error) {chatNotice(error.message)} finally {button.disabled=false}
    };
    el('chat-send').onclick=async()=>{
      const prompt=el('chat-input').value.trim();if(!prompt)return;
      const button=el('chat-send');button.disabled=true;chatNotice('Thinking…');
      try {
        const result=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({prompt,session:chatSession,run_id:el('chat-run').value||null})});
        chatSession=result.session;el('chat-input').value='';chatMessages(result.messages);chatNotice('Ready');
      } catch(error) {chatNotice(error.message)} finally {button.disabled=false}
    };
    el('chat-input').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();el('chat-send').click()}};
    async function loadProject() {
      try {
        const data=await api('/api/project');
        if(data.project){el('project-path').value=data.project;el('project-status').textContent=data.launch?'Ready to launch '+data.project:'Connected; configure a launch command in the project'}
        else el('project-status').textContent='Connect a Python agent folder to launch runs here.';
        el('project-launch').disabled=!data.launch;
      } catch(error) {el('project-status').textContent=error.message}
    }
    el('project-add').onclick=async()=>{
      const button=el('project-add');button.disabled=true;el('project-status').textContent='Connecting agent…';
      try {
        const result=await api('/api/project',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({path:el('project-path').value})});
        el('project-status').textContent=result.launch?`Connected ${result.project}. Ready to launch.`:`Connected ${result.project}; no launch command found.`;
        await loadProject();
      } catch(error){el('project-status').textContent=error.message}finally{button.disabled=false}
    };
    el('project-launch').onclick=async()=>{
      const button=el('project-launch');button.disabled=true;el('project-status').textContent='Launching agent…';
      try {const result=await api('/api/project/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        el('project-status').textContent=`Agent process ${result.pid} started. The run will appear below.`;await load(true)
      } catch(error){el('project-status').textContent=error.message}finally{button.disabled=false}
    };
    el('refresh').onclick=()=>load(true);
    loadProject();
    load();
    completeOpenRouterSignIn();
    setInterval(async()=>{
      if(document.hidden||refreshBusy)return;
      refreshBusy=true;
      try{await load(true)}finally{refreshBusy=false}
    },1200);
