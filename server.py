#!/usr/bin/env python3
"""Phone-first web interface for CHEETAAAH Stage 1.

    python3 server.py            # http://0.0.0.0:8787

Upload a recording (or a transcript), pick the project, watch it run, then read
the MoM and tap accept / reject per decision. Nothing executes, nothing is mailed.
"""
import json
import re
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

import config
import execute
import memory
import pipeline
import report

app = FastAPI(title="CHEETAAAH")


# ------------------------------------------------------------------ data ----
def projects():
    return sorted(p.stem for p in config.PROJECTS.glob("*.yaml"))


def meetings():
    out = []
    for d in sorted((config.DATA / "meetings").glob("*"), reverse=True):
        meta = d / "meeting.json"
        st = d / "status.json"
        if not st.exists():
            continue
        m = json.loads(meta.read_text()) if meta.exists() else {"id": d.name, "title": d.name}
        m.update(json.loads(st.read_text()))
        out.append(m)
    out.sort(key=lambda m: (m.get("date") or "", m.get("updated") or ""), reverse=True)
    return out


def load(meeting_id):
    d = pipeline.mdir(meeting_id)
    if not (d / "status.json").exists():
        raise HTTPException(404, "no such meeting")
    r = {"meta": json.loads((d / "meeting.json").read_text()),
         "status": json.loads((d / "status.json").read_text())}
    for name in ("extraction", "reconcile", "approval", "execution"):
        f = d / f"{name}.json"
        r[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    return r


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "meeting"


# ------------------------------------------------------------------- api ----
@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...), project: str = Form(...),
                 title: str = Form(""), date: str = Form("")):
    if project not in projects():
        raise HTTPException(400, "unknown project")
    date = date or time.strftime("%Y-%m-%d")
    mid = f"{date}-{slug(title) or slug(file.filename)}-{uuid.uuid4().hex[:4]}"
    d = pipeline.mdir(mid)
    d.mkdir(parents=True, exist_ok=True)
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in file.filename else ".bin"
    src = d / ("recording" + ext if ext in pipeline.AUDIO else "transcript-upload" + ext)
    src.write_bytes(await file.read())
    pipeline.status(mid, state="queued", step="queued")
    (d / "meeting.json").write_text(json.dumps(
        {"id": mid, "project": project, "date": date, "title": title or file.filename,
         "source": file.filename}, indent=1))
    threading.Thread(target=pipeline.run, args=(src, project, mid, date, title or file.filename),
                     daemon=True).start()
    return {"id": mid}


@app.get("/api/meetings")
def api_meetings():
    return meetings()


@app.get("/api/meetings/{mid}")
def api_meeting(mid: str):
    return load(mid)


