"""Stage 2: apply approved actionables with Claude Code, one at a time, on a branch.

Control stays here. Claude Code gets a fixed prompt per change type, a working
directory, and a small tool set; it returns a working tree. This module decides
what to keep (verify passes -> commit) and what to throw away (revert). It never
pushes and never mails.

    python3 execute.py <meeting-id>            # all accepted, executable actionables
    python3 execute.py <meeting-id> --only 3   # one actionable by index
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

import yaml

import config
import pipeline

EXECUTABLE = {"copy_change", "delete_block", "add_block", "data_change"}
MAX_ATTEMPTS = 2
CLAUDE = shutil.which("claude") or str(pathlib.Path.home() / ".local/bin/claude")

PROMPT = """You are applying ONE approved change from a meeting to this repository.

CHANGE
  Type:        {type}
  Component:   {component}
  Instruction: {instruction}
  Said in the meeting (verbatim): "{verbatim}" — {said_by}
{history}
CONTEXT
  Read CLAUDE.md in this repository first: it maps components to files and says how to
  render and verify. Component hint for this change: {component_hint}

RULES
  - Make the smallest change that satisfies the instruction. Touch nothing else.
  - Do not edit generated files (deck*_<glid>.html, PDFs, cache/).
  - After editing, run the render and verify commands from CLAUDE.md. If verification
    fails, fix and re-run. Stop after 3 attempts.
  - Do not run git commit, git push, or send anything. Leave the working tree edited.
  - Finish with exactly this block:
    RESULT: applied | already_applied | blocked
    FILES: <comma-separated files you changed>
    VERIFY: <what you ran and its result>
    NOTE: <one line: anything you were unsure about, or why blocked>
