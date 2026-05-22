const $ = (id) => document.getElementById(id);

function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}

function renderAmstraxInfo(a){
  const tb = $('amstraxInfoTable').querySelector('tbody');
  tb.innerHTML = '';
  const rows = [
    ['Path', a.path || '-'],
    ['Exists', a.exists ? 'yes' : 'no'],
    ['Version', a.version || '-'],
    ['Branch', a.branch || '-'],
    ['Commit', a.commit || '-'],
  ];
  for(const [k,v] of rows){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${esc(k)}</td><td><code>${esc(v)}</code></td>`;
    tb.appendChild(tr);
  }
}

function renderSummaryTable(entries){
  const tb = $('corrSummaryTable').querySelector('tbody');
  tb.innerHTML = '';
  if(!entries || !entries.length){
    const tr=document.createElement('tr');
    tr.innerHTML='<td colspan="5" class="hint">No correction entries.</td>';
    tb.appendChild(tr);
    return;
  }
  for(const e of entries){
    const tr=document.createElement('tr');
    const badge = e.ok ? '<span class="badge-good">OK</span>' : '<span class="badge-bad">NO</span>';
    tr.innerHTML = `
      <td>${badge}</td>
      <td><code>${esc(e.key)}</code></td>
      <td><code>${esc(e.file || '-')}</code></td>
      <td><code>${esc(e.matched_rule || '-')}</code></td>
      <td><code>${esc(e.value_preview || '-')}</code></td>
    `;
    tb.appendChild(tr);
  }
}

async function loadAmstraxInfo(){
  const p=($('amstraxPath').value||'').trim();
  const q=p?`?amstrax_path=${encodeURIComponent(p)}`:'';
  const r=await fetch(`/api/corrections/meta${q}`);
  const j=await r.json();
  const a=j.amstrax||{};
  renderAmstraxInfo(a);
  const sel=$('corrVersionSel');
  const current=sel.value;
  sel.innerHTML='';
  for(const v of (j.corrections_versions||[])){
    const o=document.createElement('option'); o.value=v; o.textContent=v; sel.appendChild(o);
  }
  if(current) sel.value=current;
}

async function loadLatestRunDefault(){
  const r=await fetch('/api/runs?page=1&page_size=1&use_active_sr=0');
  const j=await r.json();
  const rid=(j.rows&&j.rows.length)?j.rows[0].run_id:'';
  if(rid && !$('corrRunId').value) $('corrRunId').value=rid;
}

async function loadSummary(){
  const runId=($('corrRunId').value||'').trim();
  const ver=($('corrVersionSel').value||'ONLINE').trim();
  if(!runId){$('corrSummaryMeta').textContent='Set run id first.';return;}
  $('corrSummaryMeta').textContent='Loading...';
  const r=await fetch(`/api/corrections/summary?run_id=${encodeURIComponent(runId)}&corrections_version=${encodeURIComponent(ver)}`);
  const j=await r.json();
  if(j.error){$('corrSummaryMeta').textContent=`Error: ${j.error}`; renderSummaryTable([]); return;}
  $('corrSummaryMeta').textContent = `Run ${j.run_id} | Version ${j.corrections_version} | Overall compatible: ${j.ok?'yes':'no'}`;
  renderSummaryTable(j.entries||[]);
}

async function init(){
  const m=await fetch('/api/meta').then(r=>r.json()).catch(()=>({}));
  if(m.amstrax_default_path) $('amstraxPath').value=m.amstrax_default_path;
  await loadAmstraxInfo();
  await loadLatestRunDefault();
  $('refreshAmstrax').onclick=loadAmstraxInfo;
  $('refreshSummary').onclick=loadSummary;
}

document.addEventListener('DOMContentLoaded', init);
