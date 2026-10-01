"""The Stage 1 chain as one function, used by both run.py (CLI) and server.py.

State is written to <meeting dir>/status.json at every step so a crash is
visible and resumable, and the web page can poll it."""
import json
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

import config
import extract
import memory
import mom

TRANSCRIBER = pathlib.Path("/mnt/c/Users/Imart/Desktop/Issues/proposal/transcribe.py")
AUDIO = {".aac", ".m4a", ".mp3", ".wav", ".ogg", ".opus", ".mp4", ".webm", ".3gp", ".amr"}


def mdir(meeting_id):
    return config.DATA / "meetings" / meeting_id


def status(meeting_id, **kw):
    f = mdir(meeting_id) / "status.json"
    s = json.loads(f.read_text()) if f.exists() else {}
    s.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    f.write_text(json.dumps(s, indent=1))
    return s


def transcribe(src, dest):
    subprocess.run([sys.executable, str(TRANSCRIBER), str(src), "--out", str(dest)], check=True)
    return dest.read_text(encoding="utf-8")


def run(src, project, meeting_id, date, title=None):
    """src: audio file or transcript .txt. Returns the status dict."""
    src = pathlib.Path(src)
    d = mdir(meeting_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": meeting_id, "project": project, "date": date, "title": title or meeting_id,
            "source": src.name}
    (d / "meeting.json").write_text(json.dumps(meta, indent=1))
    try:
        status(meeting_id, state="running", step="transcribing", error=None)
        tpath = d / "transcript.txt"
        if src.suffix.lower() in AUDIO:
            if src.parent != d:
                shutil.copy(src, d / ("recording" + src.suffix.lower()))
            transcript = transcribe(src, tpath)
        else:
            transcript = src.read_text(encoding="utf-8")
            tpath.write_text(transcript, encoding="utf-8")
        status(meeting_id, step="extracting", words=len(transcript.split()))

        ex, cost = extract.extract(transcript, project)
        (d / "extraction.json").write_text(ex.model_dump_json(indent=2), encoding="utf-8")
        status(meeting_id, step="reconciling", cost=cost)

        stored, flags, jcost = memory.reconcile(project, meeting_id, date, ex.decisions)
        (d / "reconcile.json").write_text(json.dumps({"stored": stored, "flags": flags},
                                                     indent=1, ensure_ascii=False))
        text = mom.render({"title": meta["title"], "date": date, "project": project},
                          ex, stored, flags, cost + jcost)
        (d / "mom.md").write_text(text, encoding="utf-8")
        return status(meeting_id, state="awaiting_approval", step="done", cost=cost + jcost,
                      decisions=len(ex.decisions), actionables=len(ex.actionables),
                      reversals=len(flags))
    except Exception:
        return status(meeting_id, state="failed", error=traceback.format_exc()[-2000:])