"""


def sh(cmd, cwd, check=True, timeout=600):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr[-800:]}")
    return r.stdout


def git_clean(repo):
    return sh(["git", "status", "--porcelain"], repo).strip() == ""


def run_claude(prompt, repo, log):
    """Headless Claude Code. Returns the final text. Through the gateway if configured."""
    import os
    env = dict(os.environ)
    # Claude Code can run through the company gateway (it speaks the Anthropic API):
    # set these in dispo-analysis/.env as CLAUDE_CODE_VIA_GATEWAY=1 to enable.
    if "CLAUDE_CODE_VIA_GATEWAY=1" in config.ENV.read_text(errors="ignore"):
        base, key = config.creds()
        env["ANTHROPIC_BASE_URL"] = base.rsplit("/v1", 1)[0]
        env["ANTHROPIC_AUTH_TOKEN"] = key
        env["ANTHROPIC_MODEL"] = "anthropic/claude-sonnet-5"
    env.pop("CLAUDECODE", None)       # allow nesting when launched from inside Claude Code
    cmd = [CLAUDE, "-p", prompt, "--output-format", "text",
           "--allowedTools", "Read,Grep,Glob,Edit,Write,Bash(python3 *),Bash(ls *),Bash(cat *)",
           "--permission-mode", "acceptEdits", "--max-turns", "40"]
    r = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=1500, env=env)
    log.write_text(f"$ claude -p ...\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}",
                   encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[-600:]}")
    return r.stdout


def parse_result(text):
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", text, re.M) or [None, ""])[1].strip()
    return {"result": g("RESULT").lower() or "unknown", "files": g("FILES"),
            "verify": g("VERIFY"), "note": g("NOTE")}


def verify(project, repo):
    """Independent of the agent's claim: run the project's verify command and look for
    failure markers. Returns (ok, output)."""
    cmd = project.get("verify_cmd")
    if not cmd:
        return True, "no verify command configured"
    r = subprocess.run(cmd, shell=True, cwd=repo, text=True, capture_output=True, timeout=600)
    out = (r.stdout + r.stderr)[-2000:]
    bad = r.returncode != 0 or re.search(r"OVERFLOWS|Traceback|Error", out)
    return (not bad), out


def execute(meeting_id, only=None):
    d = pipeline.mdir(meeting_id)
    meta = json.loads((d / "meeting.json").read_text())
    ex = json.loads((d / "extraction.json").read_text(encoding="utf-8"))
    ap = json.loads((d / "approval.json").read_text()) if (d / "approval.json").exists() else None
    if not ap:
        sys.exit("nothing approved yet for this meeting")
    project = yaml.safe_load((config.PROJECTS / f"{meta['project']}.yaml").read_text())
    repo = pathlib.Path(project["repo"])
    if not (repo / ".git").exists():
        sys.exit(f"{repo} is not a git repository — the executor only works on branches")
    if not git_clean(repo):
        sys.exit(f"{repo} has uncommitted changes; commit or stash them first")

    branch = f"meeting/{meeting_id}"
    base_branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if branch not in sh(["git", "branch", "--list", branch], repo):
        sh(["git", "checkout", "-b", branch], repo)
    else:
        sh(["git", "checkout", branch], repo)

    results = []
    hist = {}
    try:
        import sqlite3
        c = sqlite3.connect(config.DATA / "decisions.db")
        for comp, instr, dt in c.execute(
                "SELECT component, instruction, date FROM decision WHERE project=? "
                "AND status='active' AND meeting_id<>? ORDER BY date", (meta["project"], meeting_id)):
            hist.setdefault(comp, []).append(f"{dt}: {instr}")
    except Exception:
        pass

    for i, a in enumerate(ex["actionables"]):
        choice = (ap.get("actionables") or {}).get(str(i))
        if only is not None and i != only:
            continue
        if choice != "accept":
            results.append({"i": i, "status": "skipped", "why": f"approval={choice}"})
            continue
        if a["type"] not in EXECUTABLE:
            results.append({"i": i, "status": "human", "why": f"type {a['type']} has no handler"})
            continue
        print(f"[{i}] {a['type']} {a['component']}: {a['instruction']}")
        history = ""
        if hist.get(a["component"]):
            history = "  Earlier decisions on this component (still active):\n" + "".join(
                f"    - {h}\n" for h in hist[a["component"]])
        prompt = PROMPT.format(type=a["type"], component=a["component"],
                               instruction=a["instruction"], verbatim=a["verbatim"],
                               said_by=a["said_by"], history=history,
                               component_hint=(project.get("components") or {}).get(
                                   a["component"], "see CLAUDE.md"))
        log = d / f"exec_{i}.log"
        rec = {"i": i, "type": a["type"], "component": a["component"],
               "instruction": a["instruction"], "attempts": []}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            t = time.time()
            try:
                text = run_claude(prompt, repo, log)
                claimed = parse_result(text)
            except Exception as e:
                claimed = {"result": "error", "note": str(e)[:300], "files": "", "verify": ""}
            diff = sh(["git", "diff", "--stat"], repo).strip()
            ok, vout = verify(project, repo) if diff else (False, "no changes made")
            rec["attempts"].append({"n": attempt, "claimed": claimed, "diff": diff,
                                    "verify_ok": ok, "verify": vout[-600:],
                                    "secs": round(time.time() - t)})
            if claimed.get("result") == "already_applied" and not diff:
                rec["status"] = "already_applied"
                rec["note"] = claimed.get("note")
                print("    already applied — nothing to change")
                break
            if ok and diff:
                sh(["git", "add", "-A"], repo)
                msg = (f"{a['type']}: {a['instruction']}\n\nMeeting {meeting_id} · {a['said_by']}: "
                       f"\"{a['verbatim']}\"\n\nApplied by CHEETAAAH; verified: "
                       f"{vout.strip().splitlines()[-1] if vout.strip() else 'ok'}")
                sh(["git", "-c", "user.name=CHEETAAAH", "-c", "user.email=cheetaaah@indiamart.local",
                    "commit", "-q", "-m", msg], repo)
                rec["status"] = "applied"
                rec["commit"] = sh(["git", "rev-parse", "--short", "HEAD"], repo).strip()
                rec["patch"] = sh(["git", "show", "--format=", "HEAD"], repo)[-6000:]
                print(f"    applied ({rec['commit']})")
                break
            sh(["git", "checkout", "--", "."], repo)
            sh(["git", "clean", "-fdq", "--exclude=cache", "--exclude=*.html"], repo)
            print(f"    attempt {attempt} failed: {claimed.get('note') or vout[-200:]}")
            if attempt < MAX_ATTEMPTS:
                prompt += (f"\n\nPREVIOUS ATTEMPT FAILED VERIFICATION:\n{vout[-800:]}\n"
                           f"Your note was: {claimed.get('note')}\nTry a different approach.")
        else:
            rec["status"] = "blocked"
        results.append(rec)

    sh(["git", "checkout", base_branch], repo)
    out = {"meeting": meeting_id, "branch": branch, "base": base_branch, "results": results,
           "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    (d / "execution.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    pipeline.status(meeting_id, state="executed",
                    applied=sum(r.get("status") in ("applied", "already_applied") for r in results),
                    blocked=sum(r.get("status") == "blocked" for r in results))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("meeting_id")
    ap.add_argument("--only", type=int)
    a = ap.parse_args()
    r = execute(a.meeting_id, a.only)
    for x in r["results"]:
        print(x["i"], x.get("status"), x.get("commit", ""), x.get("why", ""))
