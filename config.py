"""Shared settings for CHEETAAAH. Credentials come from the dispo-analysis .env
(LLM_BASE_URL / LLM_API_KEY) — never from the command line or source."""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"                    # meetings/, decisions.db
PROJECTS = HERE / "projects"            # one yaml per project the agent may touch
ENV = pathlib.Path("/mnt/c/Users/Imart/Desktop/Issues/dispo-analysis/.env")

TRANSCRIBE_MODEL = "google/gemini-3.6-flash"    # takes audio natively, good Hinglish
EXTRACT_MODEL = "anthropic/claude-sonnet-5"      # schema-enforced JSON
JUDGE_MODEL = "anthropic/claude-sonnet-5"        # same / refines / reverses / unrelated


def creds():
    if ENV.exists():
        txt = ENV.read_text(encoding="utf-8", errors="ignore")
        k = re.search(r'LLM_API_KEY\s*=\s*["\']?([^"\'\s]+)', txt)
        b = re.search(r'LLM_BASE_URL\s*=\s*["\']?([^"\'\s]+)', txt)
        if k and b:
            return b.group(1).rstrip("/"), k.group(1)
    sys.exit(f"No credentials: expected LLM_BASE_URL / LLM_API_KEY in {ENV}")
