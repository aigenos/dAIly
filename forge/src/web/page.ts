/** The single-page web UI, served inline (no bundler, no runtime deps). */
export const PAGE = /* html */ `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Forge</title>
<style>
  :root {
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2330; --border:#2a313c;
    --text:#e6edf3; --dim:#8b949e; --accent:#58a6ff; --green:#3fb950;
    --yellow:#d29922; --red:#f85149; --magenta:#bc8cff;
  }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
    background:var(--bg); color:var(--text); height:100vh; display:flex; flex-direction:column; }
  header { display:flex; align-items:center; gap:12px; padding:10px 16px;
    background:var(--panel); border-bottom:1px solid var(--border); }
  header .logo { font-weight:700; color:var(--accent); }
  header .meta { color:var(--dim); font-size:12px; }
  header select { background:var(--panel2); color:var(--text); border:1px solid var(--border);
    border-radius:6px; padding:4px 6px; }
  main { flex:1; display:flex; min-height:0; }
  #sidebar { width:240px; border-right:1px solid var(--border); overflow:auto; padding:8px; background:var(--panel); }
  #sidebar h3 { font-size:11px; text-transform:uppercase; color:var(--dim); margin:8px 4px; letter-spacing:.5px; }
  .file { padding:3px 6px; border-radius:5px; cursor:pointer; color:var(--dim); white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis; }
  .file:hover { background:var(--panel2); color:var(--text); }
  #center { flex:1; display:flex; flex-direction:column; min-width:0; }
  #log { flex:1; overflow:auto; padding:16px; }
  .msg { margin-bottom:10px; white-space:pre-wrap; word-break:break-word; }
  .user { color:var(--accent); }
  .assistant { color:var(--text); }
  .assistant b { color:var(--green); }
  .tool { color:var(--magenta); }
  .tool .ok { color:var(--green); } .tool .err { color:var(--red); }
  .phase { color:var(--accent); font-weight:700; margin:14px 0 6px; border-top:1px solid var(--border); padding-top:10px; }
  .task { color:var(--yellow); font-weight:700; margin:10px 0 4px; }
  .dim { color:var(--dim); }
  .plan { background:var(--panel2); border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin:6px 0; }
  .plan ol { margin:6px 0 0; padding-left:20px; }
  #composer { display:flex; gap:8px; padding:12px 16px; border-top:1px solid var(--border); background:var(--panel); }
  #composer input { flex:1; background:var(--panel2); color:var(--text); border:1px solid var(--border);
    border-radius:8px; padding:10px 12px; font:inherit; }
  button { background:var(--accent); color:#0b1020; border:0; border-radius:8px; padding:10px 14px;
    font:inherit; font-weight:700; cursor:pointer; }
  button.alt { background:var(--magenta); }
  button:disabled { opacity:.5; cursor:default; }
  #viewer { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; align-items:center; justify-content:center; }
  #viewer .box { background:var(--panel); border:1px solid var(--border); border-radius:10px; width:80%; height:80%;
    display:flex; flex-direction:column; }
  #viewer .hd { padding:10px 14px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; }
  #viewer pre { flex:1; overflow:auto; margin:0; padding:14px; white-space:pre; }
</style>
</head>
<body>
<header>
  <span class="logo">⚒ Forge</span>
  <span class="meta" id="meta">loading…</span>
  <span style="flex:1"></span>
  <label class="meta">mode
    <select id="mode">
      <option value="auto" selected>auto</option>
      <option value="yolo">yolo</option>
      <option value="readonly">readonly</option>
    </select>
  </label>
</header>
<main>
  <div id="sidebar"><h3>Workspace</h3><div id="tree" class="dim">…</div></div>
  <div id="center">
    <div id="log"></div>
    <div id="composer">
      <input id="input" placeholder="Describe a task or a goal…" autofocus />
      <button id="runBtn">Run task</button>
      <button id="teamBtn" class="alt">Run team</button>
    </div>
  </div>
</main>
<div id="viewer"><div class="box">
  <div class="hd"><span id="vtitle"></span><button onclick="closeViewer()">close</button></div>
  <pre id="vbody"></pre>
</div></div>
<script>
const log = document.getElementById('log');
const input = document.getElementById('input');
const runBtn = document.getElementById('runBtn');
const teamBtn = document.getElementById('teamBtn');
const modeSel = document.getElementById('mode');
let busy = false;

function add(html, cls){ const d=document.createElement('div'); d.className='msg '+(cls||''); d.innerHTML=html; log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
function esc(s){ return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

async function loadConfig(){
  const c = await (await fetch('/api/config')).json();
  document.getElementById('meta').textContent = c.provider+' · '+c.model+' · '+c.workspace;
  modeSel.value = ['auto','yolo','readonly'].includes(c.permissionMode)?c.permissionMode:'auto';
  loadTree();
}
async function loadTree(){
  const files = await (await fetch('/api/tree')).json();
  const t = document.getElementById('tree'); t.innerHTML='';
  files.forEach(f=>{ const d=document.createElement('div'); d.className='file'; d.textContent=f;
    d.onclick=()=>view(f); t.appendChild(d); });
}
async function view(path){
  const r = await fetch('/api/file?path='+encodeURIComponent(path));
  document.getElementById('vtitle').textContent=path;
  document.getElementById('vbody').textContent = r.ok ? await r.text() : 'unable to read';
  document.getElementById('viewer').style.display='flex';
}
function closeViewer(){ document.getElementById('viewer').style.display='none'; }

function handle(ev){
  switch(ev.type){
    case 'assistant': if(ev.text.trim()) add('<b>Forge:</b> '+esc(ev.text), 'assistant'); break;
    case 'tool': add('⚙ <b>'+esc(ev.name)+'</b> <span class="dim">'+esc(ev.detail||'')+'</span>', 'tool'); break;
    case 'tool_result': { const last=log.lastChild;
      const span='<span class="'+(ev.isError?'err':'ok')+'">'+(ev.isError?'✗':'✓')+' '+esc(ev.preview)+'</span>';
      if(last&&last.classList.contains('tool')) last.innerHTML+=' '+span; else add(span,'tool'); break; }
    case 'phase': add('▣ '+esc(ev.phase), 'phase'); break;
    case 'plan': { let h='<b>Plan</b> ('+ev.plan.tasks.length+' tasks): '+esc(ev.plan.overview)+'<ol>';
      ev.plan.tasks.forEach(t=>h+='<li>'+esc(t.role)+' — '+esc(t.title)+'</li>'); h+='</ol>';
      add('<div class="plan">'+h+'</div>'); break; }
    case 'task_start': add('['+ev.index+'/'+ev.total+'] '+esc(ev.role.toUpperCase())+': '+esc(ev.title), 'task'); break;
    case 'task_done': add('✓ '+esc(ev.title)+' <span class="dim">'+esc(ev.summary)+'</span>', 'assistant'); break;
    case 'review': add((ev.approved?'✓ Review: APPROVED':'△ Review: changes needed')+'<br><span class="dim">'+esc(ev.report)+'</span>', ev.approved?'assistant':'task'); break;
    case 'done': add('<span class="dim">— '+esc(ev.stopped||'done')+' —</span>'); loadTree(); break;
    case 'error': add('error: '+esc(ev.message), 'tool'); break;
  }
}

async function stream(path, payload){
  if(busy) return; busy=true; runBtn.disabled=teamBtn.disabled=true;
  try{
    const res = await fetch(path, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(payload)});
    const reader = res.body.getReader(); const dec=new TextDecoder(); let buf='';
    for(;;){ const {done,value}=await reader.read(); if(done) break; buf+=dec.decode(value,{stream:true});
      let i; while((i=buf.indexOf('\\n\\n'))>=0){ const frame=buf.slice(0,i); buf=buf.slice(i+2);
        const line=frame.split('\\n').find(l=>l.startsWith('data: ')); if(!line) continue;
        try{ handle(JSON.parse(line.slice(6))); }catch(e){} } }
  }catch(e){ add('error: '+esc(e.message),'tool'); }
  finally{ busy=false; runBtn.disabled=teamBtn.disabled=false; loadTree(); }
}

function go(team){
  const v=input.value.trim(); if(!v) return; input.value='';
  add((team?'▶ team: ':'▶ ')+esc(v), 'user');
  stream(team?'/api/team':'/api/run', {goal:v, task:v, mode:modeSel.value});
}
runBtn.onclick=()=>go(false);
teamBtn.onclick=()=>go(true);
input.addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); go(e.shiftKey); }});
loadConfig();
</script>
</body>
</html>`;
