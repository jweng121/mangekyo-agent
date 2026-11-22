    const el = id => document.getElementById(id);
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const pretty = value => esc(JSON.stringify(value, null, 2));
    let selectedRun = null, selectedSnapshot = null, selectedBranch = null, currentArtifacts = [];
    async function api(path, options) { const r = await fetch(path, options); const value = await r.json(); if (!r.ok) throw Error(value.error || `HTTP ${r.status}`); return value; }
    function notice(text) { el('notice').textContent = text; }
    async function load() {
      try {
        const data = await api('/api/runs');
        el('store-path').textContent='Store: '+data.store;
        el('runs').innerHTML = data.runs.length ? data.runs.map(r => `<div class="item ${r.id===selectedRun?'active':''}" data-run="${esc(r.id)}"><strong>${esc(r.label)}</strong><span class="pill ${r.status==='failed'?'fail':'ok'}">${esc(r.status)}</span><span class="muted">${esc(r.id)}</span></div>`).join('') : '<div class="empty">No runs yet. Run <code>mangekyo demo</code> in a terminal.</div>';
        el('branches').innerHTML = data.branches.length ? data.branches.map(b => `<div class="item" data-branch="${esc(b.name)}"><strong>${esc(b.name)}</strong><span class="muted">${esc(b.result_run || 'Not resumed')}</span></div>`).join('') : '<div class="empty">No branches yet.</div>';
        document.querySelectorAll('[data-run]').forEach(n => n.onclick=()=>showRun(n.dataset.run));
        document.querySelectorAll('[data-branch]').forEach(n => n.onclick=()=>showBranch(n.dataset.branch, data.branches));
        if (!selectedRun && data.runs.length) await showRun(data.runs[0].id);
      } catch(e) { notice(e.message); }
    }
    async function showRun(id) {
      try {
        selectedRun=id; selectedSnapshot=null;
        const data=await api('/api/run/'+encodeURIComponent(id));
        currentArtifacts=data.artifacts;
        el('summary').innerHTML=`<strong>${esc(data.run.label)}</strong><br><span class="muted">${esc(data.run.id)} · ${esc(data.run.status)} · adapter ${esc(data.run.adapter)}</span>`;
        el('events').innerHTML=data.events.map(e=>`<div class="item ${e.kind==='error'?'fail':''}" data-event="${esc(e.id)}"><span class="pill">${e.seq}</span><strong>${esc(e.kind)}</strong><span class="muted">${esc(JSON.stringify(e.payload).slice(0,110))}</span></div>`).join('');
        document.querySelectorAll('[data-event]').forEach(n=>n.onclick=()=>showEvent(data.events.find(e=>e.id===n.dataset.event)));
        el('artifacts').innerHTML=data.artifacts.length ? data.artifacts.map(a=>`<div class="item" data-artifact="${esc(a.id)}"><strong>${esc(a.name)}</strong><span class="muted">${esc(a.mime)} · ${esc(a.id)}</span></div>`).join('') : '<div class="empty">No captured documents or screenshots for this run.</div>';
        document.querySelectorAll('[data-artifact]').forEach(n=>n.onclick=()=>showArtifact(n.dataset.artifact));
        el('inspector').innerHTML=`<div class="muted">Select a timeline event.</div><h2>Benchmark</h2><pre>${pretty(data.benchmark || {note:'No benchmark for this adapter'})}</pre>`;
        await loadListOnly();
      } catch(e) { notice(e.message); }
    }
    async function loadListOnly() { document.querySelectorAll('[data-run]').forEach(n=>n.classList.toggle('active',n.dataset.run===selectedRun)); }
    async function showEvent(event) {
      selectedSnapshot=event.snapshot_id;
      let html=`<div class="muted">Event ${esc(event.id)} · ${esc(event.kind)}</div><pre>${pretty(event.payload)}</pre>`;
      if (selectedSnapshot) {
        const data=await api('/api/snapshot/'+encodeURIComponent(selectedSnapshot));
        html+=`<h2>Snapshot ${esc(selectedSnapshot)}</h2><div class="muted">${data.environment_restorable?'Simulation environment checkpoint available':'Context only; no environment restore'}</div><pre>${pretty(data.context)}</pre>`;
        html+=`<div class="form"><label>New branch name</label><input id="branch-name" value="fix-${esc(selectedSnapshot.slice(0,5))}"><label>Reference correction</label><input id="replacement" value="safe"><button id="create-branch">Create branch</button></div>`;
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
        const body={snapshot:selectedSnapshot,name:el('branch-name').value,replacement:el('replacement').value};
        await api('/api/branch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        notice(`Created branch ${body.name}`); await load();
      } catch(e) { notice(e.message); }
    }
    async function showBranch(name, branches) {
      const branch=branches.find(b=>b.name===name); selectedBranch=name;
      const comparison=await api('/api/branch/'+encodeURIComponent(name));
      const available=!comparison.resume_unavailable_reason;
      el('inspector').innerHTML=`<div class="muted">Branch from snapshot ${esc(branch.source_snapshot)}</div><h2>Correction</h2><pre>${pretty(comparison.correction)}</pre><h2>Context comparison</h2><div class="muted">Changed: ${esc(comparison.changed.join(', ') || (comparison.after?'none':'Resume to compare'))}</div><pre>${pretty({original:comparison.before,corrected:comparison.after})}</pre>${available?'<button id="resume">Restore simulation and resume</button>':`<div class="muted">Resume unavailable: ${esc(comparison.resume_unavailable_reason)}</div>`}`;
      if(available) el('resume').onclick=async()=>{ try {const result=await api('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({branch:name})});notice(`Resumed as ${result.run_id}; skipped ${result.skipped_steps} steps`);await load();await showRun(result.run_id);}catch(e){notice(e.message)} };
    }
    el('refresh').onclick=load; load();
