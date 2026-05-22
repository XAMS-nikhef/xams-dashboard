const $ = (id) => document.getElementById(id);

function fmtEntries(entries){
  if(!entries || !entries.length) return 'No correction entries.';
  return entries.map(e=>{
    const ok=e.ok?'OK ':'NO ';
    return `${ok} ${e.key}\n  file: ${e.file}\n  rule: ${e.matched_rule||'-'}\n  value: ${e.value_preview||'-'}`;
  }).join('\n\n');
}

async function loadAmstraxInfo(){
  const p=($('amstraxPath').value||'').trim();
  const q=p?`?amstrax_path=${encodeURIComponent(p)}`:'';
  const r=await fetch(`/api/corrections/meta${q}`);
  const j=await r.json();
  const a=j.amstrax||{};
  $('amstraxInfo').textContent=[
    `Path: ${a.path||'-'}`,
    `Exists: ${a.exists?'yes':'no'}`,
    `Version: ${a.version||'-'}`,
    `Branch: ${a.branch||'-'}`,
    `Commit: ${a.commit||'-'}`
  ].join('\n');
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
  if(!runId){$('corrSummary').textContent='Set run id first.';return;}
  $('corrSummary').textContent='Loading...';
  const r=await fetch(`/api/corrections/summary?run_id=${encodeURIComponent(runId)}&corrections_version=${encodeURIComponent(ver)}`);
  const j=await r.json();
  if(j.error){$('corrSummary').textContent=`Error: ${j.error}`;return;}
  const head=[
    `Run: ${j.run_id}`,
    `Corrections version: ${j.corrections_version}`,
    `Overall compatible: ${j.ok?'yes':'no'}`
  ].join('\n');
  $('corrSummary').textContent=`${head}\n\n${fmtEntries(j.entries||[])}`;
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
