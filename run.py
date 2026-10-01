#!/usr/bin/env python3
"""Stage 1: recording (or transcript) -> extraction -> reconcile -> MoM draft.

    python3 run.py recording.aac --project nsd-proposal --id friday-1340 --date 2026-09-26
    python3 run.py transcript.txt --project nsd-proposal --id monday-1535 --date 2026-09-22

Writes data/meetings/<id>/{transcript.txt, extraction.json, mom.md} and stores the
decisions as 'proposed' in data/decisions.db. Nothing is executed and nothing is sent.
Approve later with:  python3 run.py --approve <id> --accept a1,b2 --reject c3
"""
import argparse
import sys

import memory
import pipeline

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", help="audio file or transcript .txt")
    ap.add_argument("--project", default="nsd-proposal")
    ap.add_argument("--id", help="meeting id, e.g. friday-1340")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--title", default=None)
    ap.add_argument("--approve", metavar="MEETING_ID")
    ap.add_argument("--accept", default="")
    ap.add_argument("--reject", default="")
    a = ap.parse_args()

    if a.approve:
        memory.approve(a.project, a.approve,
                       [x for x in a.accept.split(",") if x],
                       [x for x in a.reject.split(",") if x])
        print("approval recorded")
        return

    if not (a.source and a.id and a.date):
        ap.error("source, --id and --date are required")
    st = pipeline.run(a.source, a.project, a.id, a.date, a.title)
    if st["state"] == "failed":
        sys.exit(st["error"])
    print(f"{st['decisions']} decisions, {st['actionables']} actionables, "
          f"{st['reversals']} reversal(s)  ${st['cost']:.4f}")
    print(f"-> {pipeline.mdir(a.id) / 'mom.md'}")


if __name__ == "__main__":
    main()