@app.post("/api/meetings/{mid}/approve")
async def approve(mid: str, body: dict):
    """body = {"decisions": {id: "accept"|"reject"|""}, "actionables": {idx: "accept"|"reject"|"not_mine"|""},
               "edits": {"a:<idx>": "new instruction", "d:<id>": "new instruction"}}
    An empty choice clears a previous one (unapprove). Edited instructions are what the
    executor will apply; the original stays in extraction.json."""
    r = load(mid)
    decisions = body.get("decisions") or {}
    memory.approve(r["meta"]["project"], mid,
                   [k for k, v in decisions.items() if v == "accept"],
                   [k for k, v in decisions.items() if v == "reject"],
                   [k for k, v in decisions.items() if v == ""])
    body["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (pipeline.mdir(mid) / "approval.json").write_text(json.dumps(body, indent=1))
    pipeline.status(mid, state="approved")
    return {"ok": True}


@app.post("/api/meetings/{mid}/execute")
def api_execute(mid: str):
    r = load(mid)
    if not r["approval"]:
        raise HTTPException(400, "approve first")
    if r["status"].get("state") == "executing":
        raise HTTPException(409, "already running")
    pipeline.status(mid, state="executing")

    def go():
        try:
            execute.execute(mid)
            report.render(mid)
        except SystemExit as e:
            pipeline.status(mid, state="approved", error=str(e))
        except Exception:
            import traceback
            pipeline.status(mid, state="approved", error=traceback.format_exc()[-1500:])
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


@app.post("/api/meetings/{mid}/retry")
def api_retry(mid: str):
    """Re-run from the last completed step (keeps transcript/extraction already on disk)."""
    r = load(mid)
    d = pipeline.mdir(mid)
    src = next((f for f in d.iterdir() if f.name.startswith(("recording", "transcript-upload"))), None) \
        or (d / "transcript.txt")
    m = r["meta"]
    pipeline.status(mid, state="queued", step="queued", error=None)
    threading.Thread(target=pipeline.run, args=(src, m["project"], mid, m["date"], m["title"]),
                     kwargs={"resume": True}, daemon=True).start()
    return {"ok": True}


@app.get("/api/meetings/{mid}/report.md")
def api_report(mid: str):
    f = pipeline.mdir(mid) / "report.md"
    if not f.exists():
        raise HTTPException(404)
    return PlainTextResponse(f.read_text(encoding="utf-8"))


@app.get("/api/meetings/{mid}/mom.md")
def api_mom(mid: str):
    f = pipeline.mdir(mid) / "mom.md"
    if not f.exists():
        raise HTTPException(404)
    return PlainTextResponse(f.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ pages ---
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#16256B">
<title>CHEETAAAH</title>
<style>
:root{--navy:#16256B;--blue:#1A73E8;--red:#E8232A;--green:#0E9F6E;--amber:#B45309;
  --ink:#1B1F2A;--muted:#5A6172;--line:#E3E8F4;--panel:#F3F6FD;--bg:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{background:var(--navy);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px;
  position:sticky;top:0;z-index:5;padding-top:calc(14px + env(safe-area-inset-top))}
header b{font-size:17px;letter-spacing:.04em}
header a{color:#C7D2F2;text-decoration:none;font-size:14px}
header .sp{margin-left:auto}
main{max-width:720px;margin:0 auto;padding:16px}
h2{font-size:17px;margin:22px 0 10px;color:var(--navy)}
.card{background:var(--panel);border-radius:14px;padding:14px;margin-bottom:12px}
.card.w{background:#fff;border:1px solid var(--line)}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
input,select{width:100%;font:inherit;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#fff}
input[type=file]{padding:8px}
.btn{display:inline-block;width:100%;text-align:center;font:inherit;font-weight:700;padding:14px;border:0;
  border-radius:12px;background:var(--red);color:#fff;margin-top:14px;cursor:pointer}
.btn.b{background:var(--blue)}.btn.g{background:var(--green)}.btn:disabled{opacity:.5}
.row{display:flex;gap:10px;align-items:center}
.pill{font-size:11px;font-weight:700;padding:3px 9px;border-radius:12px;background:#E5EEFF;color:var(--navy);white-space:nowrap}
.pill.run{background:#FEF3C7;color:var(--amber)}.pill.ok{background:#D1FAE5;color:#065F46}
.pill.bad{background:#FEE2E2;color:#991B1B}.pill.app{background:#DBEAFE;color:#1E40AF}
.mt{display:block;text-decoration:none;color:inherit}
.mt b{display:block;font-size:15px}.mt s{text-decoration:none;color:var(--muted);font-size:13px}
.item{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px}
.item .c{font-size:11px;font-weight:700;color:var(--blue);letter-spacing:.04em;text-transform:uppercase}
.item .i{font-weight:600;margin:4px 0 6px}
.item q{quotes:none;display:block;font-size:13px;color:var(--muted);border-left:3px solid var(--line);padding-left:9px;line-height:1.45}
.item .who{font-size:12px;color:var(--muted);margin-top:5px}
.item.rev{border-color:#F59E0B;background:#FFFBEB}
.item .old{margin-top:8px;font-size:13px;background:#fff;border-radius:8px;padding:8px}
.seg{display:flex;gap:6px;margin-top:10px}
.seg button{flex:1;font:inherit;font-size:13px;font-weight:700;padding:9px 4px;border:1px solid var(--line);
  background:#fff;border-radius:9px;color:var(--muted);cursor:pointer}
.seg button.on.a{background:var(--green);color:#fff;border-color:var(--green)}
.seg button.on.r{background:var(--red);color:#fff;border-color:var(--red)}
.seg button.on.n{background:var(--muted);color:#fff;border-color:var(--muted)}
.sum{font-size:14.5px;line-height:1.55}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.steps span{font-size:12px;padding:5px 10px;border-radius:10px;background:#fff;border:1px solid var(--line);color:var(--muted)}
.steps span.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.steps span.done{background:#D1FAE5;color:#065F46;border-color:#D1FAE5}
pre{white-space:pre-wrap;font-size:12px;background:#FEE2E2;padding:10px;border-radius:8px}
.save{position:sticky;bottom:0;background:linear-gradient(transparent,#fff 30%);padding:14px 0 calc(8px + env(safe-area-inset-bottom))}
.muted{color:var(--muted);font-size:13px}
ul.oq{padding-left:18px}ul.oq li{margin-bottom:6px}
</style></head><body>
<header><b>CHEETAAAH</b><a class="sp" href="/">Meetings</a></header>
<main id="app">__BODY__</main>
<script>__JS__</script></body></html>"""

HOME_BODY = """
<div class="card">
  <div class="row"><button type="button" class="btn b" id="rec" style="margin:0">● Record here</button>
    <span id="rt" class="muted" style="min-width:70px;text-align:right"></span></div>
  <div class="muted" style="margin-top:6px">Keep the screen on while recording. Or record with your phone's recorder app and upload below.</div>
  <form id="f" style="margin-top:12px">
    <label>Recording or transcript</label>
    <input type="file" name="file" accept="audio/*,.aac,.m4a,.mp3,.wav,.ogg,.opus,.txt" required>
    <label>Project</label>
    <select name="project">__PROJECTS__</select>
    <label>Title</label>
    <input name="title" placeholder="e.g. Proposal review with Amit">
    <label>Date</label>
    <input name="date" type="date" value="__TODAY__">
    <button class="btn" id="go">Upload &amp; process</button>
    <div class="muted" id="msg" style="margin-top:8px"></div>
  </form>
</div>
<h2>Meetings</h2>
<div id="list"><div class="muted">loading…</div></div>
"""

HOME_JS = """
const STATE={queued:['Queued','run'],running:['Running','run'],awaiting_approval:['Review','ok'],
  approved:['Approved','app'],executing:['Executing','run'],executed:['Executed','app'],failed:['Failed','bad']};
async function list(){
  const r=await fetch('/api/meetings');const ms=await r.json();
  document.getElementById('list').innerHTML=ms.length?ms.map(m=>{const s=STATE[m.state]||[m.state,''];
    return `<a class="card w mt" href="/m/${m.id}"><div class="row"><div style="flex:1"><b>${m.title}</b>
    <s>${m.date} · ${m.project}${m.step&&m.state==='running'?' · '+m.step:''}</s></div>
    <span class="pill ${s[1]}">${s[0]}</span></div></a>`}).join(''):'<div class="muted">No meetings yet.</div>';
}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const b=document.getElementById('go');b.disabled=true;
  document.getElementById('msg').textContent='uploading…';
  const r=await fetch('/api/ingest',{method:'POST',body:new FormData(e.target)});
  if(!r.ok){document.getElementById('msg').textContent='failed: '+await r.text();b.disabled=false;return}
  const j=await r.json();location.href='/m/'+j.id};
list();setInterval(list,8000);
// in-page recording: raw mic, no browser "enhancements" (they muffle far speakers)
let rec=null,chunks=[],t0=0,tick=null,lock=null;
const rb=document.getElementById('rec'),rt=document.getElementById('rt');
rb.onclick=async()=>{
  if(rec&&rec.state==='recording'){rec.stop();return}
  try{
    const st=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false,channelCount:1,sampleRate:48000}});
    const mime=['audio/mp4','audio/webm;codecs=opus','audio/webm'].find(m=>MediaRecorder.isTypeSupported(m))||'';
    rec=new MediaRecorder(st,mime?{mimeType:mime,audioBitsPerSecond:96000}:{});chunks=[];
    rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    rec.onstop=()=>{st.getTracks().forEach(x=>x.stop());clearInterval(tick);if(lock){lock.release();lock=null}
      const ext=(rec.mimeType||'').includes('mp4')?'m4a':'webm';
      const f=new File(chunks,`recording-${new Date().toISOString().slice(0,16).replace(/[:T]/g,'-')}.${ext}`,{type:rec.mimeType});
      const dt=new DataTransfer();dt.items.add(f);document.querySelector('input[name=file]').files=dt.files;
      rb.textContent='● Record here';rb.classList.add('b');rt.textContent='saved to the form ↓';};
    rec.start(1000);t0=Date.now();rb.textContent='■ Stop';rb.classList.remove('b');
    tick=setInterval(()=>{const s=Math.floor((Date.now()-t0)/1000);rt.textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`},1000);
    try{lock=await navigator.wakeLock.request('screen')}catch(e){}
  }catch(e){rt.textContent='mic blocked: '+e.message}
};
"""

MEETING_JS = """
const MID=__MID__;const STEPS=['transcribing','extracting','reconciling','done'];
const choice={decisions:{},actionables:{},edits:{}};
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function seg(kind,key,opts){return `<div class="seg">`+opts.map(o=>`<button type="button" class="${o[2]}" data-k="${kind}" data-id="${key}" data-v="${o[0]}">${o[1]}</button>`).join('')+`</div>`}
function render(r){
  const st=r.status,m=r.meta;let h=`<h2 style="margin-top:4px">${esc(m.title)}</h2><div class="muted">${m.date} · ${m.project}</div>`;
  if(st.state==='running'||st.state==='queued'){
    const i=STEPS.indexOf(st.step);
    h+=`<div class="card"><b>Processing…</b><div class="steps">`+STEPS.slice(0,3).map((s,k)=>`<span class="${k<i?'done':k===i?'on':''}">${s}</span>`).join('')+`</div>
    <div class="muted" style="margin-top:8px">${st.words?st.words.toLocaleString()+' words transcribed. ':''}Audio takes about 1 minute per 4 minutes of recording. This page refreshes itself.</div></div>`;
    document.getElementById('app').innerHTML=h;setTimeout(load,5000);return}
  if(st.state==='failed'){h+=`<div class="card"><b>Failed</b><pre>${esc(st.error)}</pre><button class="btn b" id="retry">Retry from last completed step</button></div>`;document.getElementById('app').innerHTML=h;
    document.getElementById('retry').onclick=async()=>{await fetch(`/api/meetings/${MID}/retry`,{method:'POST'});setTimeout(load,1000)};return}
  const ex=r.extraction,rc=r.reconcile||{stored:[],flags:[]},ap=r.approval;
  if(ap){Object.assign(choice.decisions,ap.decisions||{});Object.assign(choice.actionables,ap.actionables||{});Object.assign(choice.edits,ap.edits||{})}
  const edit=(key,text)=>`<input class="ed" data-key="${key}" value="${esc(choice.edits[key]||text)}" style="margin-top:6px;font-size:13px${choice.edits[key]?';border-color:var(--amber)':''}" title="edit the instruction before approving">`;
  h+=`<div class="card"><div class="row"><span class="pill ${st.state==='approved'?'app':'ok'}">${st.state==='approved'?'Approved '+(ap&&ap.saved||''):'Awaiting your review'}</span>
    <span class="muted">${st.decisions} decisions · ${st.actionables} actionables · $${(st.cost||0).toFixed(2)}</span></div>
    <div class="sum" style="margin-top:10px">${esc(ex.summary)}</div></div>`;
  const byId={};rc.stored.forEach(s=>byId[s.id]=s);
  if(rc.flags.length){h+=`<h2>⚠ Reversals — your call</h2>`;rc.flags.forEach(f=>{h+=`<div class="item rev"><div class="c">${f.new.component}</div>
    <div class="i">${esc(f.new.instruction)}</div><q>“${esc(f.new.verbatim)}” — ${esc(f.new.said_by)}, ${f.new.date}</q>
    <div class="old"><b>Earlier (${f.old.date}, ${esc(f.old.said_by)}):</b> ${esc(f.old.instruction)}<br><q>“${esc(f.old.verbatim)}”</q><div class="muted" style="margin-top:4px">${esc(f.why)}</div></div>
    <div class="muted" style="margin-top:6px">Accepting the decision below makes today win and marks the earlier one superseded.</div></div>`})}
  h+=`<h2>Decisions</h2>`;
  ex.decisions.forEach((d,i)=>{const s=rc.stored[i]||{};const rel={same:'restates earlier',refines:'refines earlier',reverses:'REVERSES earlier'}[s.relation];
    h+=`<div class="item${s.relation==='reverses'?' rev':''}"><div class="c">${d.component}${rel?' · '+rel:''}</div><div class="i">${esc(d.instruction)}</div>
    <q>“${esc(d.verbatim)}”</q><div class="who">${esc(d.said_by)} · confidence ${Math.round(d.confidence*100)}%</div>
    ${edit('d:'+s.id,d.instruction)}
    ${seg('decisions',s.id,[['accept','Accept','a'],['reject','Reject','r'],['','Clear','n']])}</div>`});
  const groups={};ex.actionables.forEach((a,i)=>{(groups[a.owner||'unassigned']=groups[a.owner||'unassigned']||[]).push([a,i])});
  h+=`<h2>Actionables</h2>`;
  Object.keys(groups).sort((a,b)=>(a==='unassigned')-(b==='unassigned')||a.localeCompare(b)).forEach(o=>{h+=`<h2 style="font-size:14px;color:var(--muted)">${esc(o)}</h2>`;
    groups[o].forEach(([a,i])=>{h+=`<div class="item"><div class="c">${a.component} · ${a.type}${a.due?' · due '+esc(a.due):''}</div><div class="i">${esc(a.instruction)}</div>
    <q>“${esc(a.verbatim)}”</q><div class="who">${esc(a.said_by)}${a.blocks?' · blocks: '+esc(a.blocks):''}</div>
    ${edit('a:'+i,a.instruction)}
    ${seg('actionables',i,[['accept','Accept','a'],['reject','Reject','r'],['not_mine','Not mine','n'],['','Clear','n']])}</div>`})});
  const design=ex.actionables.filter(a=>a.type==='needs_design');
  if(design.length){h+=`<h2>🧩 Needs design — new work, not automatable</h2>`+design.map(a=>`<div class="item"><div class="c">${a.component} · owner ${esc(a.owner)}</div><div class="i">${esc(a.instruction)}</div><q>“${esc(a.verbatim)}”</q></div>`).join('')}
  const dp=rc.deps||{};
  if((dp.new||[]).length||(dp.carried||[]).length||(dp.closed||[]).length){h+=`<h2>⏳ Waiting on others</h2>`;
    (dp.new||[]).forEach(d=>{h+=`<div class="item"><div class="c">${esc(d.waiting_on)} · new today</div><div class="i">${esc(d.instruction)}</div>${d.blocks?`<div class="muted">blocks: ${esc(d.blocks)}</div>`:''}</div>`});
    (dp.carried||[]).forEach(d=>{h+=`<div class="item rev"><div class="c">${esc(d.waiting_on)} · still open since ${d.since}</div><div class="i">${esc(d.instruction)}</div>${d.blocks?`<div class="muted">blocks: ${esc(d.blocks)}</div>`:''}</div>`});
    (dp.closed||[]).forEach(d=>{h+=`<div class="item"><div class="c">${esc(d.waiting_on)} · ${d.status} today</div><div class="i" style="text-decoration:line-through">${esc(d.instruction)}</div><div class="muted">${esc(d.why)}</div></div>`})}
  if(ex.open_questions.length){h+=`<h2>Open questions</h2><div class="card"><ul class="oq">`+ex.open_questions.map(q=>`<li>${esc(q)}</li>`).join('')+`</ul></div>`}
  h+=`<div class="card"><b>People</b><div class="muted">${esc(ex.people.join(', '))}</div></div>`;
  const exn=r.execution;
  if(st.state==='executing'){h+=`<h2>Executing…</h2><div class="card"><div class="muted">Claude Code is applying accepted changes on a branch, one at a time, and verifying each. 1–3 minutes per item. This page refreshes itself.</div></div>`;setTimeout(load,6000)}
  if(exn){h+=`<h2>Execution</h2><div class="card"><div class="muted">Branch <code>${esc(exn.branch)}</code> from <code>${esc(exn.base)}</code> · ${esc(exn.finished)} · nothing pushed</div></div>`;
    exn.results.forEach(x=>{const a=ex.actionables[x.i];const pill={applied:['Applied','ok'],already_applied:['Already in place','ok'],blocked:['Blocked','bad'],human:['Needs a human',''],skipped:['Skipped','']}[x.status]||[x.status,''];
      const last=(x.attempts||[]).slice(-1)[0]||{};
      h+=`<div class="item"><div class="row"><div class="c" style="flex:1">${a.component}</div><span class="pill ${pill[1]}">${pill[0]}</span></div><div class="i">${esc(a.instruction)}</div>
      ${x.commit?`<div class="muted">commit ${x.commit}</div>`:''}${x.note||x.why?`<div class="muted">${esc(x.note||x.why)}</div>`:''}
      ${last.verify?`<div class="muted" style="margin-top:4px">verify: ${esc(last.verify.trim().split('\n').slice(-1)[0])}</div>`:''}
      ${x.patch?`<details style="margin-top:6px"><summary class="muted">diff</summary><pre style="background:#F3F6FD">${esc(x.patch)}</pre></details>`:''}</div>`});
    h+=`<div class="muted" style="text-align:center;margin:6px 0"><a href="/api/meetings/${MID}/report.md">Report as text</a></div>`}
  if(st.error&&st.state!=='failed'){h+=`<div class="card"><b>Last execution problem</b><pre>${esc(st.error)}</pre></div>`}
  h+=`<div class="save"><button class="btn g" id="save">Save approval</button>`+(ap&&st.state!=='executing'?`<button class="btn b" id="run" style="margin-top:8px">Execute accepted changes</button>`:'')+`<div class="muted" id="smsg" style="text-align:center;margin-top:6px"></div></div>`;
  h+=`<div class="muted" style="margin:10px 0 30px;text-align:center"><a href="/api/meetings/${MID}/mom.md">MoM as text</a></div>`;
  document.getElementById('app').innerHTML=h;
  document.querySelectorAll('.seg button').forEach(b=>{const k=b.dataset.k,id=b.dataset.id;if(choice[k][id]===b.dataset.v)b.classList.add('on');
    b.onclick=()=>{choice[k][id]=b.dataset.v;b.parentElement.querySelectorAll('button').forEach(x=>x.classList.remove('on'));if(b.dataset.v)b.classList.add('on')}});
  document.getElementById('save').onclick=async()=>{const el=document.getElementById('smsg');el.textContent='saving…';
    document.querySelectorAll('input.ed').forEach(x=>{const orig=x.getAttribute('value');if(x.value.trim()&&x.value!==orig)choice.edits[x.dataset.key]=x.value.trim();else if(x.value===orig)delete choice.edits[x.dataset.key]});
    const r=await fetch(`/api/meetings/${MID}/approve`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(choice)});
    el.textContent=r.ok?'Saved. Accepted decisions are now active in memory.':'failed: '+await r.text();if(r.ok)setTimeout(load,800)};
  const run=document.getElementById('run');if(run)run.onclick=async()=>{run.disabled=true;const el=document.getElementById('smsg');el.textContent='starting…';
    const r=await fetch(`/api/meetings/${MID}/execute`,{method:'POST'});el.textContent=r.ok?'running':'failed: '+await r.text();if(r.ok)setTimeout(load,1500)};
}
async function load(){const r=await fetch('/api/meetings/'+MID);if(!r.ok){document.getElementById('app').innerHTML='<div class="card">Not found</div>';return}render(await r.json())}
load();
"""


@app.get("/", response_class=HTMLResponse)
def home():
    opts = "".join(f'<option value="{p}">{p}</option>' for p in projects())
    body = HOME_BODY.replace("__PROJECTS__", opts).replace("__TODAY__", time.strftime("%Y-%m-%d"))
    return PAGE.replace("__BODY__", body).replace("__JS__", HOME_JS)


@app.get("/m/{mid}", response_class=HTMLResponse)
def meeting_page(mid: str):
    return PAGE.replace("__BODY__", '<div class="muted">loading…</div>').replace(
        "__JS__", MEETING_JS.replace("__MID__", json.dumps(mid)))


if __name__ == "__main__":
    print("\n  CHEETAAAH -> http://0.0.0.0:8787  (phone: use this machine's LAN address)\n")
    uvicorn.run(app, host="0.0.0.0", port=8787, log_level="warning")
