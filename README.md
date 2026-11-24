# CHEETAAAH

**A meeting ends, and the work it asked for is already moving.**

CHEETAAAH turns a meeting recording into reviewed, verified code changes. It transcribes the
meeting, pulls out every decision and action item with the exact words that were said, checks
them against everything decided in earlier meetings, and asks you to approve each one from your
phone. Approved items are handed to Claude Code, which makes the change on a separate git
branch; an independent check then passes or reverts it, and you get a report with commits and
diffs.

Nothing is pushed, nothing is mailed, and nothing changes without your tap.

```
recording ─► transcript ─► decisions + actionables ─► compare with past decisions ─► APPROVE
                            (verbatim quotes)          (reversals flagged)             (phone)
                                                                                         │
            report ◄─ verify (outside the agent) ◄─ Claude Code edits on a branch ◄──────┘
```

## Why it exists

Decisions made in meetings decay on the way to execution: the detail of what was asked gets
lost, ownership is unclear, and a new instruction quietly contradicts one from last week. This
loop was first run by hand on two real product-review meetings for a seller-proposal document
(16 and 22 minutes, ~7,800 words of Hindi/English speech). Run through CHEETAAAH, those two
meetings produced **33 decisions, 33 actionables and 15 open questions**, at **under $0.07 of
LLM cost per meeting**.

## How it works

It is a fixed pipeline, not a free-roaming agent. The LLM does work *inside* each step; it never
chooses the next step. When something fails, it fails at a named step with state you can inspect
and resume.

```
ingest → transcribe → extract → reconcile → MoM → APPROVE → execute → verify → report
```

1. **Transcribe** — audio goes to a multimodal model (Gemini) that handles Hinglish natively.
   A ready transcript (`.txt`) can be given instead.
2. **Extract** — schema-enforced JSON (Pydantic) from Claude, one call per ~2,200 words, merged.
   Every decision and actionable must carry a `verbatim` quote, an owner, a component from the
   project's fixed vocabulary, and a confidence.
3. **Reconcile** — each new decision is compared with earlier decisions on the same component by
   an LLM judge: *same / refines / reverses / unrelated*. The latest wins, but a reversal is
   always shown with both quotes and both dates. Stored in SQLite.
4. **MoM** — a Markdown minutes-of-meeting that doubles as the approval page.
5. **Approve** — accept or reject each actionable from the phone UI or the CLI.
6. **Execute** — for each accepted actionable, on branch `meeting/<id>`: run Claude Code headless
   (`claude -p`) with a fixed prompt, then run the project's `verify_cmd`. Pass → commit.
   Fail → revert and mark blocked.
7. **Report** — applied, blocked, yours to do, someone else's, and reversals, with diffs.

## Non-negotiables

1. Approval before anything is applied — permanent, not a beta setting.
2. Only registered change types execute; everything else is routed to a human.
3. Verification runs outside the agent and must be able to fail.
4. Output is a branch and commits — never an edit on `main`, never a push.
5. The `verbatim` quote is never discarded; disagreements are settled by what was said.

## Quick start

Requirements: Python 3.10+, git, and [Claude Code](https://docs.claude.com/en/docs/claude-code)
on `PATH` for the execute step. An OpenAI-compatible LLM gateway (for example LiteLLM) that
serves the models in `config.py`.

```bash
pip install fastapi uvicorn python-multipart pydantic pyyaml requests

# credentials: environment variables, or a .env file in this folder (gitignored)
export LLM_BASE_URL=https://your-gateway.example.com
export LLM_API_KEY=...

python3 server.py                     # phone-first UI on http://localhost:8787
```

Or from the command line:

```bash
# 1. process a meeting (audio or transcript)
python3 run.py recording.aac --project nsd-proposal --id friday-1340 --date 2026-09-26

# 2. approve: accept some items, reject others (ids are listed in mom.md)
python3 run.py --approve friday-1340 --accept 032814b7712f,20a3cdc9d753 --reject 233cca2924fe

# 3. apply the accepted changes on a branch and verify each one
python3 execute.py friday-1340        # --only N to run a single actionable
python3 report.py friday-1340
```

Outputs per meeting land in `data/meetings/<id>/` (`transcript.txt`, `extraction.json`,
`reconcile.json`, `mom.md`, `status.json`); decisions in `data/decisions.db`. The whole `data/`
folder is gitignored because meeting content is confidential.

### Optional settings

| variable | purpose |
|---|---|
| `CHEETAAAH_ENV` | path to a `.env` file with `LLM_BASE_URL` / `LLM_API_KEY` (default: `./.env`) |
| `CHEETAAAH_TRANSCRIBER` | audio-to-text script (default: `../proposal/transcribe.py`) |
| `NOTIFY`, `SLACK_WEBHOOK` | where "meeting ready to approve" alerts go (`toast` or `slack`) |

On Windows + WSL, `start.ps1` starts the server and `phone-access.ps1` (run as admin) forwards
the port so a phone on the same network can open the UI.

## Adding a project

Each repo the agent may touch is registered in `projects/<name>.yaml`:

```yaml
name: nsd-proposal
repo: /path/to/the/repo
default_branch: main
people: [Malayaj, manager]
verify_cmd: python3 render_and_check.py     # must be able to fail
components:                                 # fixed vocabulary the extractor must use
  page1.hero:  deck3.py — headline and one-line description
  page3.plans: app.py (PLANS) — plan cards and prices
  other:       anything that does not fit above
```

The component list keeps extraction precise and tells Claude Code where each kind of change lives.

## Code map

| file | step |
|---|---|
| `pipeline.py` | ingest → transcribe → extract → reconcile → MoM, with `status.json` per meeting |
| `extract.py` | schema-enforced extraction, chunked and merged; `verbatim` mandatory |
| `memory.py` | SQLite decision store + LLM judge (same / refines / reverses) |
| `mom.py` | the minutes / approval page as Markdown |
| `execute.py` | per accepted actionable: branch → `claude -p` → verify → commit or revert |
| `report.py` | applied / blocked / yours / someone else's / reversals |
| `server.py` | FastAPI + single-page UI: record or upload, progress, approve, execute, report |
| `notify.py` | desktop toast or Slack alert when a meeting is ready |
| `providers/` | read-only context adapters (calendar, directory, repos, chat) — interface in place |
| `llm.py` | the only LLM client |
| `config.py` | paths, models, credentials |

Design notes: [`core-idea.md`](core-idea.md) (the problem and the evidence) and
[`architecture.md`](architecture.md) (why a pipeline, the eight steps, failure handling).

## Stack

Python · FastAPI · Pydantic · SQLite · Gemini (audio transcription) · Claude Sonnet (extraction
and judging) via a LiteLLM gateway · Claude Code (headless) · git

## Roadmap

- Ingest from Google Meet / Teams, where speaker names are already known
- Calendar and directory providers to resolve attendees and owners
- Dependencies between actionables, and owner routing for items that are not yours
