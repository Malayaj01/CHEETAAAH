"""Decision store — the memory layer. One row per decision, per project.

Reconciliation is semantic (an LLM judge), not keyword: the real case is Monday's
"utilize this space" vs Friday's "ब्लैंक स्पेसिस को खत्म करने के चक्कर में" — no shared
words, different scripts, opposite meaning. Latest wins, but every reversal is
surfaced with both quotes and both dates; resolving it stays human."""
import json
import sqlite3
import uuid

import config
import llm

DB = config.DATA / "decisions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decision (
  id          TEXT PRIMARY KEY,
  project     TEXT NOT NULL,
  meeting_id  TEXT NOT NULL,
  date        TEXT NOT NULL,
  component   TEXT NOT NULL,
  instruction TEXT NOT NULL,
  verbatim    TEXT NOT NULL,
  said_by     TEXT,
  status      TEXT NOT NULL DEFAULT 'proposed',   -- proposed | active | superseded | rejected
  supersedes  TEXT,                               -- id of the decision this one replaced
  relation    TEXT,                               -- same | refines | reverses | new
  created     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS decision_pc ON decision(project, component, status);
"""


def connect():
    config.DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def prior(project, exclude_meeting=None):
    """Every decision still standing for the project (active or awaiting approval)."""
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM decision WHERE project=? AND status IN ('active','proposed')"
            + (" AND meeting_id<>?" if exclude_meeting else "") + " ORDER BY date",
            (project, exclude_meeting) if exclude_meeting else (project,)).fetchall()
    return [dict(r) for r in rows]


JUDGE = """You compare a NEW decision from today's meeting with EARLIER decisions on the same
project. For each earlier decision, say how the new one relates to it:

  same      — the same instruction, restated
  refines   — same direction, adds detail or narrows it
  reverses  — contradicts it: doing the new one undoes or forbids the earlier one
  unrelated — different thing, even if the same component

Judge by meaning, not words. Quotes may be in Hindi, English or mixed; different
language does not mean different meaning.

NEW: {new}

EARLIER:
{earlier}

Return ONLY JSON: {{"relations": [{{"id": "<earlier id>", "relation": "same|refines|reverses|unrelated", "why": "<one line>"}}]}}
Include every earlier id exactly once."""


def reconcile(project, meeting_id, date, decisions, model=config.JUDGE_MODEL):
    """Store today's decisions as 'proposed' and relate each to prior ones.
    Returns (stored_rows, flags, cost). flags = reversals for the approval page."""
    earlier = prior(project, exclude_meeting=meeting_id)
    stored, flags, cost = [], [], 0.0
    with connect() as c:
        c.execute("DELETE FROM decision WHERE project=? AND meeting_id=?", (project, meeting_id))
        for d in decisions:
            row = {"id": uuid.uuid4().hex[:12], "project": project, "meeting_id": meeting_id,
                   "date": date, "component": d.component, "instruction": d.instruction,
                   "verbatim": d.verbatim, "said_by": d.said_by, "status": "proposed",
                   "supersedes": None, "relation": "new"}
            # Candidates: same component first; fall back to everything if that is empty,
            # because component tags are the extractor's guess.
            cands = [e for e in earlier if e["component"] == d.component] or earlier
            if cands:
                new = json.dumps({"component": d.component, "instruction": d.instruction,
                                  "verbatim": d.verbatim, "date": date}, ensure_ascii=False)
                earl = "\n".join(json.dumps({k: e[k] for k in ("id", "date", "component",
                                                               "instruction", "verbatim")},
                                            ensure_ascii=False) for e in cands)
                j, cst = llm.chat_json([{"role": "user", "content":
                                         JUDGE.format(new=new, earlier=earl)}],
                                       model, max_tokens=2000, label="judge: ")
                cost += cst
                by_id = {e["id"]: e for e in cands}
                rank = {"reverses": 0, "refines": 1, "same": 2}
                hits = sorted((r for r in j.get("relations", [])
                               if r.get("id") in by_id and r.get("relation") in rank),
                              key=lambda r: rank[r["relation"]])
                if hits:
                    r, e = hits[0], by_id[hits[0]["id"]]
                    row["relation"] = r["relation"]
                    row["supersedes"] = e["id"]
                    if r["relation"] == "reverses":
                        flags.append({"new": row, "old": e, "why": r.get("why", "")})
            c.execute("INSERT INTO decision VALUES (:id,:project,:meeting_id,:date,:component,"
                      ":instruction,:verbatim,:said_by,:status,:supersedes,:relation,"
                      "datetime('now'))", row)
            stored.append(row)
    return stored, flags, cost


def approve(project, meeting_id, accepted_ids, rejected_ids=()):
    """Apply the human's decision: accepted -> active (and supersede what they replace),
    rejected -> rejected. Anything else stays 'proposed'."""
    with connect() as c:
        for i in accepted_ids:
            c.execute("UPDATE decision SET status='active' WHERE id=? AND project=?", (i, project))
            sup = c.execute("SELECT supersedes FROM decision WHERE id=?", (i,)).fetchone()
            if sup and sup["supersedes"]:
                c.execute("UPDATE decision SET status='superseded' WHERE id=?", (sup["supersedes"],))
        for i in rejected_ids:
            c.execute("UPDATE decision SET status='rejected' WHERE id=? AND project=?", (i, project))
