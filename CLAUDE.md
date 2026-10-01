# CHEETAAAH

Meeting → decisions → approval → execution. Read `core-idea.md` and `architecture.md`
before changing the design. Stage 1 (this code) stops at the MoM draft; nothing is
executed or sent.

## Run
    python3 run.py <audio|transcript.txt> --project nsd-proposal --id <meeting-id> --date YYYY-MM-DD
    python3 run.py --approve <meeting-id> --accept id1,id2 --reject id3

Outputs: `data/meetings/<id>/{transcript.txt,extraction.json,mom.md}`; decisions in
`data/decisions.db` (SQLite). Audio goes through `../proposal/transcribe.py`.

## Files
- `config.py`  — paths, models, credentials (read from dispo-analysis/.env, never hard-coded)
- `llm.py`     — the only gateway client. `reasoning="none"` by default: Claude otherwise
                 spends the whole token budget thinking on long transcripts and returns no text
- `extract.py` — one schema-enforced call → `Extraction` (pydantic). `verbatim` is mandatory
- `memory.py`  — decision store + LLM judge (same / refines / reverses); reversals are flagged,
                 never auto-resolved
- `mom.py`     — Markdown MoM = the approval page
- `projects/*.yaml` — per-project registry: repo, people, render/verify commands, and the
                 fixed `components` vocabulary the extractor must use

## Rules
- Gateway key limit is 30,000 tokens/min and `max_tokens` counts against it. Keep
  prompt + max_tokens under ~28k per call; chunk long transcripts.
- Never store keys in source or the DB. Never send mail from code; drafts only.
- Speaker labels from phone recordings are inferred, not known. Say so in the MoM.
- Add a new project by adding `projects/<name>.yaml`; do not special-case in code.
