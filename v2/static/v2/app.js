let state={page:1,pageSize:30,total:0,nPages:1,rows:[],selectedRun:null,selectedRuns:new Set(),plotData:null,waveIdx:0,activeScienceRun:''};
const $=id=>document.getElementById(id);

function fmt(v){if(!v)return '';try{return new Date(v).toLocaleString();}catch{return String(v)}}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
function debounce(fn, ms=300){
  let t=null;
  return (...args)=>{
    if(t) clearTimeout(t);
    t=setTimeout(()=>fn(...args), ms);
  };
}

async function fetchRuns(){
  const q=encodeURIComponent($('search').value||'');
  const st=encodeURIComponent($('statusFilter').value||'');
  const sr=encodeURIComponent($('srFilter').value||'');
  const rc=encodeURIComponent($('runClassFilter').value||'');
  const src=encodeURIComponent($('sourceTypeFilter').value||'');
  const mode=encodeURIComponent($('runModeFilter').value||'');
  const useActiveSr=sr&&sr!=='all'?'0':'1';
  const r=await fetch(`/api/runs?page=${state.page}&page_size=${state.pageSize}&q=${q}&status=${st}&science_run_id=${sr}&run_class=${rc}&source_type=${src}&run_mode=${mode}&use_active_sr=${useActiveSr}`);
  const j=await r.json(); Object.assign(state,{total:j.total,nPages:j.n_pages,page:j.page,rows:j.rows,activeScienceRun:j.active_science_run||''});
  $('activeSrBadge').textContent=state.activeScienceRun?`(active: ${state.activeScienceRun})`:'';
  if(!state.selectedRun && state.rows.length){
    state.selectedRun=state.rows[0].run_id;
    history.replaceState(null,'',`?run_id=${state.selectedRun}`);
  }
  renderRuns();
}

function renderRuns(){
  const tb=$('runsTable').querySelector('tbody'); tb.innerHTML='';
  for(const row of state.rows){
    const tr=document.createElement('tr'); if(state.selectedRun===row.run_id)tr.classList.add('selected');
    tr.innerHTML=`<td><input type="checkbox" ${state.selectedRuns.has(row.run_id)?'checked':''}></td><td>${row.run_id}</td><td>${esc(row.science_run_id||'-')}</td><td>${esc(row.run_class||'-')}</td><td>${esc(row.source_type||'-')}</td><td>${esc(row.mode)}</td><td class="${row.has_raw_records?'good':'bad'}">${row.has_raw_records?'yes':'no'}</td><td class="${row.has_event_info?'good':'warn'}">${row.has_event_info?'yes':'no'}</td><td>${esc(row.status)}</td><td>${fmt(row.start)}</td>`;
    tr.querySelector('input').addEventListener('click',e=>{e.stopPropagation(); if(e.target.checked)state.selectedRuns.add(row.run_id); else state.selectedRuns.delete(row.run_id)});
    tr.addEventListener('click',()=>{state.selectedRun=row.run_id; history.replaceState(null,'',`?run_id=${row.run_id}`); renderRuns(); loadRun(row.run_id)});
    tb.appendChild(tr);
  }
  $('pageInfo').textContent=`Page ${state.page}/${state.nPages} (${state.total} runs)`;
  updateSelectionSummary();
}

