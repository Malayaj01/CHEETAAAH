"""Step 8: the report — what was applied, what was blocked and why, what is
someone else's, what reversed. Diffs and commits, not claims.

Produces <meeting>/report.md. Delivery (mail) is a separate concern: the server
exposes it at /api/meetings/<id>/report.md and the page shows it; a mail channel
can be added when credentials exist."""
import json

import pipeline


def render(meeting_id):
    d = pipeline.mdir(meeting_id)
    meta = json.loads((d / "meeting.json").read_text())
    ex = json.loads((d / "extraction.json").read_text(encoding="utf-8"))
    ap = json.loads((d / "approval.json").read_text()) if (d / "approval.json").exists() else {}
    rc = json.loads((d / "reconcile.json").read_text(encoding="utf-8")) \
        if (d / "reconcile.json").exists() else {"flags": []}
    exn = json.loads((d / "execution.json").read_text(encoding="utf-8")) \
        if (d / "execution.json").exists() else None

    out = [f"# Report — {meta['title']}", f"{meta['date']} · project `{meta['project']}`", ""]
    acts = ex["actionables"]
    by_i = {r["i"]: r for r in (exn or {}).get("results", [])}

    applied = [(i, a, by_i[i]) for i, a in enumerate(acts)
               if by_i.get(i, {}).get("status") in ("applied", "already_applied")]
    blocked = [(i, a, by_i[i]) for i, a in enumerate(acts) if by_i.get(i, {}).get("status") == "blocked"]
    human = [(i, a) for i, a in enumerate(acts)
             if (ap.get("actionables") or {}).get(str(i)) == "accept"
             and by_i.get(i, {}).get("status") in (None, "human")]
    others = [(i, a) for i, a in enumerate(acts) if (ap.get("actionables") or {}).get(str(i)) == "not_mine"]
    rejected = [(i, a) for i, a in enumerate(acts) if (ap.get("actionables") or {}).get(str(i)) == "reject"]

    if exn:
        out += [f"Branch: `{exn['branch']}` (from `{exn['base']}`) — nothing pushed, nothing on main.", ""]
    out += ["## ✅ Applied" if applied else "## ✅ Applied — none"]
    for i, a, r in applied:
        tag = "already in place" if r["status"] == "already_applied" else f"commit `{r.get('commit')}`"
        out += [f"- **{a['component']}** — {a['instruction']} — {tag}",
                f"  - \"{a['verbatim']}\" — {a['said_by']}"]
        if r.get("note"):
            out += [f"  - note: {r['note']}"]
        last = (r.get("attempts") or [{}])[-1]
        if last.get("verify"):
            out += [f"  - verified: {last['verify'].strip().splitlines()[-1]}"]
    out += [""]
    if blocked:
        out += ["## ⚠ Blocked — needs you"]
        for i, a, r in blocked:
            last = (r.get("attempts") or [{}])[-1]
            why = (last.get("claimed") or {}).get("note") or last.get("verify", "")[-200:]
            out += [f"- **{a['component']}** — {a['instruction']}", f"  - why: {why}",
                    f"  - log: `data/meetings/{meeting_id}/exec_{i}.log`"]
        out += [""]
    if human:
        out += ["## 👤 Yours, not automatable"]
        for i, a in human:
            out += [f"- **{a['component']}** ({a['type']}) — {a['instruction']}"
                    + (f" · due {a['due']}" if a.get("due") else ""),
                    f"  - \"{a['verbatim']}\" — {a['said_by']}"]
        out += [""]
    if others:
        out += ["## 📨 Someone else's — forward if you agree"]
        for i, a in others:
            out += [f"- **{a['owner']}**: {a['instruction']}" + (f" · due {a['due']}" if a.get("due") else ""),
                    f"  - \"{a['verbatim']}\" — {a['said_by']}"]
        out += [""]
    if rc.get("flags"):
        out += ["## ↩ Reversals recorded"]
        for f in rc["flags"]:
            out += [f"- **{f['new']['component']}**: {f['new']['instruction']} (today) supersedes "
                    f"\"{f['old']['instruction']}\" ({f['old']['date']})"]
        out += [""]
    if rejected:
        out += ["## ✗ Rejected at approval"] + [f"- {a['instruction']}" for i, a in rejected] + [""]
    if ex.get("open_questions"):
        out += ["## ❓ Still open"] + [f"- {q}" for q in ex["open_questions"]] + [""]
    text = "\n".join(out)
    (d / "report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    import sys
    print(render(sys.argv[1]))
