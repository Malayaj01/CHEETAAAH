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
import notify
import providers

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


def run(src, project, meeting_id, date, title=None, resume=False):
    """src: audio file or transcript .txt. Returns the status dict.
    resume=True reuses transcript.txt / extraction.json already on disk, so a failure
    in a later step never repeats a six-minute transcription."""
    src = pathlib.Path(src)
    d = mdir(meeting_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": meeting_id, "project": project, "date": date, "title": title or meeting_id,
            "source": src.name}
    (d / "meeting.json").write_text(json.dumps(meta, indent=1))
    tpath, xpath = d / "transcript.txt", d / "extraction.json"
    try:
        # context from providers (calendar attendees etc.) — enrichment only
        ctx = providers.context(meta)
        if ctx:
            (d / "context.json").write_text(json.dumps(ctx, indent=1, ensure_ascii=False))

        status(meeting_id, state="running", step="transcribing", error=None)
        if resume and tpath.exists():
            transcript = tpath.read_text(encoding="utf-8")
        elif src.suffix.lower() in AUDIO:
            if src.parent != d:
                shutil.copy(src, d / ("recording" + src.suffix.lower()))
            transcript = transcribe(src, tpath)
        else:
            transcript = src.read_text(encoding="utf-8")
            tpath.write_text(transcript, encoding="utf-8")
        status(meeting_id, step="extracting", words=len(transcript.split()))

        if resume and xpath.exists():
            ex, cost = extract.Extraction.model_validate_json(xpath.read_text(encoding="utf-8")), 0.0
        else:
            ex, cost = extract.extract(transcript, project, context=ctx)
            xpath.write_text(ex.model_dump_json(indent=2), encoding="utf-8")
        status(meeting_id, step="reconciling", cost=cost)

        stored, flags, jcost = memory.reconcile(project, meeting_id, date, ex.decisions)
        new, carried, closed, dcost = memory.track_dependencies(project, meeting_id, date,
                                                                 ex.actionables, transcript)
        deps = {"new": new, "carried": carried, "closed": closed}
        (d / "reconcile.json").write_text(json.dumps({"stored": stored, "flags": flags,
                                                      "deps": deps}, indent=1, ensure_ascii=False))
        total = cost + jcost + dcost
        text = mom.render({"title": meta["title"], "date": date, "project": project},
                          ex, stored, flags, total, deps)
        (d / "mom.md").write_text(text, encoding="utf-8")
        st = status(meeting_id, state="awaiting_approval", step="done", cost=total,
                    decisions=len(ex.decisions), actionables=len(ex.actionables),
                    reversals=len(flags), waiting=len(new) + len(carried))
        notify.send(meeting_id, meta, st)
        return st
    except Exception:
        st = status(meeting_id, state="failed", error=traceback.format_exc()[-2000:])
        notify.send(meeting_id, meta, st)
        return st
