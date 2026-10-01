# CHEETAAAH

A meeting ends, and the work it asked for is already moving.

Recording → transcript → decisions and actionables (with verbatim quotes) → check against
every earlier decision (reversals flagged) → **you approve on your phone** → Claude Code applies
the accepted changes on a branch, one at a time → each change is verified independently →
report with commits and diffs. Nothing is pushed, nothing is mailed, nothing changes without
your tap.

Design: `core-idea.md`, `architecture.md`. Working notes for Claude Code: `CLAUDE.md`.

## Run
    pip install fastapi uvicorn python-multipart pydantic pyyaml requests
    python3 server.py              # http://localhost:8787  — phone-first page
    # or the CLI
    python3 run.py recording.aac --project nsd-proposal --id friday-1340 --date 2026-09-26
    python3 execute.py <meeting-id>

Credentials: `LLM_BASE_URL` / `LLM_API_KEY` for a LiteLLM gateway (see `config.py`).
Claude Code must be installed for execution (`claude` on PATH).

## Pieces
| file | step |
|---|---|
| `pipeline.py` | ingest → transcribe → extract → reconcile → MoM, with `status.json` per meeting |
| `extract.py` | one schema-enforced LLM call per ~2,200 words, merged; `verbatim` mandatory |
| `memory.py` | SQLite decision store + LLM judge (same / refines / reverses) |
| `mom.py` | the MoM / approval page as Markdown |
| `execute.py` | per accepted actionable: branch → `claude -p` with a fixed prompt → verify → commit or revert |
| `report.py` | applied / blocked / yours / someone else's / reversals |
| `server.py` | FastAPI + single-page UI: record or upload, progress, approve, execute, report |
| `projects/*.yaml` | per-project registry: repo, people, verify command, component vocabulary |

## Non-negotiables
1. Approval before anything is applied — permanent.
2. Only registered change types execute; everything else is routed to a human.
3. Verification runs outside the agent and must be able to fail.
4. Output is a branch and commits, never an edit on main, never a push.
5. `verbatim` is never discarded.