async function loadRun(runId){
  $('plotStatus').textContent='Loading run...';
  const runP=fetch(`/api/run/${runId}`).then(r=>r.ok?r.json():Promise.reject(new Error(`run ${r.status}`)));
  const avP=fetch(`/api/run/${runId}/availability`).then(r=>r.ok?r.json():Promise.reject(new Error(`availability ${r.status}`)));
  const plP=fetch(`/api/run/${runId}/plot-data?max_points=100000&max_peaks=150000&max_waveforms=40`).then(r=>r.ok?r.json():Promise.reject(new Error(`plot ${r.status}`)));

  const [runR,avR,plR]=await Promise.allSettled([runP,avP,plP]);

  if(runR.status==='fulfilled'){
    const run=runR.value; const ps=run.processing_status||{};
    const xbk=(run.raw_doc&&run.raw_doc.xams_bookkeeping)||{};
    const ph=(run.raw_doc&&run.raw_doc.processing_history)||[];
    $('runSummary').textContent=`Run: ${run.run_id}\nScience Run: ${xbk.science_run_id||'-'}\nClass: ${xbk.run_class||'-'}\nSource: ${xbk.source_type||'-'}\nMode: ${run.mode}\nStart: ${fmt(run.start)}\nEnd: ${fmt(run.end)}\nStatus: ${ps.status||'unknown'} @ ${fmt(ps.time)}\nTags: ${(run.tags||[]).map(t=>t.name).join(', ')||'-'}\nComments: ${(run.comments||[]).length}\nProcessing history entries: ${ph.length}`;
    $('runJson').value=JSON.stringify(run.raw_doc||{},null,2);
  }else{
    $('runSummary').textContent=`Run: ${runId}\nDetails failed to load`;
    $('runJson').value='';
  }

  const ab=$('availTable').querySelector('tbody'); ab.innerHTML='';
  if(avR.status==='fulfilled'){
    for(const r of avR.value){
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${esc(r.type)}</td><td>${esc(r.lineage_hash)}</td><td>${esc(r.current_lineage_hash||'')}</td><td class="${r.loadable?'good':'warn'}">${r.loadable?'yes':'no'}</td><td>${r.n_files}</td><td>${r.size_mb}</td><td>${(r.db_is_online===true)?'yes':((r.db_is_online===false)?'no':'')}</td><td>${esc(r.db_corrections_version||'')}</td><td>${esc(r.db_amstrax_version||'')}</td><td>${esc(r.reason)}</td>`;
      ab.appendChild(tr);
    }
  }

  if(plR.status==='fulfilled'){
    state.plotData=plR.value;
    state.waveIdx=0;
    renderPlots();
    $('plotStatus').textContent=state.plotData.reason||'';
  }else{
    state.plotData={};
    $('plotStatus').textContent='Plot data failed to load';
    renderPlots();
  }
  loadJobLogs(runId);
  loadCorrectionsCompatibility(runId);
}

function rebin2D(x,y,bx,by){
  if(!x.length||!y.length)return {z:[],x:[],y:[]};
  let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
  const n=Math.min(x.length,y.length);
  for(let i=0;i<n;i++){
    const xv=Number(x[i]), yv=Number(y[i]);
    if(!Number.isFinite(xv) || !Number.isFinite(yv)) continue;
    if(xv<xmin)xmin=xv; if(xv>xmax)xmax=xv;
    if(yv<ymin)ymin=yv; if(yv>ymax)ymax=yv;
  }
  if(!Number.isFinite(xmin) || !Number.isFinite(xmax) || !Number.isFinite(ymin) || !Number.isFinite(ymax)){
    return {z:[],x:[],y:[]};
  }
  const z=Array.from({length:by},()=>Array(bx).fill(0));
  for(let i=0;i<n;i++){
    const xv=Number(x[i]), yv=Number(y[i]);
    if(!Number.isFinite(xv) || !Number.isFinite(yv)) continue;
    const xi=Math.min(bx-1,Math.max(0,Math.floor((xv-xmin)/(xmax-xmin+1e-12)*bx)));
    const yi=Math.min(by-1,Math.max(0,Math.floor((yv-ymin)/(ymax-ymin+1e-12)*by)));
    z[yi][xi]++;
  }
  const xv=Array.from({length:bx},(_,i)=>xmin+(i+0.5)*(xmax-xmin)/bx);
  const yv=Array.from({length:by},(_,i)=>ymin+(i+0.5)*(ymax-ymin)/by);
  return {z,x:xv,y:yv};
}

function renderPlots(){
  const d=state.plotData||{};
  const binsDrift=parseInt($('binsDrift').value,10)||120;
  const binsS1S2=parseInt($('binsS1S2').value,10)||120;
  const binsXY=parseInt($('binsXY').value,10)||120;
  const binsPeak=parseInt($('binsPeak').value,10)||160;
  const log=$('logY').checked;
  const xyEqual=$('xyEqual').checked;
  $('plotStatus').textContent=d.reason||'';

  if(d.plot_mode==='led' || d.is_led_run){
    const ledArea=d.led_area||[];
    const ledOn=d.led_amplitude_led||[];
    const ledOff=d.led_amplitude_noise||[];
    const ledDiff=d.led_amplitude_diff||[];
    const ledCh=(d.led_channel||[]).map(v=>Number(v)).filter(v=>Number.isFinite(v));

    Plotly.newPlot('driftPlot',[{x:ledArea,type:'histogram',nbinsx:binsDrift,marker:{color:'#56cfe1'}}],{title:'LED: Area distribution',xaxis:{title:'Area (ADC*sample)'},yaxis:{title:'Counts'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    const hLed=rebin2D(ledOn,ledOff,binsS1S2,binsS1S2);
    Plotly.newPlot('s1s2Plot',[{x:hLed.x,y:hLed.y,z:applyLogIfNeeded(hLed.z,log),type:'heatmap',colorscale:'Cividis',colorbar:{title:log?'log10(counts+1)':'counts'},hovertemplate:'amp_led=%{x:.2f}<br>amp_noise=%{y:.2f}<br>n=%{z}<extra></extra>'}],{title:'LED: amplitude_led vs amplitude_noise',xaxis:{title:'Amplitude LED window'},yaxis:{title:'Amplitude noise window'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    Plotly.newPlot('xyPlot',[{x:ledCh,type:'histogram',nbinsx:Math.min(200,binsXY),marker:{color:'#90be6d'}}],{title:'LED: channel occupancy',xaxis:{title:'Channel'},yaxis:{title:'Counts'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    Plotly.newPlot('peakAreaAftPlot',[{x:ledDiff,type:'histogram',nbinsx:binsPeak,marker:{color:'#ffafcc'}}],{title:'LED: amplitude_led - amplitude_noise',xaxis:{title:'Amplitude difference'},yaxis:{title:'Counts'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    Plotly.newPlot('peakAreaWidthPlot',[{x:ledOff,type:'histogram',nbinsx:binsPeak,marker:{color:'#bde0fe'}}],{title:'LED: noise amplitude distribution',xaxis:{title:'Noise amplitude'},yaxis:{title:'Counts'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});

    const wfs=d.waveforms||[];
    if(wfs.length){
      state.waveIdx=Math.max(0,Math.min(state.waveIdx,wfs.length-1));
      const wf=wfs[state.waveIdx];
      $('waveInfo').textContent=`Record ${state.waveIdx+1}/${wfs.length}`;
      Plotly.newPlot('waveformPlot',[{x:wf.t_ns||[],y:wf.amp||[],mode:'lines',line:{color:'#80ed99',width:2},name:'records_led'}],{title:'LED records waveform browser',xaxis:{title:'Time in record (ns)'},yaxis:{title:'Amplitude'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    }else{
      $('waveInfo').textContent='No waveform loaded';
      Plotly.newPlot('waveformPlot',[],{title:'LED waveforms not available',xaxis:{title:'time (ns)'},yaxis:{title:'amplitude'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
    }
    return;
  }

  Plotly.newPlot('driftPlot',[{x:d.drift_time||[],type:'histogram',nbinsx:binsDrift,marker:{color:'#56cfe1'}}],{title:'Drift Time',xaxis:{title:'Drift time (ns)'},yaxis:{title:'Counts'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
  const s1=d.s1_area||[], s2=d.s2_area||[]; const h1=rebin2D(s1,s2,binsS1S2,binsS1S2);
  Plotly.newPlot('s1s2Plot',[{x:h1.x,y:h1.y,z:h1.z,type:'heatmap',colorscale:'Cividis',zsmooth:false,zmin:0,z:applyLogIfNeeded(h1.z,log),colorbar:{title:log?'log10(counts+1)':'counts'},hovertemplate:'S1=%{x:.2f}<br>S2=%{y:.2f}<br>n=%{z}<extra></extra>'}],{title:'S1 vs S2',xaxis:{title:'S1 area (PE)'},yaxis:{title:'S2 area (PE)'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
  const x=d.x||[], y=d.y||[]; const h2=rebin2D(x,y,binsXY,binsXY);
  const xyLayout={title:'XY Position',xaxis:{title:'x'},yaxis:{title:'y'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}};
  if(xyEqual){xyLayout.yaxis.scaleanchor='x';xyLayout.yaxis.scaleratio=1;}
  Plotly.newPlot('xyPlot',[{x:h2.x,y:h2.y,z:applyLogIfNeeded(h2.z,log),type:'heatmap',colorscale:'IceFire',colorbar:{title:log?'log10(counts+1)':'counts'},hovertemplate:'x=%{x:.2f}<br>y=%{y:.2f}<br>n=%{z}<extra></extra>'}],xyLayout);

  const pa=d.peak_area||[], aft=d.peak_aft||[]; const h3=rebin2D(pa,aft,binsPeak,binsPeak);
  Plotly.newPlot('peakAreaAftPlot',[{x:h3.x,y:h3.y,z:applyLogIfNeeded(h3.z,log),type:'heatmap',colorscale:'YlGnBu',colorbar:{title:log?'log10(counts+1)':'counts'}}],{title:'Peak Basics: Area vs AFT',xaxis:{title:'Area (PE)',type:'log'},yaxis:{title:'Area fraction top'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});

  const pAreaW=d.peak_area_width||d.peak_area||[], pW=d.peak_width_50||[]; const h4=rebin2D(pAreaW,pW,binsPeak,binsPeak);
  Plotly.newPlot('peakAreaWidthPlot',[{x:h4.x,y:h4.y,z:applyLogIfNeeded(h4.z,log),type:'heatmap',colorscale:'Magma',colorbar:{title:log?'log10(counts+1)':'counts'}}],{title:'Peak Basics: Area vs Width50',xaxis:{title:'Area (PE)',type:'log'},yaxis:{title:'Range 50% area / Rise time (ns)',type:'log'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});

  const wfs=d.waveforms||[];
  if(wfs.length){
    state.waveIdx=Math.max(0,Math.min(state.waveIdx,wfs.length-1));
    const wf=wfs[state.waveIdx];
    $('waveInfo').textContent=`Waveform ${state.waveIdx+1}/${wfs.length}  area=${(wf.area||0).toFixed(1)} PE`;
    Plotly.newPlot('waveformPlot',[{x:wf.t_ns||[],y:wf.amp||[],mode:'lines',line:{color:'#80ed99',width:2},name:'waveform'}],{title:'Peak waveform browser (first second)',xaxis:{title:'Time in peak (ns)'},yaxis:{title:'Amplitude'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
  }else{
    $('waveInfo').textContent='No waveform loaded';
    Plotly.newPlot('waveformPlot',[],{title:'Sample Peak Waveforms (not available)',xaxis:{title:'time (ns)'},yaxis:{title:'amplitude'},paper_bgcolor:'#0f1729',plot_bgcolor:'#0f1729',font:{color:'#dce7ff'}});
  }
}

function applyLogIfNeeded(z, useLog){
  if(!useLog) return z;
  return z.map(row=>row.map(v=>Math.log10((Number(v)||0)+1)));
}

async function deleteRunIds(run_ids, label){
  if(!run_ids.length){$('submitResult').textContent='No run selected';return;}
  const word=run_ids.length===1?'run':'runs';
  if(!confirm(`Delete ALL data for ${run_ids.length} ${word} (${label})?\n\nThis wipes every data directory from disk and clears the data entries in the DB.\n\nThis cannot be undone.`)) return;
  $('submitResult').textContent=`Deleting data for ${run_ids.length} ${word}...`;
  if($('submitDetails')) $('submitDetails').textContent='';
  const lines=[];
  for(const runId of run_ids){
    try{
      const r=await fetch(`/api/run/${runId}/delete_data`,{method:'POST'});
      const j=await r.json();
      lines.push(`run ${runId}: deleted ${j.n_deleted} dir(s)${j.n_errors?' | '+j.n_errors+' error(s)':''} | DB ${j.db.modified?'updated':'unchanged'}`);
    }catch(e){
      lines.push(`run ${runId}: request failed - ${e}`);
    }
  }
  $('submitResult').textContent=`Done deleting ${run_ids.length} ${word}`;
  if($('submitDetails')) $('submitDetails').textContent=lines.join('\n');
  fetchRuns();
}

async function deleteFocused(){
  const runId=state.selectedRun;
  if(!runId){$('submitResult').textContent='No focused run';return;}
  await deleteRunIds([runId],'focused');
}

async function deleteSelected(){
  const run_ids=[...state.selectedRuns];
  if(!run_ids.length){$('submitResult').textContent='Select runs first';return;}
  await deleteRunIds(run_ids,'selected');
}

async function submitSelected(){
  const run_ids=[...state.selectedRuns]; if(!run_ids.length){$('submitResult').textContent='Select runs first';return;}
  await submitRunIds(run_ids, 'selected');
}

async function submitFocused(){
  const runId=state.selectedRun;
  if(!runId){$('submitResult').textContent='No focused run';return;}
  await submitRunIds([runId], 'focused');
}

async function submitRunIds(run_ids, label){
  const amstrax_ref=($('amstraxRef').value||'').trim();
  const corrections_version=($('corrVersion').value||'').trim();
  const resource_profile=($('resourceProfile').value||'8gb').trim();
  $('submitResult').textContent=`Submitting ${label}...`;
  if($('submitDetails')) $('submitDetails').textContent='';
  const r=await fetch('/api/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_ids,targets:['peak_basics','event_basics','event_positions','event_info'],amstrax_ref,corrections_version,resource_profile})});
  const j=await r.json();
  $('submitResult').textContent=`Submitted ${j.submitted}, skipped ${j.skipped}, failed ${j.failed}`;
  const results=(j.results||[]);
  const lines=[];
  for(const row of results){
    const runId=row.run_id;
    if(row.submitted){
      lines.push(`run ${runId}: submitted`);
      continue;
    }
    if(row.status==='skipped'){
      lines.push(`run ${runId}: skipped - ${row.reason||'already loadable'}`);
      continue;
    }
    const err=(row.stderr||row.reason||`failed (code ${row.returncode ?? 'unknown'})`).toString();
    lines.push(`run ${runId}: failed - ${err}`);
  }
  if($('submitDetails')){
    $('submitDetails').textContent = lines.length ? lines.join('\n') : 'No detailed result returned.';
  }
  fetchRuns();
}

async function loadMeta(){
  const r=await fetch('/api/meta');
  const j=await r.json();
  state.activeScienceRun=j.active_science_run||'';
  const srSel=$('srFilter');
  const prev=srSel.value;
  srSel.innerHTML=`<option value="">Active SR</option><option value="all">All SR</option>`;
  for(const sr of (j.science_runs||[])){
    const opt=document.createElement('option'); opt.value=sr; opt.textContent=sr; srSel.appendChild(opt);
  }
  if(prev) srSel.value=prev;
  const modeSel=$('runModeFilter');
  const prevMode=modeSel.value;
  modeSel.innerHTML='<option value="">All modes</option>';
  for(const m of (j.run_modes||[])){
    const opt=document.createElement('option'); opt.value=m; opt.textContent=m; modeSel.appendChild(opt);
  }
  if(prevMode) modeSel.value=prevMode;
}

async function refreshHeldJobs(){
  const r=await fetch('/api/held-jobs');
  const j=await r.json();
  $('heldJobs').textContent=String((j.rows||[]).length);
  try{
    const rq=await fetch('/api/jobs');
    const jq=await rq.json();
    const c=jq.counts||{};
    $('heldJobs').textContent=`held ${c.held||0}, running ${c.running||0}, idle ${c.idle||0}`;
    const rows=(jq.rows||[]).slice(0,8);
    $('jobsList').textContent=rows.map(r=>`${r.cluster_id}.${r.proc_id} ${r.status} ${r.batch_name||''}`).join('\n');
  }catch(_e){}
}

function showSelected(){
  const run_ids=[...state.selectedRuns];
  const runId=run_ids.length?run_ids[0]:state.selectedRun;
  if(!runId){$('submitResult').textContent='No run selected';return;}
  state.selectedRun=runId;
  history.replaceState(null,'',`?run_id=${runId}`);
  renderRuns();
  loadRun(runId);
  setActiveTab('inspect');
}

function updateSelectionSummary(){
  const focused = state.selectedRun ? String(state.selectedRun) : 'none';
  const ids = [...state.selectedRuns].sort((a,b)=>a-b);
  const preview = ids.length ? (ids.slice(0, 12).join(', ') + (ids.length > 12 ? ' ...' : '')) : '-';
  if($('focusedRunId')) $('focusedRunId').textContent = focused;
  if($('selectedCount')) $('selectedCount').textContent = String(ids.length);
  if($('selectedRunIds')) $('selectedRunIds').textContent = preview;
}

function selectPageRuns(){
  for(const row of state.rows){ state.selectedRuns.add(row.run_id); }
  renderRuns();
}

function clearSelection(){
  state.selectedRuns.clear();
  renderRuns();
}

async function loadJobLogs(runId){
  try{
    const r=await fetch(`/api/run/${runId}/job-logs?limit=6`);
    const j=await r.json();
    const files=j.files||[];
    if(!files.length){
      $('jobLogs').textContent='No matching log files found.';
      return;
    }
    const text=files.map(f=>{
      const head=`[${f.name}] mtime=${f.mtime} size=${f.size_bytes}`;
      const tail=(f.tail||'').trim();
      return `${head}\n${tail.slice(-2200)}`;
    }).join('\n\n------------------------------\n\n');
    $('jobLogs').textContent=text;
  }catch(_e){
    $('jobLogs').textContent='Failed to load logs.';
  }
}

async function loadCorrectionsCompatibility(runId){
  try{
    const r=await fetch(`/api/run/${runId}/corrections-compat`);
    const j=await r.json();
    const rows=j.rows||[];
    if(!rows.length){
      $('corrCompat').textContent='No correction versions discovered.';
      return;
    }
    const lines=rows.map(x=>`${x.compatible?'OK ':'NO '} ${x.version}${x.compatible?'':` - ${x.reason||'not compatible'}`}`);
    $('corrCompat').textContent=lines.join('\n');
  }catch(_e){
    $('corrCompat').textContent='Failed to load corrections compatibility.';
  }
}

function setActiveTab(name){
  document.querySelectorAll('.tab-btn').forEach(btn=>{
    btn.classList.toggle('active', btn.dataset.tab===name);
  });
  document.querySelectorAll('.tab-content').forEach(el=>{
    el.classList.toggle('active', el.id===`tab-${name}`);
  });
}

function init(){
  $('refreshBtn').onclick=()=>fetchRuns();
  const onSearch=debounce(()=>{state.page=1;fetchRuns()}, 300);
  const onSource=debounce(()=>{state.page=1;fetchRuns()}, 300);
  $('search').oninput=onSearch;
  $('statusFilter').onchange=()=>{state.page=1;fetchRuns()};
  $('srFilter').onchange=()=>{state.page=1;fetchRuns()};
  $('runClassFilter').onchange=()=>{state.page=1;fetchRuns()};
  $('sourceTypeFilter').oninput=onSource;
  $('runModeFilter').onchange=()=>{state.page=1;fetchRuns()};
  $('prevPage').onclick=()=>{state.page=Math.max(1,state.page-1);fetchRuns()};
  $('nextPage').onclick=()=>{state.page=Math.min(state.nPages,state.page+1);fetchRuns()};
  $('submitSelected').onclick=submitSelected;
  $('submitFocused').onclick=submitFocused;
  $('deleteFocused').onclick=deleteFocused;
  $('deleteSelected').onclick=deleteSelected;
  $('selectPage').onclick=selectPageRuns;
  $('clearSelection').onclick=clearSelection;
  $('showSelected').onclick=showSelected;
  $('refreshJobLogs').onclick=()=>{if(state.selectedRun) loadJobLogs(state.selectedRun)};
  $('refreshCorrCompat').onclick=()=>{if(state.selectedRun) loadCorrectionsCompatibility(state.selectedRun)};
  $('binsDrift').oninput=()=>renderPlots();
  $('binsS1S2').oninput=()=>renderPlots();
  $('binsXY').oninput=()=>renderPlots();
  $('binsPeak').oninput=()=>renderPlots();
  $('xyEqual').onchange=()=>renderPlots();
  $('logY').onchange=()=>renderPlots();
  $('wavePrev').onclick=()=>{state.waveIdx=Math.max(0,state.waveIdx-1); renderPlots();};
  $('waveNext').onclick=()=>{const n=(state.plotData&&state.plotData.waveforms?state.plotData.waveforms.length:0); if(!n)return; state.waveIdx=Math.min(n-1,state.waveIdx+1); renderPlots();};
  document.querySelectorAll('.tab-btn').forEach(btn=>{
    btn.onclick=()=>setActiveTab(btn.dataset.tab);
  });
  const u=new URL(window.location.href); const rid=u.searchParams.get('run_id'); if(rid){state.selectedRun=parseInt(rid,10)}
  setActiveTab('inspect');
  updateSelectionSummary();
  loadMeta().then(()=>fetchRuns().then(()=>{if(state.selectedRun)loadRun(state.selectedRun)}));
  refreshHeldJobs();
  setInterval(refreshHeldJobs, 20000);
}

document.addEventListener('DOMContentLoaded',init);
